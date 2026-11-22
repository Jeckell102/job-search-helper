from contextlib import contextmanager
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import stat
from types import SimpleNamespace

import pytest
import five_tool_forward as forward

ATOMIC = Path('/tmp/jsh-amphenol-native-two-tool.HQkjpe8m/deploy_two_tool_forward.py')
STAGE = Path('/tmp/jsh-embraer-owned-pilot.xXaXrqW0')
CANDIDATE = Path('/tmp/jsh-embraer-03-continuation/tools')
BEFORE = {
 'coordinator.py': STAGE/'successor-context-repair/coordinator.py',
 'coordinator_store.py': STAGE/'dev/wrapper-coder/tools/coordinator_store.py',
 'coordinator_inference.py': STAGE/'dev/wrapper-coder/tools/coordinator_inference.py',
 'embraer_operator_pilot.py': STAGE/'successor-admission/embraer_successor_admission.py',
}


def load_atomic():
    assert sha256(ATOMIC.read_bytes()).hexdigest()=='cf9f82f6b85f441ab2e0fdd9bfee1448aa6c1e444ade09a3e66e2748ebb75597'
    spec=importlib.util.spec_from_file_location('accepted_atomic',ATOMIC)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def reference(path):
    raw,info=load_atomic()._read(path)
    return [info.st_dev,info.st_ino,stat.S_IMODE(info.st_mode),info.st_uid,info.st_gid,sha256(raw).hexdigest(),info.st_mtime_ns]


@pytest.mark.parametrize('fail_restart',[False,True])
def test_exact_five_transition_and_compensation(tmp_path,fail_restart):
    atomic=load_atomic();project=tmp_path/'project';tools=project/forward.PREFIX
    tools.mkdir(parents=True)
    repairs=project/'dev/wrapper-coder/repairs';repairs.mkdir();(repairs/'deployment.lock').touch()
    transaction=tmp_path/'transaction';transaction.mkdir(mode=0o700)
    scope={};candidates={}
    for name,(old,new) in forward.PINS.items():
        target=tools/name
        if old:
            data=BEFORE[name].read_bytes();assert sha256(data).hexdigest()==old
            target.write_bytes(data);target.chmod(0o644)
        relative=forward.PREFIX+name
        scope[relative]={'before':reference(target) if old else None,
            'after':{'sha256':new,'mode':0o644,'uid':os.geteuid(),'gid':os.getegid()}}
        candidates[relative]=(CANDIDATE/name).read_bytes()
    sibling=tools/'unrelated.py';sibling.write_text('unchanged = True\n');sibling_ref=reference(sibling)
    archive=tmp_path/'original-helper.py';archive.write_bytes(BEFORE['embraer_operator_pilot.py'].read_bytes())
    helper_ref=reference(tools/'embraer_operator_pilot.py')
    archive_ref=reference(archive)
    database=tmp_path/'disposable.sqlite3'
    with sqlite3.connect(database) as db:
        db.execute('CREATE TABLE ownership (key TEXT PRIMARY KEY, value TEXT)')
        db.executemany('INSERT INTO ownership VALUES (?,?)',[
            ('task',forward.PARENT),('status','PAUSED_BUDGET'),('pilot',forward.PARENT),
            ('counters','7/15/118059'),('receipts','all fifteen immutable')])
    def snapshot():
        with sqlite3.connect(f'file:{database}?mode=ro',uri=True) as db:
            rows=db.execute('SELECT key,value FROM ownership ORDER BY key').fetchall()
            found=db.execute("SELECT name FROM sqlite_master WHERE name='embraer_03_continuations'").fetchall()
            assert not found or db.execute('SELECT count(*) FROM embraer_03_continuations').fetchone()[0]==0
        return {'rows':[list(row) for row in rows]}
    saved=snapshot();authority={};events=[];active=[True]
    def original_verify():
        assert reference(tools/'embraer_operator_pilot.py')==helper_ref
        assert reference(archive)==archive_ref
        return helper_ref
    helper=SimpleNamespace(verify=original_verify,archived=archive)
    def old_custody(status):
        assert reference(tools/'coordinator.py')==scope[forward.PREFIX+'coordinator.py']['before']
        return helper.verify()
    window=SimpleNamespace(_wrapper_custody=old_custody)
    forward.install_custody_projection(window,helper,authority,project,reference)
    @contextmanager
    def guard():
        window._wrapper_custody({});assert active[0];events.append('guard')
        yield {'coordinator_receipt':'97c83a0e','helper_receipt':'5f65476a','app':forward.RELEASE}
    def stop(service):
        assert service==forward.SERVICE;active[0]=False;events.append('stop')
    def start(service):
        assert service==forward.SERVICE;active[0]=True;events.append('start')
        # The candidate Store has this sole expected schema addition on restart.
        if sha256((tools/'coordinator_store.py').read_bytes()).hexdigest()==forward.PINS['coordinator_store.py'][1]:
            with sqlite3.connect(database) as db:db.execute('CREATE TABLE IF NOT EXISTS embraer_03_continuations (id TEXT)')
    def ready(expected,intent):
        window._wrapper_custody({});helper.verify()
        for relative,pin in expected.items():
            path=project/relative
            assert (sha256(path.read_bytes()).hexdigest() if path.exists() else None)==pin
        if fail_restart and expected[forward.PREFIX+'coordinator.py']==forward.PINS['coordinator.py'][1]:
            raise RuntimeError('injected restart readback refusal')
        return {'loaded_hashes':expected,'active':active[0]}
    kwargs=dict(project=project,candidates=candidates,scope=scope,receipt_directory=transaction,
        approved_snapshot_sha256=forward.digest(saved),atomic=atomic,guard=guard,snapshot=snapshot,
        stop=stop,stopped=lambda:not active[0],start=start,ready=ready,reference=reference,authority=authority)
    if fail_restart:
        with pytest.raises(RuntimeError,match='injected restart'):forward.apply_five_tool_forward(**kwargs)
    else:
        result=forward.apply_five_tool_forward(**kwargs);assert result['status']=='INSTALLED'
    receipt=json.loads((transaction/'receipt.json').read_text())
    assert receipt['status']==('ROLLED_BACK' if fail_restart else 'INSTALLED')
    forward.verify_transition(project,receipt['transition'],reference,terminal=receipt)
    assert snapshot()==saved and reference(sibling)==sibling_ref and active[0]
    assert authority['receipt']==receipt
    assert (tools/'embraer_compact_prompt.py').exists() is not fail_restart
    assert events==(['guard','stop','start','stop','start'] if fail_restart else ['guard','stop','start'])
    with pytest.raises(ValueError,match='Terminal installation must not be replayed'):
        forward.apply_five_tool_forward(**kwargs)
