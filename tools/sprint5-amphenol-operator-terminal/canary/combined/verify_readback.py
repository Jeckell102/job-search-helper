from contextlib import closing, ExitStack
from hashlib import sha256
from pathlib import Path
import json
import sqlite3
import stat

stage = Path('/tmp/jsh-amphenol-operator-combined.hfpsslle')
run = stage/'run-__8sidmc'
project = run/'project'
state_dir = project/'.state'
original_run = stage/'run-695d3e03'

def raw_sha(raw):
    return sha256(raw).hexdigest()

def sha(data):
    return raw_sha(json.dumps(data, sort_keys=True, separators=(',',':'), ensure_ascii=False).encode())

def packet(path):
    return json.loads(path.read_bytes())

def metadata(path):
    attrs=path.stat()
    assert path.resolve(strict=True)==path and path.is_file() and attrs.st_nlink==1
    return {'sha256':raw_sha(path.read_bytes()), 'size':attrs.st_size, 'mode':stat.S_IMODE(attrs.st_mode)}

def tree(base):
    root=base/'src/job_search_helper'
    return {file.relative_to(root).as_posix(): metadata(file) for file in root.rglob('*')
            if file.is_file() and file.suffix in ('.py','.json') and '__pycache__' not in file.parts}

def disk(paths):
    result={}
    for path in paths:
        for suffix in ('','-wal','-shm','-journal'):
            item=path.with_name(path.name+suffix)
            if item.exists():
                attrs=item.stat()
                assert suffix not in ('-wal','-journal') or attrs.st_size==0
                result[item]=(attrs.st_ino,attrs.st_mtime_ns,attrs.st_ctime_ns,attrs.st_size,
                              raw_sha(item.read_bytes()))
    return result

result=packet(run/'RESULT.json')
assert result['result']=='PASS_DISPOSABLE_WORKER_AND_COORDINATOR' and result['native_qualification'] is False
release,attempt,retry_id,failed=(result[k] for k in ('release_id','attempt_id','outcome_id','failed_request_id'))
request='company-retry:'+attempt
assert packet(run/'TERMINAL.json')=={'state':'RECIPE_RETRY_CONFIRMED','attempt_id':attempt,'outcome_id':retry_id}
first=packet(run/'FIRST.json')
assert first['release']['state']=='REQUEST_WRITTEN' and first['retry']['state']=='COMPLETE'
manifest=packet(run/'manifest.json')
release_dir=run/'records'/release
active=packet(state_dir/'integration-release-journal.json')
release_receipt=packet(release_dir/'receipt.json')
assert packet(release_dir/'manifest.json')==manifest and active['state']==release_receipt['state']=='COMPLETE'
assert sha(manifest)==active['manifest_sha256']==release_receipt['manifest_sha256']
assert sha(release_receipt)==active['receipt_sha256'] and active['record']==str(release_dir)
assert release==manifest['release_id'] and failed==manifest['failed_request_id']
target,=manifest['files']
assert target=='src/job_search_helper/acquiretm.py'
after=metadata(project/target)
before=metadata(release_dir/'before'/target)
assert after==metadata(run/'candidate'/target)==manifest['files'][target]['after']
assert before==manifest['files'][target]['before']
assert before['sha256']=='a95953afe2bc10138714f6b11af22572b17ab344bf61d78b834647895025aa61'
assert (project/target).read_bytes()==(release_dir/'before'/target).read_bytes()+b'\n# Disposable qualified-owner worker contract fixture.\n'
installed=tree(project)
assert installed==tree(run/'candidate') and sha(installed)==manifest['source_manifest_sha256']
assert sha({**installed,'acquiretm.py':before})==manifest['before_source_manifest_sha256']
for name,pin in result['source_pins'].items():
    assert metadata(project/name)['sha256']==pin
assert metadata(project/'dev/wrapper-coder/tools/amphenol_retry_completion.py')['sha256']=='1b598db426c24611adc5303a71c4f9d21fe4ddc5e2560459be7a78d1989abf67'
ticket=packet(run/'approval'/(release+'.json'))
assert ticket['manifest_sha256']==sha(manifest)
assert ticket['candidate_validation_sha256']==sha(release_receipt['verification'])
assert ticket['capture_manifest_sha256']==metadata(project/'provider-fixture.json')['sha256']
assert ticket['reviewed_tools_sha256']==metadata(stage/'offline_child.py')['sha256']
assert release_receipt['verification']['fixture_only'] is True

