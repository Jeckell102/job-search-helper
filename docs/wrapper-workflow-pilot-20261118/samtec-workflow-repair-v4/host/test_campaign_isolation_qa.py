"""Independent finding-1 QA: campaign isolation and fail-closed migration."""
import tempfile
import threading
import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import coordinator as coordinator_module
from coordinator_store import (
    CAMPAIGN_FINISHED,
    EXCLUDED,
    HELD_FOR_CAMPAIGN,
    SELECTED,
    USER_PAUSED,
    Store,
    campaign_manifest_digest,
)
from migrate_campaign_membership import migrate_campaign_membership


CAMPAIGN = 'integration-backlog-20261118'


class CampaignMigrationQATests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / 'tasks')
        self.store.set_queue_enabled(False)
        self.store.set_autopilot_enabled(False)
        self.store.set_pilot_task(None)

    @staticmethod
    def item(number=1):
        tests = [f'tests/test_company_{number}.py']
        integration = {
            'company_id': f'COMP-{number:04}',
            'company': f'Company {number}',
            'configured_url': f'https://example.com/company-{number}',
            'tests': tests,
            'source_targets': [f'src/company_{number}.py'],
        }
        return {
            'objective': f'Integrate Company {number} using {tests[0]}',
            'mode': 'develop',
            'integration': integration,
        }

    def legacy(self, number=1, **fields):
        item = self.item(number)
        state = self.store.create(
            item['objective'], item['integration']['tests'], 'develop',
            authorization_version=1, workflow_version=2,
            integration=item['integration'],
        )
        baseline = dict(
            isolated_workspace=True,
            status='PAUSED',
            phase='baseline',
            stop_requested=True,
            reason='Pause requested.',
        )
        baseline.update(fields)
        self.store.update(state['id'], **baseline)
        return state['id'], item

    def migrate(self, items, reviewed=(), **kwargs):
        return migrate_campaign_membership(
            self.store, CAMPAIGN, items,
            reviewed_hold_ids=reviewed, **kwargs,
        )

    def assert_controls_off(self):
        self.assertFalse(self.store.queue_enabled())
        self.assertFalse(self.store.autopilot_enabled())
        self.assertIsNone(self.store.pilot_task())

    def test_clean_reviewed_hold_dry_run_apply_and_rerun_are_idempotent(self):
        task, item = self.legacy()
        before = self.store.get(task)

        dry = self.migrate([item], [task])
        self.assertTrue(dry['clean'])
        self.assertEqual(dry['held'], [task])
        self.assertEqual(dry['changed'], [task])
        self.assertEqual(self.store.get(task), before)

        applied = self.migrate([item], [task], apply=True)
        state = self.store.get(task)
        self.assertEqual(applied['held'], [task])
        self.assertEqual(state['campaign_id'], CAMPAIGN)
        self.assertEqual(state['campaign_company_id'], 'COMP-0001')
        self.assertEqual(state['campaign_disposition'], 'HELD_FOR_CAMPAIGN')
        self.assertTrue(state['campaign_manifest_digest'])
        self.assertFalse(state['stop_requested'])
        self.assertEqual(state['reason'], 'Held for one-company campaign selection.')

        rerun = self.migrate([item], [task], apply=True)
        self.assertTrue(rerun['clean'])
        self.assertEqual(rerun['held'], [task])
        self.assertEqual(rerun['changed'], [])
        self.assertEqual(self.store.get(task), state)
        self.assert_controls_off()

    def test_nonreviewed_legacy_pause_is_preserved_as_user_paused(self):
        task, item = self.legacy()
        report = self.migrate([item], apply=True)
        state = self.store.get(task)
        self.assertTrue(report['clean'])
        self.assertEqual(report['user_paused'], [task])
        self.assertEqual(state['campaign_disposition'], 'USER_PAUSED')
        self.assertTrue(state['stop_requested'])
        self.assertEqual(state['reason'], 'Pause requested.')
        self.assert_controls_off()

    def test_reviewed_hold_with_history_or_changed_reason_aborts_all_apply(self):
        unsafe = (
            {'stop_requested': False},
            {'calls': 1},
            {'tokens': 1},
            {'sessions': 1},
            {'activated_at': 1.0},
            {'selected_at': 1.0},
            {'reason': 'Operator excluded this company.'},
        )
        for number, fields in enumerate(unsafe, 1):
            with self.subTest(fields=fields):
                task, item = self.legacy(number, **fields)
                report = self.migrate([item], [task])
                self.assertFalse(report['clean'])
                self.assertIn(task, report['conflicting'])
                with self.assertRaisesRegex(ValueError, 'Migration conflict'):
                    self.migrate([item], [task], apply=True)
                self.assertIsNone(self.store.get(task).get('campaign_id'))

        task, item = self.legacy(20)
        receipt = self.store.intent(task, 'baseline', 'code_read', {'path': 'src/company_20.py'})
        self.store.finish(receipt, {'ok': True, 'result': {'text': 'saved'}})
        report = self.migrate([item], [task])
        self.assertFalse(report['clean'])
        self.assertIn(task, report['conflicting'])

    def test_unknown_reviewed_id_duplicate_task_and_identity_conflict_fail_closed(self):
        task, item = self.legacy(1)
        report = self.migrate([item], [task, 'WRAP-ffffffffff'])
        self.assertFalse(report['clean'])
        self.assertIn('WRAP-ffffffffff', report['conflicting'])

        duplicate = self.store.create(
            item['objective'], item['integration']['tests'], 'develop',
            authorization_version=1, workflow_version=2,
            integration=item['integration'],
        )
        self.store.update(
            duplicate['id'], isolated_workspace=True, status='PAUSED',
            stop_requested=True, reason='Pause requested.',
        )
        report = self.migrate([item], [task, duplicate['id']])
        self.assertFalse(report['clean'])
        self.assertTrue(report['conflicting'])
        with self.assertRaisesRegex(ValueError, 'Migration conflict'):
            self.migrate([item], [task, duplicate['id']], apply=True)
        self.assertIsNone(self.store.get(task).get('campaign_id'))
        self.assertIsNone(self.store.get(duplicate['id']).get('campaign_id'))

        other_task, other_item = self.legacy(2)
        self.corrupt(other_task, integration=dict(other_item['integration'], company='Wrong Company'))
        report = self.migrate([other_item], [other_task])
        self.assertFalse(report['clean'])
        self.assertIn(other_task, report['conflicting'])

    def corrupt(self, task_id, **fields):
        # Simulate an old/corrupted database; public updates now reject mutation.
        state = self.store.get(task_id)
        state.update(fields)
        with self.store.connect() as db:
            db.execute('UPDATE tasks SET state=? WHERE id=?', (json.dumps(state), task_id))

    def test_partial_existing_membership_and_changed_campaign_are_conflicts(self):
        task, item = self.legacy()
        self.corrupt(task, campaign_id=CAMPAIGN, campaign_company_id='COMP-0001')
        report = self.migrate([item], [task])
        self.assertFalse(report['clean'])
        self.assertIn(task, report['conflicting'])

        self.corrupt(
            task, campaign_id='different-campaign',
            campaign_company_id='COMP-0001',
            campaign_disposition='HELD_FOR_CAMPAIGN',
        )
        report = self.migrate([item], [task])
        self.assertFalse(report['clean'])
        self.assertIn(task, report['conflicting'])

    def test_manifest_validation_and_off_control_preconditions_fail_closed(self):
        task, item = self.legacy()
        bad = dict(item, integration={'company_id': 'COMP-0001'})
        with self.assertRaisesRegex(ValueError, 'complete integration identity'):
            self.migrate([bad], [task])
        with self.assertRaisesRegex(ValueError, 'Duplicate company or objective'):
            self.migrate([item, item], [task])

        self.store.set_queue_enabled(True)
        with self.assertRaisesRegex(ValueError, 'queue and autopilot OFF'):
            self.migrate([item], [task])
        self.assertIsNone(self.store.get(task).get('campaign_id'))

    def test_expected_cohort_mismatch_fails_before_any_write(self):
        task, item = self.legacy()
        before = self.store.get(task)
        expected = {
            'count': 2,
            'sha256': '0' * 64,
            'original_batches': {'missing-batch': [task]},
        }
        with self.assertRaisesRegex(ValueError, 'cohort or original batch provenance changed'):
            self.migrate([item], [task], apply=True, expected_cohort=expected)
        self.assertEqual(self.store.get(task), before)


