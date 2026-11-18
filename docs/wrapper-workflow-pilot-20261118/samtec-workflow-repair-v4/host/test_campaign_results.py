"""Implementation regressions for campaign accounting and delayed publication."""
import json
import unittest
from unittest.mock import patch
import test_coordinator_workflow as fixture
import test_coordinator_queue as queue_fixture
from coordinator_campaign import valid_live_evidence
from coordinator_store import Store


class CampaignResultsTests(unittest.TestCase):
    setUp = fixture.WorkflowTests.setUp
    batch = queue_fixture.QueueTests.batch

    def test_terminal_once_and_retry_preserves_one_company(self):
        store = self.co.store
        task = self.batch(1)['ids'][0]
        store.configure_campaign(True)
        store.activate_next_campaign()
        store.update(task, status='PAUSED_BUDGET', reason='Calls exhausted')
        first = store.reconcile_campaign()
        self.assertEqual(first['state'], 'DRAINED_WITH_EXCEPTIONS')
        self.assertEqual(Store(store.base).reconcile_campaign(), first)
        self.assertEqual(len(store.campaign_history(first['campaign_id'])), 1)
        retry = store.retry_campaign_task(task)
        second = store.reconcile_campaign()
        self.assertEqual(second['revision'], 2)
        self.assertEqual(second['total'], 1)
        self.assertEqual(second['members'][0]['task_id'], retry['id'])
        self.assertEqual(store.get(task)['reason'], 'Calls exhausted')

    def test_pausing_member_cannot_drain(self):
        store = self.co.store
        task = self.batch(1)['ids'][0]
        store.configure_campaign(True)
        store.activate_next_campaign()
        store.claim_campaign()
        store.pause_task(task)
        self.assertEqual(store.get(task)['status'], 'PAUSING')
        self.assertNotIn(store.reconcile_campaign()['state'], ('DRAINED','DRAINED_WITH_EXCEPTIONS'))
        self.assertEqual(store.campaign_history(store.active_campaign_id()), [])
        store.stop_at_boundary(task, 'Finished action')
        self.assertEqual(store.reconcile_campaign()['state'], 'DRAINED_WITH_EXCEPTIONS')

    def test_baseline_pause_result_preserves_phase_reason(self):
        store = self.co.store
        task = self.batch(1)['ids'][0]
        store.configure_campaign(True)
        store.activate_next_campaign()
        store.claim_campaign()
        def tests(state):
            store.pause_task(task, 'Operator hold')
            return True
        with patch.object(self.co, 'tests', side_effect=tests):
            self.co.step(task)
        after = store.get(task)
        self.assertEqual(after['phase'], 'baseline')
        self.assertEqual(after['status'], 'PAUSED')
        self.assertEqual(after['reason'], 'Operator hold')

    def test_control_aba_cannot_publish_old_result(self):
        store = self.co.store
        task = self.batch(1)['ids'][0]
        store.configure_campaign(True)
        store.activate_next_campaign()
        store.claim_campaign()
        snapshot = store.result_snapshot(task)
        store.configure_campaign(False)
        store.configure_campaign(True)
        state = store.publish_result(task, snapshot, status='QUEUED', phase='inspect', reason='late')
        self.assertEqual(state['phase'], 'baseline')
        self.assertNotEqual(state['reason'], 'late')

    def test_unversioned_receipt_requires_exact_identity_and_complete_evidence(self):
        state = self.co.store.get(self.batch(1)['ids'][0])
        identity = state['integration_identity']
        proof = dict(operator='Host operator', dispatch='fetch_inventory', company_id=identity['company_id'],
                     company=identity['company'], configured_url=identity['configured_url'], source_url='https://example.com/feed',
                     status='complete', job_count=1, posting_ids=['1'], description_lengths=[500],
                     unique_ids=True, unique_urls=True, stable_reread=True)
        state['live_validation'] = proof
        receipt = dict(name='operator_live_validation', arguments=dict(company_id=identity['company_id'], dispatch='fetch_inventory'),
                       result=dict(ok=True, result=json.loads(json.dumps(proof))))
        self.assertTrue(valid_live_evidence(state, [receipt]))
        proof['configured_url'] = 'https://wrong.example'
        self.assertFalse(valid_live_evidence(state, [receipt]))

    def test_changed_membership_cannot_rebaseline_itself_on_repeated_status(self):
        store = self.co.store
        first = self.batch(1)['ids'][0]
        store.configure_campaign(True)
        store.configure_campaign(False)
        initial = store.reconcile_campaign()
        # Simulate a reviewed import being added under an already pinned campaign ID.
        other = dict(store.get(first))
        with store.connect() as db:
            db.execute('UPDATE campaign_company_registry SET identity_digest=?', ('changed',))
        first_error = store.reconcile_campaign()
        second_error = store.reconcile_campaign()
        self.assertEqual(first_error['state'], 'PAUSED_RECONCILIATION')
        self.assertEqual(second_error['membership_digest'], initial['membership_digest'])
        self.assertIn('membership changed', ' '.join(second_error['errors']))

    def test_unsealed_status_allows_more_batches_and_sealed_import_rejects(self):
        store = self.co.store
        first = self.batch(1)['ids'][0]
        campaign = store.get(first)['campaign_id']
        store.configure_campaign(False)
        store.exclude_campaign_task(first)
        status = store.reconcile_campaign()
        self.assertFalse(status['membership_sealed'])
        self.assertEqual(status['state'], 'PAUSED')
        spec = {key: store.get(first)[key] for key in ('objective','tests','mode','max_sessions','authorization_version','evidence_requirements','workflow_version','integration')}
        spec['integration'] = dict(spec['integration'], company_id='COMP-9999')
        second = store.enqueue_batch('new-reviewed-batch', [spec], held=True, campaign_id=campaign)[0][0]
        store.configure_campaign(True)
        self.assertTrue(store.reconcile_campaign()['membership_sealed'])
        spec['integration']['company_id'] = 'COMP-9998'
        with self.assertRaisesRegex(ValueError, 'sealed'):
            store.enqueue_batch('unreviewed-addition', [spec], held=True, campaign_id=campaign)
        self.assertEqual(len(store.all()), 2)

    def test_old_terminal_status_preserves_explicit_generic_queue_resume(self):
        store = self.co.store
        task = self.batch(1)['ids'][0]
        store.configure_campaign(True)
        store.exclude_campaign_task(task)
        old = store.reconcile_campaign()
        self.assertEqual(old['state'], 'DRAINED_WITH_EXCEPTIONS')
        store.configure_queue(True)
        self.assertEqual(store.reconcile_campaign(), old)
        self.assertTrue(store.queue_enabled())
        self.assertFalse(store.campaign_enabled())
