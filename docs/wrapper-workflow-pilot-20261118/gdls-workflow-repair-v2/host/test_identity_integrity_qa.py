"""Independent Group-3 QA for canonical identity, registry, and lineage."""
import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import coordinator as coordinator_module
from backfill_campaign_metadata import backfill_campaign_identity
from coordinator_identity import (
    bind_identity,
    canonical_identity,
    canonical_requirements,
    identity_digest,
    validate_bound_identity,
    worker_assignment,
)
from coordinator_store import DEFAULT_CAMPAIGN_ID, Store, campaign_manifest_digest


class IdentityIntegrityQATests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name) / 'tasks'
        self.store = Store(self.base)

    @staticmethod
    def integration(number=1, **changes):
        result = {
            'company_id': f'COMP-{number:04}',
            'company': f'Canonical Company {number}',
            'configured_url': f'https://canonical.example/company-{number}',
            'tests': [f'tests/test_company_{number}.py'],
            'source_targets': [f'src/company_{number}.py'],
            'work_order': f'W{number:03}',
            'ats': 'canonical-ats',
        }
        result.update(changes)
        return result

    @classmethod
    def requirements(cls, number=1, integration=None):
        identity = canonical_identity(integration or cls.integration(number))
        return {
            'version': 1,
            'required_files': identity['tests'] + identity['source_targets'],
            'source_targets': [{
                'url': identity['configured_url'],
                'allowed_urls': [identity['configured_url']],
                'identity_terms': [identity['company']],
            }],
            'read_hints': {},
        }

    @classmethod
    def spec(cls, number=1, *, objective=None, integration=None):
        integration = integration or cls.integration(number)
        identity = canonical_identity(integration)
        return {
            'objective': objective or f'Audited import for Company {number}',
            'tests': identity['tests'],
            'mode': 'develop',
            'max_sessions': 10,
            'authorization_version': 1,
            'evidence_requirements': cls.requirements(number, integration),
            'workflow_version': 2,
            'integration': integration,
        }

    def campaign(self, digest, specs, campaign=DEFAULT_CAMPAIGN_ID):
        return self.store.enqueue_batch(digest, specs, held=True, campaign_id=campaign)

    def legacy_campaign_members(self, numbers):
        self.store.configure_queue(False)
        ids = []
        items = []
        bound_fields = (
            'integration_identity', 'integration_identity_digest',
            'worker_assignment', 'worker_assignment_digest',
            'identity_binding_digest', 'evidence_requirements_digest',
        )
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for number in numbers:
                spec = self.spec(number)
                state = self.store.new_state(**spec)
                state.update(
                    isolated_workspace=True,
                    status='PAUSED',
                    campaign_id=DEFAULT_CAMPAIGN_ID,
                    campaign_company_id=spec['integration']['company_id'],
                    campaign_disposition='HELD_FOR_CAMPAIGN',
                    stop_requested=False,
                    reason='Held for one-company campaign selection.',
                )
                state['campaign_manifest_digest'] = campaign_manifest_digest(state)
                for key in bound_fields:
                    state.pop(key, None)
                db.execute('INSERT INTO tasks VALUES (?,?)',
                           (state['id'], json.dumps(state)))
                ids.append(state['id'])
                items.append({'objective': spec['objective'], 'integration': spec['integration']})
            db.execute('INSERT INTO batches VALUES (?,?)',
                       ('legacy-original-batch', json.dumps(ids)))
        return ids, items

    @staticmethod
    def registry(store):
        with store.connect() as db:
            return db.execute(
                'SELECT campaign_id,company_id,current_task_id,identity_digest,import_digest,retry_of '
                'FROM campaign_company_registry ORDER BY campaign_id,company_id'
            ).fetchall()

    def test_canonical_identity_replaces_contradictory_audit_text_everywhere_model_facing(self):
        integration = self.integration(1)
        contradictory = (
            'Integrate WRONG-9999 Adversarial Alpha from https://wrong.example/jobs. '
            'Run tests/test_company_1.py and inspect src/company_1.py.')
        state = self.store.create(**self.spec(1, objective=contradictory, integration=integration))
        identity = canonical_identity(integration)

        self.assertEqual(state['objective'], contradictory)
        self.assertEqual(state['integration_identity'], identity)
        self.assertEqual(state['integration_identity_digest'], identity_digest(integration))
        self.assertEqual(state['worker_assignment'], worker_assignment(integration))
        self.assertNotIn('Adversarial Alpha', state['worker_assignment'])
        self.assertNotIn('wrong.example', state['worker_assignment'])
        validate_bound_identity(state)

        coordinator = coordinator_module.Coordinator(
            self.base, model=lambda *_: None, budget=lambda *_: None)
        packet = coordinator.messages(state, 'bounded protocol')
        packet_text = json.dumps(packet)
        payload = json.loads(packet[1]['content'])
        self.assertEqual(payload['objective'], state['worker_assignment'])
        self.assertEqual(payload['integration_identity'], identity)
        self.assertEqual(payload['integration_identity_digest'], identity_digest(integration))
        self.assertNotIn('Adversarial Alpha', packet_text)
        self.assertNotIn('wrong.example', packet_text)

        status = coordinator.describe(state)
        self.assertIn(identity['company_id'], status)
        self.assertIn(identity['company'], status)
        self.assertIn(identity['configured_url'], status)
        self.assertIn(identity_digest(integration), status)

    def test_requirements_tests_and_edit_targets_share_exact_canonical_identity(self):
        integration = self.integration(2)
        requirements = self.requirements(2, integration)
        canonical = canonical_requirements(integration, requirements)
        identity = canonical_identity(integration)
        state = bind_identity({
            'objective': 'Historical free-form import',
            'tests': identity['tests'],
            'integration': integration,
            'evidence_requirements': canonical,
        })

        self.assertEqual(state['tests'], identity['tests'])
        self.assertEqual(canonical['required_files'], identity['tests'] + identity['source_targets'])
        self.assertEqual(canonical['source_targets'][0]['url'], identity['configured_url'])
        self.assertEqual(canonical['source_targets'][0]['identity_terms'], [identity['company']])
        self.assertEqual(set(identity), {
            'company_id', 'company', 'configured_url', 'tests', 'source_targets'})
        validate_bound_identity(state)

    def test_exact_replay_reuses_ids_and_changed_duplicate_aborts_entire_batch(self):
        original_ids, reused = self.campaign('batch-original', [self.spec(1)])
        self.assertFalse(reused)
        replay_ids, reused = self.campaign('batch-original', [self.spec(1)])
        self.assertTrue(reused)
        self.assertEqual(replay_ids, original_ids)
        before_tasks = self.store.all()
        before_registry = self.registry(self.store)

        changed = self.integration(1, company='Changed Company Name')
        with self.assertRaisesRegex(ValueError, 'already imported|duplicates'):
            self.campaign('batch-changed', [self.spec(2), self.spec(1, integration=changed)])
        self.assertEqual(self.store.all(), before_tasks)
        self.assertEqual(self.registry(self.store), before_registry)

        other_ids, reused = self.campaign('batch-other-campaign', [self.spec(1)], 'other-campaign')
        self.assertFalse(reused)
        self.assertNotEqual(other_ids, original_ids)
        self.assertEqual(len(self.registry(self.store)), 2)

    def test_concurrent_exact_import_creates_one_task_and_registry_assignment(self):
        stores = [Store(self.base), Store(self.base)]
        barrier = threading.Barrier(2)

        def submit(store):
            barrier.wait()
            return store.enqueue_batch(
                'concurrent-batch', [self.spec(3)], held=True,
                campaign_id=DEFAULT_CAMPAIGN_ID)

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(submit, stores))
        self.assertEqual(results[0][0], results[1][0])
        self.assertEqual(sorted(result[1] for result in results), [False, True])
        self.assertEqual(len(self.store.all()), 1)
        self.assertEqual(len(self.registry(self.store)), 1)

    def test_concurrent_conflicting_imports_commit_only_one_complete_assignment(self):
        stores = [Store(self.base), Store(self.base)]
        barrier = threading.Barrier(2)
        specs = [
            self.spec(13),
            self.spec(13, integration=self.integration(13, company='Conflicting Company 13')),
        ]

        def submit(index):
            barrier.wait()
            try:
                return stores[index].enqueue_batch(
                    f'conflicting-batch-{index}', [specs[index]], held=True,
                    campaign_id=DEFAULT_CAMPAIGN_ID)[0][0]
            except ValueError:
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(submit, (0, 1)))
        committed = [task for task in results if task]
        self.assertEqual(len(committed), 1)
        self.assertEqual([state['id'] for state in self.store.all()], committed)
        self.assertEqual(len(self.registry(self.store)), 1)
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM batches').fetchone()[0], 1)

    def test_public_update_and_activation_reject_every_identity_mutation(self):
        task = self.campaign('mutation-base', [self.spec(4)])[0][0]
        original = self.store.get(task)
        for field, value in (
            ('objective', 'Changed audit objective'),
            ('tests', ['tests/test_changed.py']),
            ('integration', self.integration(4, company='Changed')),
            ('worker_assignment', 'Changed worker assignment'),
            ('integration_identity_digest', '0' * 64),
            ('campaign_company_id', 'COMP-9999'),
        ):
            with self.subTest(public_field=field):
                with self.assertRaisesRegex(ValueError, 'Immutable assignment identity'):
                    self.store.update(task, **{field: value})
                self.assertEqual(self.store.get(task), original)

        wrong_requirements = json.loads(json.dumps(original['evidence_requirements']))
        wrong_requirements['source_targets'][0]['allowed_urls'].append(
            'https://wrong.example/alias')
        with self.assertRaisesRegex(ValueError, 'identity|Evidence requirements'):
            self.store.update(task, evidence_requirements=wrong_requirements)
        self.assertEqual(self.store.get(task), original)

        mutations = {
            'objective': lambda state: state.update(objective='Raw changed objective'),
            'integration_name': lambda state: state['integration'].update(company='Raw changed company'),
            'tests': lambda state: state.update(tests=['tests/test_changed.py']),
            'source_target': lambda state: state['integration']['source_targets'].__setitem__(0, 'src/changed.py'),
            'assignment': lambda state: state.update(worker_assignment='Raw changed assignment'),
            'identity_digest': lambda state: state.update(integration_identity_digest='f' * 64),
            'requirements_url': lambda state: state['evidence_requirements']['source_targets'][0].update(
                url='https://wrong.example/jobs'),
            'requirements_allowed_url': lambda state: state['evidence_requirements']['source_targets'][0][
                'allowed_urls'].append('https://wrong.example/alias'),
            'requirements_file_scope': lambda state: state['evidence_requirements'][
                'required_files'].pop(),
        }
        for label, mutate in mutations.items():
            with self.subTest(raw_mutation=label):
                base = Path(self.tmp.name) / ('raw-' + label)
                store = Store(base)
                store.configure_queue(False)
                ids, _ = store.enqueue_batch(
                    'raw-batch', [self.spec(5)], held=True,
                    campaign_id=DEFAULT_CAMPAIGN_ID)
                current = store.get(ids[0])
                mutate(current)
                with store.connect() as db:
                    db.execute('UPDATE tasks SET state=? WHERE id=?',
                               (json.dumps(current), current['id']))
                snapshot = store.activation_snapshot(current['id'])
                before = store.get(current['id'])
                with self.assertRaisesRegex(ValueError, 'identity|assignment|Evidence'):
                    store.commit_activation(
                        current['id'], {'reason': 'resume'},
                        expected_state_digest=snapshot['state_digest'],
                        expected_control_generation=snapshot['control_generation'],
                        pilot=True)
                self.assertEqual(store.get(current['id']), before)
                self.assertIsNone(store.pilot_task())

    def test_activation_fields_cannot_replace_bound_evidence_requirements(self):
        task = self.campaign('activation-requirements', [self.spec(8)])[0][0]
        self.store.configure_queue(False)
        snapshot = self.store.activation_snapshot(task)
        wrong = json.loads(json.dumps(snapshot['state']['evidence_requirements']))
        wrong['source_targets'][0]['allowed_urls'].append('https://wrong.example/alias')
        before = self.database_rows(self.store)

        with self.assertRaisesRegex(ValueError, 'identity|requirements'):
            self.store.commit_activation(
                task, {'evidence_requirements': wrong, 'reason': 'resume'},
                expected_state_digest=snapshot['state_digest'],
                expected_control_generation=snapshot['control_generation'],
                pilot=True)
        self.assertEqual(self.database_rows(self.store), before)
        self.assertIsNone(self.store.pilot_task())

    def test_retry_preserves_predecessor_and_receipts_and_advances_current_pointer(self):
        task = self.campaign('retry-base', [self.spec(6)])[0][0]
        self.store.configure_queue(False)
        self.store.update(task, calls=2, sessions=1, tokens=321, status='PAUSED_ERROR')
        receipt = self.store.intent(task, 'inspect', 'code_read', {'path': 'src/company_6.py'})
        self.store.finish(receipt, {'ok': True, 'result': {'text': 'historical evidence'}})
        predecessor = self.store.get(task)
        predecessor_receipts = self.store.receipts(task)

        retry = self.store.retry_campaign_task(task)
        self.assertNotEqual(retry['id'], task)
        self.assertEqual(retry['retry_of'], task)
        self.assertEqual(retry['integration_identity_digest'], predecessor['integration_identity_digest'])
        self.assertEqual((retry['calls'], retry['sessions'], retry['tokens']), (0, 0, 0))
        self.assertEqual(self.store.get(task), predecessor)
        self.assertEqual(self.store.receipts(task), predecessor_receipts)
        row = self.registry(self.store)[0]
        self.assertEqual(row[2], retry['id'])
        self.assertEqual(row[5], task)

        with self.assertRaisesRegex(ValueError, 'superseded'):
            self.store.retry_campaign_task(task)
        with self.assertRaisesRegex(ValueError, 'superseded'):
            self.campaign('retry-base', [self.spec(6)])

        second = self.store.retry_campaign_task(retry['id'])
        self.assertEqual(second['retry_of'], retry['id'])
        self.assertEqual(self.registry(self.store)[0][2], second['id'])
        self.assertEqual(self.store.get(task), predecessor)

        self.store.configure_campaign(True, DEFAULT_CAMPAIGN_ID)
        selected = self.store.activate_next_campaign(DEFAULT_CAMPAIGN_ID)
        self.assertEqual(selected['id'], second['id'])
        self.assertEqual(self.store.get(task)['status'], predecessor['status'])
        self.assertEqual(self.store.get(retry['id'])['status'], 'PAUSED')

    def test_concurrent_retries_advance_pointer_once(self):
        task = self.campaign('retry-race', [self.spec(7)])[0][0]
        self.store.configure_queue(False)
        self.store.update(task, status='PAUSED_ERROR')
        stores = [Store(self.base), Store(self.base)]
        barrier = threading.Barrier(2)

        def retry(store):
            barrier.wait()
            try:
                return store.retry_campaign_task(task)['id']
            except ValueError:
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(retry, stores))
        created = [task_id for task_id in results if task_id]
        self.assertEqual(len(created), 1)
        self.assertEqual(len(self.store.all()), 2)
        self.assertEqual(self.registry(self.store)[0][2], created[0])
        self.assertEqual(self.registry(self.store)[0][5], task)

    def test_identity_backfill_dry_run_apply_and_rerun_are_complete_and_idempotent(self):
        ids, items = self.legacy_campaign_members([11, 12])
        before = self.database_rows(self.store)

        dry = backfill_campaign_identity(self.store, items)
        self.assertEqual(dry['matched'], ids)
        self.assertEqual(dry['changed'], ids)
        self.assertEqual(dry['registered'], ids)
        self.assertEqual(self.database_rows(self.store), before)

        applied = backfill_campaign_identity(self.store, items, apply=True)
        self.assertEqual(applied, dry)
        self.assertEqual(len(self.registry(self.store)), 2)
        for task in ids:
            state = self.store.get(task)
            validate_bound_identity(state)
            row = next(row for row in self.registry(self.store) if row[2] == task)
            self.assertEqual(row[3], state['integration_identity_digest'])
            self.assertEqual(row[4], 'legacy-original-batch')

        applied_rows = self.database_rows(self.store)
        rerun = backfill_campaign_identity(self.store, items, apply=True)
        self.assertEqual(rerun['matched'], ids)
        self.assertEqual(rerun['changed'], [])
        self.assertEqual(rerun['registered'], [])
        self.assertEqual(self.database_rows(self.store), applied_rows)
        self.assertFalse(self.store.queue_enabled())
        self.assertFalse(self.store.campaign_enabled())
        self.assertIsNone(self.store.pilot_task())

    def test_partial_or_conflicting_identity_backfill_aborts_all_writes(self):
        ids, items = self.legacy_campaign_members([21, 22])
        before = self.database_rows(self.store)
        with self.assertRaisesRegex(ValueError, 'disagrees with campaign member'):
            backfill_campaign_identity(self.store, items[:1], apply=True)
        self.assertEqual(self.database_rows(self.store), before)
        self.assertEqual(self.registry(self.store), [])

        conflicting = json.loads(json.dumps(items))
        conflicting[1]['integration']['company'] = 'Conflicting Reviewed Name'
        with self.assertRaisesRegex(ValueError, 'disagrees with campaign member'):
            backfill_campaign_identity(self.store, conflicting, apply=True)
        self.assertEqual(self.database_rows(self.store), before)
        self.assertEqual(self.registry(self.store), [])

        with self.store.connect() as db:
            db.execute(
                'INSERT INTO campaign_company_registry VALUES (?,?,?,?,?,?)',
                (DEFAULT_CAMPAIGN_ID, 'COMP-0021', 'WRAP-ffffffffff',
                 '0' * 64, 'legacy-original-batch', None))
        conflict_before = self.database_rows(self.store)
        with self.assertRaisesRegex(ValueError, 'registry conflicts'):
            backfill_campaign_identity(self.store, items, apply=True)
        self.assertEqual(self.database_rows(self.store), conflict_before)

    @staticmethod
    def database_rows(store):
        with store.connect() as db:
            return {
                'tasks': db.execute('SELECT id,state FROM tasks ORDER BY rowid').fetchall(),
                'settings': db.execute('SELECT key,value FROM settings ORDER BY key').fetchall(),
                'batches': db.execute('SELECT digest,task_ids FROM batches ORDER BY digest').fetchall(),
                'registry': db.execute(
                    'SELECT campaign_id,company_id,current_task_id,identity_digest,import_digest,retry_of '
                    'FROM campaign_company_registry ORDER BY campaign_id,company_id').fetchall(),
            }


if __name__ == '__main__':
    unittest.main()
