"""Serialized exact-identity review writeback; never changes Current Snapshot."""
from __future__ import annotations
from contextlib import contextmanager,nullcontext
from datetime import datetime,timezone
import fcntl
import json
from pathlib import Path
from .core import canonicalize_url,reconsiderations
from .cli import review_lock_name
from .review_runtime import digest,encoded

@contextmanager
def sheet_writer_lock(path):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    with path.open("a") as handle:
        try: fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as exc: raise RuntimeError("Another local Sheet writer is active; assessment remains staged") from exc
        try: yield
        finally: fcntl.flock(handle,fcntl.LOCK_UN)

def history_row(repo,key):
    found=[(n,r) for n,r in repo.read_columns("Job History",["Job Key"]) if r.get("Job Key")==key]
    if len(found)>1: raise ValueError("Duplicate Job Key; cannot choose a write target")
    if not found: return None
    row=repo.read_row("Job History",found[0][0])
    if row.get("Job Key")!=key: raise ValueError("Job moved during lookup")
    return row

def opportunity_rows(repo,old):
    company,url=str(old.get("Company","")).strip(),canonicalize_url(old["Official Job URL"]); found=[]
    for number,row in repo.read_columns("Opportunities",["Company","Job URL"]):
        if str(row.get("Company","")).strip().casefold()!=company.casefold(): continue
        try: same=canonicalize_url(str(row.get("Job URL","")))==url
        except ValueError: same=False
        if same:
            full=repo.read_row("Opportunities",number)
            if full.get("Company")!=row.get("Company") or full.get("Job URL")!=row.get("Job URL"): raise ValueError("Opportunity moved during lookup")
            found.append(full)
    if len(found)>1: raise ValueError("Duplicate Opportunities; reconcile before writeback")
    return found

def set_status(runtime,stage,key,source,state,detail):
    with runtime.transaction():
        row=runtime.db.execute("SELECT payload FROM decisions WHERE stage=? AND job_key=? AND source_hash=?",(stage,key,source)).fetchone()
        value=json.loads(row[0]); value.update(writeback_status=state,writeback_detail=detail)
        runtime.db.execute("UPDATE decisions SET payload=?,updated=? WHERE stage=? AND job_key=? AND source_hash=?",(encoded(value),runtime.clock(),stage,key,source))
        runtime.event(stage,key,source,"writeback_"+state,detail)
    runtime.export(stage)
    return {"job_key":key,"source_hash":source,"writeback_status":state,"detail":detail}

def preserved_rejection(intent):
    return (intent.get("decision")=="Reject" and intent.get("pass")==3 and intent.get("requires_opportunity") is True
            and intent.get("preserve_existing_opportunity") is True and intent.get("correction_kind")=="published_fit_or_questions_to_reject"
            and intent.get("correction_from_decision") in {"Accept","Needs Info"}
            and bool(intent.get("correction_id")))

def requires_opportunity(intent):
    """Accepts and explicitly routed third-pass questions require an Opportunity."""
    return preserved_rejection(intent) or intent.get("decision")=="Accept" or (intent.get("requires_opportunity") is True and intent.get("pass")==3 and intent.get("decision")=="Needs Info")

def verified(repo,intent):
    row=history_row(repo,intent["job_key"])
    if not row or row.get("Source Hash")!=intent["source_hash"]: return False
    if any(row.get(k,"")!=v for k,v in intent["history_values"].items()): return False
    if intent["marker"] not in str(row.get("Review Notes","")): return False
    matches=opportunity_rows(repo,row)
    if requires_opportunity(intent):
        return len(matches)==1 and all(matches[0].get(k,"")==v for k,v in intent["opportunity_values"].items())
    return True

