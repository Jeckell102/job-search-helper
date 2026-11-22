"""Receipt-aware readback only; no native or application effects."""
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest

HERE=Path(__file__).resolve().parent

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value

d=load('disarm_fixture',HERE/'native_embraer_disarm.py')
f=load('disarm_forward_fixture',HERE.parent/'forward/coordinator_forward.py')

class ReceiptTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.project=Path(temp.name);old=d.PROJECT;d.PROJECT=self.project
        self.addCleanup(setattr,d,'PROJECT',old)
        self.target=self.project/f.RELATIVE;self.target.parent.mkdir(parents=True)
        self.target.write_bytes((HERE.parent/'coordinator.py').read_bytes())
        self.target.chmod(0o644)
        def reference(path):
            s=path.stat();return [s.st_dev,s.st_ino,stat.S_IMODE(s.st_mode),s.st_uid,s.st_gid,sha256(path.read_bytes()).hexdigest()]
        self.window=SimpleNamespace(c=SimpleNamespace(ref=reference),wrapper_scope_sha256='a'*64)
        current=[*reference(self.target),self.target.stat().st_mtime_ns]
        original=[*current];original[5]=f.BEFORE
        snapshot={'enrollment':{'request_id':'operator-embraer-exact'}}
        predecessor=dict(application_journal_sha256=d.ACTIVE_JOURNAL_PIN,
            application_receipt_sha256=d.ACTIVE_RECEIPT_PIN,restored_records=d.RESTORED,
            original_wrapper_scope_sha256=self.window.wrapper_scope_sha256)
        self.receipt=dict(schema=f.SCHEMA,status='INSTALLED',current_reference=current,
            restart={'coordinator_reference':current},transition=dict(schema=f.SCHEMA,
            release_id=f.RELEASE,task_id=f.TASK,path=f.RELATIVE,before_sha256=f.BEFORE,
            after_sha256=f.AFTER,before_reference=original,snapshot=snapshot,
            snapshot_sha256=f.digest(snapshot),predecessor=predecessor))

    def verify(self,pin=None):
        raw=f.canonical(self.receipt);expected=sha256(raw).hexdigest()
        def read(path,claimed,private):
            self.assertTrue(private)
            if claimed!=expected:raise ValueError('independent receipt pin mismatch')
            return raw
        return d.verified_forward_receipt(read,self.window,f,pin or expected)

    def test_exact_terminal_and_wrong_independent_pin(self):
        self.assertEqual(self.verify(),self.receipt)
        with self.assertRaises(ValueError):self.verify('0'*64)

    def test_changed_source_or_reference_is_held(self):
        self.target.write_text('foreign coordinator')
        with self.assertRaises(ValueError):self.verify()

    def test_foreign_predecessor_and_unfinished_receipt_hold(self):
        self.receipt['transition']['predecessor']['application_journal_sha256']='0'*64
        with self.assertRaises(ValueError):self.verify()
        self.receipt['transition']['predecessor']['application_journal_sha256']=d.ACTIVE_JOURNAL_PIN
        self.receipt['status']='PREPARED'
        with self.assertRaises(ValueError):self.verify()

if __name__=='__main__':unittest.main()
