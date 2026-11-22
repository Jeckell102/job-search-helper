import json
import shlex
from pathlib import Path
import pytest
import coordinator_baseline as baseline
import embraer_pilot_arming as armer
import successor_environment as environment
import native_arm_next as entry


def test_actual_approved_baseline_publish_and_exact_replay(tmp_path):
    source=entry.STAGE/'implementation-recovery/acceptance'/('embraer-'+entry.NEXT_BASELINE)
    target=tmp_path/source.name
    original=baseline.files(source)
    assert len(original)==700
    entry.publish_baseline(source,target,baseline.files,baseline.binding)
    identity=(target.stat().st_dev,target.stat().st_ino)
    entry.publish_baseline(source,target,baseline.files,baseline.binding)
    assert identity==(target.stat().st_dev,target.stat().st_ino)
    assert baseline.files(target)==original and baseline.files(source)==original
    changed=target/'tests/test_embraer_typed_defect.py'
    changed.write_bytes(changed.read_bytes()+b'\n# unrelated drift\n')
    with pytest.raises(ValueError):entry.publish_baseline(source,target,baseline.files,baseline.binding)


def test_exact_arm_owner_and_lost_restart_reply_replay(tmp_path):
    outcome='OUT-'+'3'*24
    selected={'request_id':entry.NEXT_REQUEST,'request_sha256':'a'*64,
        'source_revision':'b'*64,'shared_boards_sha256':'c'*64,'ats_sha256':'d'*64,
        'baseline_sha256':entry.NEXT_BASELINE,'successor':{'outcome_id':outcome,
        'predecessor_outcome_id':entry.OUTCOME,'predecessor_repair_key':'e'*64,
        'predecessor_task_id':entry.TASK,'predecessor_task_state_sha256':entry.TASK_STATE_PIN,
        'failure_fingerprint':'f'*64}}
    state={'manager':{'UNRELATED':'preserved'},'process':{},'pid':10,'lost':True,'writes':[]}
    quiet=[]
    def system(op,*args):
        if op=='show-environment':return '\n'.join(k+'='+shlex.quote(v) for k,v in state['manager'].items())
        state['writes'].append((op,*args))
        if op=='set-environment':
            key,_,value=args[0].partition('=');assert key==environment.ENROLLMENT;state['manager'][key]=value
        elif op=='restart':
            assert args==(environment.WRAPPER,);state['pid']+=1
            state['process']={environment.ENROLLMENT:state['manager'][environment.ENROLLMENT]}
            if state['lost']:state['lost']=False;raise TimeoutError('lost after actual restart')
        else:pytest.fail(op)
    def run():return entry.arm_verified_next(armer,environment,root=tmp_path,selected=selected,outcome=outcome,
        system=system,inspect_wrapper=lambda:(state['pid'],state['process']),check_quiescent=lambda:quiet.append(True))
    with pytest.raises(TimeoutError):run()
    path=armer._owner_path(tmp_path,entry.NEXT_REQUEST);saved=path.read_bytes()
    result=run();assert result['state']=='EMBRAER_PILOT_ENROLLED'
    assert run()==result and path.read_bytes()==saved
    assert len(state['writes'])==2 and state['manager']['UNRELATED']=='preserved'
    assert json.loads(saved)['enrollment']==selected
    changed={**selected,'request_sha256':'0'*64}
    with pytest.raises(ValueError):entry.arm_verified_next(armer,environment,root=tmp_path,selected=changed,outcome=outcome,
        system=system,inspect_wrapper=lambda:(state['pid'],state['process']),check_quiescent=lambda:None)
    assert len(state['writes'])==2 and path.read_bytes()==saved
