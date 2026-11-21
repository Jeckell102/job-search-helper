from contextlib import closing, contextmanager
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import fcntl
import json
import sqlite3

import pytest

import amphenol_operator_one_shot as one_shot
from amphenol_retry_completion import RetryReleaseApproval
from coordinator_store import Store
import host_server
from job_search_helper import cli

CANARY=Path('/tmp/jsh-amphenol-one-shot-canary.080vithb/run-kkxsfnse')


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    root=tmp_path/'project'
    root.mkdir()
    tasks=tmp_path/'wrapper'/'tasks'
    existing=Store(tasks)
    for path in (tasks/'scheduler.lock',tasks/'supervision.lock'):
        path.touch(mode=0o600)
    monkeypatch.setattr(host_server,'BASE',tasks.parent)
    monkeypatch.setattr(host_server,'JOB_SEARCH_ROOT',root)
    monkeypatch.setattr(cli,'load_environment',lambda _:None)
    monkeypatch.setattr(cli,'state_path',lambda:root/'state.db')
    monkeypatch.setattr(cli,'job_database_path',lambda:root/'jobs.sqlite3')
    monkeypatch.setattr(cli,'storage_backend',lambda:'sqlite')

    approval_dir=CANARY/'approval'
    release=json.loads((CANARY/'RESULT.json').read_bytes())['release_id']
    ticket=approval_dir/(release+'.json')
    attrs=approval_dir.stat()
    approval=RetryReleaseApproval(release,str(approval_dir),attrs.st_dev,attrs.st_ino,
                                  sha256(ticket.read_bytes()).hexdigest())
    events=[]
    @contextmanager
    def outer():
        events.append('enter')
        try:
            yield
        finally:
            events.append('exit')
    args={'approval':approval,'original_outcome':'OUT-'+'a'*24,'request_sha256':'b'*64,
          'historical_task_id':'WRAP-'+'c'*10,'maintenance_scope':outer}
    return args,events,existing,tasks


def test_default_has_no_scope_or_approval_read(prepared,monkeypatch):
    args,events,_,_=prepared
    monkeypatch.setattr(RetryReleaseApproval,'read_install_inputs',lambda _:pytest.fail('read approval'))
    result=one_shot.run_operator_release(**args)
    assert result=={'state':'HELD_OPERATOR_EXECUTION_NOT_REQUESTED'} and events==[]


def test_failed_approval_precedes_scope_or_store(prepared,monkeypatch):
    args,events,_,_=prepared
    monkeypatch.setattr(Store,'__init__',lambda *a,**k:pytest.fail('opened writable Store'))
    try:
        held=one_shot.run_operator_release(execute=True,**{**args,'approval':replace(args['approval'],receipt_sha256='0'*64)})
    except ValueError as exc:
        assert 'qualification receipt changed' in str(exc)
    else:
        assert held['state'].startswith('HELD_')
    assert events==[]


@pytest.mark.parametrize('name',('scheduler.lock','supervision.lock'))
def test_contention_releases_any_acquired_lock_without_store(prepared,monkeypatch,name):
    args,events,_,tasks=prepared
    monkeypatch.setattr(Store,'__init__',lambda *a,**k:pytest.fail('opened writable Store'))
    with (tasks/name).open('rb') as competing:
        fcntl.flock(competing,fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert one_shot.run_operator_release(execute=True,**args)=={'state':'HELD_OPERATOR_COORDINATOR_BUSY'}
    for lock in ('scheduler.lock','supervision.lock'):
        with (tasks/lock).open('rb') as fresh:
            fcntl.flock(fresh,fcntl.LOCK_EX|fcntl.LOCK_NB)
    assert events==['enter','exit']


def test_both_locks_remain_owned_through_terminal(prepared,monkeypatch):
    args,events,existing,tasks=prepared
    existing.set_queue_enabled(False)
    attempt='RTRY-'+'d'*24
    exact='OUT-'+'e'*24

    def prove_owned():
        assert events==['enter']
        for name in ('scheduler.lock','supervision.lock'):
            with (tasks/name).open('rb') as other:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(other,fcntl.LOCK_EX|fcntl.LOCK_NB)

    def release(**selected):
        prove_owned()
        assert selected['outcome_id']==args['original_outcome']
        return {'release':{'attempt_id':attempt},'retry':{'state':'COMPLETE','outcome':{'outcome_id':exact}}}

    def deliver(enrollment,coordinator,**selected):
        prove_owned()
        assert selected=={'original_outcome':args['original_outcome'],'approval':args['approval']}
        assert enrollment.request_sha256==args['request_sha256']
        return {'state':'RECIPE_RETRY_CONFIRMED','attempt_id':attempt,'outcome_id':exact}

    monkeypatch.setattr(one_shot,'continue_operator_retained_release',release)
    monkeypatch.setattr(one_shot,'deliver_qualified_operator_retry',deliver)
    assert one_shot.run_operator_release(execute=True,**args)['state']=='OPERATOR_RELEASE_CONFIRMED'
    assert events==['enter','exit']


def test_held_controls_do_not_bootstrap_coordinator_database(prepared,monkeypatch):
    args,events,existing,_=prepared
    existing.set_queue_enabled(True)
    path=Path(existing.path)
    with closing(sqlite3.connect(path)) as db:
        assert db.execute('PRAGMA journal_mode=DELETE').fetchone()==('delete',)
    before=path.read_bytes()
    monkeypatch.setattr(one_shot,'continue_operator_retained_release',lambda **kw:pytest.fail('called release'))
    assert one_shot.run_operator_release(execute=True,**args)=={'state':'HELD_OPERATOR_COORDINATOR_CONTROLS'}
    assert events==['enter','exit']
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro&immutable=1',uri=True)) as db:
        queue=db.execute("SELECT value FROM settings WHERE key='queue_enabled'").fetchone()
    assert queue==('true',)
    assert path.read_bytes()==before, 'opening writable Store silently changed persisted SQLite journal mode'
