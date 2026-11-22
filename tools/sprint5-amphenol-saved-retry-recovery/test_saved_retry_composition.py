"""Private composition across normal retry admission, exact recovery and closeout."""
from contextlib import contextmanager
from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

import recover_saved_retry as recovery
from rejected_retry_plan import _encode, _sha
from job_search_helper.ats import Inventory
from job_search_helper.cli import writer_lock
from job_search_helper.exact_cycle_planner import (
    _exact_plan_digest, _seal_exact_plan_v2, freeze_exact_cycle_plans,
)
from job_search_helper.exact_cycle_receipt import (
    REPAIR_RETRY_PLAN_BINDING, repair_retry_has_confirmed_publication,
)
from job_search_helper.exact_cycle_recovery import close_published_repair_retry
from job_search_helper.exact_cycle_sync import _company_guard
from job_search_helper.sheet_profile import COMPACT_PROFILE, COMPACT_SCHEMAS
from test_exact_cycle_recovery import RecordingRemote
from test_repair_retry_admission_replay import admit, retry


STAMP = '2026-11-22T04:20:00Z'


def archive(inbox, key):
    table = inbox.connection.execute("SELECT 1 FROM sqlite_schema WHERE name='rejected_retry_plan_archive'").fetchone()
    if table is None:
        return None
    return inbox.connection.execute('SELECT * FROM rejected_retry_plan_archive WHERE cycle=? AND company=?',key).fetchone()


@pytest.fixture
def frozen_retry(retry, monkeypatch):
    bridge,binding,engine,state=retry
    jobs,inbox=engine.repo,engine.inbox
    company=binding['company_id']
    jobs.ensure_columns('Opportunities',['Opportunity ID'])
    jobs.set_meta('sheets_profile',COMPACT_PROFILE)
    rows=jobs.read('Companies')
    url=rows[0]['Official Careers URL']
    posting={'posting_id':'fixture-1','title':'Implementation Manager','url':url+'/jobs/1','location':'Remote',
             'description':'Full fabricated job description with implementation, deployment and customer success responsibilities.',
             'ats':'AcquireTM'}
    assert bridge.deliver(binding)['state']=='REQUEST_WRITTEN'
    cycle=admit(bridge,engine,state)
    key=(cycle,company)
    engine.fetcher=Mock(spec=lambda *_: None, return_value=Inventory('complete',[posting],source_url=url,ats='AcquireTM'))
    with writer_lock(bridge.database.parent/'scraper.lock'):
        assert engine.resume_local(cycle,fetch_workers=1,assignment_window=1,defer_sync=True)[
            'attempted_company_ids']==[company]
    engine.fetcher.assert_called_once()
    engine.fetcher.side_effect=AssertionError('recovery unexpectedly fetched')
    clean_company=jobs.read('Companies')
    workbook=RecordingRemote(clean_company,schemas=COMPACT_SCHEMAS)
    workbook.spreadsheet_id=jobs.spreadsheet_id
    report=freeze_exact_cycle_plans(engine,cycle,[company],company_guard=lambda cid,selected_url:
        _company_guard(jobs,workbook,cid,selected_url),stamp=STAMP)
    assert report['planned']==[company],report
    candidate,cursor=inbox.plan(*key)
    assert cursor==0
    payload,blocked=inbox.get(*key)
    assert not blocked
    # A real guarded operation that cannot apply in the fixture case. Its
    # separate exact seal proves rejection is not caused by malformed bytes.
    old=deepcopy(candidate)
    local=old['local_operations']
    company_op=next(op for op in local if op['tab']=='Companies')
    company_op.setdefault('expected',{})['Company Status']='Paused'
    frozen_shape={'operations':local,'requested_url':candidate['requested_url'],
        'final':deepcopy(candidate['final']),'control_evidence':deepcopy(candidate['control_evidence']),
        'control_evidence_version':candidate['control_evidence_version'],
        'control_evidence_digest':candidate['control_evidence_digest']}
    original=_seal_exact_plan_v2(frozen_shape,payload,jobs,*key)
    original[REPAIR_RETRY_PLAN_BINDING]=candidate[REPAIR_RETRY_PLAN_BINDING]
    original['plan_digest']=_exact_plan_digest(original)
    assert original['plan_digest']!=candidate['plan_digest']
    with inbox.connection as db:
        db.execute('UPDATE sync_plans SET payload=? WHERE cycle=? AND company=?',
                   (json.dumps(original,sort_keys=False),*key))
        db.execute('UPDATE exact_plan_local_state SET plan_digest=?,local_operations_digest=?,remote_projection_digest=? '
                   'WHERE cycle=? AND company=?',
                   (original['plan_digest'],original['local_operations_digest'],original['remote_projection_digest'],*key))
    old_raw=inbox.connection.execute('SELECT payload FROM sync_plans WHERE cycle=? AND company=?',key).fetchone()[0]
    old_inventory=inbox.connection.execute('SELECT payload FROM inventories WHERE cycle=? AND company=?',key).fetchone()[0]
    old_marker=inbox.connection.execute(
        'SELECT plan_digest,local_operations_digest,remote_projection_digest,state,local_apply_id,'
        'local_records_digest,created_at,updated_at FROM exact_plan_local_state WHERE cycle=? AND company=?',key
    ).fetchone()
    approval={'cycle_id':cycle,'company_id':company,'attempt_id':binding['attempt_id'],
        'release_id':binding['release']['release_id'],'successor_plan_sha256':candidate['plan_digest'],
        'successor_file_sha256':_sha(_encode(candidate)),'original_plan_sha256':original['plan_digest'],
        'original_file_sha256':_sha(old_raw),'original_local_state_sha256':_sha(_encode(old_marker)),
        'inventory_file_sha256':_sha(old_inventory)}
    owner=object()
    qualification_calls=[]
    def verify_fixture_owner(db, selected, actual):
        assert db==bridge.database and selected==binding and actual is owner
        qualification_calls.append(1)
    # The measured approval-entry custody is a separate lane. The saved
    # runtime, admission, exact local plan, publication, and receipt are real.
    monkeypatch.setattr(recovery,'_require_qualified_retry',verify_fixture_owner)
    remote_calls=[]
    @contextmanager
    def remote_factory():
        remote_calls.append(1)
        yield workbook
    def run():
        with writer_lock(bridge.database.parent/'scraper.lock'):
            return recovery.recover_saved_retry_admitted(engine,binding,candidate,approval,
                qualification_owner=owner,remote_factory=remote_factory,timestamp=STAMP)
    return {'key':key,'engine':engine,'state':state,'workbook':workbook,'run':run,'candidate':candidate,
            'original':original,'archive_values':(_encode(approval),old_raw,0,_encode(old_marker),
                                                 old_inventory,_encode(candidate)),
            'remote_calls':remote_calls,'binding':binding,'qualification_calls':qualification_calls, 'bridge':bridge}


