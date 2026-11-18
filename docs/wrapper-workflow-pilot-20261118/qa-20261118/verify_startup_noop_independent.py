"""Read-only source backup, then two disposable startup recovery invocations."""
from pathlib import Path
from contextlib import contextmanager
from unittest.mock import patch
import hashlib,json,sqlite3,sys,tempfile
QA=Path(__file__).resolve().parent
HOST=QA.parent/'wrapper-workflow-20261118/host'
sys.path.insert(0,str(HOST))
from coordinator_store import Store
from test_startup_session_noop import database_snapshot

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()

source=Path('/tmp/wrapper-final-v2-migration-rehearsal/tasks.sqlite3')
evidence={'source':str(source),'real_inference_calls':0,'production_mutations':0,'recoveries':[]}
with tempfile.TemporaryDirectory(prefix='independent-startup-noop-') as folder:
    target=Path(folder)/'tasks.sqlite3'
    with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True) as before:
        with sqlite3.connect(target) as out:
            before.backup(out)
    store=Store(folder)
    initial=database_snapshot(store)
    evidence['task_count']=len(initial['tasks'])
    evidence['registry_count']=len(initial['campaign_company_registry'])
    evidence['initial_database_digest']=digest(initial)
    assert evidence['task_count']==111
    assert evidence['registry_count']==102
    assert all('inference_session_open' not in json.loads(row[1]) for row in initial['tasks'])
    controls={key:json.loads(value) for key,value in initial['settings']}
    assert controls['queue_enabled'] is False and controls['autopilot_enabled'] is False and controls.get('campaign_enabled',False) is False and controls.get('pilot_task') is None
    connect=store.connect
    for index in range(2):
        statements=[]
        @contextmanager
        def traced():
            with connect() as db:
                db.set_trace_callback(statements.append)
                yield db
        with patch.object(store,'connect',traced):
            store.recover()
        actual=database_snapshot(store)
        updates=[sql for sql in statements if sql.lstrip().upper().startswith(('UPDATE','INSERT','DELETE','REPLACE'))]
        assert actual==initial
        assert not updates
        evidence['recoveries'].append({'index':index+1,'database_digest':digest(actual),'changed_tables':[],'mutation_statement_count':len(updates)})
    with store.connect() as db:
        evidence['integrity']=db.execute('PRAGMA integrity_check').fetchone()[0]
    assert evidence['integrity']=='ok'
evidence['source_hashes']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(HOST.glob('*.py'))}
evidence['result']='PASS'
(QA/'independent-startup-noop-verification.json').write_text(json.dumps(evidence,indent=2)+'\n')
print('PASS: actual migrated 111-task copy, registry102, two recovery calls, exact complete database equality, zero mutation statements, controls OFF, integrity OK.')