def rejection_guard(matches):
    if len(matches)>1: raise ValueError("Duplicate Opportunities; reconcile before writeback")
    if not matches: return None
    row=matches[0]
    if str(row.get("Application Status","")).strip()!="Not Interested" or str(row.get("Fit Review","")).strip()!="Unlikely Fit":
        raise ValueError("Reject conflicts with an existing Opportunity; preserve it")
    return {"tab":"Opportunities","identity":{"Company":row["Company"],"Job URL":row["Job URL"]},"values":{"Application Status":"Not Interested","Fit Review":"Unlikely Fit"},"expected":{"Application Status":"Not Interested","Fit Review":"Unlikely Fit"}}


def guard_replayed_rejection(intent,matches):
    if intent["decision"]!="Reject" or preserved_rejection(intent): return intent
    guard=rejection_guard(matches)
    if guard and not any(op.get("tab")=="Opportunities" for op in intent["operations"]):
        return {**intent,"operations":[*intent["operations"],guard]}
    return intent

def current_manual_intent(runtime,intent,*,stage=None,repo=None,result=None,old=None,matches=None):
    """Upgrade queued intents only while the original expected values still hold."""
    if stage==3 and intent["decision"]=="Needs Info" and not requires_opportunity(intent):
        if repo is None or result is None or old is None:
            raise ValueError("Third-pass queued manual intent requires guarded Opportunity replanning")
        from .repository import _equivalent
        expected=next((op.get("expected",{}) for op in intent["operations"] if op.get("tab")=="Job History"),{})
        if any(not _equivalent(field,old.get(field,""),value) for field,value in expected.items()):
            raise ValueError("Live values changed since the saved manual intent; preserve and reconcile")
        intent=plan(runtime,repo,result,old,3,opportunity_matches=matches)
        with runtime.transaction():
            runtime.db.execute("UPDATE writeback SET payload=? WHERE job_key=? AND source_hash=?",(encoded(intent),intent["job_key"],intent["source_hash"]))
        return intent
    if stage==3: return intent
    if intent["decision"]!="Needs Info" or intent["history_values"].get("Added to Opportunities?")!="Pending": return intent
    intent={**intent,"history_values":{**intent["history_values"],"Added to Opportunities?":"Manual Review"},"operations":[
        {**operation,"values":{**operation["values"],"Added to Opportunities?":"Manual Review"}}
        if operation["tab"]=="Job History" and operation.get("values",{}).get("Added to Opportunities?")=="Pending" else operation
        for operation in intent["operations"]]}
    with runtime.transaction():
        runtime.db.execute("UPDATE writeback SET payload=? WHERE job_key=? AND source_hash=?",(encoded(intent),intent["job_key"],intent["source_hash"]))
    return intent

