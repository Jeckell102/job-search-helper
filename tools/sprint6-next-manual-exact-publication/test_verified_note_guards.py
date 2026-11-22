from copy import deepcopy
import json
import sqlite3

import pytest

from verified_note_guards import adopt_note_guards, measure_note_guards
from rejected_retry_plan import _encode, _sha
from job_search_helper.exact_cycle_planner import _exact_plan_digest, _seal_exact_plan_v2
from job_search_helper.exact_cycle_receipt import REPAIR_RETRY_PLAN_BINDING, repair_retry_receipt_binding
from job_search_helper.exact_cycle_recovery import recover_exact_cycle
from test_saved_retry_composition import frozen_retry, retry


@pytest.fixture
def held_app(frozen_retry):
    fixture=frozen_retry
    engine=fixture['engine']
    db,inbox=engine.repo,engine.inbox
    remote=fixture['workbook']
    key=fixture['key']
    company=db.read('Companies')[0]['Company']
    baseline=[]
    note_ops=[]
    for index in range(4):
        stable={'Job Key':f'historical:{index}'}
        url=f'https://fixture.invalid/historical/{index}'
        values={'Company':company,'Official Job URL':url,'Job Title':'Historical fixture',
                'Source Hash':f'{index+1:064x}','Review Notes':f'Prior note {index}',
                'Material Change Summary':'','Job Status':'Open and verified'}
        baseline.append((index+2,{**stable,**values}))
        remote.commit([{'tab':'Job History','identity':stable,'append_if_missing':True,
                        'values':{k:v for k,v in values.items() if k in remote.schemas['Job History']}}])
        note_ops.append({'tab':'Job History','identity':stable,'values':{'Material Change Summary':'Curated fixture note'},
             'expected':{'Material Change Summary':'','Review Notes':values['Review Notes'],'Added to Opportunities?':''},
             'append_notes':{'Review Notes':f'Appended fixture note {index}'}})
    remote.commits.clear()
    db.import_rows('Job History',baseline)
    old=fixture['candidate']
    payload,blocked=inbox.get(*key)
    assert not blocked
    plan=_seal_exact_plan_v2({
        **{k:deepcopy(old[k]) for k in ('final','requested_url','control_evidence',
                         'control_evidence_version','control_evidence_digest')},
        'operations':note_ops+deepcopy(old['local_operations']),
    },payload,db,*key)
    plan[REPAIR_RETRY_PLAN_BINDING]=old[REPAIR_RETRY_PLAN_BINDING]
    plan['plan_digest']=_exact_plan_digest(plan)
    raw=_encode(plan)
    with inbox.connection:
        inbox.connection.execute('UPDATE sync_plans SET payload=? WHERE cycle=? AND company=?',(raw,*key))
        inbox.connection.execute('UPDATE exact_plan_local_state SET plan_digest=?,local_operations_digest=?,'
            'remote_projection_digest=? WHERE cycle=? AND company=?',
            (plan['plan_digest'],plan['local_operations_digest'],plan['remote_projection_digest'],*key))
    failure=recover_exact_cycle(engine,remote,key[0],[key[1]])
    assert len(failure['held'])==1 and 'Exact Sheets Source Hash guard is required' in failure['held'][0]['reason'],failure
    assert not remote.commits and inbox.exact_remote_state(*key) is None
    assert inbox.exact_local_state(*key)['state']=='LOCAL_VERIFIED'
    cycle=fixture['state'].cycle(key[0])
    receipt=inbox.receipt({'binding':repair_retry_receipt_binding(cycle,key[1])})
    assert receipt['state']=='LOCAL_COMMITTED'
    approval={'cycle_id':key[0],'company_id':key[1],'attempt_id':fixture['binding']['attempt_id'],
        'release_id':fixture['binding']['release']['release_id'],'plan_digest':plan['plan_digest'],
        'plan_file_sha256':_sha(raw),'verified_scope':measure_note_guards(db,*key,plan)}
    def adopt(claims=approval):
        return adopt_note_guards(inbox,db,cycle,key[1],claims,timestamp='2026-11-22T04:55:00Z')
    return engine, remote, key, plan, approval, adopt


