"""Real private file replacement/rollback, with native observations substituted."""
from contextlib import contextmanager
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest

HERE = Path(__file__).resolve().parent

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module

f = load('forward_fixture_library', HERE/'coordinator_forward.py')
n = load('forward_fixture_native', HERE/'native_forward.py')
a = load('forward_fixture_atomic', n.ATOMIC)
assert sha256(n.ATOMIC.read_bytes()).hexdigest() == n.ATOMIC_PIN
BEFORE = (n.TOOLS/'coordinator.py').read_bytes()
AFTER = (HERE.parent/'coordinator.py').read_bytes()
assert sha256(BEFORE).hexdigest() == f.BEFORE
assert sha256(AFTER).hexdigest() == f.AFTER


def ref(path):
    s=path.stat()
    return [s.st_dev,s.st_ino,stat.S_IMODE(s.st_mode),s.st_uid,s.st_gid,
            sha256(path.read_bytes()).hexdigest(),s.st_mtime_ns]


class ForwardTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.project=Path(self.tmp.name)/'project'; self.target=self.project/f.RELATIVE
        self.target.parent.mkdir(parents=True); self.target.write_bytes(BEFORE); self.target.chmod(0o644)
        lock=self.project/'dev/wrapper-coder/repairs/deployment.lock'; lock.parent.mkdir(); lock.touch()
        self.root=Path(self.tmp.name)/'receipt'; self.root.mkdir(mode=0o700)
        self.data={'task_sha256':'a'*64,'receipts':'b'*64}; self.running=True; self.starts=0
        self.fail_candidate=False

    @contextmanager
    def guard(self): yield {'app_release':f.RELEASE,'same_original':'12'}

    def stop(self, service):
        self.assertEqual(service,f.SERVICE); self.running=False

    def start(self, service):
        self.assertEqual(service,f.SERVICE); self.starts+=1; self.running=True

    def ready(self,pin,intent):
        self.assertTrue(self.running); self.assertEqual(sha256(self.target.read_bytes()).hexdigest(),pin)
        if self.fail_candidate and pin==f.AFTER: raise ValueError('fixture restart refusal')
        return {'coordinator_reference':ref(self.target)}

    def run_forward(self, **kwargs):
        return f.apply(project=self.project,candidate=AFTER,receipt_directory=self.root,atomic=a,
            guard=self.guard,snapshot=lambda:self.data.copy(),approved_snapshot_sha256=f.digest(self.data),
            stop=self.stop,stopped=lambda:not self.running,start=self.start,ready=self.ready,
            reference=ref,**kwargs)

    def test_exact_success_and_no_replay(self):
        result=self.run_forward(); self.assertEqual(result['status'],'INSTALLED')
        self.assertEqual(self.target.read_bytes(),AFTER); self.assertEqual(self.starts,1)
        self.assertEqual((self.root/'coordinator.py.before').read_bytes(),BEFORE)
        with self.assertRaises(ValueError): self.run_forward()
        self.assertEqual(self.starts,1)

    def test_failed_restart_restores_and_preserves_receipts(self):
        self.fail_candidate=True
        with self.assertRaisesRegex(ValueError,'fixture restart refusal'): self.run_forward()
        self.assertEqual(self.target.read_bytes(),BEFORE); self.assertTrue(self.running)
        self.assertEqual(json.loads((self.root/'receipt.json').read_bytes())['status'],'ROLLED_BACK')
        self.assertEqual(self.data,{'task_sha256':'a'*64,'receipts':'b'*64})

    def test_crash_after_write_has_explicit_same_intent_rollback(self):
        record=f.transition_record(dict(schema=f.SCHEMA,release_id=f.RELEASE,task_id=f.TASK,path=f.RELATIVE,
            before_sha256=f.BEFORE,after_sha256=f.AFTER,before_reference=ref(self.target),snapshot=self.data,
            snapshot_sha256=f.digest(self.data),predecessor={'app_release':f.RELEASE,'same_original':'12'}))
        a._write_new_private(self.root/'coordinator.py.before',BEFORE)
        a._write_new_private(self.root/'intent.json',f.canonical(record))
        a._write_atomic(self.target,AFTER,0o644)
        with self.assertRaises(ValueError): self.run_forward()
        self.assertEqual(self.run_forward(rollback_only=True)['status'],'ROLLED_BACK')
        self.assertEqual(self.target.read_bytes(),BEFORE)

    def test_exact_tool_projection_rejects_other_changes(self):
        from types import SimpleNamespace as NS
        encoder=lambda value:json.dumps(value,sort_keys=True,separators=(',',':')).encode()
        c=NS(ref=lambda p:ref(p)[:-1],installer=NS(identity=lambda s:[s.st_dev,s.st_ino],
              ownership=lambda s:[s.st_uid,s.st_gid],encode=encoder,digest=lambda raw:sha256(raw).hexdigest()))
        tools=self.target.parent
        (tools/'unchanged.py').write_text('unchanged')
        original=n.wrapper_map(c,tools,())
        intent=f.transition_record(dict(schema=f.SCHEMA,release_id=f.RELEASE,task_id=f.TASK,path=f.RELATIVE,
            before_sha256=f.BEFORE,after_sha256=f.AFTER,before_reference=original['coordinator.py'],
            snapshot=self.data,snapshot_sha256=f.digest(self.data),predecessor={}))
        native=NS(NativeWindow=type('NativeWindow',(),{}),CURRENT=Path('/unused'),RECEIPT_05='ignored',
            CURRENT_TOOLS={},CHANGED_WRAPPER_TOOLS=(),read_private=lambda *x:b'{"paths":{}}')
        window=native.NativeWindow(); window.c=c; window.old=NS(wrapper_tools=tools)
        window.wrapper_scope_sha256=sha256(encoder(original)).hexdigest()
        copied=n.extended_window(window,native,f,intent)
        a._write_atomic(self.target,AFTER,0o644)
        copied._wrapper_custody({})
        (tools/'unchanged.py').write_text('unrelated change')
        with self.assertRaises(ValueError): copied._wrapper_custody({})

    def test_inactive_crash_rollback_keeps_exact_stopped_gate(self):
        calls=[]
        def active():
            calls.append('active'); raise ValueError('inactive wrapper')
        def stopped():
            calls.append('stopped'); return True
        n.admit_process_boundary('rollback', {'owned':'intent'}, {'ActiveState':'inactive'}, active, stopped)
        self.assertEqual(calls,['stopped'])
        for action,intent in (('apply',{'owned':'intent'}),('inspect',{'owned':'intent'}),('rollback',None)):
            with self.assertRaises(ValueError):
                n.admit_process_boundary(action,intent,{'ActiveState':'inactive'},active,stopped)
        with self.assertRaises(ValueError):
            n.admit_process_boundary('rollback',{'owned':'intent'},{'ActiveState':'inactive'},active,lambda:False)


if __name__=='__main__': unittest.main()
