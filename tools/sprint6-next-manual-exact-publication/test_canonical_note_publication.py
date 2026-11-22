from copy import deepcopy
import json

import pytest

from job_search_helper.sheets_sync import SheetsSynchronizer as GuardedJobHistoryNotesSynchronizer
from job_search_helper.cli import writer_lock
from job_search_helper.exact_cycle_receipt import REPAIR_RETRY_PLAN_BINDING, repair_retry_has_confirmed_publication
from job_search_helper.exact_cycle_recovery import close_published_repair_retry
from job_search_helper.exact_cycle_sync import _company_guard, publish_exact_cycle
from job_search_helper.repository import UncertainWriteError
from job_search_helper.sheets_sync import SheetsSynchronizer
from test_saved_retry_composition import frozen_retry, retry
from test_verified_note_guards import held_app


def publish_fixture(engine, workbook, key, adapter):
    with writer_lock(engine.repo.path.parent/'scraper.lock'), writer_lock(engine.repo.path.parent/'writer.lock'):
        return publish_exact_cycle(engine.inbox,key[0],workbook,company_ids=[key[1]],state=engine.state,
            company_guard=lambda company,url:_company_guard(engine.repo,workbook,company,url),
            local=engine.repo,synchronizer=adapter)


def lose_first_response(remote, monkeypatch):
    commit=remote.commit
    def lost(operations):
        commit(operations)
        raise UncertainWriteError('synthetic workbook response lost after commit')
    monkeypatch.setattr(remote,'commit',lost)


@pytest.mark.parametrize('lose',[False,True])
def test_exact_normal_and_lost_response_closeout_without_replay(held_app,monkeypatch,lose):
    engine, remote, key, plan, approval, adopt=held_app
    assert adopt()=='NOTE_GUARDS_ADOPTED'
    adapter=GuardedJobHistoryNotesSynchronizer(engine.repo,remote)
    if lose:
        lose_first_response(remote,monkeypatch)
        first=publish_fixture(engine,remote,key,adapter)
        assert first['held'] and len(remote.commits)==1,first
        assert engine.inbox.exact_remote_state(*key)['first_attempt_claimed']
    recovered=publish_fixture(engine,remote,key,adapter)
    assert recovered['confirmed']==[key[1]],recovered
    assert len(remote.commits)==1
    assert engine.inbox.get(*key) is None and engine.inbox.exact_remote_state(*key) is None
    cycle=engine.state.cycle(key[0])
    binding=cycle['repair_retry']
    assert repair_retry_has_confirmed_publication(engine.inbox,engine.repo,cycle,key[1],require_complete=False)
    output=close_published_repair_retry(engine,*key,attempt_id=binding['attempt_id'],
        release_id=binding['release']['release_id'])
    assert output['outcome']=='COMPLETE'
    assert close_published_repair_retry(engine,*key,attempt_id=binding['attempt_id'],
        release_id=binding['release']['release_id'])==output
    assert engine.repo.scrape_outcomes()==[output]
    assert len(remote.commits)==1
    for index in range(4):
        [row]=[row for row in remote.snapshot('Job History') if row['Job Key']==f'historical:{index}']
        assert row['Review Notes']==f'Prior note {index}\n\nAppended fixture note {index}'
    engine.fetcher.assert_called_once()


@pytest.mark.parametrize('defect',['foreign_parent','extra_scope','unbound_observation'])
def test_durable_adapter_preserves_baseline_authority(held_app,monkeypatch,defect):
    engine, remote, key, plan, approval, adopt=held_app
    jobs,inbox=engine.repo,engine.inbox
    assert adopt()=='NOTE_GUARDS_ADOPTED'
    adapter=GuardedJobHistoryNotesSynchronizer(jobs,remote)
    lose_first_response(remote,monkeypatch)
    first=publish_fixture(engine,remote,key,adapter)
    assert first['held'] and len(remote.commits)==1,first
    pending=inbox.exact_remote_state(*key)
    receipt=inbox.receipt({'binding':plan[REPAIR_RETRY_PLAN_BINDING]})
    params=dict(inbox=inbox,cycle_id=key[0],company_id=key[1],plan_digest=plan['plan_digest'],
                receipt_id=receipt['receipt_id'],intent_id=pending['intent_id'])
    if defect=='foreign_parent':
        jobs.db.execute('UPDATE exact_local_applications SET plan_digest=? WHERE cycle=? AND company=?',
                        ('f'*64,*key))
    elif defect=='extra_scope':
        row_scope=json.loads(jobs.db.execute('SELECT row_scope FROM exact_local_applications '
                                             'WHERE cycle=? AND company=?',key).fetchone()[0])
        distinct={'Job Key':'extra-fixture'}
        jobs.import_rows('Job History',[(8,{**distinct,'Job Title':'Unrelated fixture'})])
        [(row_id,_)]=jobs.matches('Job History',distinct)
        row_scope.append({'tab':'Job History','identity':distinct,'fields':['Job Title'],'row_id':row_id,
                          'append_if_missing':False,'guards':{},'expected':{}})
        jobs.db.execute('UPDATE exact_local_applications SET row_scope=? WHERE cycle=? AND company=?',
                        (json.dumps(row_scope),*key))
    else:
        with inbox.connection:
            inbox.connection.execute("UPDATE exact_remote_plans SET delivery_mode='observation_only' WHERE cycle=? AND company=?",key)
    with pytest.raises(ValueError):
        SheetsSynchronizer(jobs,remote)._durable_exact_plan(**params)
    with pytest.raises(ValueError):
        adapter._durable_exact_plan(**params)
