"""Independent Group-7 QA for the paused rollout controller."""
import contextlib
import fcntl
import io
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


STAGE_SOURCE = Path(__file__).resolve().parent.parent / 'wrapper-workflow-20261118'
sys.path.insert(0, str(STAGE_SOURCE))
import release_bundle as release
import rollout_controller as rollout


class FakeRunner:
    def __init__(self):
        self.calls = []
        self.active = True
        self.pid = 4321
        self.unit_fragment = None
        self.unit_dropin = None
        self.jetson_hash = None

    def __call__(self, command, **kwargs):
        self.calls.append((list(command), dict(kwargs)))
        if command[:2] == ['systemctl', '--user']:
            action = command[2]
            if action == 'stop':
                self.active, self.pid = False, 0
                return types.SimpleNamespace(stdout='', returncode=0)
            if action == 'start':
                self.active, self.pid = True, 4322
                return types.SimpleNamespace(stdout='', returncode=0)
            if action == 'show':
                if any(arg.startswith('--property=FragmentPath') for arg in command):
                    return types.SimpleNamespace(
                        stdout=(f'FragmentPath={self.unit_fragment}\n'
                                f'DropInPaths={self.unit_dropin}\n'),
                        returncode=0)
                active = 'active' if self.active else 'inactive'
                sub = 'running' if self.active else 'dead'
                return types.SimpleNamespace(
                    stdout=(f'ActiveState={active}\nSubState={sub}\n'
                            f'UnitFileState=enabled\nMainPID={self.pid}\n'),
                    returncode=0)
            raise AssertionError(command)
        if command and command[0] == 'ssh':
            return types.SimpleNamespace(
                stdout=f'{self.jetson_hash}  wrapper_commands.py\n',
                returncode=0)
        code = command[3] if len(command) > 3 and command[1:3] == ['-B', '-c'] else ''
        if 'estimate_context' not in code or any(word in code for word in ('infer(', 'urllib', 'model(')):
            raise AssertionError('Tokenizer smoke attempted an unexpected action: ' + repr(command))
        return types.SimpleNamespace(stdout='TOKENIZER_OK\n', returncode=0)


