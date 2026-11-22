from contextlib import contextmanager
from hashlib import sha256
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import sys
from types import SimpleNamespace, ModuleType

import pytest


HERE=Path(__file__).parent
REVIEW=HERE/'OUTER_71.py'
ATTEMPT='RTRY-8d1210858e4e26f325312a89'
CYCLE='CYC-4650772EEE1E'
RELEASE='REL-f509ed362bf8781ea8840adc'
OUTCOME='OUT-'+'b'*24


def pin(path):
    return sha256(path.read_bytes()).hexdigest()


def private(path,value):
    path.write_text(json.dumps(value))
    path.chmod(0o600)
    return path


@pytest.fixture
def outer(tmp_path, monkeypatch):
    chosen=Path(__import__('os').environ.get('OUTER_QA_SOURCE', str(REVIEW)))
    spec=spec_from_file_location('fixture_reviewed_outer',chosen)
    runner=module_from_spec(spec)
    spec.loader.exec_module(runner)
    history=[]
    project=tmp_path/'project'
    project.mkdir()
    interpreter=project/'.venv'
    interpreter.mkdir()
    monkeypatch.setattr(runner,'PROJECT',project)
    sys_flags=SimpleNamespace(isolated=True,dont_write_bytecode=True)
    monkeypatch.setattr(runner,'sys',SimpleNamespace(flags=sys_flags,prefix=interpreter,pycache_prefix='/dev/null',
                                                      executable='/synthetic/python'))
    prior_source=tmp_path/'prior.py'
    prior_source.write_text('from outer_fixture_dependencies import *\n')
    monkeypatch.setattr(runner,'PRIOR_ENTRY',prior_source)
    monkeypatch.setattr(runner,'PRIOR_ENTRY_SHA256',pin(prior_source))
    prior=ModuleType('outer_fixture_dependencies')
    prior.MANIFEST_SHA='a'*64
    prior.REQUEST_SHA='b'*64
    prior.OUTCOME='OUT-'+'c'*24
    prior.ATTEMPT=ATTEMPT
    prev_manifest={'release_id':RELEASE,'failed_request_id':'fixture-prior-request','source_revision':'d'*64}
    authority={'release_id':RELEASE,'directory':str(tmp_path/'owner'),'device':1,'inode':1,'receipt_sha256':'c'*64}
    protected=private(tmp_path/'authority.json',authority)
    witness=private(tmp_path/'independent.json',{'test':'fixture'})
    owner_file=private(tmp_path/'recovery.json',{'schema':'amphenol-saved-retry-approval-v1',
        'native':{'entry_sha256':pin(chosen),'independent_review_path':str(witness),'independent_review_sha256':pin(witness),
                  'window_sha256':'e'*64,'wrapper_scope_sha256':'f'*64,'window_root':str(tmp_path/'window')},
        'qualification_path':str(protected),'qualification_sha256':pin(protected)})
    def load_env(path):
        assert path==project/'.env'
        history.append('environment')

    pkg=ModuleType('job_search_helper')
    pkg.__path__=[]
    cli=ModuleType('job_search_helper.cli')
    cli.load_environment=load_env
    rel=ModuleType('job_search_helper.integration_release')
    rel.digest=lambda value: prior.MANIFEST_SHA if value == prev_manifest else 'foreign'
    for module in (prior,pkg,cli,rel):
        monkeypatch.setitem(sys.modules,module.__name__,module)

    class Approval:
        @classmethod
        def from_json(cls,raw):
            assert json.loads(raw)==authority
            return cls()
        def read_install_inputs(self):
            assert 'environment' in history
            return tmp_path/'candidate',prev_manifest
    class Window:
        def ready(self):
            assert 'environment' in history
            history.append('ready')
            return {'state':'QUALIFIED_NATIVE_WINDOW_READY'}
        def restore(self):
            assert 'environment' in history
            history.append('explicit_restore')
            return {'state':'NATIVE_WINDOW_RESTORED'}
        @contextmanager
        def hold(self):
            assert history[-1]=='verify-inputs'
            history.append('held')
            try:
                yield
            finally:
                history.append('restored')
    def create_window(**kwargs):
        assert kwargs['resume_complete'] is True and kwargs['release_id']==RELEASE
        assert kwargs['qualification_check']()=={'release_id':RELEASE,'manifest_sha256':prior.MANIFEST_SHA}
        return Window()

    @contextmanager
    def lease(base):
        assert history[-1]=='held' and base==project/'tasks'
        history.append('locked')
        try:
            yield
        finally:
            history.append('unlocked')
    def coordinator(**kwargs):
        assert kwargs['existing_store_only'] is True
        assert history[-1]=='apply'
        return object()
    def settlement(enrollment, actual, *, original_outcome, approval):
        assert isinstance(approval,Approval) and original_outcome==prior.OUTCOME
        assert enrollment==('fixture-prior-request','d'*64,prior.REQUEST_SHA)
        history.append('terminal')
        return {'state':'RECIPE_RETRY_CONFIRMED','attempt_id':ATTEMPT,'outcome_id':OUTCOME}
    owner=SimpleNamespace(_physical_directory=lambda path:path,_physical_file=lambda path:path,
                           _coordinator_lease=lease,_coordinator_is_idle=lambda path:history[-1]=='locked')
    host=SimpleNamespace(BASE=project,current_company_revision=object(),
       OperatorAmphenolRecipeEnrollment=lambda request, revision, *, request_sha256:(request,revision,request_sha256))
    prior.verify_tool_origins=lambda:{'amphenol_retry_completion':SimpleNamespace(RetryReleaseApproval=Approval,
          deliver_qualified_operator_retry=settlement),'amphenol_operator_one_shot':owner,
          'host_server':host,'coordinator':SimpleNamespace(Coordinator=coordinator)}
    prior.load_native_window=lambda *_:(SimpleNamespace(create_window=create_window),{})
    def call(action):
        monkeypatch.setattr(sys,'argv',[str(chosen),action,'--approval',str(owner_file),'--approval-sha256',pin(owner_file)])
        return runner.main()
    return runner,history,call


