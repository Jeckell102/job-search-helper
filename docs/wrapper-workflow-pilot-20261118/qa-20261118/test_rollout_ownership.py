"""Separate-process release ownership and durable crash regression."""
import multiprocessing as mp
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from test_paused_rollout import Controller, PausedRolloutTests, deployment


def controller(base):
    c = Controller(base)
    c.before = {'rows': [('old',)], 'tools': 'old', 'jetson': 'old'}
    return c


def crash(base, prepared, archive, boundary):
    def fault(phase):
        if phase == boundary: os._exit(73)
    deployment.rollout(base, prepared, archive, controller(base), fault=fault)


def hold(base, prepared, archive, action, entered, release):
    c = controller(base)
    def wait():
        entered.set()
        if not release.wait(15): raise RuntimeError('owner timeout')
    if action == 'apply':
        deployment.rollout(base, prepared, archive, c, fault=lambda p: wait() if p == 'after_rehearsal' else None)
    else:
        stop = c.stop
        def blocked():
            wait(); stop()
        c.stop = blocked
        deployment.recover_archive(archive, c)


def contend(base, prepared, archive, action, output):
    c = controller(base)
    try:
        if action == 'apply': deployment.rollout(base, prepared, archive, c)
        elif action == 'recover': deployment.recover_archive(archive, c)
        else:
            with deployment.deployment_owner(base): raise AssertionError('unexpected ownership')
    except ValueError as exc: output.put((str(exc), c.events))
    else: output.put(('ACCEPTED', c.events))


class OwnershipTests(unittest.TestCase):
    ctx = mp.get_context('fork')

    def kill_boundary(self, base, prepared, archive, boundary):
        p = self.ctx.Process(target=crash, args=(base, prepared, archive, boundary))
        p.start(); p.join(15)
        self.assertEqual(p.exitcode, 73)

    def contender(self, base, prepared, archive, action):
        q = self.ctx.Queue()
        p = self.ctx.Process(target=contend, args=(base, prepared, archive, action, q))
        p.start(); p.join(10)
        self.assertEqual(p.exitcode, 0)
        result, events = q.get(timeout=2)
        q.close(); q.join_thread()
        self.assertNotEqual(result, 'ACCEPTED'); self.assertEqual(events, [])
        return result

    def test_malformed_pending_record_is_preserved_and_rejected(self):
        for value in (None, [], {}, {'version': 1}, 'text'):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as tmp:
                base, prepared, archive, c = PausedRolloutTests().fixture(Path(tmp))
                (base / 'repairs').mkdir()
                marker = base / 'repairs/deployment-pending.json'
                marker.write_text(json.dumps(value))
                before = marker.read_bytes()
                with self.assertRaisesRegex(ValueError, 'Invalid durable'):
                    deployment.rollout(base, prepared, archive, c)
                self.assertEqual(marker.read_bytes(), before)
                self.assertFalse(archive.exists())
                self.assertEqual(c.events, [])

    def test_separate_process_contention(self):
        for owner in ('apply', 'recover'):
            for contender in ('apply', 'recover', 'rehearse'):
                with self.subTest(owner=owner, contender=contender), tempfile.TemporaryDirectory() as tmp:
                    base, prepared, archive, _ = PausedRolloutTests().fixture(Path(tmp))
                    prepared2, archive2 = Path(tmp)/'prepared2', Path(tmp)/'archive2'
                    shutil.copytree(prepared, prepared2)
                    if owner == 'recover': self.kill_boundary(base, prepared, archive, 'after_rehearsal')
                    entered, release = self.ctx.Event(), self.ctx.Event()
                    p = self.ctx.Process(target=hold, args=(base, prepared, archive, owner, entered, release))
                    p.start()
                    try:
                        self.assertTrue(entered.wait(10))
                        before = controller(base).snapshot()
                        target = archive if contender == 'recover' else archive2
                        self.assertIn('owns', self.contender(base, prepared2, target, contender))
                        self.assertEqual(controller(base).snapshot(), before)
                        self.assertFalse(archive2.exists())
                    finally:
                        release.set(); p.join(15)
                        if p.is_alive(): p.kill(); p.join()
                    self.assertEqual(p.exitcode, 0)

    def test_crash_barrier_matching_recovery_and_stale_archive(self):
        for boundary in ('after_pending', 'after_rehearsal', 'after_publish_tools', 'after_publish_jetson',
                         'after_membership', 'after_migration', 'after_terminal_journal'):
            with self.subTest(boundary=boundary), tempfile.TemporaryDirectory() as tmp:
                base, prepared, archive, _ = PausedRolloutTests().fixture(Path(tmp))
                prepared2, archive2 = Path(tmp)/'prepared2', Path(tmp)/'archive2'
                shutil.copytree(prepared, prepared2)
                self.kill_boundary(base, prepared, archive, boundary)
                self.assertIn('Unfinished', self.contender(base, prepared2, archive2, 'apply'))
                self.assertFalse(archive2.exists())
                self.assertIn('matching', self.contender(base, prepared2, archive2, 'recover'))
                result = deployment.recover_archive(archive, controller(base))
                self.assertEqual(result['phase'], 'INSTALLED_PAUSED' if boundary == 'after_terminal_journal' else 'ROLLED_BACK')
                self.assertFalse((base/'repairs/deployment-pending.json').exists())
                if boundary != 'after_terminal_journal':
                    self.assertEqual(controller(base).snapshot(), controller(base).before)
                    deployment.rollout(base, prepared2, archive2, Controller(base))
                snapshot = controller(base).snapshot()
                with self.assertRaisesRegex(ValueError, 'matching'):
                    deployment.recover_archive(archive, controller(base))
                self.assertEqual(controller(base).snapshot(), snapshot)

if __name__ == '__main__': unittest.main()