class RolloutControllerQATests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.stage = self.root / 'stage'
        self.qa = self.root / 'qa'
        self.base = self.root / 'installed' / 'dev' / 'wrapper-coder'
        self.prepared = self.root / 'prepared'
        self.archive = self.root / 'archive'
        self.qa.mkdir()
        self.base.mkdir(parents=True)
        names = ['host/' + name for name in (
            'coordinator.py', 'coordinator_store.py', 'coordinator_workspace.py',
            'coordinator_budget.py', 'migrate_campaign_membership.py',
            'backfill_campaign_metadata.py')]
        names += [
            'jetson/wrapper_commands.py', 'backlog/batch-1.json',
            'WORKFLOW.md', 'deploy_campaign_update.py', 'release_bundle.py',
            'rollout_controller.py',
        ]
        items = [{'objective': f'Company {n}', 'integration': {
            'company_id': f'COMP-{n:04}', 'company': f'Company {n}',
            'configured_url': f'https://example.test/{n}',
            'tests': ['tests/test_company.py'],
            'source_targets': ['src/company.py'],
        }} for n in range(1, 103)]
        for name in names:
            path = self.stage / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(items) if name == 'backlog/batch-1.json'
                            else '# reviewed fixture ' + name + '\n')

        tools = self.base / 'tools'
        for name in (*release.PREREQUISITE_FILES,
                     'resources/qwen35/tokenizer.json',
                     'coordinator_vendor/library.py'):
            path = tools / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('reviewed prerequisite ' + name + '\n')
        (self.base / 'jetson').mkdir()
        (self.base / 'jetson/old.py').write_text('old jetson source\n')
        (tools / 'old.py').write_text('old installed source\n')
        (self.base / 'queue-base').mkdir()
        (self.base / 'queue-base/reviewed').write_text('baseline\n')
        (self.base / 'client-config.json').write_text('{"url":"http://127.0.0.1:18789"}\n')
        (self.base / 'bridge-token').write_text('TOP-SECRET-BRIDGE-TOKEN\n')
        (self.base.parents[1] / '.venv/bin').mkdir(parents=True)
        (self.base.parents[1] / '.venv/bin/python').write_text('# fake python\n')

        self.reviewed_ids = [f'WRAP-{n:010x}' for n in range(1, 103)]
        inputs = {
            rollout.INPUTS[0]: self.reviewed_ids,
            rollout.INPUTS[1]: {'count': 102, 'sha256': 'a' * 64,
                                'original_batches': {'reviewed': self.reviewed_ids}},
            rollout.INPUTS[2]: {'tests/test_company.py': 'b' * 64},
            rollout.INPUTS[3]: {'src/company.py': 'c' * 64},
        }
        for name, value in inputs.items():
            (self.qa / name).write_text(json.dumps(value))

        self.sources = release.source_manifest(self.stage)
        self.prerequisites = release.prerequisite_manifest(tools)
        self.manifest = {
            'version': 1,
            'sources': self.sources,
            'prerequisites': self.prerequisites,
            'migration_inputs': {name: release.metadata(self.qa / name)
                                 for name in rollout.INPUTS},
            'release_digest': release.digest(
                release.expected_release(self.sources, self.prerequisites)),
        }
        self.manifest_path = self.root / 'manifest.json'
        self.manifest_path.write_text(json.dumps(self.manifest))
        self.pass_report = {
            'result': 'PASS', 'independent': True,
            'manifest_digest': release.digest(self.manifest),
        }
        self.report_path = self.root / 'qa-pass.json'
        self.report_path.write_text(json.dumps(self.pass_report))
        release.build_release(
            self.stage, tools, self.prepared, self.sources, self.prerequisites)
        self.make_database(self.base / 'tasks/tasks.sqlite3')
        self.manifest['expected_database_digest'] = rollout.paused_database(
            self.base / 'tasks/tasks.sqlite3')['digest']
        self.manifest_path.write_text(json.dumps(self.manifest))
        self.pass_report['manifest_digest'] = release.digest(self.manifest)
        self.report_path.write_text(json.dumps(self.pass_report))
        self.runner = FakeRunner()
        unit = self.root / 'wrapper-development-host.service'
        dropin = self.root / 'wrapper-development-host.service.d/override.conf'
        dropin.parent.mkdir()
        unit.write_text('[Service]\nExecStart=/reviewed/host\n')
        dropin.write_text('[Service]\nEnvironment=ROLLOUT=reviewed\n')
        self.runner.unit_fragment = unit
        self.runner.unit_dropin = dropin
        self.runner.jetson_hash = self.sources['jetson/wrapper_commands.py']['sha256']

    @staticmethod
    def make_database(path, *, controls=None, members=(), nonmembers=()):
        path.parent.mkdir(parents=True, exist_ok=True)
        controls = controls or {
            'queue_enabled': False, 'autopilot_enabled': False,
            'campaign_enabled': False, 'pilot_task': None,
        }
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT)')
            db.executemany('INSERT INTO settings VALUES (?,?)',
                           [(key, json.dumps(value)) for key, value in controls.items()])
            db.execute('CREATE TABLE tasks(id TEXT PRIMARY KEY,state TEXT)')
            for task_id in members:
                db.execute('INSERT INTO tasks VALUES (?,?)',
                           (task_id, json.dumps({'id': task_id, 'status': 'PAUSED'})))
            for task_id in nonmembers:
                db.execute('INSERT INTO tasks VALUES (?,?)',
                           (task_id, json.dumps({'id': task_id, 'status': 'PAUSED',
                                                'note': 'preserve exactly'})))
            db.execute('CREATE TABLE receipts(id INTEGER,task TEXT,name TEXT,result TEXT)')
            db.execute('CREATE TABLE inference_receipts(request_id TEXT,status TEXT)')
            db.execute('CREATE TABLE batches(digest TEXT,task_ids TEXT)')

    def controller(self, report=None, health=None):
        return rollout.Controller(
            self.stage, self.qa, self.manifest,
            self.pass_report if report is None else report,
            run=self.runner, health=health)

    def snapshot(self):
        return {
            'database': rollout.logical_database(self.base / 'tasks/tasks.sqlite3'),
            'tools': release.tree(self.base / 'tools'),
            'jetson': release.tree(self.base / 'jetson'),
        }

    def test_preflight_is_read_only_and_rejects_every_unbound_input_before_callbacks(self):
        controller = self.controller()
        before = self.snapshot()
        self.assertEqual(controller.preflight(self.base, self.prepared)['integrity'], 'ok')
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.runner.calls, [])

        bad_reports = (
            {},
            {'result': 'FAIL', 'independent': True,
             'manifest_digest': release.digest(self.manifest)},
            {'result': 'PASS', 'independent': False,
             'manifest_digest': release.digest(self.manifest)},
            {'result': 'PASS', 'independent': True,
             'manifest_digest': '0' * 64},
        )
        for report in bad_reports:
            with self.subTest(report=report):
                with self.assertRaisesRegex(ValueError, 'staged PASS'):
                    self.controller(report=report).preflight(self.base, self.prepared)
                self.assertEqual(self.snapshot(), before)
                self.assertEqual(self.runner.calls, [])

        changed = self.stage / 'host/coordinator.py'
        original = changed.read_bytes()
        changed.write_text('changed source\n')
        with self.assertRaisesRegex(ValueError, 'source changed'):
            controller.preflight(self.base, self.prepared)
        changed.write_bytes(original)
        migration_input = self.qa / rollout.INPUTS[0]
        original = migration_input.read_bytes()
        migration_input.write_text('[]')
        with self.assertRaisesRegex(ValueError, 'migration inputs changed'):
            controller.preflight(self.base, self.prepared)
        migration_input.write_bytes(original)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.runner.calls, [])

    def test_controls_active_tasks_and_unfinished_work_always_fail_closed(self):
        database = self.base / 'tasks/tasks.sqlite3'
        for key, value in (
            ('queue_enabled', True), ('autopilot_enabled', True),
            ('campaign_enabled', True), ('pilot_task', 'WRAP-pilot'),
        ):
            with self.subTest(control=key), sqlite3.connect(database) as db:
                db.execute('UPDATE settings SET value=? WHERE key=?',
                           (json.dumps(value), key))
                db.commit()
                with self.assertRaisesRegex(ValueError, 'controls'):
                    rollout.paused_database(database)
                db.execute('UPDATE settings SET value=? WHERE key=?',
                           (json.dumps(None if key == 'pilot_task' else False), key))
                db.commit()
        with sqlite3.connect(database) as db:
            db.execute('INSERT INTO tasks VALUES (?,?)',
                       ('WRAP-active', json.dumps({'id': 'WRAP-active', 'status': 'RUNNING'})))
        with self.assertRaisesRegex(ValueError, 'Active task'):
            rollout.paused_database(database)
        with sqlite3.connect(database) as db:
            db.execute('DELETE FROM tasks')
            db.execute('INSERT INTO receipts VALUES (1,?,?,NULL)',
                       ('WRAP-x', 'code_edit'))
        with self.assertRaisesRegex(ValueError, 'Unfinished tool'):
            rollout.paused_database(database)

    def test_exact_102_migration_is_noop_on_second_apply_and_preserves_nonmembers(self):
        database = self.base / 'tasks/tasks.sqlite3'
        database.unlink()
        nonmember = 'WRAP-fffffffffe'
        self.make_database(database, members=self.reviewed_ids,
                           nonmembers=[nonmember])

        class FakeStore:
            def __init__(store_self, base):
                store_self.base = Path(base)
                store_self.path = store_self.base / 'tasks.sqlite3'
                with sqlite3.connect(store_self.path) as db:
                    db.execute('CREATE TABLE IF NOT EXISTS campaign_company_registry('
                               'campaign_id TEXT,company_id TEXT,current_task_id TEXT,identity_digest TEXT,import_digest TEXT,retry_of TEXT)')

        def membership(store, campaign, items, *, apply=False, reviewed_hold_ids=(), **_):
            ids = list(reviewed_hold_ids)
            with sqlite3.connect(store.path) as db:
                states = {task: json.loads(raw) for task, raw in db.execute('SELECT id,state FROM tasks')}
                changed = [task for task in ids if not states[task].get('membership')]
                if apply:
                    for task in changed:
                        states[task]['membership'] = campaign
                        db.execute('UPDATE tasks SET state=? WHERE id=?',
                                   (json.dumps(states[task]), task))
            return {'clean': True, 'held': ids, 'changed': changed}

        def identity(store, items, *, apply=False, **_):
            ids = self.reviewed_ids
            with sqlite3.connect(store.path) as db:
                states = {task: json.loads(raw) for task, raw in db.execute('SELECT id,state FROM tasks')}
                changed = [task for task in ids if not states[task].get('identity')]
                registered = [task for task in ids if not db.execute(
                    'SELECT 1 FROM campaign_company_registry WHERE current_task_id=?',
                    (task,)).fetchone()]
                if apply:
                    for index, task in enumerate(changed, 1):
                        states[task]['identity'] = True
                        db.execute('UPDATE tasks SET state=? WHERE id=?',
                                   (json.dumps(states[task]), task))
                    for index, task in enumerate(registered, 1):
                        db.execute('INSERT INTO campaign_company_registry VALUES (?,?,?,?,?,NULL)',
                                   (rollout.CAMPAIGN, f'COMP-{index:04}', task,
                                    f'digest-{index}', 'reviewed'))
            return {'matched': ids, 'changed': changed, 'registered': registered}

        modules = {
            'coordinator_store': types.SimpleNamespace(Store=FakeStore),
            'migrate_campaign_membership': types.SimpleNamespace(
                migrate_campaign_membership=membership),
            'backfill_campaign_metadata': types.SimpleNamespace(
                backfill_campaign_identity=identity),
        }
        before_nonmember = dict(rollout.logical_database(database)['tasks'])[nonmember]
        self.manifest['expected_database_digest'] = rollout.paused_database(database)['digest']
        with patch.dict(sys.modules, modules):
            result = self.controller().migration(database, self.base / 'queue-base')
        self.assertEqual(result['result'], 'PASS')
        self.assertEqual(result['reviewed_count'], 102)
        self.assertTrue(result['second_apply_noop'])
        self.assertTrue(result['nonmembers_preserved'])
        after = rollout.logical_database(database)
        self.assertEqual(dict(after['tasks'])[nonmember], before_nonmember)
        self.assertEqual(len(after['campaign_company_registry']), 102)
        self.assertFalse(any(result['paused']['controls'][key]
                             for key in ('queue_enabled', 'autopilot_enabled',
                                         'campaign_enabled')))
        self.assertIsNone(result['paused']['controls']['pilot_task'])

    def install_prepared(self):
        shutil.rmtree(self.base / 'tools')
        shutil.rmtree(self.base / 'jetson')
        shutil.copytree(self.prepared / 'tools', self.base / 'tools')
        shutil.copytree(self.prepared / 'jetson', self.base / 'jetson')

    def test_stopped_and_running_checks_require_parity_health_lock_and_no_ai(self):
        self.install_prepared()
        controller = self.controller(health=lambda _base: {
            'ok': True, 'worker_alive': True, 'status': 'healthy',
            'secret': 'must not be persisted',
        })
        controller.recovery_binding(self.base, self.prepared, self.archive)
        self.runner.active, self.runner.pid = False, 0
        self.archive.mkdir()
        controller.capture_before(self.base, self.archive)
        controller.verify_stopped(self.base, self.archive)
        self.assertTrue((self.archive / 'stopped-verification.json').is_file())
        tokenizer_calls = [call for call, _ in self.runner.calls
                           if call and call[0].endswith('/python')]
        self.assertEqual(len(tokenizer_calls), 1)

        self.runner.active, self.runner.pid = True, 5000
        lock_path = self.base / 'tasks/scheduler.lock'
        with lock_path.open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            controller.verify_running(self.base, self.archive)
        saved = (self.archive / 'running-verification.json').read_text()
        self.assertNotIn('must not be persisted', saved)
        self.assertIn('"live_inference_performed": false', saved)

        with self.assertRaisesRegex(ValueError, 'ownership lock'):
            controller.verify_running(self.base, self.archive)

    def test_running_verification_rejects_paused_database_drift_after_start(self):
        self.install_prepared()
        controller = self.controller(health=lambda _base: {
            'ok': True, 'worker_alive': True, 'status': 'healthy',
        })
        controller.recovery_binding(self.base, self.prepared, self.archive)
        self.runner.active, self.runner.pid = False, 0
        self.archive.mkdir()
        controller.capture_before(self.base, self.archive)
        controller.verify_stopped(self.base, self.archive)

        # Model a startup callback that changes durable state while leaving all
        # controls OFF and every task safely paused.
        with sqlite3.connect(self.base / 'tasks/tasks.sqlite3') as db:
            db.execute('INSERT INTO tasks VALUES (?,?)', (
                'WRAP-startup-drift',
                json.dumps({'id': 'WRAP-startup-drift', 'status': 'PAUSED'}),
            ))
        self.runner.active, self.runner.pid = True, 5001
        lock_path = self.base / 'tasks/scheduler.lock'
        with lock_path.open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(ValueError, 'database|paused|changed'):
                controller.verify_running(self.base, self.archive)
        self.assertFalse((self.archive / 'running-verification.json').exists())

    def test_auth_token_is_used_only_in_header_and_never_appears_in_errors(self):
        controller = self.controller()
        captured = {}

        def reject(request, timeout):
            captured['authorization'] = request.headers.get('Authorization')
            raise RuntimeError('connection failed')

        with patch.object(rollout.urllib.request, 'urlopen', side_effect=reject):
            with self.assertRaisesRegex(ValueError, 'health request failed') as caught:
                controller.health(self.base)
        self.assertEqual(captured['authorization'], 'Bearer TOP-SECRET-BRIDGE-TOKEN')
        self.assertNotIn('TOP-SECRET-BRIDGE-TOKEN', str(caught.exception))

    def test_rollback_verification_detects_source_or_database_mismatch(self):
        controller = self.controller()
        controller.recovery_binding(self.base, self.prepared, self.archive)
        self.runner.active, self.runner.pid = False, 0
        self.archive.mkdir()
        controller.capture_before(self.base, self.archive)
        tools_before = release.tree(self.base / 'tools')
        jetson_before = release.tree(self.base / 'jetson')
        database_before = rollout.logical_database(self.base / 'tasks/tasks.sqlite3')

        (self.base / 'tools/old.py').write_text('corrupt source\n')
        with self.assertRaisesRegex(ValueError, 'source parity'):
            controller.verify_restored(self.base, self.archive)
        (self.base / 'tools/old.py').write_text('old installed source\n')
        with sqlite3.connect(self.base / 'tasks/tasks.sqlite3') as db:
            db.execute('INSERT INTO tasks VALUES (?,?)',
                       ('WRAP-corrupt', json.dumps({'id': 'WRAP-corrupt',
                                                   'status': 'PAUSED'})))
        with self.assertRaisesRegex(ValueError, 'database parity'):
            controller.verify_restored(self.base, self.archive)
        with sqlite3.connect(self.base / 'tasks/tasks.sqlite3') as db:
            db.execute("DELETE FROM tasks WHERE id='WRAP-corrupt'")
        controller.verify_restored(self.base, self.archive)
        self.assertEqual(release.tree(self.base / 'tools'), tools_before)
        self.assertEqual(release.tree(self.base / 'jetson'), jetson_before)
        self.assertEqual(rollout.logical_database(self.base / 'tasks/tasks.sqlite3'),
                         database_before)

    def test_cli_allows_disposable_preparation_but_rejects_output_under_production(self):
        disposable = self.root / 'disposable-release'
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            rollout.main([
                'prepare', '--stage', str(self.stage), '--qa', str(self.qa),
                '--manifest', str(self.manifest_path), '--base', str(self.base),
                '--prepared', str(disposable),
            ])
        self.assertTrue(disposable.is_dir())
        self.assertEqual(json.loads(output.getvalue())['result'], 'PREPARED')

        unsafe = self.base / 'tasks/unsafe-release'
        with self.assertRaisesRegex(ValueError, 'outside|overlap|production'):
            rollout.main([
                'prepare', '--stage', str(self.stage), '--qa', str(self.qa),
                '--manifest', str(self.manifest_path), '--base', str(self.base),
                '--prepared', str(unsafe),
            ])
        self.assertFalse(unsafe.exists())
        unsafe_archive = self.base / 'tasks/unsafe-rehearsal'
        with self.assertRaisesRegex(ValueError, 'outside|overlap|production'):
            rollout.main([
                'rehearse', '--stage', str(self.stage), '--qa', str(self.qa),
                '--manifest', str(self.manifest_path), '--base', str(self.base),
                '--archive', str(unsafe_archive),
            ])
        self.assertFalse(unsafe_archive.exists())


if __name__ == '__main__':
    unittest.main()