class CampaignStoreIsolationQATests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name) / 'tasks'
        self.store = Store(self.base)
        self.store.configure_campaign(False, CAMPAIGN)

    @staticmethod
    def spec(number, campaign=CAMPAIGN):
        tests = [f'tests/test_company_{number}.py']
        integration = {
            'company_id': f'COMP-{number:04}',
            'company': f'Company {number}',
            'configured_url': f'https://example.com/company-{number}',
            'tests': tests,
            'source_targets': [f'src/company_{number}.py'],
        }
        return {
            'objective': f'Integrate Company {number} for {campaign}',
            'tests': tests,
            'mode': 'develop',
            'max_sessions': 10,
            'authorization_version': 1,
            'evidence_requirements': {},
            'workflow_version': 2,
            'integration': integration,
        }

    def campaign(self, numbers, campaign=CAMPAIGN):
        specs = [self.spec(number, campaign) for number in numbers]
        digest = f'{campaign}-' + '-'.join(map(str, numbers))
        ids, reused = self.store.enqueue_batch(digest, specs, held=True, campaign_id=campaign)
        self.assertFalse(reused)
        return ids

    def test_held_metadata_and_selector_are_campaign_scoped(self):
        first, second = self.campaign([1, 2])
        other = self.campaign([3], 'another-campaign')[0]
        for task in (first, second, other):
            state = self.store.get(task)
            self.assertEqual(state['campaign_disposition'], HELD_FOR_CAMPAIGN)
            self.assertEqual(state['campaign_company_id'], state['integration']['company_id'])
            self.assertEqual(state['campaign_manifest_digest'], campaign_manifest_digest(state))
            self.assertFalse(state['stop_requested'])

        self.store.configure_campaign(True, CAMPAIGN)
        selected = self.store.activate_next_campaign(CAMPAIGN)
        self.assertEqual(selected['id'], first)
        self.assertEqual(self.store.get(first)['campaign_disposition'], SELECTED)
        self.assertEqual(self.store.get(second)['campaign_disposition'], HELD_FOR_CAMPAIGN)
        self.assertEqual(self.store.get(other)['campaign_disposition'], HELD_FOR_CAMPAIGN)
        self.assertIsNone(self.store.claim_queued(first))
        self.assertIsNone(self.store.claim_campaign('another-campaign'))
        self.assertEqual(self.store.claim_campaign(CAMPAIGN)['id'], first)

    def test_user_paused_and_excluded_members_are_skipped_and_pause_advances(self):
        excluded, user_paused, first, second = self.campaign([1, 2, 3, 4])
        self.store.exclude_campaign_task(excluded)
        self.store.pause_task(user_paused)
        self.store.configure_campaign(True, CAMPAIGN)

        self.assertEqual(self.store.activate_next_campaign()['id'], first)
        self.assertEqual(self.store.claim_campaign()['id'], first)
        paused = self.store.pause_task(first)
        self.assertEqual(paused['campaign_disposition'], USER_PAUSED)
        self.assertEqual(paused['status'], 'PAUSING')
        self.store.update(first, status='PAUSED')

        self.assertEqual(self.store.activate_next_campaign()['id'], second)
        self.assertEqual(self.store.get(excluded)['campaign_disposition'], EXCLUDED)
        self.assertEqual(self.store.get(user_paused)['campaign_disposition'], USER_PAUSED)
        selected = [s['id'] for s in self.store.all()
                    if s.get('campaign_disposition') == SELECTED]
        self.assertEqual(selected, [second])

    def test_campaign_stop_and_restart_retain_the_same_selected_company(self):
        first, second = self.campaign([1, 2])
        self.store.configure_campaign(True, CAMPAIGN)
        self.assertEqual(self.store.activate_next_campaign()['id'], first)
        self.assertEqual(self.store.claim_campaign()['id'], first)

        self.store.configure_campaign(False, CAMPAIGN)
        self.store.update(first, status='PAUSED', stop_requested=False,
                          reason='Campaign stopped at an action boundary; selection retained.')
        restarted = Store(self.base)
        restarted.recover()
        self.assertEqual(restarted.get(first)['campaign_disposition'], SELECTED)
        self.assertEqual(restarted.get(second)['campaign_disposition'], HELD_FOR_CAMPAIGN)
        self.assertIsNone(restarted.claim_campaign())

        restarted.configure_campaign(True, CAMPAIGN)
        resumed = restarted.activate_next_campaign()
        self.assertEqual(resumed['id'], first)
        self.assertEqual(restarted.get(second)['campaign_disposition'], HELD_FOR_CAMPAIGN)
        self.assertEqual(restarted.claim_campaign()['id'], first)

    def test_global_queue_pause_stops_campaign_and_retains_selected_at_boundary(self):
        first, second = self.campaign([1, 2])
        self.store.configure_campaign(True, CAMPAIGN)
        self.assertEqual(self.store.activate_next_campaign()['id'], first)
        self.assertEqual(self.store.claim_campaign()['id'], first)
        coordinator = coordinator_module.Coordinator(
            self.base, model=lambda *_: None, budget=lambda *_: None)

        result = coordinator.command({'action': 'queue-pause'})
        self.assertFalse(result['campaign']['enabled'])
        self.assertFalse(coordinator.store.queue_enabled())
        self.assertEqual(coordinator.store.get(first)['campaign_disposition'], SELECTED)
        self.assertTrue(coordinator.paused(first))
        self.assertEqual(coordinator.store.get(first)['status'], 'PAUSED')
        self.assertEqual(coordinator.store.get(first)['campaign_disposition'], SELECTED)
        self.assertEqual(coordinator.store.get(second)['campaign_disposition'], HELD_FOR_CAMPAIGN)

    def test_action_intent_requires_selected_member_of_active_campaign(self):
        held = self.campaign([1])[0]
        wrong_campaign = self.campaign([2], 'another-campaign')[0]
        self.store.configure_campaign(True, CAMPAIGN)

        self.store.update(held, status='RUNNING')
        self.assertIsNone(self.store.active_intent(
            held, 'baseline', 'code_read', {'path': 'src/company_1.py'}))
        self.store.update(held, status='PAUSED')

        self.store.update(wrong_campaign, status='RUNNING', campaign_disposition=SELECTED)
        self.assertIsNone(self.store.active_intent(
            wrong_campaign, 'baseline', 'code_read', {'path': 'src/company_2.py'}))
        self.assertEqual(self.store.receipts(held), [])
        self.assertEqual(self.store.receipts(wrong_campaign), [])

    def test_direct_step_cannot_run_nonselected_campaign_members(self):
        held, user_paused, excluded = self.campaign([1, 2, 3])
        self.store.pause_task(user_paused)
        self.store.exclude_campaign_task(excluded)
        self.store.configure_campaign(True, CAMPAIGN)
        coordinator = coordinator_module.Coordinator(
            self.base, model=lambda *_: None, budget=lambda *_: None)

        for task in (held, user_paused, excluded):
            with self.subTest(task=task):
                coordinator.store.update(task, status='RUNNING')
                coordinator.step(task)
                state = coordinator.store.get(task)
                self.assertEqual(state['status'], 'PAUSED')
                self.assertEqual(state['phase'], 'baseline')
                self.assertEqual(coordinator.store.receipts(task), [])

    def test_two_store_instances_select_and_claim_exactly_one_company(self):
        first, second = self.campaign([1, 2])
        self.store.configure_campaign(True, CAMPAIGN)
        stores = [Store(self.base), Store(self.base)]
        barrier = threading.Barrier(2)

        def activate(store):
            barrier.wait()
            result = store.activate_next_campaign(CAMPAIGN)
            return result['id'] if result else None

        with ThreadPoolExecutor(max_workers=2) as pool:
            activated = list(pool.map(activate, stores))
        self.assertEqual([task for task in activated if task], [first])
        self.assertEqual(sum(s.get('campaign_disposition') == SELECTED
                             for s in self.store.all()), 1)

        barrier = threading.Barrier(2)

        def claim(store):
            barrier.wait()
            result = store.claim_campaign(CAMPAIGN)
            return result['id'] if result else None

        with ThreadPoolExecutor(max_workers=2) as pool:
            claimed = list(pool.map(claim, stores))
        self.assertEqual([task for task in claimed if task], [first])
        self.assertEqual(self.store.get(first)['status'], 'RUNNING')
        self.assertEqual(self.store.get(second)['status'], 'PAUSED')

    def test_resume_requires_a_free_lane_and_excluded_requires_include(self):
        first, second = self.campaign([1, 2])
        self.store.pause_task(first)
        self.store.exclude_campaign_task(second)
        self.store.configure_campaign(True, CAMPAIGN)

        with self.assertRaisesRegex(ValueError, 'Include the excluded'):
            self.store.resume_campaign_task(second)
        resumed = self.store.resume_campaign_task(first)
        self.assertEqual(resumed['campaign_disposition'], SELECTED)
        included = self.store.include_campaign_task(second)
        self.assertEqual(included['campaign_disposition'], HELD_FOR_CAMPAIGN)
        with self.assertRaisesRegex(ValueError, 'Another task owns'):
            self.store.resume_campaign_task(second)

        self.store.pause_task(first)
        self.store.update(first, status='PAUSED')
        resumed = self.store.resume_campaign_task(second)
        self.assertEqual(resumed['campaign_disposition'], SELECTED)

    def test_terminal_selection_is_released_before_next_company_is_selected(self):
        first, second = self.campaign([1, 2])
        self.store.configure_campaign(True, CAMPAIGN)
        self.assertEqual(self.store.activate_next_campaign()['id'], first)
        self.store.update(first, status='AWAITING_LIVE_VALIDATION')

        self.assertEqual(self.store.activate_next_campaign()['id'], second)
        self.assertEqual(self.store.get(first)['campaign_disposition'], CAMPAIGN_FINISHED)
        self.assertEqual(self.store.get(second)['campaign_disposition'], SELECTED)
        self.assertEqual(sum(s.get('campaign_disposition') == SELECTED
                             for s in self.store.all()), 1)


if __name__ == '__main__':
    unittest.main()
