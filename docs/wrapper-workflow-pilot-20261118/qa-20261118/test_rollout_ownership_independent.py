"""Independent cross-process deployment ownership and crash-barrier regressions."""
import json
import multiprocessing as mp
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from test_paused_rollout import Controller, deployment
import test_paused_rollout as fixture_module
import rollout_controller

CTX = mp.get_context('fork')

def child_apply(base, prepared, archive, entered, release, crash=None):
    controller = Controller(base)
    def fault(phase):
        if phase == (crash or 'after_rehearsal'):
            entered.set()
            if crash:
                os._exit(73)
            if not release.wait(15):
                raise RuntimeError('test owner timed out')
    deployment.rollout(base, prepared, archive, controller, fault=fault)

def child_recover(base, archive, entered, release):
    controller = Controller(base)
    original = controller.validate_recovery
    def validate(*args):
        original(*args)
        entered.set()
        if not release.wait(15):
            raise RuntimeError('test recovery timed out')
    controller.validate_recovery = validate
    deployment.recover_archive(archive, controller)

class IndependentOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base,self.prepared,self.archive,self.controller = fixture_module.PausedRolloutTests().fixture(self.root)

    def start(self, target, *args):
        entered, release = CTX.Event(), CTX.Event()
        process = CTX.Process(target=target, args=(*args,entered,release))
        process.start()
        self.addCleanup(lambda: process.kill() if process.is_alive() else None)
        self.addCleanup(release.set)
        self.assertTrue(entered.wait(8), 'owner did not enter operation')
        self.assertTrue(process.is_alive())
        return process,release

    def contenders(self):
        prepared2,archive2=self.root/'prepared2',self.root/'archive2'
        shutil.copytree(self.prepared,prepared2)
        before=self.controller.snapshot()
        for operation in (lambda: deployment.rollout(self.base,prepared2,archive2,self.controller),
                          lambda: deployment.recover_archive(self.archive,self.controller)):
            with self.assertRaisesRegex(ValueError,'Another deployment'):
                operation()
            self.assertEqual(self.controller.events,[])
            self.assertEqual(self.controller.snapshot(),before)
            self.assertFalse(archive2.exists())
        # Public CLI preparation/rehearsal must share the guard before outputs.
        class Fake:
            def __init__(self,*args): pass
            def inputs(self): pass
        for action in ('prepare','rehearse'):
            with patch.object(rollout_controller,'Controller',Fake), patch.object(rollout_controller,'validate_outputs'), patch.object(rollout_controller,'execute_action') as execute:
                with self.assertRaisesRegex(ValueError,'Another deployment'):
                    rollout_controller.main([action,'--base',str(self.base),'--qa',str(self.root/'qa'),'--manifest',str(self.root/'manifest'),'--prepared',str(prepared2),'--archive',str(archive2)])
                execute.assert_not_called()

    def test_apply_excludes_apply_recover_prepare_rehearse_across_process(self):
        process,release=self.start(child_apply,self.base,self.prepared,self.archive)
        self.contenders()
        release.set(); process.join(8)
        self.assertEqual(process.exitcode,0)
        self.assertEqual(json.loads((self.archive/'journal.json').read_text())['phase'],'INSTALLED_PAUSED')
        self.assertFalse((self.base/'repairs/deployment-pending.json').exists())
        self.assertEqual((self.base/'tools/version').read_text(),'new')

    def crash(self, boundary):
        entered,release=CTX.Event(),CTX.Event()
        process=CTX.Process(target=child_apply,args=(self.base,self.prepared,self.archive,entered,release,boundary))
        process.start(); process.join(8)
        self.assertFalse(process.is_alive()); self.assertEqual(process.exitcode,73)
        self.assertTrue(entered.is_set())

    def test_crash_pending_blocks_fresh_apply_and_wrong_recovery_then_matching_recovery(self):
        for boundary in ('after_pending','after_rehearsal','after_publish_tools'):
            with self.subTest(boundary=boundary):
                # A fresh disposable fixture per crash boundary.
                with tempfile.TemporaryDirectory() as tmp:
                    base,prepared,archive,controller=fixture_module.PausedRolloutTests().fixture(Path(tmp))
                    entered,release=CTX.Event(),CTX.Event()
                    process=CTX.Process(target=child_apply,args=(base,prepared,archive,entered,release,boundary))
                    process.start(); process.join(8)
                    self.assertEqual(process.exitcode,73)
                    pending=(base/'repairs/deployment-pending.json').read_bytes()
                    with self.assertRaisesRegex(ValueError,'Unfinished deployment'):
                        deployment.rollout(base,prepared,Path(tmp)/'other',controller)
                    with self.assertRaisesRegex(ValueError,'No matching'):
                        deployment.recover_archive(Path(tmp)/'other',controller)
                    self.assertEqual(controller.events,[])
                    self.assertEqual((base/'repairs/deployment-pending.json').read_bytes(),pending)
                    result=deployment.recover_archive(archive,controller)
                    self.assertEqual(result['phase'],'ROLLED_BACK')
                    self.assertEqual(controller.snapshot(),controller.before)
                    self.assertEqual((base/'tasks/workspace/keep').read_text(),'preserve')
                    self.assertFalse((base/'repairs/deployment-pending.json').exists())
                    self.assertTrue((base/'repairs/deployment.lock').exists())

    def test_recover_excludes_apply_and_recover_across_process(self):
        self.crash('after_rehearsal')
        process,release=self.start(child_recover,self.base,self.archive)
        self.contenders()
        release.set();process.join(8)
        self.assertEqual(process.exitcode,0)
        self.assertEqual(self.controller.snapshot(),self.controller.before)

    def test_existing_null_marker_is_not_treated_as_absent(self):
        repairs=self.base/'repairs'
        repairs.mkdir()
        (repairs/'deployment-pending.json').write_text('null')
        with self.assertRaisesRegex(ValueError,'[Tt]ransaction|[Pp]ending|[Uu]nfinished'):
            deployment.rollout(self.base,self.prepared,self.archive,self.controller)
        self.assertFalse(self.archive.exists())
        self.assertEqual(self.controller.events,[])
        self.assertEqual(self.controller.snapshot(),self.controller.before)

    def test_crash_pending_blocks_cli_prepare_and_rehearse(self):
        self.crash('after_pending')
        class Fake:
            def __init__(self,*args): pass
            def inputs(self): pass
        for action in ('prepare','rehearse'):
            with patch.object(rollout_controller,'Controller',Fake), patch.object(rollout_controller,'validate_outputs'), patch.object(rollout_controller,'execute_action') as execute:
                with self.assertRaisesRegex(ValueError,'Unfinished deployment'):
                    rollout_controller.main([action,'--base',str(self.base),'--qa',str(self.root/'qa'),'--manifest',str(self.root/'manifest'),'--prepared',str(self.root/'extra-prepared'),'--archive',str(self.root/'extra-archive')])
                execute.assert_not_called()

    def test_terminal_marker_is_retained_when_installed_verification_fails(self):
        self.crash('after_terminal_journal')
        before=self.controller.snapshot()
        marker=self.base/'repairs/deployment-pending.json'
        pending=marker.read_bytes()
        def reject(*args):
            raise ValueError('independent readiness rejection')
        self.controller.verify_running=reject
        with self.assertRaisesRegex(ValueError,'readiness rejection'):
            deployment.recover_archive(self.archive,self.controller)
        self.assertEqual(marker.read_bytes(),pending)
        self.assertEqual(self.controller.snapshot(),before)
        with self.assertRaisesRegex(ValueError,'Unfinished deployment'):
            deployment.rollout(self.base,self.prepared,self.root/'new-archive',self.controller)

    def test_terminal_pending_verifies_current_install_without_undoing_it(self):
        self.crash('after_terminal_journal')
        old_archive=(self.archive/'tools-before/version').read_bytes()
        before=self.controller.snapshot()
        inode=(self.base/'repairs/deployment.lock').stat().st_ino
        result=deployment.recover_archive(self.archive,self.controller)
        self.assertEqual(result['phase'],'INSTALLED_PAUSED')
        self.assertEqual(self.controller.snapshot(),before)
        self.assertEqual((self.archive/'tools-before/version').read_bytes(),old_archive)
        self.assertEqual(self.controller.events,[])
        self.assertEqual((self.base/'repairs/deployment.lock').stat().st_ino,inode)
        with self.assertRaisesRegex(ValueError,'No matching'):
            deployment.recover_archive(self.archive,self.controller)

if __name__=='__main__': unittest.main()