def plan(runtime,repo,result,old,stage,opportunity_matches=None,*,authorized_manual_conversion=False):
    key,source=result["job_key"],result["source_hash"]
    if old.get("Source Hash")!=source: raise ValueError("Source changed; do not apply a stale review")
    pending=str(old.get("Added to Opportunities?","")).casefold()=="pending" and old.get("Review Status")=="Needs Review"
    conversion=authorized_manual_conversion and stage==3 and result.get("decision")=="Needs Info" and old.get("Added to Opportunities?")=="Manual Review" and old.get("Review Status")=="Manual Review" and old.get("Decision")=="Needs Info"
    if not pending and not conversion: raise ValueError("Manual choice, completed review, or another Sheet claim prevents writeback")
    if str(old.get("Job Status","")).casefold()=="closed" or str(old.get("Reconsideration Status","")).casefold()=="frozen after 2" or reconsiderations(old)>=2: raise ValueError("Job is closed or frozen")
    decision=("Reject" if stage==1 else {"CLEAR_REJECT":"Reject","NEEDS_INFO":"Needs Info"}.get(result.get("triage_decision")) if stage==2 else result["decision"])
    if stage==1 and result.get("decision")!="PASS": raise ValueError("First-pass writeback is limited to saved PASS title rejections")
    if stage==2 and result.get("triage_decision") not in {"CLEAR_REJECT","NEEDS_INFO"}:
        raise ValueError("Second-pass writeback is limited to saved CLEAR_REJECT or NEEDS_INFO decisions")
    if not str(old.get("Company","")).strip() or not old.get("Official Job URL"): raise ValueError("Missing company/URL needed for write identity")
    matches=opportunity_rows(repo,old) if opportunity_matches is None else opportunity_matches
    if len(matches)>1: raise ValueError("Duplicate Opportunities; reconcile before writeback")
    if decision=="Reject": rejection_guard(matches)
    if decision=="Accept":
        location=result.get("location_check",{})
        if location.get("status")!="verified_us" or location.get("source_value")!=old.get("Location","") or not location.get("evidence"): raise ValueError("Acceptance needs verified_us location_check matching current Location source_value")
        if result.get("policy_conflicts"): raise ValueError("Unresolved policy conflicts prevent acceptance")
        from .screening import screen_posting
        evidence=runtime.hydrate(key,source,repo=repo)
        if not evidence.get("job_description"): raise ValueError("Missing exact description; acceptance cannot be written")
        screening=screen_posting({"title":old.get("Job Title",""),"description":evidence["job_description"],"compensation":old.get("Salary / Range","")})
        if screening.reason: raise ValueError("Acceptance conflicts with deterministic rule: "+screening.reason)
    stamp=datetime.now(timezone.utc).isoformat(timespec="seconds"); marker=f"[{ {1:'first',2:'second',3:'third'}[stage]}-pass {digest([key,source])[:16]}]"; reason=("Title-only review: " if stage==1 else "")+result["reason"]; note=(marker+" Unresolved questions moved to Opportunity per user instruction.") if conversion else marker+" "+reason
    values={"Review Started At":"","Last Evaluated":stamp}
    if stage in (1,2) and decision=="Reject":
        values.update({"Review Status":"Reviewed","Decision":"Reject","Fit Level":"","Added to Opportunities?":"No","Rejection Reason":reason})
        if stage==2: values["Description Hash"]=source
    elif decision=="Needs Info": values.update({"Review Status":"Reviewed" if stage==3 else "Manual Review","Decision":"Needs Info","Fit Level":"","Added to Opportunities?":"Yes" if stage==3 else "Manual Review",**({"Rejection Reason":""} if stage==3 else {})})
    else:
        values.update({"Review Status":"Reviewed","Decision":decision,"Fit Level":result.get("fit_level") or "","Added to Opportunities?":"Yes" if decision=="Accept" else "No","Rejection Reason":"" if decision=="Accept" else result["reason"],"Description Hash":source})
        if old.get("Description Hash") and old.get("Description Hash")!=source:
            count=reconsiderations(old)+1
            values.update({"Reconsideration Count":count,"Reconsideration Status":"Frozen after 2" if count>=2 else old.get("Reconsideration Status","Eligible"),"Material Change Summary":result.get("material_change_summary","Source version changed; third-pass reassessment completed.")})
    guards=["Company","Job Title","Official Job URL","Source Hash","Added to Opportunities?","Review Status","Review Started At","Decision","Description Hash","Job Status","Reconsideration Count","Reconsideration Status","Review Notes","Location","Salary / Range"]
    operations=[{"tab":"Job History","identity":{"Job Key":key},"values":values,"expected":{field:old.get(field,"") for field in guards},"append_notes":{"Review Notes":note}}]
    opportunity_values={}
    question_signature=None
    if decision=="Reject" and matches:
        operations.append(rejection_guard(matches))
    if decision=="Accept" or (stage==3 and decision=="Needs Info"):
        opportunity_values={"Job Title":old["Job Title"],"Fit Review":"Strong Potential Fit" if result.get("fit_level")=="Strong" else "Potential Fit","Last Checked":old.get("Last Checked","")}
        existing=matches[0] if matches else None
        if decision=="Needs Info":
            opportunity_values.pop("Fit Review")
            previous=str(existing.get("Review Questions","") or "") if existing else ""
            question=result["reason"]
            question_signature=digest([key,source,question])
            present=(previous==question or previous.startswith(question+"\n\n") or previous.endswith("\n\n"+question) or "\n\n"+question+"\n\n" in previous)
            opportunity_values["Review Questions"]=previous if present else previous+("\n\n" if previous else "")+question
        operations.append({"tab":"Opportunities","identity":{"Company":old["Company"],"Job URL":existing["Job URL"] if existing else old["Official Job URL"]},"values":opportunity_values,"append_if_missing":not bool(existing),"on_insert":{"Location":old.get("Location",""),"Salary / Range":old.get("Salary / Range",""),"Work Arrangement":old.get("Work Arrangement",""),"Application Status":"Not Reviewed","Date Applied":"","Date Found":stamp[:10],**({"Fit Review":""} if decision=="Needs Info" else {})},"expected":{k:existing.get(k,"") for k in opportunity_values} if existing else {}})
    return {"job_key":key,"source_hash":source,"decision":decision,"pass":stage,"requires_opportunity":decision=="Accept" or (stage==3 and decision=="Needs Info"),**({"question_signature":question_signature} if question_signature else {}),"marker":marker,"history_values":values,"opportunity_values":opportunity_values,"operations":operations}