def test_guard_metadata_history_chunks_and_inbox_stay_exact(held_app):
    engine, remote, key, plan, approval, adopt=held_app
    jobs=engine.repo.db
    inbox=engine.inbox.connection
    app=approval['verified_scope']['apply_id']
    before_jobs=tuple(jobs.iterdump())
    before_inbox=tuple(inbox.iterdump())
    def protected():
        return tuple(jobs.execute('SELECT * FROM records ORDER BY tab,row_id')), tuple(
            jobs.execute('SELECT * FROM exact_local_apply_chunks WHERE apply_id=? ORDER BY start_cursor',(app,)))
    preserved=protected()
    wrong=deepcopy(approval)
    wrong['verified_scope']['chunk_evidence_sha256']='0'*64
    with pytest.raises(ValueError,match='pre-apply note evidence changed'):
        adopt(wrong)
    assert before_jobs==tuple(jobs.iterdump()) and before_inbox==tuple(inbox.iterdump())
    with inbox:
        inbox.execute('INSERT INTO exact_sync_chunks VALUES (?,?,?,?,?,?)',(*key,0,1,'fixture','PENDING'))
    with pytest.raises(ValueError,match='Remote work already exists'):
        adopt()
    with inbox:
        inbox.execute('DELETE FROM exact_sync_chunks WHERE cycle=? AND company=?',key)
    before_inbox=tuple(inbox.iterdump())
    jobs.execute("""CREATE TRIGGER inject_private_cut BEFORE UPDATE ON exact_local_applications
                    BEGIN SELECT RAISE(ABORT,'private guard update failure'); END""")
    before_cut=tuple(jobs.iterdump())
    with pytest.raises(sqlite3.IntegrityError,match='private guard update failure'):
        adopt()
    assert before_cut==tuple(jobs.iterdump())
    jobs.execute('DROP TRIGGER inject_private_cut')
    assert adopt()=='NOTE_GUARDS_ADOPTED'
    approved_row=jobs.execute('SELECT approval,original_scope,selected_scope FROM exact_retry_note_guard_archive '
                              'WHERE apply_id=?',(app,)).fetchone()
    assert approved_row[0]==_encode(approval)
    before_scope=json.loads(approved_row[1])
    after_scope=json.loads(approved_row[2])
    assert len(before_scope)==len(after_scope)
    delta=0
    for original, selected in zip(before_scope,after_scope):
        actual=deepcopy(selected)
        if 'Source Hash' not in original['guards'] and original['tab']=='Job History':
            assert actual['guards'].pop('Source Hash')
            delta+=1
        assert actual==original
    assert delta==4
    assert protected()==preserved and tuple(inbox.iterdump())==before_inbox and not remote.commits
    preserved_after=tuple(jobs.iterdump())
    assert adopt()=='NOTE_GUARDS_ALREADY_ADOPTED'
    assert tuple(jobs.iterdump())==preserved_after


def test_guard_adoption_does_not_repair_unmodified_renderer(held_app):
    engine, remote, key, plan, approval, adopt=held_app
    assert adopt()=='NOTE_GUARDS_ADOPTED'
    result=recover_exact_cycle(engine,remote,key[0],[key[1]])
    assert not remote.commits and engine.inbox.exact_remote_state(*key) is None
    assert result['held'][0]['reason']=='Exact Sheets scoped plan differs from the frozen projection.',result


def test_unmodified_durable_ack_drops_append_after_one_real_send(held_app):
    """Isolate the downstream cut behind the already known renderer mismatch."""
    from job_search_helper.exact_cycle_sync import _remote_intent_id
    from job_search_helper.exact_local_plan import _final_identity, exact_local_plan
    from job_search_helper.sheets_sync import SheetsSynchronizer
    engine, remote, key, plan, approval, adopt=held_app
    assert adopt()=='NOTE_GUARDS_ADOPTED'
    sync=SheetsSynchronizer(engine.repo, remote)
    parent=exact_local_plan(engine.repo,*key)
    prepared=[]
    for operation in plan['remote_projection']:
        identity=_final_identity(operation)
        [item]=[item for item in parent['row_scope'] if item['tab']==operation['tab'] and item['identity']==identity]
        [(_, row)]=engine.repo.matches(item['tab'],identity)
        prepared.append({**item,'sent':deepcopy(row),'operation':deepcopy(operation)})
    # Fixture only: supply already validated selected rendering so the real
    # first write, durable remote confirmation and local ack can be exercised
    # even though the unmodified renderer fails earlier.
    frozen={'rows':prepared,'operations':plan['remote_projection'],'projection_digest':plan['remote_projection_digest'],
            'delivery_mode':'write_once'}
    receipt=engine.inbox.receipt({'binding':plan[REPAIR_RETRY_PLAN_BINDING]})
    intent=_remote_intent_id(*key,plan['plan_digest'],plan['remote_projection_digest'])
    options={'inbox':engine.inbox,'cycle_id':key[0],'company_id':key[1],'plan_digest':plan['plan_digest'],
             'receipt_id':receipt['receipt_id'],'intent_id':intent}
    engine.inbox.freeze_exact_remote_plan(
        *key,local_plan_digest=plan['plan_digest'],projection=plan['remote_projection'],
        projection_digest=plan['remote_projection_digest'],receipt_id=receipt['receipt_id'],
        intent_id=intent,timestamp='2026-11-22T04:56:00Z')
    sync.publish_exact_scope(frozen,**options)
    assert len(remote.commits)==1
    with pytest.raises(ValueError,match='Exact Sheets confirmed value differs from frozen sent value'):
        sync.confirm_and_acknowledge_exact_scope(**options)
    state=engine.inbox.exact_remote_state(*key)
    assert state['first_attempt_claimed'] and state['remote_cursor']==len(plan['remote_projection'])
    assert engine.inbox.get(*key) is not None and not engine.repo.scrape_outcomes()
    assert len(engine.repo.db.execute('SELECT * FROM exact_local_acknowledgements').fetchall())==0
    with pytest.raises(ValueError,match='Exact Sheets confirmed value differs from frozen sent value'):
        sync.confirm_and_acknowledge_exact_scope(**options)
    assert len(remote.commits)==1
