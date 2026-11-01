"""Cooperative multi-worker three-pass coordination. No AI calls or daemon.
SQLite owns exact-identity claims and handoffs. Legacy logs are read-only inputs.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
import uuid
VERSION = "three-pass-concurrent-v1"
COORDINATION_VERSION = "multi-run-v2"
SYNC_CACHE_VERSION = "verified-inputs-v1"
ROOT = Path(__file__).resolve().parents[2]
LOGS = {1:"first-pass-decisions.jsonl",2:"second-pass-triage-decisions.jsonl",3:"third-pass-decisions.jsonl"}
LEASE_SECONDS = 1800
TRIAGE_BATCH_CHARACTERS = 60000
MISSING_DESCRIPTION_RESERVE = 12000

def local_evidence(repo,key,source):
    """Indexed, exact-source lookup only; no whole-table or remote reads."""
    if repo is None or not getattr(repo,'is_local',False): return None
    matches=[row for _,row in repo.matches('Job Evidence',{'Job Key':key,'Source Hash':source})
             if row.get('Job Key')==key and row.get('Source Hash')==source]
    if len(matches)>1:
        return {'job_description':'','evidence_missing':True,'evidence_conflict':True,
                'next_action':'NEEDS_INFO_OR_TARGETED_SOURCE_RECOVERY'}
    if not matches: return None
    description=matches[0].get('Job Description','')
    if not isinstance(description,str) or not description.strip() or '[truncated' in description.casefold(): return None
    return {'job_description':description,'evidence_missing':False,
            'evidence_source':'local_sqlite_job_evidence',
            'evidence_locator':f'Job Evidence exact identity {key} / {source}'}

def encoded(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"))

def digest(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()

def assessment_signature(row):
    administrative = {"workflow_version","pass","run_id","reviewed_at","claim_token","input_version","writeback_status","writeback_detail","company","Company"}
    return digest({k:v for k,v in row.items() if k not in administrative})

def identity(row):
    key, source = row.get("job_key"),row.get("source_hash")
    if not isinstance(key,str) or not key.strip() or not isinstance(source,str) or not source.strip():
        raise ValueError("Missing exact job_key + source_hash; never guess an identity")
    return key,source

def read_stable_bytes(path):
    if not path.exists(): return b""
    before=path.stat(); raw=path.read_bytes(); after=path.stat()
    if (before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_ino,after.st_size,after.st_mtime_ns):
        raise RuntimeError(f"Input changed during read: {path.name}; retry, not completion")
    return raw

def parse_jsonl(raw,name):
    rows=[]
    for number,line in enumerate(raw.decode("utf-8-sig").splitlines(),1):
        if line.strip():
            try: row=json.loads(line)
            except ValueError as exc: raise ValueError(f"Malformed {name}:{number}; preserve input") from exc
            if not isinstance(row,dict): raise ValueError(f"{name}:{number} is not an object")
            rows.append(row)
    return rows

def read_jsonl(path):
    return parse_jsonl(read_stable_bytes(path),path.name)

def validate_scope_identities(identities):
    """Validate a bounded exact-identity allowlist without changing runtime state."""
    result=[]; seen=set()
    for pair in identities:
        if not isinstance(pair,(tuple,list)) or len(pair)!=2:
            raise ValueError("Scope requires exact job_key + source_hash pairs")
        exact=identity(dict(zip(("job_key","source_hash"),pair)))
        if exact in seen: raise ValueError("Duplicate exact identity in scope")
        seen.add(exact); result.append(exact)
        if len(result)>100: raise ValueError("Scope exceeds 100 exact identities")
    if not result: raise ValueError("Scope must contain at least one exact identity")
    return tuple(result)

def read_scope_file(path):
    rows=read_jsonl(path)
    for row in rows:
        if set(row)!={"job_key","source_hash"}:
            raise ValueError("Scope objects must contain only job_key and source_hash")
    return validate_scope_identities([identity(row) for row in rows])

def atomic_json(path,value,*,lines=False):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    temporary=path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as stream:
            if lines:
                for row in value: stream.write(encoded(row)+"\n")
            else: stream.write(json.dumps(value,ensure_ascii=False,indent=2)+"\n")
            stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:
        if temporary.exists(): temporary.unlink()

@contextmanager
def publication_lock(queue,exclusive=False):
    queue.mkdir(parents=True,exist_ok=True,mode=0o700)
    with (queue/".publish.lock").open("a") as handle:
        fcntl.flock(handle,fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        try: yield
        finally: fcntl.flock(handle,fcntl.LOCK_UN)

def read_snapshot(queue,*,decode=True):
    with publication_lock(queue):
        manifest_raw=(queue/"summary.json").read_bytes(); manifest=json.loads(manifest_raw); files={}
        for name in ("first-pass.jsonl","second-pass.jsonl"):
            raw=(queue/name).read_bytes(); expected=manifest.get("file_sha256",{}).get(name)
            if not expected or hashlib.sha256(raw).hexdigest()!=expected:
                raise RuntimeError("Queue generation changing or invalid; retry snapshot read")
            files[name]=parse_jsonl(raw,name) if decode else raw
        if manifest_raw!=(queue/"summary.json").read_bytes():
            raise RuntimeError("Queue generation changed during read")
    return manifest,files

def safe_payload(row):
    fields=("job_key","source_hash","job_title","row_number","score","band","score_reasons","python_reason","evidence_missing","evidence_source","evidence_locator","job_description","observed_at")
    return {key:row[key] for key in fields if key in row}

class Runtime:
    def __init__(self,queue,*,clock=time.time,lease_seconds=LEASE_SECONDS):
        self.queue=Path(queue).resolve(); self.directory=self.queue/"concurrent"
        self.directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.clock,self.lease_seconds=clock,lease_seconds
        self.db=sqlite3.connect(self.directory/"review-runtime.sqlite3",timeout=30)
        self.db.row_factory=sqlite3.Row
        self.db.execute("PRAGMA busy_timeout=30000"); self.db.execute("PRAGMA journal_mode=WAL"); self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS runs(stage INTEGER PRIMARY KEY,run_id TEXT NOT NULL,state TEXT NOT NULL,lease_until REAL NOT NULL,updated REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS review_runs(run_id TEXT PRIMARY KEY,stage INTEGER NOT NULL,state TEXT NOT NULL,lease_until REAL NOT NULL,updated REAL NOT NULL);
        CREATE INDEX IF NOT EXISTS review_runs_stage ON review_runs(stage,state,lease_until);
        CREATE TABLE IF NOT EXISTS tasks(stage INTEGER NOT NULL,job_key TEXT NOT NULL,source_hash TEXT NOT NULL,payload TEXT NOT NULL,version TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1,state TEXT NOT NULL DEFAULT 'ready',owner TEXT,token TEXT,lease_until REAL,PRIMARY KEY(stage,job_key,source_hash));
        CREATE TABLE IF NOT EXISTS decisions(stage INTEGER NOT NULL,job_key TEXT NOT NULL,source_hash TEXT NOT NULL,payload TEXT NOT NULL,origin TEXT NOT NULL,updated REAL NOT NULL,PRIMARY KEY(stage,job_key,source_hash));
        CREATE TABLE IF NOT EXISTS conflicts(stage INTEGER NOT NULL,job_key TEXT NOT NULL,source_hash TEXT NOT NULL,reason TEXT NOT NULL,PRIMARY KEY(stage,job_key,source_hash));
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,at REAL NOT NULL,stage INTEGER,job_key TEXT,source_hash TEXT,event TEXT NOT NULL,detail TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS evidence(job_key TEXT NOT NULL,source_hash TEXT NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(job_key,source_hash));
        CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS writeback(job_key TEXT NOT NULL,source_hash TEXT NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(job_key,source_hash));
        CREATE TABLE IF NOT EXISTS review_publications(stage INTEGER NOT NULL,job_key TEXT NOT NULL,source_hash TEXT NOT NULL,state TEXT NOT NULL,detail TEXT NOT NULL,updated REAL NOT NULL,PRIMARY KEY(stage,job_key,source_hash));
        CREATE TABLE IF NOT EXISTS sheet_controls(job_key TEXT PRIMARY KEY,choice TEXT NOT NULL,eligible INTEGER NOT NULL,source_hash TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS manual_reopens(job_key TEXT NOT NULL,source_hash TEXT NOT NULL,requested_at REAL NOT NULL,PRIMARY KEY(job_key,source_hash));
        """)
        # Persistent invalidation works across CLI processes, including writers
        # using SQL directly. Run leases, claims and audit events do not change
        # routing; status and lease checks remain live on the cached path.
        with self.transaction():
            self.db.execute("INSERT OR IGNORE INTO metadata VALUES('routing_revision','0')")
            for table in ('decisions','conflicts','sheet_controls','manual_reopens'):
                for operation in ('INSERT','UPDATE','DELETE'):
                    self.db.execute(f"""CREATE TRIGGER IF NOT EXISTS routing_{table}_{operation.lower()}
                        AFTER {operation} ON {table} BEGIN
                        UPDATE metadata SET value=CAST(value AS INTEGER)+1 WHERE key='routing_revision';
                        END""")
        os.chmod(self.directory/"review-runtime.sqlite3",0o600)
    def close(self): self.db.close()
    def set_sheet_controls(self,rows,*,reopened_keys=(),delivery_target=None):
        """Publish a complete live selection snapshot and fence cancelled claims.

        An explicit change back to Pending requests a new assessment. Prior
        decisions and delivery intents are retained in the append-only audit.
        """
        rows=list(rows)
        if len({r[0] for r in rows})!=len(rows): raise ValueError("Duplicate live Job Key; preserve review state")
        with self.transaction():
            previous_rows=[tuple(r) for r in self.db.execute('SELECT job_key,choice,eligible,source_hash FROM sheet_controls')]
            previous={r[0]:r[1] for r in previous_rows}
            reopened=set(reopened_keys)
            reopened.update(key for key,choice,eligible,source in rows
                            if eligible and choice.casefold()=='pending' and key in previous
                            and previous[key].casefold()!='pending')
            for key,choice,eligible,source in rows:
                if key not in reopened or not eligible or not source: continue
                old=[dict(r) for r in self.db.execute('SELECT * FROM decisions WHERE job_key=? AND source_hash=?',(key,source))]
                intent=self.db.execute('SELECT payload FROM writeback WHERE job_key=? AND source_hash=?',(key,source)).fetchone()
                self.event(None,key,source,'manual_review_requested',encoded({'prior_decisions':old,'prior_write_intent':json.loads(intent[0]) if intent else None}))
                self.db.execute('INSERT INTO manual_reopens VALUES(?,?,?) ON CONFLICT DO UPDATE SET requested_at=excluded.requested_at',(key,source,self.clock()))
                self.db.execute('DELETE FROM decisions WHERE job_key=? AND source_hash=?',(key,source))
                self.db.execute('DELETE FROM writeback WHERE job_key=? AND source_hash=?',(key,source))
                self.db.execute('DELETE FROM review_publications WHERE job_key=? AND source_hash=?',(key,source))
                self.db.execute("UPDATE tasks SET state='ready',owner=NULL,token=NULL,lease_until=NULL WHERE job_key=? AND source_hash=?",(key,source))
            previous_by_key={r[0]:r for r in previous_rows}
            current_by_key={r[0]:tuple(r) for r in rows}
            self.db.executemany('DELETE FROM sheet_controls WHERE job_key=?',
                                [(key,) for key in previous_by_key.keys()-current_by_key.keys()])
            self.db.executemany('INSERT INTO sheet_controls VALUES(?,?,?,?) ON CONFLICT(job_key) DO UPDATE SET choice=excluded.choice,eligible=excluded.eligible,source_hash=excluded.source_hash',
                                [row for key,row in current_by_key.items() if previous_by_key.get(key)!=row])
            cancelled=self.db.execute("SELECT COUNT(*) FROM tasks t WHERE state='claimed' AND NOT EXISTS(SELECT 1 FROM sheet_controls c WHERE c.job_key=t.job_key AND c.eligible=1 AND c.source_hash=t.source_hash)").fetchone()[0]
            self.db.execute("UPDATE tasks SET active=0,state=CASE WHEN state='done' THEN 'done' ELSE 'withdrawn' END,owner=NULL,token=NULL,lease_until=NULL WHERE NOT EXISTS(SELECT 1 FROM sheet_controls c WHERE c.job_key=tasks.job_key AND c.eligible=1 AND c.source_hash=tasks.source_hash)")
            report={'checked_at':datetime.now(timezone.utc).isoformat(),'visible_jobs':len(rows),'eligible_jobs':sum(bool(r[2]) for r in rows),'cancelled_claims':cancelled,'reopened_jobs':len(reopened),'scope':'visible_sheet_jobs'}
            if delivery_target: report['delivery_target']=delivery_target
            self.db.execute("INSERT INTO metadata VALUES('sheet_controls',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(encoded(report),))
        return report
    def sheet_exclusion(self,key,source):
        if not self.db.execute("SELECT 1 FROM metadata WHERE key='sheet_controls'").fetchone(): return None
        row=self.db.execute('SELECT * FROM sheet_controls WHERE job_key=?',(key,)).fetchone()
        if row is None: return 'Job is not present in the live sheet; off-sheet audit is excluded'
        if row['choice'].casefold()!='pending': return 'Live sheet selection is '+(row['choice'] or 'blank')
        if row['source_hash']!=source: return None  # Changed evidence must retain normal stale-claim errors.
        if not row['eligible']: return 'Job is no longer eligible for review in the local record'
        return None
    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try: yield; self.db.commit()
        except BaseException: self.db.rollback(); raise
    def event(self,stage,key,source,action,detail=""):
        self.db.execute("INSERT INTO events(at,stage,job_key,source_hash,event,detail) VALUES(?,?,?,?,?,?)",(self.clock(),stage,key,source,action,detail))
    def _conflict(self,stage,key,source,reason):
        self.db.execute("INSERT INTO conflicts VALUES(?,?,?,?) ON CONFLICT DO UPDATE SET reason=excluded.reason",(stage,key,source,reason))
    def _run(self,stage,run_id):
        # Keep v1 rows intact so an existing chat can resume its original lease.
        for table in ("review_runs","runs"):
            row=self.db.execute(f"SELECT * FROM {table} WHERE stage=? AND run_id=?",(stage,run_id)).fetchone()
            if row: return table,row
        return None,None
    def _owned(self,stage,run_id):
        table,row=self._run(stage,run_id)
        if not row or row["state"]!="active" or row["lease_until"]<=self.clock():
            raise RuntimeError("Run not owned or lease expired; start/resume this pass first")
        self.db.execute(f"UPDATE {table} SET lease_until=?,updated=? WHERE stage=? AND run_id=?",(self.clock()+self.lease_seconds,self.clock(),stage,run_id))
    def _expire_claims(self,stage):
        self.db.execute("UPDATE tasks SET state='ready',owner=NULL,token=NULL,lease_until=NULL WHERE stage=? AND state='claimed' AND lease_until<=?",(stage,self.clock()))
    def start(self,stage,run_id=None):
        if stage not in (1,2,3): raise ValueError("Select pass 1, 2, or 3")
        with self.transaction():
            if run_id:
                table,previous=self._run(stage,run_id)
                if previous is None: raise ValueError("Unknown run ID for this pass; omit --run-id to start a new worker")
                self.db.execute(f"UPDATE {table} SET state='active',lease_until=?,updated=? WHERE stage=? AND run_id=?",(self.clock()+self.lease_seconds,self.clock(),stage,run_id))
            else:
                run_id=f"pass-{stage}-{uuid.uuid4().hex}"
                self.db.execute("INSERT INTO review_runs VALUES(?,?,?,?,?)",(run_id,stage,"active",self.clock()+self.lease_seconds,self.clock()))
            self._expire_claims(stage)
            self.event(stage,None,None,"run_started",run_id)
        self.checkpoint(stage,run_id)
        return {"run_id":run_id,"pass":stage,"coordination_version":COORDINATION_VERSION,"lease_seconds":self.lease_seconds,"checkpoint":str(self.checkpoint_path(stage,run_id)),"instruction":"Each worker keeps its own run_id. Call next, assess, submit, and repeat. Never share a run_id between chats."}
    def heartbeat(self,stage,run_id):
        with self.transaction():
            self._owned(stage,run_id)
            renewed=self.db.execute("UPDATE tasks SET lease_until=? WHERE stage=? AND state='claimed' AND owner=? AND lease_until>?",(self.clock()+self.lease_seconds,stage,run_id,self.clock())).rowcount
        self.checkpoint(stage,run_id)
        return {"pass":stage,"run_id":run_id,"renewed_claims":renewed,"lease_seconds":self.lease_seconds}
    def sync(self):
        with (self.directory/".sync.lock").open("a") as handle:
            fcntl.flock(handle,fcntl.LOCK_EX)
            try: return self._sync()
            finally: fcntl.flock(handle,fcntl.LOCK_UN)
    def _sync(self):
        # Verify actual bytes on every call, not just timestamps or the manifest.
        # An unchanged generation can skip parsing and rebuilding thousands of
        # rows, but corruption and new legacy assessments must still be detected.
        manifest,raw_files=read_snapshot(self.queue,decode=False)
        raw_imports={stage:read_stable_bytes(self.queue/name) for stage,name in LOGS.items()}
        input_fingerprint=digest({'version':SYNC_CACHE_VERSION,'manifest':manifest,
                       'imports':{stage:hashlib.sha256(raw).hexdigest() for stage,raw in raw_imports.items()}})
        with self.transaction():
            cached=self.db.execute("SELECT value FROM metadata WHERE key='sync_cache'").fetchone()
            if cached and json.loads(cached[0])==self._sync_cache_key(input_fingerprint):
                self.last_sync_reused=True
                return self.status()
        self.last_sync_reused=False
        files={name:parse_jsonl(raw,name) for name,raw in raw_files.items()}
        imports={stage:parse_jsonl(raw,LOGS[stage]) for stage,raw in raw_imports.items()}
        first,second={},{}
        for destination,name in ((first,"first-pass.jsonl"),(second,"second-pass.jsonl")):
            for raw in files[name]:
                item=safe_payload(raw); key=identity(item)
                if key in destination and destination[key]!=item: raise ValueError("Conflicting duplicate queue identity")
                destination[key]=item
        if first.keys()&second.keys(): raise ValueError("Identity occurs in both first/second queues")
        sources={}
        for key,source in first.keys()|second.keys():
            if key in sources and sources[key]!=source: raise ValueError("Multiple current hashes for one job")
            sources[key]=source
        with self.transaction():
            controls_enabled=self.db.execute("SELECT 1 FROM metadata WHERE key='sheet_controls'").fetchone() is not None
            allowed={(r['job_key'],r['source_hash']) for r in self.db.execute('SELECT * FROM sheet_controls WHERE eligible=1')} if controls_enabled else None
            reopened={(r[0],r[1]) for r in self.db.execute('SELECT job_key,source_hash FROM manual_reopens')}
            if allowed is not None:
                first={key:item for key,item in first.items() if key in allowed}
                second={key:item for key,item in second.items() if key in allowed}
            # The user's explicit Pending request warrants description review even
            # when an older title decision had screened this same source out.
            for key in first.keys() & reopened:
                second[key]=first[key]
            first={key:item for key,item in first.items() if key not in reopened}
            for stage,rows in imports.items():
                for item in rows:
                    key,source=identity(item); item=dict(item)
                    if (key,source) in reopened: continue
                    if stage==1 and item.get("decision")=="SKIP": item["decision"]="PASS"
                    field="triage_decision" if stage==2 else "decision"
                    valid={1:{"RESCUE","PASS"},2:{"ESCALATE","CLEAR_REJECT","NEEDS_INFO"},3:{"Accept","Reject","Needs Info"}}[stage]
                    if item.get(field) not in valid:
                        self._conflict(stage,key,source,"Invalid legacy decision; preserve and inspect"); continue
                    old=self.db.execute("SELECT * FROM decisions WHERE stage=? AND job_key=? AND source_hash=?",(stage,key,source)).fetchone()
                    if old and assessment_signature(item)!=assessment_signature(json.loads(old["payload"])):
                        self._conflict(stage,key,source,"Legacy/managed assessments differ; no automatic overwrite")
                    elif not old:
                        self.db.execute("INSERT INTO decisions VALUES(?,?,?,?,?,?)",(stage,key,source,encoded(item),"legacy",self.clock()))
            # Imported decisions and managed results share one durable outbox.
            # Preserve all assessment data and only add missing delivery state.
            for row in self.db.execute("SELECT stage,job_key,source_hash,payload FROM decisions WHERE stage IN (1,2,3)").fetchall():
                item=json.loads(row["payload"])
                if (row["stage"]==3 or (row["stage"]==1 and item.get("decision")=="PASS") or item.get("triage_decision") in {"CLEAR_REJECT","NEEDS_INFO"}) and not item.get("writeback_status"):
                    item["writeback_status"]="Pending"
                    self.db.execute("UPDATE decisions SET payload=?,updated=? WHERE stage=? AND job_key=? AND source_hash=?",(encoded(item),self.clock(),row["stage"],row["job_key"],row["source_hash"]))
            # A conflict discovered while deriving handoffs changes the inputs
            # again. Leave the cache invalid until the next reconciliation has
            # incorporated that quarantine, just as an uncached sync would.
            reconciled_key=self._sync_cache_key(input_fingerprint)
            decisions={stage:{} for stage in (1,2,3)}
            conflicts={(r["stage"],r["job_key"],r["source_hash"]) for r in self.db.execute("SELECT * FROM conflicts")}
            for row in self.db.execute("SELECT * FROM decisions"):
                if (row["stage"],row["job_key"],row["source_hash"]) not in conflicts:
                    decisions[row["stage"]][(row["job_key"],row["source_hash"])]=json.loads(row["payload"])
            for key,item in first.items():
                if decisions[1].get(key,{}).get("decision")=="RESCUE": second[key]=dict(item)
            third={}
            for key,item in second.items():
                triage=decisions[2].get(key,{})
                if triage.get("triage_decision")=="ESCALATE":
                    if triage.get("description_complete") is not True or not isinstance(triage.get("evidence_packet"),dict):
                        self._conflict(2,*key,"Escalation lacks complete-evidence declaration/packet"); continue
                    third[key]={k:v for k,v in item.items() if k!="job_description"}
                    third[key].update(evidence_packet=triage["evidence_packet"],evidence_source=triage.get("evidence_source",""),evidence_locator=triage.get("evidence_locator",""),upstream_version=digest(triage))
            self.db.execute("UPDATE tasks SET active=0")
            for stage,inputs in ((1,first),(2,second),(3,third)):
                for (key,source),payload in inputs.items():
                    value,version=encoded(payload),digest(payload)
                    old=self.db.execute("SELECT * FROM tasks WHERE stage=? AND job_key=? AND source_hash=?",(stage,key,source)).fetchone()
                    done=(key,source) in decisions[stage]
                    if old:
                        if old["version"]!=version and old["state"]=="claimed": self.event(stage,key,source,"claim_invalidated","Input changed")
                        state="done" if done else old["state"] if old["version"]==version and old["state"] not in {"withdrawn","done"} else "ready"
                        self.db.execute("UPDATE tasks SET payload=?,version=?,active=1,state=?,token=CASE WHEN version=? THEN token ELSE NULL END WHERE stage=? AND job_key=? AND source_hash=?",(value,version,state,version,stage,key,source))
                    else:
                        self.db.execute("INSERT INTO tasks(stage,job_key,source_hash,payload,version,state) VALUES(?,?,?,?,?,?)",(stage,key,source,value,version,"done" if done else "ready"))
            self.db.execute("UPDATE tasks SET state='withdrawn',token=NULL WHERE active=0 AND state<>'done'")
            self.db.execute("INSERT INTO metadata VALUES('generation',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(encoded({"generated_at":manifest.get("generated_at"),"hashes":manifest["file_sha256"]}),))
            self.db.execute("INSERT INTO metadata VALUES('sync_cache',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(encoded(reconciled_key),))
        return self.status()

    def _sync_cache_key(self,inputs):
        revision=self.db.execute("SELECT value FROM metadata WHERE key='routing_revision'").fetchone()[0]
        controls=self.db.execute("SELECT 1 FROM metadata WHERE key='sheet_controls'").fetchone() is not None
        return {'inputs':inputs,'revision':revision,'controls_enabled':controls}

    def run_status(self,stage,run_id):
        _,row=self._run(stage,run_id)
        if row is None: raise ValueError("Unknown run ID for this pass")
        outcomes={r[0]:r[1] for r in self.db.execute("SELECT COALESCE(json_extract(payload,'$.triage_decision'),json_extract(payload,'$.decision')),COUNT(*) FROM decisions WHERE stage=? AND json_extract(payload,'$.run_id')=? GROUP BY 1",(stage,run_id))}
        delivery={r[0]:r[1] for r in self.db.execute("SELECT COALESCE(json_extract(payload,'$.writeback_status'),'Handoff'),COUNT(*) FROM decisions WHERE stage=? AND json_extract(payload,'$.run_id')=? GROUP BY 1",(stage,run_id))}
        return {**dict(row),"saved_assessments":sum(outcomes.values()),"outcomes":outcomes,"delivery":delivery,"owned_claims":self.db.execute("SELECT COUNT(*) FROM tasks WHERE stage=? AND active=1 AND state='claimed' AND owner=?",(stage,run_id)).fetchone()[0]}
    def status(self,stage=None,run_id=None):
        output={}
        for selected in ((stage,) if stage else (1,2,3)):
            counts={"ready":0,"claimed":0,"done":0}
            for row in self.db.execute("SELECT state,COUNT(*) n FROM tasks WHERE active=1 AND stage=? GROUP BY state",(selected,)):
                counts[row["state"]]=row["n"]
            counts["conflicts"]=self.db.execute("SELECT COUNT(*) FROM conflicts c JOIN tasks t USING(stage,job_key,source_hash) WHERE c.stage=? AND t.active=1",(selected,)).fetchone()[0]
            counts["upstream_active"]=[r[0] for r in self.db.execute("SELECT stage FROM runs WHERE stage<? AND state='active' AND lease_until>? UNION SELECT stage FROM review_runs WHERE stage<? AND state='active' AND lease_until>? ORDER BY stage",(selected,self.clock(),selected,self.clock()))]
            counts["active_runs"]=[dict(r) for r in self.db.execute("SELECT run_id,lease_until FROM runs WHERE stage=? AND state='active' AND lease_until>? UNION ALL SELECT run_id,lease_until FROM review_runs WHERE stage=? AND state='active' AND lease_until>? ORDER BY run_id",(selected,self.clock(),selected,self.clock()))]
            counts["pending_writeback"]=self.db.execute("SELECT COUNT(*) FROM decisions d WHERE d.stage=? AND json_extract(d.payload,'$.writeback_status')='Pending' AND NOT EXISTS (SELECT 1 FROM conflicts c WHERE c.stage=d.stage AND c.job_key=d.job_key AND c.source_hash=d.source_hash)",(selected,)).fetchone()[0] if selected in (1,2,3) else 0
            from .review_publication import publication_counts
            counts['publication']=publication_counts(self,selected)
            counts['pending_publication']=counts['publication'].get('Pending',0)
            counts["deferred"]=self.db.execute("SELECT COUNT(*) FROM decisions d WHERE d.stage=? AND (json_extract(d.payload,'$.triage_decision')='NEEDS_INFO' OR json_extract(d.payload,'$.decision')='Needs Info' OR json_extract(d.payload,'$.writeback_status') IN ('Conflict','Needs Staging') OR EXISTS (SELECT 1 FROM conflicts c WHERE c.stage=d.stage AND c.job_key=d.job_key AND c.source_hash=d.source_hash))",(selected,)).fetchone()[0] if selected in (1,2,3) else 0
            if selected==3:
                control=self.db.execute("SELECT value FROM metadata WHERE key='sheet_controls'").fetchone()
                local_target=bool(control and json.loads(control[0]).get('delivery_target')=='local_database')
                questions=self.db.execute("""SELECT COUNT(*) FROM decisions d
                  JOIN writeback w USING(job_key,source_hash)
                  LEFT JOIN review_publications p USING(stage,job_key,source_hash)
                  WHERE d.stage=3 AND json_extract(d.payload,'$.decision')='Needs Info'
                  AND json_extract(d.payload,'$.writeback_status')='Written'
                  AND json_extract(w.payload,'$.requires_opportunity')=1
                  AND json_extract(w.payload,'$.pass')=3
                  AND (p.state IN ('Written','Acknowledged') OR ?=0)
                  AND NOT EXISTS (SELECT 1 FROM conflicts c WHERE c.stage=3
                    AND c.job_key=d.job_key AND c.source_hash=d.source_hash)""",(int(local_target),)).fetchone()[0]
                counts['question_opportunities']=questions
                counts['deferred']=max(0,counts['deferred']-questions)
            output[str(selected)]=counts
        result={"workflow_version":VERSION,"coordination_version":COORDINATION_VERSION,"passes":output}
        controls=self.db.execute("SELECT value FROM metadata WHERE key='sheet_controls'").fetchone()
        if controls: result['sheet_controls']=json.loads(controls[0])
        if run_id is not None:
            if stage is None: raise ValueError("Select --pass when inspecting a specific run")
            result["run"]=self.run_status(stage,run_id)
            if result.get('sheet_controls',{}).get('delivery_target')=='local_database':
                delivery=result['run']['delivery']
                if 'Written' in delivery: delivery['Saved Locally']=delivery.pop('Written')
                result['run']['publication']=publication_counts(self,stage,run_id)
        return result
    def next(self,stage,run_id,limit=None,*,repo=None,identities=None):
        limit={1:100,2:10,3:1}[stage] if limit is None else limit
        if not 1<=limit<={1:100,2:10,3:3}[stage]: raise ValueError("Batch exceeds per-pass context limit")
        scope_sql=""; scope_parameters=()
        if identities is not None:
            if stage!=3: raise ValueError("Identity scope is supported only for next --pass 3")
            identities=validate_scope_identities(identities)
            scope_sql=" AND (t.job_key,t.source_hash) IN ("+",".join("(?,?)" for _ in identities)+")"
            scope_parameters=tuple(value for pair in identities for value in pair)
        self.sync()
        with self.transaction():
            self._owned(stage,run_id)
            self._expire_claims(stage)
            if identities is not None:
                held=self.db.execute("SELECT job_key,source_hash FROM tasks WHERE stage=? AND active=1 AND state='claimed' AND owner=?",(stage,run_id)).fetchall()
                if any(tuple(row) not in identities for row in held):
                    raise RuntimeError("Run holds claims outside supplied scope; resume with the full scope or pause before narrowing")
            rows=self.db.execute("SELECT t.* FROM tasks t WHERE stage=? AND active=1 AND (state='ready' OR (state='claimed' AND owner=?)) AND NOT EXISTS(SELECT 1 FROM conflicts c WHERE c.stage=t.stage AND c.job_key=t.job_key AND c.source_hash=t.source_hash)"+scope_sql+" ORDER BY CASE WHEN state='claimed' THEN 0 ELSE 1 END,CAST(json_extract(payload,'$.score') AS REAL) DESC,job_key LIMIT ?",(stage,run_id,*scope_parameters,limit)).fetchall()
            result=[]; payload_characters=0; estimated_characters=0
            for row in rows:
                token=row["token"] if row["state"]=="claimed" else uuid.uuid4().hex
                item=json.loads(row["payload"]); item.update(claim_token=token,input_version=row["version"])
                if stage==2 and not item.get("job_description"):
                    cached=self.db.execute("SELECT payload FROM evidence WHERE job_key=? AND source_hash=?",(row["job_key"],row["source_hash"])).fetchone()
                    if cached: item.update(json.loads(cached[0]))
                    else:
                        evidence=local_evidence(repo,row['job_key'],row['source_hash'])
                        if evidence: item.update(evidence)
                size=len(encoded(item))
                estimated_size=size+(MISSING_DESCRIPTION_RESERVE if stage==2 and not item.get('job_description') else 0)
                # Never truncate evidence, strand an oversized first job, or drop
                # previously held claims when resuming a run. Only new claims
                # are limited by the soft character budget.
                if stage==2 and result and row['state']!='claimed' and estimated_characters+estimated_size>TRIAGE_BATCH_CHARACTERS:
                    break
                self.db.execute("UPDATE tasks SET state='claimed',owner=?,token=?,lease_until=? WHERE stage=? AND job_key=? AND source_hash=?",(run_id,token,self.clock()+self.lease_seconds,stage,row["job_key"],row["source_hash"]))
                result.append(item)
                payload_characters+=size; estimated_characters+=estimated_size
            self.event(stage,None,None,"batch_claimed",str(len(result)))
        self.checkpoint(stage,run_id)
        output={"pass":stage,"run_id":run_id,"items":result,"queue":self.status(stage),"checkpoint":str(self.checkpoint_path(stage,run_id)),"next_action":"ASSESS_AND_SUBMIT_THEN_NEXT" if result else "FRESH_FINISH_CHECK_REQUIRED"}
        if stage==2:
            output['batch']={'max_jobs':limit,'soft_character_budget':TRIAGE_BATCH_CHARACTERS,
                             'payload_characters':payload_characters,'estimated_characters':estimated_characters,
                             'missing_descriptions':sum(not bool(item.get('job_description')) for item in result),
                             'over_budget':estimated_characters>TRIAGE_BATCH_CHARACTERS}
        return output
    @staticmethod
    def validate_result(stage,item):
        identity(item)
        if not str(item.get("reason","")).strip(): raise ValueError("A specific assessment reason is required")
        if stage==1:
            if item.get("decision") not in {"PASS","RESCUE"}: raise ValueError("Pass 1 permits PASS or RESCUE")
        elif stage==2:
            choice=item.get("triage_decision")
            if choice not in {"ESCALATE","CLEAR_REJECT","NEEDS_INFO"}: raise ValueError("Invalid triage decision")
            if choice!="NEEDS_INFO" and item.get("description_complete") is not True: raise ValueError("Triage requires complete description evidence")
            if choice=="ESCALATE" and not isinstance(item.get("evidence_packet"),dict): raise ValueError("ESCALATE requires an evidence packet")
            if not item.get("evidence_locator") or not item.get("evidence_source"): raise ValueError("Description result requires a retrievable locator")
        else:
            if item.get("decision") not in {"Accept","Reject","Needs Info"}: raise ValueError("Invalid final decision")
            if item.get("decision")=="Accept" and item.get("fit_level") not in {"Strong","Possible","Stretch"}: raise ValueError("Acceptance requires a fit level")
            if item.get("decision")!="Accept" and item.get("fit_level") is not None: raise ValueError("Nonacceptance requires null fit_level")
    def submit(self,stage,run_id,results):
        if not results: raise ValueError("Empty results file")
        self.sync(); saved=0; reused=0; skipped=[]
        with self.transaction():
            self._owned(stage,run_id)
            for raw in results:
                key,source=identity(raw)
                excluded=self.sheet_exclusion(key,source)
                if excluded:
                    skipped.append({'job_key':key,'source_hash':source,'reason':excluded})
                    self.event(stage,key,source,'submission_skipped_manual_choice',excluded)
                    continue
                self.validate_result(stage,raw)
                row=self.db.execute("SELECT * FROM tasks WHERE stage=? AND job_key=? AND source_hash=?",(stage,key,source)).fetchone()
                prior=self.db.execute("SELECT payload FROM decisions WHERE stage=? AND job_key=? AND source_hash=?",(stage,key,source)).fetchone()
                if row and row["active"] and prior:
                    previous=json.loads(prior[0])
                    if previous.get("run_id")==run_id and assessment_signature(previous)==assessment_signature(raw):
                        reused+=1; continue
                if not row or not row["active"] or row["state"]!="claimed" or row["owner"]!=run_id or row["lease_until"]<=self.clock() or row["token"]!=raw.get("claim_token") or row["version"]!=raw.get("input_version"):
                    raise RuntimeError("Stale/unowned claim or changed input; preserve result and reconcile")
                if self.db.execute("SELECT 1 FROM conflicts WHERE stage=? AND job_key=? AND source_hash=?",(stage,key,source)).fetchone(): raise RuntimeError("Conflicting assessment must be reconciled")
                value={k:v for k,v in raw.items() if k not in {"claim_token","input_version","company","Company"}}
                value.update(workflow_version=VERSION,**{"pass":stage},run_id=run_id,reviewed_at=datetime.now(timezone.utc).isoformat())
                if stage==3 or (stage==1 and value.get("decision")=="PASS") or (stage==2 and value.get("triage_decision") in {"CLEAR_REJECT","NEEDS_INFO"}):
                    value["writeback_status"]="Pending"
                self.db.execute("INSERT INTO decisions VALUES(?,?,?,?,?,?)",(stage,key,source,encoded(value),"managed",self.clock()))
                self.db.execute("UPDATE tasks SET state='done',token=NULL,lease_until=NULL WHERE stage=? AND job_key=? AND source_hash=?",(stage,key,source))
                self.event(stage,key,source,"decision_saved",value.get("triage_decision",value.get("decision",""))); saved+=1
        self.sync(); self.export(stage); self.checkpoint(stage,run_id)
        return {"saved":saved,"reused":reused,"skipped_manual":skipped,"pass":stage,"run_id":run_id,"queue":self.status(stage),"next_action":"NEXT_BATCH"}
    def amend_pending(self,stage,run_id,request):
        """Resolve this run's unwritten Needs Info after explicit user clarification."""
        if stage!=3: raise ValueError("Only pass 3 permits amend-pending")
        required={"job_key","source_hash","input_version","expected_assessment_signature","revision_id","revision_reason","user_clarification","assessment"}
        if not isinstance(request,dict) or set(request)!=required:
            raise ValueError("Amendment requires exact identity/version, expected signature, revision ID/reason, user clarification, and assessment")
        key,source=identity(request)
        for field in required-{"assessment"}:
            if not isinstance(request[field],str) or not request[field].strip():
                raise ValueError(f"Amendment {field} must be nonblank text")
        raw=request["assessment"]
        if not isinstance(raw,dict) or identity(raw)!=(key,source):
            raise ValueError("Revised assessment must match the exact amendment identity")
        if raw.get("input_version",request["input_version"])!=request["input_version"] or raw.get("run_id",run_id)!=run_id or raw.get("pass",3)!=3:
            raise ValueError("Revised assessment has conflicting version or ownership metadata")
        self.validate_result(3,raw)
        if raw["decision"] not in {"Accept","Reject"}:
            raise ValueError("Amend-pending only resolves Needs Info to Accept or Reject")
        if not raw.get("evidence_source") or not raw.get("evidence_locator"):
            raise ValueError("Revised assessment requires its source and locator")
        if raw["decision"]=="Accept":
            location=raw.get("location_check",{})
            if not isinstance(location,dict) or location.get("status")!="verified_us" or not location.get("source_value") or not location.get("evidence") or raw.get("policy_conflicts"):
                raise ValueError("Revised acceptance requires verified U.S. location and no policy conflicts")
        administrative={"workflow_version","pass","run_id","reviewed_at","claim_token","input_version","writeback_status","writeback_detail","company","Company"}
        proposed={k:v for k,v in raw.items() if k not in administrative}
        receipt={k:v for k,v in request.items() if k!="assessment"}
        receipt.update(run_id=run_id,assessment=proposed)
        request_signature=digest(receipt)
        self.sync()
        from .review_writeback import sheet_writer_lock
        amended=reused=0
        from .cli import review_lock_name
        from .runner import _load_environment
        _load_environment()
        with sheet_writer_lock(self.queue.parent/review_lock_name()):
            with self.transaction():
                self._owned(3,run_id)
                task=self.db.execute("SELECT * FROM tasks WHERE stage=3 AND job_key=? AND source_hash=?",(key,source)).fetchone()
                saved=self.db.execute("SELECT * FROM decisions WHERE stage=3 AND job_key=? AND source_hash=?",(key,source)).fetchone()
                if not task or not task["active"] or task["state"]!="done" or task["owner"]!=run_id or task["version"]!=request["input_version"]:
                    raise RuntimeError("Amendment requires this run's active, unchanged, completed exact-identity task")
                if not saved or saved["origin"]!="managed":
                    raise RuntimeError("Only this run's managed pending assessment can be amended")
                previous=json.loads(saved["payload"])
                if previous.get("run_id")!=run_id or previous.get("writeback_status")!="Pending":
                    raise RuntimeError("Amendment cannot change another owner's or non-Pending assessment")
                if self.db.execute("SELECT 1 FROM writeback WHERE job_key=? AND source_hash=?",(key,source)).fetchone():
                    raise RuntimeError("A durable write intent exists; amendment is forbidden")
                if self.db.execute("SELECT 1 FROM conflicts WHERE job_key=? AND source_hash=?",(key,source)).fetchone():
                    raise RuntimeError("Conflicting assessment must be reconciled before amendment")
                prior_revision=self.db.execute("SELECT detail FROM events WHERE event='pending_assessment_amended' AND json_extract(detail,'$.revision_id')=?",(request["revision_id"],)).fetchone()
                if prior_revision:
                    audit=json.loads(prior_revision[0])
                    if audit.get("request_signature")!=request_signature or audit.get("revised")!=previous:
                        raise RuntimeError("Revision ID was already used for a different request or result")
                    revised=previous; reused=1
                else:
                    if previous.get("decision")!="Needs Info":
                        raise RuntimeError("Only an unwritten Needs Info decision can be amended")
                    if assessment_signature(previous)!=request["expected_assessment_signature"]:
                        raise RuntimeError("Previous assessment signature changed; preserve and reconcile")
                    revised=dict(proposed)
                    revised.update(workflow_version=VERSION,**{"pass":3},run_id=run_id,reviewed_at=datetime.now(timezone.utc).isoformat(),writeback_status="Pending")
                    audit={**receipt,"request_signature":request_signature,"prior":previous,"revised":revised}
                    self.db.execute("UPDATE decisions SET payload=?,updated=? WHERE stage=3 AND job_key=? AND source_hash=?",(encoded(revised),self.clock(),key,source))
                    self.event(3,key,source,"pending_assessment_amended",encoded(audit)); amended=1
        self.export(3); self.checkpoint(3,run_id)
        return {"amended":amended,"reused":reused,"pass":3,"run_id":run_id,"job_key":key,"source_hash":source,"revision_id":request["revision_id"],"assessment_signature":assessment_signature(revised),"next_action":"WRITEBACK_REQUIRED"}
    def export(self,stage):
        # Separate managed views: never overwrite the legacy chat-owned logs.
        with self.transaction():
            rows=[json.loads(r[0]) for r in self.db.execute("SELECT payload FROM decisions WHERE stage=? ORDER BY job_key,source_hash",(stage,))]
            atomic_json(self.directory/LOGS[stage],rows,lines=True)
    def checkpoint_path(self,stage,run_id):
        return self.directory/"run-checkpoints"/f"pass-{stage}-{digest(run_id)}.json"
    def checkpoint(self,stage,run_id):
        with self.transaction():
            value={"run_id":run_id,"pass":stage,"updated_at":datetime.now(timezone.utc).isoformat(),**self.status(stage,run_id)}
            value["owned_claims"]=self.db.execute("SELECT COUNT(*) FROM tasks WHERE stage=? AND active=1 AND state='claimed' AND owner=?",(stage,run_id)).fetchone()[0]
            atomic_json(self.checkpoint_path(stage,run_id),value)
            # Retain the v1 path only as a pass-wide progress view, never a resume ID.
            atomic_json(self.directory/f"pass-{stage}-checkpoint.json",{**value,"scope":"pass_summary","resume_from":"Use this chat's saved run_id and run-checkpoints file"})
    def finish(self,stage,run_id):
        self.sync()
        with self.transaction():
            self._owned(stage,run_id); self._expire_claims(stage)
            status=self.status(stage)["passes"][str(stage)]
            unfinished=status.get("ready",0)+status.get("claimed",0)
            available=self.db.execute("SELECT COUNT(*) FROM tasks t WHERE stage=? AND active=1 AND (state='ready' OR (state='claimed' AND owner=?)) AND NOT EXISTS(SELECT 1 FROM conflicts c WHERE c.stage=t.stage AND c.job_key=t.job_key AND c.source_hash=t.source_hash)",(stage,run_id)).fetchone()[0]
            other_claims=self.db.execute("SELECT COUNT(*) FROM tasks t WHERE stage=? AND active=1 AND state='claimed' AND owner<>? AND NOT EXISTS(SELECT 1 FROM conflicts c WHERE c.stage=t.stage AND c.job_key=t.job_key AND c.source_hash=t.source_hash)",(stage,run_id)).fetchone()[0]
            if available: action="CONTINUE"
            elif other_claims: action="WAITING_WORKERS"
            elif unfinished: action="BLOCKED_CONFLICTS"
            elif status["pending_writeback"] or status['pending_publication']: action="WRITEBACK_PENDING"
            elif status["upstream_active"]: action="WAITING_UPSTREAM"
            else:
                action="DRAINED_WITH_EXCEPTIONS" if status["conflicts"] or status["deferred"] or status['publication'].get('Conflict') else "DRAINED"
                table,_=self._run(stage,run_id)
                self.db.execute(f"UPDATE {table} SET state='drained',updated=? WHERE stage=? AND run_id=?",(self.clock(),stage,run_id))
            self.event(stage,None,None,"finish_check",action)
        self.checkpoint(stage,run_id)
        return {"pass":stage,"run_id":run_id,"state":action,"queue":status,"note":"An empty batch is not completion; new upstream work is included on the next check."}
    def pause(self,stage,run_id):
        with self.transaction():
            self._owned(stage,run_id)
            table,_=self._run(stage,run_id)
            self.db.execute(f"UPDATE {table} SET state='paused',updated=? WHERE stage=? AND run_id=?",(self.clock(),stage,run_id))
            self.db.execute("UPDATE tasks SET state='ready',owner=NULL,token=NULL,lease_until=NULL WHERE stage=? AND owner=? AND state='claimed'",(stage,run_id))
            self.event(stage,None,None,"run_paused",run_id)
        self.checkpoint(stage,run_id)
        return {"state":"PAUSED_NOT_COMPLETE","pass":stage,"run_id":run_id}
    def hydrate(self,key,source,*,repo=None):
        identity({"job_key":key,"source_hash":source})
        stored=self.db.execute("SELECT payload FROM evidence WHERE job_key=? AND source_hash=?",(key,source)).fetchone()
        if stored: return json.loads(stored[0])
        indexed=local_evidence(repo,key,source)
        if indexed:
            if not indexed.get('evidence_missing'):
                with self.transaction(): self.db.execute('INSERT INTO evidence VALUES(?,?,?) ON CONFLICT DO NOTHING',(key,source,encoded(indexed)))
            return indexed
        _,files=read_snapshot(self.queue)
        matches=[r for r in files["second-pass.jsonl"] if identity(r)==(key,source)]
        if not matches: matches=[r for r in read_jsonl(self.queue/"second-pass-work/rescue-evidence-cache.jsonl") if identity(r)==(key,source)]
        evidence=None
        for row in matches:
            text=row.get("job_description") or row.get("description")
            if text and "[truncated" not in text.casefold():
                evidence={"job_description":text,"evidence_source":row.get("evidence_source","queue_snapshot"),"evidence_locator":row.get("evidence_locator",f"{key} / {source}")}; break
        if evidence is None:
            from .title_audit import load_title_audits
            records,_=load_title_audits(self.queue.parent/"inventories.sqlite3",getattr(repo,"spreadsheet_id",None))
            for row in records:
                if identity(row)==(key,source):
                    text=row.get("posting",{}).get("description","")
                    if text and "[truncated" not in text.casefold(): evidence={"job_description":text,"evidence_source":"local_title_audit","evidence_locator":f"{key} / {source}"}
        if evidence is None and repo is not None and not getattr(repo,'is_local',False):
            matches=[(n,r) for n,r in repo.read_columns("Job Evidence",["Job Key","Source Hash"]) if r.get("Job Key")==key and r.get("Source Hash")==source]
            if len(matches)==1:
                row=repo.read_row("Job Evidence",matches[0][0])
                if row.get("Job Key")==key and row.get("Source Hash")==source:
                    text=str(row.get("Job Description",""))
                    if text and "[truncated" not in text.casefold(): evidence={"job_description":text,"evidence_source":"local_sqlite_job_evidence" if getattr(repo,"is_local",False) else "google_sheet_job_evidence","evidence_locator":f"Job Evidence exact identity {key} / {source}"}
        if evidence is None: return {"job_description":"","evidence_missing":True,"next_action":"NEEDS_INFO_OR_TARGETED_SOURCE_RECOVERY"}
        with self.transaction(): self.db.execute("INSERT INTO evidence VALUES(?,?,?) ON CONFLICT DO NOTHING",(key,source,encoded(evidence)))
        return evidence


def live_refresh(queue, *, reuse_if_current=False):
    from .runner import _load_environment
    from .cli import get_repository,state_path
    from .review_queue import export_review_queues
    _load_environment(); repo=get_repository(write=False,interactive=False)
    try:
        return export_review_queues(repo,queue,overwrite=True,inventory_database=state_path().parent/"inventories.sqlite3",reuse_if_current=reuse_if_current)
    finally:
        if getattr(repo,"is_local",False): repo.close()

def main(argv=None):
    parser=argparse.ArgumentParser(description="Multiple independent workers per pass. Supplies batches; never runs an AI model.")
    parser.add_argument("command",choices=["start","next","submit","amend-pending","promote-questions","correct-questions-reject","correct-published-reject","finish","pause","heartbeat","status","refresh","controls","evidence","writeback","publish"])
    parser.add_argument("--pass",dest="stage",type=int,choices=[1,2,3]); parser.add_argument("--run-id")
    parser.add_argument("--limit",type=int); parser.add_argument("--file")
    parser.add_argument("--queue-dir",default=str(ROOT/".state/review-queue"))
    parser.add_argument("--job-key"); parser.add_argument("--source-hash")
    parser.add_argument("--scope-file",help="Exact-identity JSONL allowlist (1–100 objects), only for next --pass 3")
    parser.add_argument("--local-only",action="store_true",help="Use published input and stage submissions without automatic Sheets writeback; not a final completion check.")
    args=parser.parse_args(argv)
    if args.command in {'promote-questions','correct-questions-reject','correct-published-reject'} and (args.stage!=3 or args.local_only):
        parser.error('Questions promotion requires --pass 3 and fresh live Sheet controls')
    if args.command=='publish' and args.local_only: parser.error('Publish requires fresh live Sheet controls; --local-only is not supported')
    if args.command not in {"status","refresh","controls"} and args.stage is None: parser.error("Select --pass 1, --pass 2, or --pass 3 explicitly")
    if args.command not in {"start","status","refresh","controls","publish"} and not args.run_id: parser.error("--run-id from this pass's start is required")
    runtime=None
    try:
        identities=None
        if args.scope_file is not None:
            if args.command!="next" or args.stage!=3:
                raise ValueError("--scope-file is supported only for next --pass 3")
            identities=read_scope_file(Path(args.scope_file))
        queue=Path(args.queue_dir).resolve()
        runtime=Runtime(queue)
        controls=None
        if not args.local_only and args.command not in {'pause','evidence','amend-pending'}:
            from .review_controls import refresh_sheet_controls
            controls=refresh_sheet_controls(runtime)
        refresh_result=None
        if args.command in {"start","refresh","finish"} and not args.local_only:
            refresh_result=live_refresh(queue,reuse_if_current=args.command=='start' and not (controls or {}).get('reopened_jobs'))
        elif controls and controls['reopened_jobs']: refresh_result=live_refresh(queue)
        if args.command in {"start","refresh","status","controls","heartbeat"}: runtime.sync()
        if args.command=="start":
            result=runtime.start(args.stage,args.run_id); result["queue"]=runtime.status(args.stage)
        elif args.command=="next":
            repo=None
            try:
                if args.stage==2 and not args.local_only:
                    from .runner import _load_environment
                    from .cli import get_repository,storage_backend
                    _load_environment()
                    if storage_backend()=='sqlite': repo=get_repository(write=False,interactive=False)
                result=runtime.next(args.stage,args.run_id,args.limit,repo=repo,identities=identities)
            finally:
                if repo is not None: repo.close()
        elif args.command=="submit":
            if not args.file: raise ValueError("--file containing model-assessed claimed-identity JSONL is required")
            submitted=read_jsonl(Path(args.file))
            result=runtime.submit(args.stage,args.run_id,submitted)
            if args.stage in (1,2,3):
                if not args.local_only:
                    from .review_writeback import sync_pending
                    result["writeback"]=sync_pending(runtime,args.stage,args.run_id,100,identities={identity(item) for item in submitted})
                    from .review_publication import publish_reviews
                    publication=publish_reviews(runtime,args.stage,args.run_id,100,identities={identity(item) for item in submitted})
                    if publication is not None: result['publication']=publication
                result["queue"]=runtime.status(args.stage)
                counts=result['queue']['passes'][str(args.stage)]
                result["next_action"]="WRITEBACK_PENDING" if counts['pending_writeback'] or counts['pending_publication'] else "NEXT_BATCH"
        elif args.command=="promote-questions":
            if not args.file: raise ValueError('An explicit promotion-request JSONL file is required')
            from .review_question_migration import promote_questions
            requests=read_jsonl(Path(args.file))
            result=promote_questions(runtime,args.run_id,requests)
            identities={identity(request) for request in requests}
            from .review_writeback import sync_pending
            result['writeback']=sync_pending(runtime,3,args.run_id,100,identities=identities)
            from .review_publication import publish_reviews
            publication=publish_reviews(runtime,3,None,100,identities=identities)
            if publication is not None: result['publication']=publication
            result['queue']=runtime.status(3)
        elif args.command in {"correct-questions-reject","correct-published-reject"}:
            if not args.file: raise ValueError('One explicit audited correction request is required')
            requests=read_jsonl(Path(args.file))
            if len(requests)!=1: raise ValueError('Correction requires exactly one request')
            from .review_question_correction import correct_published_questions
            result=correct_published_questions(runtime,args.run_id,requests[0])
            identities={identity(requests[0])}
            from .review_writeback import sync_pending
            result['writeback']=sync_pending(runtime,3,args.run_id,1,identities=identities)
            from .review_publication import publish_reviews
            publication=publish_reviews(runtime,3,args.run_id,1,identities=identities)
            if publication is not None: result['publication']=publication
            result['queue']=runtime.status(3)
        elif args.command=="amend-pending":
            if not args.file: raise ValueError("--file containing one audited amendment request is required")
            requests=read_jsonl(Path(args.file))
            if len(requests)!=1: raise ValueError("Amend-pending requires exactly one request")
            result=runtime.amend_pending(args.stage,args.run_id,requests[0])
        elif args.command=="finish":
            if args.local_only: raise ValueError("Finish requires a live queue refresh; use status for a local checkpoint")
            delivery=None
            if args.stage in (1,2,3):
                from .review_writeback import sync_pending
                delivery=sync_pending(runtime,args.stage,args.run_id,args.limit or 25)
                from .review_publication import publish_reviews
                # Finish checks the whole pass, including saved deliveries from
                # a worker that paused or expired before it could publish them.
                publication=publish_reviews(runtime,args.stage,None,args.limit or 25)
            result=runtime.finish(args.stage,args.run_id)
            if delivery is not None: result["writeback"]=delivery
            if publication is not None: result['publication']=publication
        elif args.command=="pause": result=runtime.pause(args.stage,args.run_id)
        elif args.command=="heartbeat": result=runtime.heartbeat(args.stage,args.run_id)
        elif args.command=="evidence":
            if args.stage==1: raise ValueError("First pass cannot fetch descriptions")
            with runtime.transaction():
                runtime._owned(args.stage,args.run_id)
                claim=runtime.db.execute("SELECT 1 FROM tasks WHERE stage=? AND job_key=? AND source_hash=? AND active=1 AND state='claimed' AND owner=? AND lease_until>?",(args.stage,args.job_key,args.source_hash,args.run_id,runtime.clock())).fetchone()
                if not claim: raise ValueError("Evidence retrieval requires this run's current claim")
            from .runner import _load_environment
            from .cli import get_repository,storage_backend
            _load_environment()
            if storage_backend()=='sqlite':
                repo=get_repository(write=False,interactive=False)
                try: result=runtime.hydrate(args.job_key,args.source_hash,repo=repo)
                finally: repo.close()
            else: result=runtime.hydrate(args.job_key,args.source_hash)
            if result.get("evidence_missing") and storage_backend()!='sqlite':
                from .runner import _load_environment
                from .cli import get_repository
                _load_environment(); result=runtime.hydrate(args.job_key,args.source_hash,repo=get_repository(write=False,interactive=False))
        elif args.command=='publish':
            from .review_publication import publish_reviews
            result=publish_reviews(runtime,args.stage,args.run_id,args.limit or 25)
            if result is None: result={'state':'DIRECT_SHEETS_MODE','note':'Writeback already publishes directly to Google Sheets.'}
        elif args.command=="writeback":
            if args.stage not in (1,2,3): raise ValueError("Only saved pass 1 PASS, pass 2 CLEAR_REJECT/NEEDS_INFO, and pass 3 decisions write Sheets")
            from .review_writeback import sync_pending,writeback
            if not args.job_key:
                result=sync_pending(runtime,args.stage,args.run_id,args.limit or 25)
            else:
                if not args.job_key or not args.source_hash: raise ValueError("Single-item writeback requires --job-key and --source-hash")
                result=writeback(runtime,args.stage,args.run_id,args.job_key,args.source_hash)
            from .review_publication import publish_reviews
            identities={(args.job_key,args.source_hash)} if args.job_key else None
            publication=publish_reviews(runtime,args.stage,None,args.limit or 25,identities=identities)
            if publication is not None: result['publication']=publication
        else: result=runtime.status(args.stage,args.run_id)
        if isinstance(refresh_result,dict) and 'refresh' in refresh_result:
            result['queue_refresh']=refresh_result['refresh']
        if controls:
            result['sheet_controls']=controls
            if 'writeback' in result:
                result['writeback']['delivery_target']=controls['delivery_target']
                if controls['delivery_target']=='local_database':
                    counts=result['writeback'].get('counts',{})
                    if 'Written' in counts: counts['Saved Locally']=counts.pop('Written')
                    result['writeback']['note']='Local storage verified; see publication for verified Google Sheets delivery.'
            if args.command=='writeback':
                result['delivery_target']=controls['delivery_target']
                if controls['delivery_target']=='local_database':
                    counts=result.get('counts',{})
                    if 'Written' in counts: counts['Saved Locally']=counts.pop('Written')
                    if result.get('writeback_status')=='Written': result['writeback_status']='Saved Locally'
                    result['note']='Local storage verified; see publication for verified Google Sheets delivery.'
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    except (ValueError,RuntimeError,OSError,sqlite3.Error) as exc:
        print(json.dumps({"state":"BLOCKED_NOT_COMPLETE","error":str(exc)}),file=sys.stderr); return 1
    finally:
        if runtime: runtime.close()

if __name__=="__main__": raise SystemExit(main())
