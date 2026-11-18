"""Fault injection proves stopped-service source/database rollback boundaries."""
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'wrapper-workflow-20261118'))
import deploy_campaign_update as deployment


class Controller:
    def __init__(self, base):
        self.base, self.running = base, True
        self.before = self.snapshot()
        self.events = []

    def snapshot(self):
        with sqlite3.connect(self.base / 'tasks/tasks.sqlite3') as db:
            rows = db.execute('select * from fixture').fetchall()
        return {'rows': rows, 'tools': (self.base / 'tools/version').read_text(),
                'jetson': (self.base / 'jetson/version').read_text()}

    def preflight(self, base, prepared):
        assert self.snapshot() == self.before
        assert (base / 'tasks/workspace/keep').read_text() == 'preserve'

    def recovery_binding(self, base, prepared, archive):
        return {'base': str(base), 'prepared': str(prepared), 'archive': str(archive)}

    def validate_recovery(self, journal, archive):
        assert Path(journal['base']) == self.base
        assert Path(journal['prepared']) == self.base.parent / 'prepared'
        assert archive == self.base.parent / 'archive'

    def service_state(self):
        return {'active': self.running, 'enabled': True}

    def stop(self):
        self.running = False
        self.events.append('stop')

    def assert_stopped(self):
        assert not self.running

    def capture_before(self, base, archive):
        self.events.append('backup')

    def rehearse(self, backup, archive):
        assert not self.running
        with sqlite3.connect(backup) as db:
            assert db.execute('select value from fixture').fetchone()[0] == 'old'

    def migrate(self, base, archive, fault):
        assert not self.running
        for boundary in ('membership', 'identity', 'baseline'):
            with sqlite3.connect(base / 'tasks/tasks.sqlite3') as db:
                db.execute('update fixture set value=?', (boundary,))
            fault('after_' + boundary)

    def verify_stopped(self, base, archive):
        assert not self.running
        assert self.snapshot() == {'rows': [('baseline',)], 'tools': 'new', 'jetson': 'new'}

    def start(self):
        self.running = True
        self.events.append('start')

    def verify_running(self, base, archive):
        assert self.running
        assert self.snapshot()['tools'] == 'new'

    def verify_restored(self, base, archive):
        assert not self.running
        assert self.snapshot() == self.before

    def restore_service(self, before):
        self.running = before['active']


