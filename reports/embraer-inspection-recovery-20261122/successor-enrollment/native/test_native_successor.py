from contextlib import contextmanager
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import shlex
from types import SimpleNamespace

import pytest
import native_projection as projection
import successor_tool_forward as forward
import successor_environment as environment

HERE=Path(__file__).resolve().parent
PROJECT=Path('/unused')

def metadata(path):
    s=path.stat();return {'mode':s.st_mode&0o777,'size':s.st_size,'sha256':sha256(path.read_bytes()).hexdigest()}


def fixture_files(tmp_path):
    project=tmp_path/'project';target=project/forward.RELATIVE;target.parent.mkdir(parents=True)
    archived=tmp_path/'old.py'
    before=(HERE.parents[1]/'deployment/staged'/forward.RELATIVE).read_bytes()
    after=(HERE/'embraer_operator_pilot.py').read_bytes()
    assert sha256(before).hexdigest()==forward.BEFORE and sha256(after).hexdigest()==forward.AFTER
    target.write_bytes(before);target.chmod(0o644);archived.write_bytes(before);archived.chmod(0o644)
    (project/'unchanged').write_bytes(b'unchanged')
    original=projection.reference(target)
    intent=dict(schema=forward.SCHEMA,release_id=forward.RELEASE,task_id=forward.TASK,path=forward.RELATIVE,
        before_sha256=forward.BEFORE,after_sha256=forward.AFTER,before_reference=original,
        snapshot={'unchanged':'task'},snapshot_sha256=forward.digest({'unchanged':'task'}),predecessor={'prior':'exact'})
    return project,target,archived,before,after,intent


def test_projection_retains_original_owner_and_direct_lineage_checks(tmp_path,monkeypatch):
    project,target,archived,before,after,intent=fixture_files(tmp_path)
    original=metadata(target);authority={'intent':None,'receipt':None}
    p=projection.Projection(project,archived,original,projection.reference(target)[3:5],authority,forward)
    class Owner:
        def status(self):
            assert metadata(self.project/forward.RELATIVE)==original
            assert (self.project/'unchanged').read_bytes()==b'unchanged'
            return {'phase':'STAGED','endpoints':{forward.RELATIVE:metadata(self.project/forward.RELATIVE)}}
    owner=Owner();owner.project=project
    class Window:
        def _lineage(self):
            assert metadata(PROJECT/forward.RELATIVE)==original
            assert (PROJECT/'unchanged').read_bytes()==b'unchanged'
            return self.source_owner.status()
    monkeypatch.setitem(Window._lineage.__globals__,'PROJECT',project)
    w=Window();w.source_owner=owner;w=p.wrap_window(w)
    assert w._lineage()['phase']=='STAGED'
    target.write_bytes(after)
    with pytest.raises(ValueError,match='no exact owned'):w._lineage()
    authority['intent']=intent
    assert w._lineage()['endpoints'][forward.RELATIVE]==original
    receipt={'status':'INSTALLED','transition':intent,'current_reference':projection.reference(target)}
    authority['receipt']=receipt
    assert w._lineage()['phase']=='STAGED'
    (project/'unchanged').write_bytes(b'other')
    with pytest.raises(AssertionError):w._lineage()
    (project/'unchanged').write_bytes(b'unchanged')
    target.chmod(0o600)
    with pytest.raises(ValueError,match='metadata'):w._lineage()


def test_terminal_source_precedes_arm_failure_and_no_rollback_after_arm(tmp_path):
    project,target,archived,before,after,intent=fixture_files(tmp_path)
    atomic_path=Path('/tmp/jsh-amphenol-native-two-tool.HQkjpe8m/deploy_two_tool_forward.py')
    assert sha256(atomic_path.read_bytes()).hexdigest()=='cf9f82f6b85f441ab2e0fdd9bfee1448aa6c1e444ade09a3e66e2748ebb75597'
    spec=importlib.util.spec_from_file_location('successor_atomic_fixture',atomic_path)
    atomic=importlib.util.module_from_spec(spec);spec.loader.exec_module(atomic)
    lock=project/'dev/wrapper-coder/repairs/deployment.lock';lock.parent.mkdir();lock.touch()
    root=tmp_path/'receipt';root.mkdir(mode=0o700)
    state={'running':True,'manager':{},'process':{},'pid':30,'fail':True,'starts':0}
    @contextmanager
    def guard():yield {'prior':'exact'}
    def stop(service):state['running']=False
    def start(service):state['running']=True;state['starts']+=1
    result=forward.apply(project=project,candidate=after,receipt_directory=root,atomic=atomic,
        guard=guard,snapshot=lambda:intent['snapshot'],approved_snapshot_sha256=intent['snapshot_sha256'],
        stop=stop,stopped=lambda:not state['running'],start=start,
        ready=lambda expected,transaction:{'coordinator_reference':projection.reference(target)},reference=projection.reference)
    raw=(root/'receipt.json').read_bytes(); assert result['status']=='INSTALLED'
    selected={'request_id':'operator-embraer-fixture','request_sha256':'a'*64,'source_revision':'b'*64,
        'shared_boards_sha256':'c'*64,'ats_sha256':'d'*64,'baseline_sha256':'e'*64,
        'successor':{'outcome_id':'OUT-'+'1'*24,'predecessor_outcome_id':'OUT-'+'2'*24,
          'predecessor_repair_key':'3'*64,'predecessor_task_id':'WRAP-'+'4'*10,
          'predecessor_task_state_sha256':'5'*64,'failure_fingerprint':'6'*64}}
    def system(operation,*values):
        if operation=='show-environment':return '\n'.join(f'{k}={shlex.quote(v)}' for k,v in state['manager'].items())
        if operation=='set-environment':
            k,v=values[0].split('=',1);state['manager'][k]=v
        elif operation=='restart':
            assert (root/'receipt.json').read_bytes()==raw
            state['pid']+=1;state['process']=dict(state['manager'])
            if state['fail']:state['fail']=False;raise TimeoutError('response lost after restart')
        else:pytest.fail(operation)
    def arm():return environment.reconcile_enrollment(selected,enabled=True,system=system,
        inspect_wrapper=lambda:(state['pid'],state['process']),check_quiescent=lambda:None)
    with pytest.raises(TimeoutError):arm()
    assert target.read_bytes()==after and (root/'receipt.json').read_bytes()==raw
    assert arm()['state']=='EMBRAER_PILOT_ENROLLED'
    assert state['starts']==1 and target.read_bytes()==after