def test_archived_replay_finishes_normal_exact_scope_once(frozen_retry, monkeypatch):
    f=frozen_retry
    engine=f['engine']
    inbox,jobs,state=engine.inbox,engine.repo,f['state']
    key=f['key']
    before_jobs=tuple(jobs.db.iterdump())
    before_state=state.cycles()
    def pause_after_archive(*args, **kwargs):
        assert archive(inbox,key)[2:8]==f['archive_values']
        assert inbox.plan(*key)==(f['candidate'],0)
        raise OSError('private cutoff after archive')
    with monkeypatch.context() as cut:
        cut.setattr(recovery,'_recover_exact_cycle_locked',pause_after_archive)
        with pytest.raises(OSError,match='private cutoff'):
            f['run']()
    frozen_archive=archive(inbox,key)
    assert tuple(jobs.db.iterdump())==before_jobs and state.cycles()==before_state
    assert not f['workbook'].commits and not f['bridge'].request_path.exists()
    assert f['run']()=={'state':'READY_FOR_CLOSEOUT','cycle_id':key[0]}
    assert len(f['workbook'].commits)==1
    assert archive(inbox,key)==frozen_archive
    assert inbox.get(*key) is None and inbox.plan(*key) is None and inbox.exact_remote_state(*key) is None
    assert repair_retry_has_confirmed_publication(inbox,jobs,state.cycle(key[0]),key[1],require_complete=False)
    assert f['run']()=={'state':'READY_FOR_CLOSEOUT','cycle_id':key[0]}
    assert len(f['remote_calls'])==2
    outcome=close_published_repair_retry(engine,*key,attempt_id=f['binding']['attempt_id'],
                                       release_id=f['binding']['release']['release_id'])
    assert outcome['outcome']=='COMPLETE'
    done=tuple(jobs.db.iterdump()),tuple(inbox.connection.iterdump()),state.cycles()
    assert f['run']()=={'state':'READY_FOR_CLOSEOUT','cycle_id':key[0]}
    assert done==(tuple(jobs.db.iterdump()),tuple(inbox.connection.iterdump()),state.cycles())
    assert len(f['remote_calls'])==2 and len(f['workbook'].commits)==1
    assert archive(inbox,key)==frozen_archive
    engine.fetcher.assert_called_once()


@pytest.mark.parametrize('defect',['wrong_workbook','changed_scope'])
def test_remote_mismatch_stops_before_selection_or_any_local_apply(frozen_retry, defect):
    f=frozen_retry
    engine=f['engine']
    key=f['key']
    workbook=f['workbook']
    if defect=='wrong_workbook':
        workbook.spreadsheet_id='different-fixture'
    else:
        workbook.commit([{'tab':'Companies','identity':{'Company ID':key[1]},
            'values':{'Official Careers URL':'https://example.test/moved'}}])
    commits_before=len(workbook.commits)
    snapshot=tuple(engine.repo.db.iterdump()),tuple(engine.inbox.connection.iterdump()),f['state'].cycles()
    with pytest.raises(ValueError,match='destination|source|controls|URL'):
        f['run']()
    assert snapshot==(tuple(engine.repo.db.iterdump()),tuple(engine.inbox.connection.iterdump()),f['state'].cycles())
    assert archive(engine.inbox,key) is None and engine.inbox.plan(*key)==(f['original'],0)
    assert len(workbook.commits)==commits_before
    engine.fetcher.assert_called_once()