paths=[state_dir/'jobs.sqlite3',run/'fixture-coordinator/tasks.sqlite3',
       state_dir/'state.db',state_dir/'inventories.sqlite3']
snapshot=disk(paths)
company='COMP-0490'
with ExitStack() as stack:
    jobs,coord,state,inbox=(stack.enter_context(closing(sqlite3.connect(path.as_uri()+'?mode=ro&immutable=1',uri=True))) for path in paths)
    assert all(conn.execute('PRAGMA quick_check').fetchall()==[('ok',)] for conn in (jobs,coord,state,inbox))
    outcomes={ident:json.loads(raw) for ident,raw in jobs.execute('SELECT outcome_id,payload FROM scrape_outcomes')}
    assert len(outcomes)==2 and outcomes[retry_id]==first['retry']['outcome']
    origin_id,=[ident for ident in outcomes if ident!=retry_id]
    origin,retry=outcomes[origin_id],outcomes[retry_id]
    assert origin['identity']['request_id']==failed and origin['outcome']=='QUALIFIED_INTEGRATION_REPAIR'
    assert 'company_event_id' not in origin['identity'] and retry['identity']['request_id']==request and retry['outcome']=='COMPLETE'
    sql='SELECT consumer,outcome_id,record_sha256,receipt,receipt_sha256 FROM scrape_outcome_delivery_receipts ORDER BY outcome_id'
    pairs=jobs.execute(sql).fetchall()
    assert pairs==coord.execute(sql).fetchall() and len(pairs)==2
    for consumer,ident,record_hash,raw,receipt_hash in pairs:
        receipt=json.loads(raw)
        status='VALIDATED_COMPLETE' if ident==retry_id else 'HELD_FOR_REPAIR_TRIAGE'
        assert (consumer,receipt['outcome_id'],receipt['sink_status'])==('repair-coordinator',ident,status)
        assert record_hash==sha(outcomes[ident]) and receipt_hash==raw_sha(raw.encode())
        assert coord.execute('SELECT sink_status FROM scrape_outcome_delivery_receipts WHERE outcome_id=?',(ident,)).fetchone()==(status,)
        assert json.loads(coord.execute('SELECT payload FROM scrape_outcome_intake WHERE outcome_id=?',(ident,)).fetchone()[0])==outcomes[ident]
        assert jobs.execute('SELECT count(*) FROM scrape_outcome_deliveries WHERE consumer=? AND outcome_id=?',(consumer,ident)).fetchone()==(1,)
    rel_pin=retry['identity']['release_binding_sha256']
    lifecycle=coord.execute('SELECT attempt_id,failed_request_id,release_version,release_binding_sha256,state,first_outcome_id,latest_outcome_id FROM repair_retry_lifecycles').fetchall()
    assert lifecycle==[(attempt,failed,release,rel_pin,'VALIDATED_COMPLETE',retry_id,retry_id)]
    event,=coord.execute('SELECT outcome_id,attempt_id,event_kind,payload FROM repair_retry_outcome_events')
    assert event[:3]==(retry_id,attempt,'COMPLETE') and json.loads(event[3])==retry
    assert coord.execute('SELECT outcome_id,status,task_id FROM repair_intake').fetchall()==[(origin_id,'SUPERSEDED_BY_REPAIRED_RETRY',None)]
    for db,tables in ((coord,('tasks','inference_receipts')), (jobs,('company_event_outbox','company_event_deliveries','scrape_outcome_delivery_attempts'))):
        assert all(db.execute('SELECT count(*) FROM '+name).fetchone()==(0,) for name in tables)
    old_id,new_id=origin['identity']['cycle_id'],retry['identity']['cycle_id']
    cycles={ident:json.loads(raw) for ident,raw in state.execute('SELECT id,data FROM cycles')}
    assert set(cycles)=={old_id,new_id} and cycles[old_id]['status']=='Complete with exceptions' and cycles[new_id]['status']=='Complete'
    assert cycles[old_id]['operator_request']['request_id']==failed and not cycles[old_id].get('company_event')
    intent=packet(state_dir/'repair-retry/intents'/(attempt+'.json'))
    assert intent==cycles[new_id]['repair_retry'] and intent['release']==active['release']
    assert sha(intent['release'])==rel_pin
    settlement_raw,=jobs.execute('SELECT payload FROM operator_amphenol_settlements').fetchall()
    settlement=json.loads(settlement_raw[0])
    scanned=[json.loads(row[0]) for row in jobs.execute("SELECT data FROM records WHERE tab='Scan Cycles'")]
    mirror,=[row for row in scanned if row['Cycle ID']==old_id]
    assert settlement['outcome']==origin and settlement['terminal_state_sha256']==sha(cycles[old_id])
    assert settlement['terminal_mirror_sha256']==sha(mirror)
    pub,=inbox.execute('SELECT receipt_id,binding,state,acknowledgement_id FROM publication_receipts')
    assert inbox.execute('SELECT id FROM destination').fetchall()==[('fixture-sheet',)] and pub[2]=='SYNC_CONFIRMED'
    assert json.loads(pub[1])=={'company_id':company,'release_binding_sha256':rel_pin,'release_id':release,
                              'request_id':request,'source_revision':manifest['source_revision']}
    assert jobs.execute('SELECT receipt_id,acknowledgement_id FROM exact_local_acknowledgements').fetchall()==[(pub[0],pub[3])]
    workbook=packet(state_dir/'workbook-after.json')
    workbook_before=packet(project/'workbook-before.json')
    local=[json.loads(row[0]) for row in jobs.execute("SELECT data FROM records WHERE tab='Job History'")]
    selected=[row['Job Key'] for row in local if row['Company']=='Amphenol Aerospace']
    assert selected==[row['Job Key'] for row in workbook['jobs'] if row['Company']=='Amphenol Aerospace']
    assert selected==['comp-0490:acquiretm:fixture-1'] and workbook['batches']==1
    for table,key,value in (('Companies','Company ID','COMP-OTHER'),('Job History','Job Key','other-existing')):
        row_before,=[row for row in workbook_before[table] if row[key]==value]
        row_after,=[row for row in (json.loads(raw[0]) for raw in jobs.execute('SELECT data FROM records WHERE tab=?',(table,))) if row[key]==value]
        assert row_after==row_before