def sync_clear_rejects(runtime,run_id,limit=25,*,repo=None,lock_path=None):
    """Compatibility wrapper for bounded pass-2 outcome synchronization."""
    return sync_pending(runtime,2,run_id,limit,repo=repo,lock_path=lock_path)


def sync_pending(runtime,stage,run_id,limit=25,*,repo=None,lock_path=None,identities=None):
    """One cooperating writer owns selection, delivery AND status persistence."""
    if stage not in (1,2,3): raise ValueError("Writeback supports pass 1, pass 2, or pass 3")
    if not 1<=limit<=100: raise ValueError("Sync limit must be between 1 and 100")
    from .runner import _load_environment
    _load_environment()
    with runtime.transaction(): runtime._owned(stage,run_id)
    lock_path=Path(lock_path) if lock_path is not None else runtime.queue.parent/review_lock_name()
    try:
        with sheet_writer_lock(lock_path):
            return _sync_pending_locked(runtime,stage,run_id,limit,repo=repo,identities=identities)
    except (RuntimeError,OSError) as exc:
        # A losing writer must never overwrite a winner's Written/Conflict state.
        return {"pass":stage,"run_id":run_id,"selected":0,"counts":{},"state":"WRITEBACK_DEFERRED","detail":str(exc),"queue":runtime.status(stage)}


