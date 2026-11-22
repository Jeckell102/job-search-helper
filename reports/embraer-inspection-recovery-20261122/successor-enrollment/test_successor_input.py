import hashlib
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

import embraer_successor_enrollment_input as entry


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def record(*, request_id, source_revision, fingerprint):
    value = {'outcome': 'QUALIFIED_INTEGRATION_REPAIR', 'action': 'upsert_qualified_repair',
             'identity': {'request_id': request_id, 'company_id': 'COMP-0634',
                          'source_revision': source_revision},
             'failure_fingerprint': fingerprint, 'repair_category': 'full_description_regression'}
    immutable = {key: value[key] for key in ('identity', 'failure_fingerprint', 'outcome', 'repair_category')}
    return {'outcome_id': 'OUT-'+digest(immutable)[:24], **value}


@pytest.fixture
def sample(tmp_path, monkeypatch):
    project=tmp_path/'project'; root=project/'.state'; root.mkdir(parents=True)
    wrapper=project/'dev/wrapper-coder'; (wrapper/'tasks').mkdir(parents=True)
    old_manifest={'src/a.py':'a'*64,'docs/backlog/COMP-0634.md':'b'*64}
    new_manifest={**old_manifest,'docs/backlog/COMP-0634.md':entry.NOTE_SHA256}
    old,new=digest(old_manifest),digest(new_manifest)
    monkeypatch.setattr(entry,'OLD_BASELINE',old); monkeypatch.setattr(entry,'BASELINE',new)
    for value in (old,new): (wrapper/'pilot-bases'/('embraer-'+value)).mkdir(parents=True)
    selected={'request_id':entry.REQUEST,'request_sha256':entry.REQUEST_SHA256,'source_revision':'a'*64,
              'shared_boards_sha256':'b'*64,'ats_sha256':'c'*64,'baseline_sha256':old}
    pins=dict(entry.OWNER_PINS)
    predecessor = record(request_id=entry.OLD_REQUEST, source_revision=selected['source_revision'],
                         fingerprint=pins['failure_fingerprint'])
    fresh = record(request_id=entry.REQUEST, source_revision=selected['source_revision'],
                   fingerprint=pins['failure_fingerprint'])
    pins['predecessor_outcome_id'] = predecessor['outcome_id']
    pins['outcome_id'] = fresh['outcome_id']
    task={'id':pins['predecessor_task_id'],'held_repair_key':pins['predecessor_repair_key'],
          'status':'PAUSED','stop_requested':True,'sessions':3}
    pins['predecessor_task_state_sha256']=digest(task); monkeypatch.setattr(entry,'OWNER_PINS',pins)
    receipt=json.dumps({'outcome_id':pins['predecessor_outcome_id'],'disposition':'ACCEPTED'})
    pair=hashlib.sha256(receipt.encode()).hexdigest(); monkeypatch.setattr(entry,'PAIRED_RECEIPT',pair)
    owner=root/'operator-company-requests/embraer-pilot'/(hashlib.sha256(entry.OLD_REQUEST.encode()).hexdigest()+'.json')
    owner.parent.mkdir(parents=True)
    owner.write_text(json.dumps({'schema':'embraer-operator-pilot-enrollment-v1',
        'enrollment':{**selected,'request_id':entry.OLD_REQUEST,'request_sha256':entry.OLD_REQUEST_SHA256},
        'outcome_id':pins['predecessor_outcome_id'],'disarm_receipts':{'sender_receipt_sha256':pair,'receiver_receipt_sha256':pair}})); owner.chmod(0o600)
    evidence=tmp_path/'evidence'; evidence.mkdir(); monkeypatch.setattr(entry,'EVIDENCE',evidence)
    data={'PROPOSED_SUCCESSOR_OWNER_PINS.json':pins,'LIVE_WITHDRAW_RECEIPT.json':{
        'state':'EMBRAER_PILOT_WITHDRAWN','task_id':task['id'],'outcome_id':pins['predecessor_outcome_id'],
        'owner_record':str(owner)}}
    file_pins={}
    for name,value in data.items():
        path=evidence/name;path.write_text(json.dumps(value));file_pins[name]=hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(entry,'PIN_FILES',file_pins)
    database=wrapper/'tasks/tasks.sqlite3'
    with sqlite3.connect(database) as db:
        db.executescript('CREATE TABLE settings(key TEXT,value TEXT);CREATE TABLE tasks(id TEXT,state TEXT);'
            'CREATE TABLE inference_receipts(status TEXT);CREATE TABLE receipts(result TEXT);'
            'CREATE TABLE repair_intake(repair_key TEXT,outcome_id TEXT,company_id TEXT,source_revision TEXT,status TEXT,task_id TEXT,payload TEXT);'
            'CREATE TABLE scrape_outcome_delivery_receipts(consumer TEXT,outcome_id TEXT,receipt_sha256 TEXT,receipt TEXT);')
        db.executemany('INSERT INTO settings VALUES (?,?)',[('queue_enabled','false'),('campaign_enabled','false'),('autopilot_enabled','false'),('pilot_task','null')])
        db.execute('INSERT INTO tasks VALUES (?,?)',(task['id'],json.dumps(task)))
        db.execute('INSERT INTO repair_intake VALUES (?,?,?,?,?,?,?)',(pins['predecessor_repair_key'],pins['predecessor_outcome_id'],'COMP-0634',selected['source_revision'],'PROMOTED_PAUSED',task['id'],json.dumps(predecessor)))
        db.execute('INSERT INTO scrape_outcome_delivery_receipts VALUES (?,?,?,?)',('repair-coordinator',pins['predecessor_outcome_id'],pair,receipt))
    seen=[]
    def original_reader(**kw):
        assert kw['request_id']==entry.REQUEST and kw['request_sha256']==entry.REQUEST_SHA256
        seen.append('source')
        kw['source_reader'](None,fresh,entry.REQUEST_SHA256)
        return selected.copy(),pins['outcome_id']
    def repository_factory(path):
        assert path==root/'jobs.sqlite3'
        return SimpleNamespace(close=lambda:None,_outcome_delivery_rows=lambda *a,**k:[(None,)*6+(receipt,pair)])
    manifests={old:old_manifest,new:new_manifest}
    def run():
        return entry.read_operator_embraer_successor_enrollment(state_root=root,wrapper_base=wrapper,
            expected_source_manifest_sha256='e'*64,original_reader=original_reader,
            repository_factory=repository_factory,source_reader=lambda *a:{'actual':'source fixture'},
            baseline_files=lambda path:manifests[path.name.removeprefix('embraer-')],
            baseline_binding=lambda files:{'digest':digest(files)})
    return SimpleNamespace(run=run,db=database,owner=owner,task=task,selected=selected,pins=pins,
                           manifests=manifests,new=new,seen=seen,predecessor=predecessor)