workers=[json.loads(row) for row in (state_dir/'workers.jsonl').read_text().splitlines()]
expected={'state':'COMPLETE',**{k:v for k,v in active['release'].items() if k!='schema'}}
assert len(workers)==len({row['pid'] for row in workers})==2 and all(row['runtime']==expected for row in workers)
assert all((state_dir/marker).read_text()==release for marker in ('fetch-once','workbook-once'))
trace=[json.loads(row) for row in (state_dir/'publication-trace.jsonl').read_text().splitlines()]
assert [row['function'] for row in trace]==['freeze_exact_cycle_plans','_recover_exact_cycle_locked']
assert trace[1]['result']['confirmed']==[company] and not (state_dir/'company-event-bridge').exists()
assert disk(paths)==snapshot
old_child,=list((original_run/'project/.venv').rglob('offline_child.py'))
new_child,=list((project/'.venv').rglob('offline_child.py'))
assert new_child.read_bytes()==(stage/'offline_child.py').read_bytes()
assert '/tmp/jsh-operator-worker-proof.20261121' in old_child.read_text() and str(stage) in new_child.read_text()
assert packet(original_run/'FIRST.json')['retry']['state']=='RETRY_INVENTORY_HELD'
assert packet(original_run/'FAILURE.json')['native_qualification'] is False
assert not (original_run/'project/.state/workers.jsonl').exists() and not (original_run/'RESULT.json').exists()
print(json.dumps({'verdict':'ACCEPT_DISPOSABLE_COMBINED_RUN','origin_outcome':origin_id,'retry_outcome':retry_id,
                  'sender_receiver_pairs':len(pairs),'single_lifecycle':lifecycle[0][4],'publication_receipt':pub[0],
                  'fixture_connector_sha256':after['sha256'],'job_key':selected[0],'fixture_batches':workbook['batches'],
                  'measured_pids':[row['pid'] for row in workers],'immutable_databases_verified':len(paths),
                  'original_cut_preserved':'RETRY_INVENTORY_HELD'},sort_keys=True))