def _sync_pending_locked(runtime,stage,run_id,limit=25,*,repo=None,identities=None):
    """Write a bounded batch of persisted decisions, then verify live values.

    Decision origin is deliberately irrelevant: imported hard no's need the same
    guarded writeback as newly managed results. Assessment conflicts are deferred.
    """
    if stage not in (1,2,3): raise ValueError("Writeback supports pass 1, pass 2, or pass 3")
    if not 1<=limit<=100: raise ValueError("Sync limit must be between 1 and 100")
    with runtime.transaction():
        runtime._owned(stage,run_id)
        candidates=runtime.db.execute("SELECT d.job_key,d.source_hash,d.payload FROM decisions d WHERE d.stage=? AND json_extract(d.payload,'$.writeback_status')='Pending' AND NOT EXISTS (SELECT 1 FROM conflicts c WHERE c.stage=d.stage AND c.job_key=d.job_key AND c.source_hash=d.source_hash) ORDER BY d.updated,d.job_key",(stage,)).fetchall()
        pending=[]
        for row in candidates:
            if stage==1 and json.loads(row["payload"]).get("decision")!="PASS": continue
            if stage==2 and json.loads(row["payload"]).get("triage_decision") not in {"CLEAR_REJECT","NEEDS_INFO"}: continue
            if identities is not None and (row["job_key"],row["source_hash"]) not in identities: continue
            pending.append(row)
            if len(pending)==limit: break
    if not pending: return {"pass":stage,"run_id":run_id,"selected":0,"counts":{},"queue":runtime.status(stage)}
    history_fields=["Company","Job Title","Official Job URL","Job Key","Source Hash","Added to Opportunities?","Review Status","Review Started At","Decision","Fit Level","Description Hash","Rejection Reason","Last Evaluated","Job Status","Reconsideration Count","Reconsideration Status","Review Notes","Location","Salary / Range","Last Checked","Work Arrangement","Material Change Summary"]
    opportunity_fields=["Company","Job URL","Job Title","Fit Review","Last Checked","Application Status","Review Questions"]
    updates=[]; intents=[]
    def history_snapshot():
        grouped={}
        for _,row in repo.read_columns("Job History",history_fields): grouped.setdefault(row.get("Job Key"),[]).append(row)
        return grouped
    def matches_for(old,opportunities):
        company=str(old.get("Company","")).strip().casefold()
        url=canonicalize_url(str(old.get("Official Job URL",""))); matches=[]
        for _,candidate in opportunities:
            if str(candidate.get("Company","")).strip().casefold()!=company: continue
            try: same=canonicalize_url(str(candidate.get("Job URL","")))==url
            except ValueError: same=False
            if same: matches.append(candidate)
        return matches
    def matches_intent(intent,rows,opportunities):
        if len(rows)!=1 or rows[0].get("Source Hash")!=intent["source_hash"]: return False
        row=rows[0]
        if not all(row.get(field,"")==value for field,value in intent["history_values"].items()): return False
        if intent["marker"] not in str(row.get("Review Notes","")): return False
        if requires_opportunity(intent):
            matches=matches_for(row,opportunities)
            return len(matches)==1 and all(matches[0].get(k,"")==v for k,v in intent["opportunity_values"].items())
        return True
    try:
        with nullcontext():  # The public entrypoint holds writer.lock through commit below.
            if repo is None:
                from .runner import _load_environment
                from .cli import get_repository
                _load_environment(); repo=get_repository(write=True,interactive=False)
            history=history_snapshot()
            opportunities=list(repo.read_columns("Opportunities",opportunity_fields))
            operations=[]
            for saved in pending:
                key,source=saved["job_key"],saved["source_hash"]
                # An amendment can arrive while waiting for the writer lock.
                current=runtime.db.execute("SELECT payload FROM decisions WHERE stage=? AND job_key=? AND source_hash=?",(stage,key,source)).fetchone()
                result=json.loads(current[0])
                if runtime.db.execute("SELECT 1 FROM conflicts WHERE stage=? AND job_key=? AND source_hash=?",(stage,key,source)).fetchone():
                    updates.append((key,source,"Conflict","Conflicting assessment must be reconciled before writeback")); continue
                if result.get("writeback_status")!="Pending": continue
                rows=history.get(key,[])
                if not rows:
                    updates.append((key,source,"Needs Staging","No History row; requires explicitly authorized keyed staging")); continue
                if len(rows)>1:
                    updates.append((key,source,"Conflict","Duplicate Job Key; cannot choose a write target")); continue
                old=rows[0]
                try:
                    if old.get("Source Hash")!=source: raise ValueError("Source changed; do not apply a stale review")
                    matches=matches_for(old,opportunities)
                    previous=runtime.db.execute("SELECT payload FROM writeback WHERE job_key=? AND source_hash=?",(key,source)).fetchone()
                    if previous:
                        intent=current_manual_intent(runtime,json.loads(previous[0]),stage=stage,repo=repo,result=result,old=old,matches=matches)
                        if matches_intent(intent,rows,opportunities):
                            updates.append((key,source,"Written","Previously uncertain write verified; no duplicate replay")); continue
                        if any(operation.get("tab")=="Opportunities" and any("Notes" in operation.get(field,{}) for field in ("values","on_insert","append_notes")) for operation in intent["operations"]):
                            raise ValueError("Saved write intent modifies personal Opportunities Notes; preserve and reconcile before retry")
                        if preserved_rejection(intent):
                            old=history_row(repo,key)
                            matches=opportunity_rows(repo,old)
                            if len(matches)!=1: raise ValueError("Correction requires its existing unique Opportunity")
                        intent=guard_replayed_rejection(intent,matches)
                        # Avoid letting one stale durable intent block unrelated jobs.
                        from .repository import _equivalent
                        for operation in intent["operations"]:
                            existing=old if operation["tab"]=="Job History" else matches[0] if len(matches)==1 else {}
                            if any(not _equivalent(field,existing.get(field,""),value) for field,value in operation.get("expected",{}).items()):
                                raise ValueError("Live values changed since the saved write intent; preserve and reconcile")
                    else:
                        if str(old.get("Added to Opportunities?","")).strip().casefold()=="no" and (stage in (1,2) or result.get("decision")!="Accept"):
                            updates.append((key,source,"Preserved","Existing No preserved; no Sheet fields changed")); continue
                        intent=plan(runtime,repo,result,old,stage,opportunity_matches=matches)
                        with runtime.transaction():
                            runtime._owned(stage,run_id)
                            runtime.db.execute("INSERT INTO writeback VALUES(?,?,?)",(key,source,encoded(intent)))
                    intents.append(intent); operations.extend(intent["operations"])
                except ValueError as exc:
                    updates.append((key,source,"Conflict",str(exc)))
            commit_error=""
            if operations:
                try: repo.commit(operations)
                except (RuntimeError,OSError,ValueError) as exc: commit_error=str(exc)
            refreshed=history_snapshot()
            refreshed_opportunities=list(repo.read_columns("Opportunities",opportunity_fields)) if any(requires_opportunity(intent) for intent in intents) else opportunities
            for intent in intents:
                ok=matches_intent(intent,refreshed.get(intent["job_key"],[]),refreshed_opportunities)
                updates.append((intent["job_key"],intent["source_hash"],"Written" if ok else "Pending","History and required Opportunity verified by readback" if ok else (commit_error or "Batch write verification incomplete; safe retry required")))
    except (RuntimeError,OSError) as exc:
        updates=[(row["job_key"],row["source_hash"],"Pending",str(exc)) for row in pending]
    counts={}
    with runtime.transaction():
        runtime._owned(stage,run_id)
        for key,source,state,detail in updates:
            row=runtime.db.execute("SELECT payload FROM decisions WHERE stage=? AND job_key=? AND source_hash=?",(stage,key,source)).fetchone()
            value=json.loads(row[0]); value.update(writeback_status=state,writeback_detail=detail)
            runtime.db.execute("UPDATE decisions SET payload=?,updated=? WHERE stage=? AND job_key=? AND source_hash=?",(encoded(value),runtime.clock(),stage,key,source))
            runtime.event(stage,key,source,"writeback_"+state,detail); counts[state]=counts.get(state,0)+1
    runtime.export(stage); runtime.checkpoint(stage,run_id)
    return {"pass":stage,"run_id":run_id,"selected":len(pending),"counts":counts,"queue":runtime.status(stage)}