def test_exact_readonly_successor_projection_preserves_original_input(sample):
    before_db=sample.db.read_bytes(); before_owner=sample.owner.read_bytes(); before_input=dict(sample.selected)
    selected,outcome=sample.run()
    assert outcome==sample.pins['outcome_id'] and selected['successor']==sample.pins
    assert selected['baseline_sha256']==sample.new and len(selected)==7
    assert sample.selected==before_input and sample.seen==['source']
    assert sample.db.read_bytes()==before_db and sample.owner.read_bytes()==before_owner
    assert sample.run()==(selected,outcome)


def test_drifted_receipt_stopped_task_baseline_and_missing_db_hold(sample):
    with sqlite3.connect(sample.db) as db:db.execute("UPDATE scrape_outcome_delivery_receipts SET receipt='changed'")
    with pytest.raises(ValueError,match='receiver receipt'):sample.run()
    with sqlite3.connect(sample.db) as db:
        db.execute('UPDATE tasks SET state=?',(json.dumps({**sample.task,'stop_requested':False}),))
    with pytest.raises(ValueError,match='stopped counted'):sample.run()
    sample.manifests[sample.new]['src/a.py']='f'*64
    with pytest.raises(ValueError,match='baseline'):sample.run()
    sample.manifests[sample.new]['src/a.py']='a'*64
    with sqlite3.connect(sample.db) as db:
        db.execute('UPDATE tasks SET state=?',(json.dumps(sample.task),))
        bad = {**sample.predecessor, 'failure_fingerprint': 'f' * 64}
        db.execute('UPDATE repair_intake SET payload=?', (json.dumps(bad),))
    with pytest.raises(ValueError, match='classifier'):
        sample.run()
    sample.db.rename(sample.db.with_suffix('.saved'))
    with pytest.raises(FileNotFoundError):sample.run()
    assert not sample.db.exists()
