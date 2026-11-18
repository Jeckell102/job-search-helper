"""Independent Group-2 QA for atomic scheduler control transitions."""
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import coordinator as coordinator_module
import coordinator_store as store_module
from coordinator_store import DEFAULT_CAMPAIGN_ID, Store


class ControlTransitionQATests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name) / 'tasks'
        self.store = Store(self.base)
        self.store.configure_queue(False)

    @staticmethod
    def spec(number):
        tests = [f'tests/test_company_{number}.py']
        return {
            'objective': f'Integrate Company {number}',
            'tests': tests,
            'mode': 'develop',
            'max_sessions': 10,
            'authorization_version': 1,
            'evidence_requirements': {},
            'workflow_version': 2,
            'integration': {
                'company_id': f'COMP-{number:04}',
                'company': f'Company {number}',
                'configured_url': f'https://example.com/company-{number}',
                'tests': tests,
                'source_targets': [f'src/company_{number}.py'],
            },
        }

    def candidates(self, numbers):
        ids, reused = self.store.enqueue_batch(
            'qa-' + '-'.join(map(str, numbers)),
            [self.spec(number) for number in numbers],
            held=True,
            campaign_id=DEFAULT_CAMPAIGN_ID,
        )
        self.assertFalse(reused)
        return ids

    @staticmethod
    def fields():
        return {
            'errors': 0,
            'reason': 'Resumed by operator.',
            'manifest': {},
        }

    @staticmethod
    def database_snapshot(store):
        with store.connect() as db:
            settings = db.execute('SELECT key,value FROM settings ORDER BY key').fetchall()
            tasks = db.execute('SELECT id,state FROM tasks ORDER BY rowid').fetchall()
        return settings, tasks

    @staticmethod
    def committed_mode(store):
        queue = store.queue_enabled()
        campaign = store.campaign_control()
        pilot = store.pilot_task()
        if pilot is not None:
            if queue or campaign['enabled']:
                raise AssertionError('mixed pilot controls')
            return 'pilot'
        if campaign['enabled']:
            if not queue:
                raise AssertionError('campaign without queue compatibility flag')
            return 'campaign'
        return 'generic_queue' if queue else 'stopped'

    def commit_pilot(self, store, task, snapshot):
        return store.commit_activation(
            task,
            self.fields(),
            expected_state_digest=snapshot['state_digest'],
            expected_control_generation=snapshot['control_generation'],
            pilot=True,
        )

    def race(self, left, right):
        barrier = threading.Barrier(2)

        def run(operation):
            barrier.wait()
            try:
                operation()
                return 'ok'
            except ValueError as exc:
                return type(exc).__name__ + ': ' + str(exc)

        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(run, (left, right)))

    def test_pilot_start_racing_campaign_start_commits_exactly_one_mode(self):
        task = self.candidates([1])[0]
        snapshot = self.store.activation_snapshot(task)
        pilot_store = Store(self.base)
        campaign_store = Store(self.base)

        results = self.race(
            lambda: self.commit_pilot(pilot_store, task, snapshot),
            lambda: campaign_store.configure_campaign(True, DEFAULT_CAMPAIGN_ID),
        )
        self.assertEqual(results.count('ok'), 1, results)
        mode = self.committed_mode(self.store)
        self.assertIn(mode, ('pilot', 'campaign'))
        if mode == 'pilot':
            self.assertEqual(self.store.pilot_task(), task)
            self.assertEqual(self.store.get(task)['status'], 'QUEUED')
        else:
            self.assertIsNone(self.store.pilot_task())
            self.assertEqual(self.store.get(task), snapshot['state'])

    def test_pilot_start_racing_queue_resume_commits_exactly_one_mode(self):
        task = self.candidates([1])[0]
        snapshot = self.store.activation_snapshot(task)
        pilot_store = Store(self.base)
        queue_store = Store(self.base)

        results = self.race(
            lambda: self.commit_pilot(pilot_store, task, snapshot),
            lambda: queue_store.configure_queue(True),
        )
        self.assertEqual(results.count('ok'), 1, results)
        mode = self.committed_mode(self.store)
        self.assertIn(mode, ('pilot', 'generic_queue'))
        self.assertEqual(self.store.get(task)['status'],
                         'QUEUED' if mode == 'pilot' else 'PAUSED')

    def test_competing_pilot_starts_publish_one_slot_and_one_task(self):
        first, second = self.candidates([1, 2])
        first_snapshot = self.store.activation_snapshot(first)
        second_snapshot = self.store.activation_snapshot(second)
        stores = [Store(self.base), Store(self.base)]

        results = self.race(
            lambda: self.commit_pilot(stores[0], first, first_snapshot),
            lambda: self.commit_pilot(stores[1], second, second_snapshot),
        )
        self.assertEqual(results.count('ok'), 1, results)
        owner = self.store.pilot_task()
        self.assertIn(owner, (first, second))
        queued = [state['id'] for state in self.store.all() if state['status'] == 'QUEUED']
        self.assertEqual(queued, [owner])
        self.assertEqual(self.committed_mode(self.store), 'pilot')

    def test_pause_during_preparation_prevents_pilot_publication(self):
        task = self.candidates([1])[0]
        snapshot = self.store.activation_snapshot(task)
        self.store.pause_task(task, 'Operator paused during preparation.')
        before_commit = self.database_snapshot(self.store)

        with self.assertRaisesRegex(ValueError, 'changed during activation preparation'):
            self.commit_pilot(self.store, task, snapshot)
        self.assertEqual(self.database_snapshot(self.store), before_commit)
        self.assertIsNone(self.store.pilot_task())

    def test_failed_workspace_preparation_never_publishes_pilot(self):
        task = self.candidates([1])[0]
        coordinator = coordinator_module.Coordinator(
            self.base, model=lambda *_: None, budget=lambda *_: None)
        before = self.database_snapshot(self.store)

        with patch.object(coordinator_module, 'workspace', side_effect=OSError('workspace failed')):
            with self.assertRaisesRegex(OSError, 'workspace failed'):
                coordinator.command({'action': 'pilot-start', 'id': task})
        self.assertEqual(self.database_snapshot(self.store), before)
        self.assertIsNone(self.store.pilot_task())

    def test_failed_commit_rolls_back_pilot_and_task_writes(self):
        task = self.candidates([1])[0]
        snapshot = self.store.activation_snapshot(task)
        before = self.database_snapshot(self.store)

        with patch.object(Store, '_bump_control_generation', side_effect=RuntimeError('injected')):
            with self.assertRaisesRegex(RuntimeError, 'injected'):
                self.commit_pilot(self.store, task, snapshot)
        self.assertEqual(self.database_snapshot(self.store), before)
        self.assertIsNone(self.store.pilot_task())

    def test_pilot_rejects_any_other_queued_task_without_partial_write(self):
        pilot = self.candidates([1])[0]
        direct = self.store.create('Direct task', ['tests/test_direct.py'], 'review')
        snapshot = self.store.activation_snapshot(pilot)
        before = self.database_snapshot(self.store)

        with self.assertRaisesRegex(ValueError, 'execution lane|assignments are active'):
            self.commit_pilot(self.store, pilot, snapshot)
        self.assertEqual(self.database_snapshot(self.store), before)
        self.assertEqual(self.store.get(direct['id'])['status'], 'QUEUED')
        self.assertIsNone(self.store.pilot_task())

    def test_gate_auth_budget_deadline_and_receipt_fail_without_state_change(self):
        cases = {
            'live_gate': lambda store, task: store.update(task, status='LIVE_VALIDATED'),
            'awaiting_gate': lambda store, task: store.update(task, status='AWAITING_LIVE_VALIDATION'),
            'authorization': lambda store, task: store.update(task, authorization_version=0),
            'sessions': lambda store, task: store.update(task, sessions=10),
            'calls': lambda store, task: store.update(task, calls=48),
            'tokens': lambda store, task: store.update(task, tokens=120000),
            'unfinished_receipt': lambda store, task: store.intent(
                task, 'baseline', 'code_read', {'path': 'src/company_1.py'}),
            'non_isolated': lambda store, task: store.update(task, isolated_workspace=False),
        }
        for index, (label, arrange) in enumerate(cases.items(), 10):
            with self.subTest(case=label):
                base = Path(self.tmp.name) / label
                store = Store(base)
                store.configure_queue(False)
                ids, _ = store.enqueue_batch(
                    f'qa-{label}', [self.spec(index)], held=True,
                    campaign_id=DEFAULT_CAMPAIGN_ID)
                task = ids[0]
                arrange(store, task)
                snapshot = store.activation_snapshot(task)
                before = self.database_snapshot(store)
                with self.assertRaises(ValueError):
                    self.commit_pilot(store, task, snapshot)
                self.assertEqual(self.database_snapshot(store), before)
                self.assertIsNone(store.pilot_task())

        base = Path(self.tmp.name) / 'deadline'
        store = Store(base)
        store.configure_queue(False)
        ids, _ = store.enqueue_batch(
            'qa-deadline', [self.spec(99)], held=True,
            campaign_id=DEFAULT_CAMPAIGN_ID)
        task = ids[0]
        store.update(task, activated_at=1000.0)
        snapshot = store.activation_snapshot(task)
        before = self.database_snapshot(store)
        with patch.object(store_module.time, 'time', return_value=4601.0):
            with self.assertRaisesRegex(ValueError, 'budget exhausted'):
                self.commit_pilot(store, task, snapshot)
        self.assertEqual(self.database_snapshot(store), before)
        self.assertIsNone(store.pilot_task())

    def test_public_pause_cannot_launder_operator_gates_into_resumable_tasks(self):
        gates = (
            'AWAITING_LIVE_VALIDATION',
            'REVIEW_COMPLETE_LIVE_NOT_VALIDATED',
            'LIVE_VALIDATED',
        )
        tasks = self.candidates([31, 32, 33])
        coordinator = coordinator_module.Coordinator(
            self.base, model=lambda *_: None, budget=lambda *_: None)

        for task, gate in zip(tasks, gates):
            with self.subTest(gate=gate):
                coordinator.store.update(task, status=gate, reason='Operator gate.')
                paused = coordinator.command({'action': 'pause', 'id': task})['state']
                self.assertEqual(paused['status'], gate)
                self.assertTrue(paused['stop_requested'])
                self.assertEqual(paused['campaign_disposition'], 'USER_PAUSED')
                after_pause = self.database_snapshot(coordinator.store)

                with self.assertRaisesRegex(ValueError, 'operator gate'):
                    coordinator.command({'action': 'resume', 'id': task})
                self.assertEqual(self.database_snapshot(coordinator.store), after_pause)
                with self.assertRaisesRegex(ValueError, 'operator gate'):
                    coordinator.command({'action': 'pilot-start', 'id': task})
                self.assertEqual(self.database_snapshot(coordinator.store), after_pause)
                self.assertIsNone(coordinator.store.pilot_task())

    def test_exclude_include_chain_preserves_terminal_gate_and_cannot_resume(self):
        task = self.candidates([41])[0]
        coordinator = coordinator_module.Coordinator(
            self.base, model=lambda *_: None, budget=lambda *_: None)
        coordinator.store.update(
            task, status='LIVE_VALIDATED', activated_at=1000.0,
            reason='Operator live validation recorded.')

        excluded = coordinator.command({'action': 'exclude', 'id': task})['state']
        self.assertEqual(excluded['status'], 'LIVE_VALIDATED')
        self.assertEqual(excluded['campaign_disposition'], 'EXCLUDED')
        included = coordinator.command({'action': 'include', 'id': task})['state']
        self.assertEqual(included['status'], 'LIVE_VALIDATED')
        self.assertEqual(included['campaign_disposition'], 'USER_PAUSED')
        before_rejections = self.database_snapshot(coordinator.store)

        with self.assertRaisesRegex(ValueError, 'operator gate'):
            coordinator.command({'action': 'resume', 'id': task})
        with self.assertRaisesRegex(ValueError, 'operator gate'):
            coordinator.command({'action': 'pilot-start', 'id': task})
        with self.assertRaisesRegex(ValueError, 'operator gate'):
            coordinator.store.resume_campaign_task(task, reason='legacy helper resume')
        self.assertEqual(self.database_snapshot(coordinator.store), before_rejections)
        self.assertIsNone(coordinator.store.pilot_task())

    def test_pilot_stop_racing_campaign_start_ends_in_an_allowed_mode(self):
        task = self.candidates([1])[0]
        snapshot = self.store.activation_snapshot(task)
        self.commit_pilot(self.store, task, snapshot)
        self.assertEqual(self.committed_mode(self.store), 'pilot')
        stop_store = Store(self.base)
        campaign_store = Store(self.base)

        results = self.race(
            stop_store.stop_pilot,
            lambda: campaign_store.configure_campaign(True, DEFAULT_CAMPAIGN_ID),
        )
        self.assertIn(results.count('ok'), (1, 2), results)
        self.assertIn(self.committed_mode(self.store), ('stopped', 'campaign'))
        self.assertIsNone(self.store.pilot_task())
        state = self.store.get(task)
        self.assertTrue(state['stop_requested'] or state['status'] == 'PAUSED')
        self.assertNotEqual(state['status'], 'RUNNING')

    def test_restart_preserves_last_committed_mode(self):
        task = self.candidates([1])[0]
        snapshot = self.store.activation_snapshot(task)
        self.commit_pilot(self.store, task, snapshot)

        restarted = Store(self.base)
        self.assertEqual(self.committed_mode(restarted), 'pilot')
        self.assertEqual(restarted.pilot_task(), task)
        self.assertEqual(restarted.get(task)['status'], 'QUEUED')

        restarted.stop_pilot()
        stopped = Store(self.base)
        self.assertEqual(self.committed_mode(stopped), 'stopped')
        self.assertIsNone(stopped.pilot_task())
        self.assertEqual(stopped.get(task)['status'], 'PAUSED')


if __name__ == '__main__':
    unittest.main()