class PausedRolloutTests(unittest.TestCase):
    def fixture(self, path):
        base, prepared, archive = [path / s for s in ('base', 'prepared', 'archive')]
        for root, version in ((base, 'old'), (prepared, 'new')):
            for name in ('tools', 'jetson'):
                (root / name).mkdir(parents=True)
                (root / name / 'version').write_text(version)
        (base / 'tasks/workspace').mkdir(parents=True)
        (base / 'tasks/workspace/keep').write_text('preserve')
        with sqlite3.connect(base / 'tasks/tasks.sqlite3') as db:
            db.execute('create table fixture(value text)')
            db.execute("insert into fixture values ('old')")
        return base, prepared, archive, Controller(base)

    def test_success_publishes_with_backup_and_preserves_workspace(self):
        with tempfile.TemporaryDirectory() as folder:
            base, prepared, archive, controller = self.fixture(Path(folder))
            report = deployment.rollout(base, prepared, archive, controller)
            self.assertEqual(report['phase'], 'INSTALLED_PAUSED')
            self.assertEqual((archive / 'tools-before/version').read_text(), 'old')
            self.assertEqual((base / 'tasks/workspace/keep').read_text(), 'preserve')
            self.assertTrue(controller.running)

    def test_each_failure_restores_exact_source_database_and_service(self):
        for boundary in ('after_rehearsal', 'after_publish_tools', 'after_publish_jetson',
                         'after_membership', 'after_identity', 'after_baseline', 'after_migration'):
            with self.subTest(boundary=boundary), tempfile.TemporaryDirectory() as folder:
                base, prepared, archive, controller = self.fixture(Path(folder))
                def fault(phase):
                    if phase == boundary:
                        raise RuntimeError('injected ' + phase)
                with self.assertRaisesRegex(RuntimeError, 'injected'):
                    deployment.rollout(base, prepared, archive, controller, fault=fault)
                self.assertEqual(controller.snapshot(), controller.before)
                self.assertTrue(controller.running)
                self.assertEqual((base / 'tasks/workspace/keep').read_text(), 'preserve')
                self.assertEqual(json.loads((archive / 'journal.json').read_text())['phase'], 'ROLLED_BACK')

    def test_failed_preflight_writes_nothing_and_does_not_stop_service(self):
        with tempfile.TemporaryDirectory() as folder:
            base, prepared, archive, controller = self.fixture(Path(folder))
            def reject(*args):
                raise ValueError('preflight rejection')
            controller.preflight = reject
            with self.assertRaises(ValueError):
                deployment.rollout(base, prepared, archive, controller)
            self.assertFalse(archive.exists())
            self.assertEqual(controller.events, [])
            self.assertEqual(controller.snapshot(), controller.before)

    def test_interrupted_rename_and_partial_publication_recover(self):
        for published_new in (False, True):
            with self.subTest(published_new=published_new), tempfile.TemporaryDirectory() as folder:
                base, prepared, archive, controller = self.fixture(Path(folder))
                archive.mkdir()
                deployment.backup_database(base / 'tasks/tasks.sqlite3', archive / 'tasks-before.sqlite3')
                journal = dict(version=1, phase='PUBLISHING', base=str(base), prepared=str(prepared),
                    published=['tools'], backup_ready=True, service_before=controller.service_state())
                deployment.save_json(archive / 'journal.json', journal)
                controller.stop()
                (base / 'tools').rename(archive / 'tools-before')
                if published_new:
                    (prepared / 'tools').rename(base / 'tools')
                with sqlite3.connect(base / 'tasks/tasks.sqlite3') as db:
                    db.execute("update fixture set value='partial'")
                result = deployment.recover_archive(archive, controller)
                self.assertEqual(result['phase'], 'ROLLED_BACK')
                self.assertEqual(controller.snapshot(), controller.before)
                self.assertTrue(controller.running)
                self.assertEqual((base / 'tasks/workspace/keep').read_text(), 'preserve')

    def test_interrupted_recovery_can_resume_after_old_directory_already_restored(self):
        with tempfile.TemporaryDirectory() as folder:
            base, prepared, archive, controller = self.fixture(Path(folder))
            archive.mkdir()
            deployment.backup_database(base / 'tasks/tasks.sqlite3', archive / 'tasks-before.sqlite3')
            journal = dict(version=1, phase='ROLLING_BACK', base=str(base), prepared=str(prepared),
                published=['tools'], backup_ready=True, service_before=controller.service_state())
            deployment.save_json(archive / 'journal.json', journal)
            with sqlite3.connect(base / 'tasks/tasks.sqlite3') as db:
                db.execute("update fixture set value='partial'")
            deployment.recover_archive(archive, controller)
            self.assertEqual(controller.snapshot(), controller.before)
            self.assertTrue(controller.running)

    def test_malformed_recovery_journal_does_not_touch_service_or_files(self):
        for changes in ({'version': 99}, {'phase': 'invented'}, {'published': ['jetson']},
                        {'published': ['tools', 'tools']}, {'backup_ready': 'yes'}):
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as folder:
                base, prepared, archive, controller = self.fixture(Path(folder))
                archive.mkdir()
                journal = dict(version=1, phase='PREPARED', base=str(base), prepared=str(prepared),
                    published=[], backup_ready=False, service_before=controller.service_state())
                journal.update(changes)
                deployment.save_json(archive / 'journal.json', journal)
                with self.assertRaises(ValueError):
                    deployment.recover_archive(archive, controller)
                self.assertEqual(controller.events, [])
                self.assertEqual(controller.snapshot(), controller.before)

    def test_failed_running_check_also_rolls_back(self):
        with tempfile.TemporaryDirectory() as folder:
            base, prepared, archive, controller = self.fixture(Path(folder))
            def reject(*args):
                raise ValueError('health failed')
            controller.verify_running = reject
            with self.assertRaisesRegex(ValueError, 'health failed'):
                deployment.rollout(base, prepared, archive, controller)
            self.assertEqual(controller.snapshot(), controller.before)
            self.assertTrue(controller.running)


if __name__ == '__main__':
    unittest.main()