def child_stub(history, *, fail=False, foreign=False):
    def invoke(*values):
        action=values[1] if isinstance(values[0],bytes) else values[0]
        history.append(action)
        if action=='verify-inputs':
            return {'state':'SAVED_RETRY_INPUTS_VERIFIED','attempt_id':ATTEMPT}
        assert history[-2]=='locked'
        if fail:
            raise RuntimeError('fixture worker stopped')
        return {'state':'COMPLETE','cycle_id':CYCLE,'outcome_id':OUTCOME if not foreign else 'OUT-'+'e'*24}
    return invoke


@pytest.mark.parametrize('action,events', [('ready',['environment','verify-inputs','ready']),
                                            ('restore',['environment','explicit_restore'])])
def test_ready_restore_load_environment_and_use_separate_scope(outer, monkeypatch, action, events):
    runner,history,call=outer
    monkeypatch.setattr(runner,'run_child',child_stub(history))
    assert call(action)==0
    assert history==events


@pytest.mark.parametrize('fail,foreign,code',[(False,False,0),(False,True,1),(True,False,None)])
def test_apply_owns_lease_through_terminal_and_restores_on_all_cuts(outer, monkeypatch, fail, foreign, code):
    runner,history,call=outer
    monkeypatch.setattr(runner,'run_child',child_stub(history,fail=fail,foreign=foreign))
    if fail:
        with pytest.raises(RuntimeError,match='worker stopped'):
            call('apply')
    else:
        assert call('apply')==code
    assert history[:5]==['environment','verify-inputs','held','locked','apply']
    assert history[-2:]==['unlocked','restored']
    assert history.count('terminal')==int(not fail)


def test_sealed_child_passes_exact_bytes_to_bootstrap(outer, monkeypatch):
    runner,history,_=outer
    exact=(HERE/'approved_recovery_entry.py').read_bytes()
    def process(command,*,cwd,input,stdout,check):
        assert command[:7]==['/synthetic/python','-I','-B','-X','pycache_prefix=/dev/null','-c',runner.CHILD_BOOT]
        assert command[7:]==[str(runner.RECOVERY_ENTRY),'verify-inputs','--approval','/tmp/private-approval.json',
                            '--approval-sha256','c'*64]
        assert cwd==runner.PROJECT and input is exact and not check
        history.append('sealed')
        return SimpleNamespace(returncode=0,stdout=json.dumps({'state':'SAVED_RETRY_INPUTS_VERIFIED','attempt_id':ATTEMPT}).encode())
    monkeypatch.setattr(runner.subprocess,'run',process)
    assert runner.run_child(exact,'verify-inputs',Path('/tmp/private-approval.json'),'c'*64)['attempt_id']==ATTEMPT
    assert history==['sealed']


def test_positive_terminal_state_requires_exact_receiver_call(outer, monkeypatch):
    runner,history,call=outer
    def noncontract(command, *, cwd, input, stdout, check):
        action=command[8]
        history.append(action)
        assert input==(HERE/'approved_recovery_entry.py').read_bytes()
        if action=='verify-inputs':
            response={'state':'SAVED_RETRY_INPUTS_VERIFIED','attempt_id':ATTEMPT}
        else:
            assert history[-2]=='locked'
            response={'state':'OPERATOR_RELEASE_CONFIRMED','cycle_id':CYCLE,'outcome_id':OUTCOME}
        return SimpleNamespace(returncode=0, stdout=json.dumps(response).encode())
    monkeypatch.setattr(runner.subprocess,'run',noncontract)
    try:
        result=call('apply')
    except (ValueError,RuntimeError):
        result=1
    assert result == 1
    assert history[-1]=='restored' and 'terminal' not in history