def writeback(runtime,stage,run_id=None,key=None,source=None,*,repo=None,lock_path=None):
    # Backward-compatible direct Python API: older callers supplied
    # (runtime, run_id, key, source) for third-pass writeback.
    if not isinstance(stage,int):
        source,key,run_id,stage=key,run_id,stage,3
    from .runner import _load_environment
    _load_environment()
    with runtime.transaction(): runtime._owned(stage,run_id)
    lock_path=Path(lock_path) if lock_path is not None else runtime.queue.parent/review_lock_name()
    try:
        with sheet_writer_lock(lock_path):
            return _writeback_locked(runtime,stage,run_id,key,source,repo=repo)
    except (RuntimeError,OSError) as exc:
        # Report contention without changing durable delivery state outside the lock.
        return {"job_key":key,"source_hash":source,"writeback_status":"Pending","detail":str(exc),"state":"WRITEBACK_DEFERRED"}


def _writeback_locked(runtime,stage,run_id,key,source,*,repo=None):
    if stage not in (1,2,3): raise ValueError("Writeback supports pass 1, pass 2, or pass 3")
    with runtime.transaction():
        runtime._owned(stage,run_id)
        saved=runtime.db.execute("SELECT payload FROM decisions WHERE stage=? AND job_key=? AND source_hash=?",(stage,key,source)).fetchone()
        if not saved: raise ValueError("Persist the assessment before writeback")
        result=json.loads(saved[0])
        if stage==1 and result.get("decision")!="PASS": raise ValueError("First-pass writeback is limited to saved PASS title rejections")
        if stage==2 and result.get("triage_decision") not in {"CLEAR_REJECT","NEEDS_INFO"}: raise ValueError("Second-pass writeback is limited to CLEAR_REJECT or NEEDS_INFO")
        if result.get("writeback_status")=="Written": return {"writeback_status":"Written","reused":True,"job_key":key}
    try:
        with nullcontext():  # Held by writeback(), including exception status updates.
            # An authorized amendment may have replaced the pre-lock snapshot.
            # Read under the same writer lock before planning any Sheet writes.
            with runtime.transaction():
                runtime._owned(stage,run_id)
                saved=runtime.db.execute("SELECT payload FROM decisions WHERE stage=? AND job_key=? AND source_hash=?",(stage,key,source)).fetchone()
                if not saved: raise ValueError("Persist the assessment before writeback")
                result=json.loads(saved[0])
                if runtime.db.execute("SELECT 1 FROM conflicts WHERE stage=? AND job_key=? AND source_hash=?",(stage,key,source)).fetchone():
                    raise ValueError("Conflicting assessment must be reconciled before writeback")
                if result.get("writeback_status")=="Written": return {"writeback_status":"Written","reused":True,"job_key":key}
            if repo is None:
                from .runner import _load_environment
                from .cli import get_repository
                _load_environment(); repo=get_repository(write=True,interactive=False)
            previous=runtime.db.execute("SELECT payload FROM writeback WHERE job_key=? AND source_hash=?",(key,source)).fetchone()
            if previous:
                old=history_row(repo,key)
                if old is None: return set_status(runtime,stage,key,source,"Needs Staging","No History row; requires explicitly authorized keyed staging")
                intent=current_manual_intent(runtime,json.loads(previous[0]),stage=stage,repo=repo,result=result,old=old,matches=opportunity_rows(repo,old))
                if verified(repo,intent): return set_status(runtime,stage,key,source,"Written","Previously uncertain write verified; no duplicate replay")
                old=history_row(repo,key)
                if old is None: return set_status(runtime,stage,key,source,"Needs Staging","No History row; requires explicitly authorized keyed staging")
                intent=guard_replayed_rejection(intent,opportunity_rows(repo,old))
            else:
                old=history_row(repo,key)
                if old is None: return set_status(runtime,stage,key,source,"Needs Staging","No History row; requires explicitly authorized keyed staging")
                if old.get("Source Hash")==source and str(old.get("Added to Opportunities?","")).strip().casefold()=="no" and (stage in (1,2) or result.get("decision")!="Accept"):
                    return set_status(runtime,stage,key,source,"Preserved","Existing No preserved; no Sheet fields changed")
                intent=plan(runtime,repo,result,old,stage)
                with runtime.transaction():
                    runtime._owned(stage,run_id)
                    runtime.db.execute("INSERT INTO writeback VALUES(?,?,?)",(key,source,encoded(intent)))
            # Old durable intents must not replay writes to personal Notes.
            if any(operation.get("tab")=="Opportunities" and
                   any("Notes" in operation.get(field,{}) for field in ("values","on_insert","append_notes"))
                   for operation in intent["operations"]):
                raise ValueError("Saved write intent modifies personal Opportunities Notes; preserve and reconcile before retry")
            repo.commit(intent["operations"])
            if not verified(repo,intent): return set_status(runtime,stage,key,source,"Pending","Write returned but verification incomplete; reconcile before retry")
            return set_status(runtime,stage,key,source,"Written","History and required Opportunity verified by readback")
    except ValueError as exc: return set_status(runtime,stage,key,source,"Conflict",str(exc))
    except (RuntimeError,OSError) as exc: return set_status(runtime,stage,key,source,"Pending",str(exc))
