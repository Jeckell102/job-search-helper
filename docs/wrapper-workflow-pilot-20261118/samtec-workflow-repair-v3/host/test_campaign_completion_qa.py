"""Independent Group-6 QA for durable, truthful campaign completion."""
import json
import tempfile
import threading
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import coordinator as coordinator_module
from coordinator_campaign import campaign_text
from coordinator_store import (
    CAMPAIGN_FINISHED,
    EXCLUDED,
    HELD_FOR_CAMPAIGN,
    SELECTED,
    USER_PAUSED,
    Store,
)


CAMPAIGN = 'qa-campaign-completion'


class CampaignCompletionQATests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name) / 'tasks'
        self.store = Store(self.base)

    @staticmethod
    def spec(number):
        integration = {
            'company_id': f'COMP-{number:04}',
            'company': f'Canonical Company {number}',
            'configured_url': f'https://canonical.example/company-{number}',
            'tests': [f'tests/test_company_{number}.py'],
            'source_targets': [f'src/company_{number}.py'],
            'work_order': f'W{number:03}',
            'ats': 'canonical-ats',
        }
        return {
            'objective': f'Implement reviewed Company {number}',
            'tests': list(integration['tests']),
            'mode': 'develop',
            'max_sessions': 10,
            'authorization_version': 1,
            'workflow_version': 2,
            'integration': integration,
            'evidence_requirements': {
                'version': 1,
                'required_files': integration['tests'] + integration['source_targets'],
                'source_targets': [{
                    'url': integration['configured_url'],
                    'allowed_urls': [integration['configured_url']],
                    'identity_terms': [integration['company']],
                }],
                'read_hints': {},
            },
        }

    def campaign(self, count=2):
        specs = [self.spec(number) for number in range(1, count + 1)]
        return self.store.enqueue_batch(
            'campaign-completion-' + str(count), specs, held=True,
            campaign_id=CAMPAIGN)[0]

    def select(self):
        self.store.configure_campaign(True, CAMPAIGN)
        queued = self.store.activate_next_campaign(CAMPAIGN)
        self.assertIsNotNone(queued)
        running = self.store.claim_campaign(CAMPAIGN)
        self.assertIsNotNone(running)
        return running

    def seal(self):
        self.store.configure_campaign(True, CAMPAIGN)
        self.store.configure_campaign(False, CAMPAIGN)

    def finish_selected(self, status, **fields):
        state = next(s for s in self.store.all()
                     if s.get('campaign_disposition') == SELECTED)
        return self.store.update(
            state['id'], status=status, stop_requested=False,
            reason=fields.pop('reason', status), **fields)

    def coordinator(self):
        return coordinator_module.Coordinator(
            self.base, model=lambda *_: None,
            budget=lambda *_: types.SimpleNamespace(
                prompt_tokens=100, available_generation_tokens=1000))

    @staticmethod
    def member(report, company_id):
        return next(item for item in report['members']
                    if item['company_id'] == company_id)

    def test_registry_current_retry_is_the_only_denominator_member(self):
        original = self.campaign(1)[0]
        self.select()
        self.finish_selected('PAUSED_BUDGET', calls=48)
        first = self.store.reconcile_campaign(CAMPAIGN)
        self.assertEqual(first['state'], 'DRAINED_WITH_EXCEPTIONS')
        self.assertEqual(first['total'], 1)

        self.store = Store(self.base)
        retry = self.store.retry_campaign_task(original)
        reopened = self.store.reconcile_campaign(CAMPAIGN)
        self.assertEqual(reopened['revision'], 2)
        self.assertEqual(reopened['total'], 1)
        self.assertEqual([m['task_id'] for m in reopened['members']], [retry['id']])
        self.assertNotEqual(retry['id'], original)
        self.assertEqual(self.store.get(original)['campaign_disposition'], CAMPAIGN_FINISHED)
        self.assertEqual(len(self.store.campaign_history(CAMPAIGN)), 1)

    def test_user_pause_and_exclude_are_explicit_exceptions(self):
        first, second = self.campaign(2)
        self.seal()
        self.store.pause_task(first, 'Operator chose to defer this company.')
        self.store.exclude_campaign_task(second)
        report = self.store.reconcile_campaign(CAMPAIGN)
        self.assertEqual(report['state'], 'DRAINED_WITH_EXCEPTIONS')
        self.assertEqual(report['total'], 2)
        self.assertEqual(report['counts'][USER_PAUSED], 1)
        self.assertEqual(report['counts'][EXCLUDED], 1)
        self.assertEqual({m['task_id'] for m in report['exceptions']}, {first, second})
        self.assertIn('explicitly resume', self.member(report, 'COMP-0001')['next_action'].lower())
        self.assertIn('include', self.member(report, 'COMP-0002')['next_action'].lower())

    def test_budget_error_retires_selection_and_advances_exactly_one(self):
        first, second = self.campaign(2)
        selected = self.select()
        self.assertEqual(selected['id'], first)
        self.finish_selected('PAUSED_ERROR', errors=1)
        next_task = self.store.activate_next_campaign(CAMPAIGN)
        self.assertIsNotNone(next_task)
        self.assertEqual(next_task['id'], second)
        old = self.store.get(first)
        self.assertEqual(old['campaign_disposition'], CAMPAIGN_FINISHED)
        self.assertEqual(old['campaign_outcome'], 'PAUSED_ERROR')
        self.assertEqual(sum(s.get('campaign_disposition') == SELECTED
                             for s in self.store.all()), 1)

    def test_offline_ready_is_not_live_validated_or_installed(self):
        self.campaign(1)
        self.select()
        self.finish_selected('AWAITING_LIVE_VALIDATION')
        report = self.store.reconcile_campaign(CAMPAIGN)
        self.assertEqual(report['state'], 'DRAINED')
        self.assertEqual(report['counts']['OFFLINE_READY_AWAITING_LIVE_VALIDATION'], 1)
        text = campaign_text(report)
        self.assertIn('not certification of live results, installation, or complete job downloads', text)
        self.assertNotIn('"LIVE_VALIDATED": 1', text)
        self.assertNotIn('"INSTALLED": 1', text)

    def test_live_validated_requires_matching_identity_url_schema_and_receipt(self):
        self.campaign(1)
        selected = self.select()
        state = self.store.get(selected['id'])
        proof = {
            'schema_version': 1,
            'company_id': state['integration_identity']['company_id'],
            'configured_url': state['integration_identity']['configured_url'],
            'integration_identity_digest': state['integration_identity_digest'],
            'status': 'complete', 'dispatch': 'normal', 'job_count': 1,
            'full_description_coverage': True, 'stable_reread': True,
            'postings': [{'id': 'job-1', 'url': 'https://jobs.example/1',
                          'description': 'Complete role description'}],
        }
        receipt = self.store.intent(selected['id'], 'verify',
                                    'operator_live_validation', {})
        self.store.finish(receipt, {'ok': True, 'live_validation': proof})
        proof['receipt_id'] = receipt
        self.store.update(selected['id'], status='LIVE_VALIDATED',
                          live_validation=proof, phase='verify')
        later = self.store.intent(selected['id'], 'verify', 'status_export', {})
        self.store.finish(later, {'ok': True})
        report = self.store.reconcile_campaign(CAMPAIGN)
        self.assertEqual(report['state'], 'DRAINED')
        self.assertEqual(report['counts']['LIVE_VALIDATED_AWAITING_INSTALLATION'], 1)
        self.assertEqual(self.member(report, 'COMP-0001')['receipt_id'], receipt)

        # A changed URL is no longer bound to that receipt and fails closed.
        self.store.retry_campaign_task(selected['id'])
        retry = self.select()
        bad = dict(proof, configured_url='https://wrong.example/jobs')
        self.store.update(retry['id'], status='LIVE_VALIDATED',
                          live_validation=bad, phase='verify')
        rejected = self.store.reconcile_campaign(CAMPAIGN)
        self.assertEqual(rejected['state'], 'PAUSED_RECONCILIATION')
        self.assertRegex(' '.join(rejected['errors']), 'identity-bound operator evidence')

    def test_terminal_snapshots_are_durable_and_reopen_uses_new_revision(self):
        task = self.campaign(1)[0]
        self.seal()
        self.store.exclude_campaign_task(task)
        terminal = self.store.reconcile_campaign(CAMPAIGN)
        self.assertEqual(terminal['revision'], 1)
        self.assertEqual(len(self.store.campaign_history(CAMPAIGN)), 1)
        self.assertEqual(self.store.reconcile_campaign(CAMPAIGN)['revision'], 1)

        included = self.store.include_campaign_task(task)
        self.assertEqual(included['campaign_disposition'], HELD_FOR_CAMPAIGN)
        reopened = self.store.reconcile_campaign(CAMPAIGN)
        self.assertEqual(reopened['revision'], 2)
        self.assertEqual(reopened['state'], 'PAUSED')
        self.store.exclude_campaign_task(task)
        terminal2 = self.store.reconcile_campaign(CAMPAIGN)
        self.assertEqual(terminal2['revision'], 2)
        history = self.store.campaign_history(CAMPAIGN)
        self.assertEqual([r['revision'] for r in history], [1, 2])
        self.assertEqual(history[0]['state'], 'DRAINED_WITH_EXCEPTIONS')

    def test_global_pause_retains_selected_and_never_reports_drained(self):
        self.campaign(1)
        selected = self.select()
        self.store.configure_queue(False)
        self.store.update(selected['id'], status='PAUSED', stop_requested=False,
                          reason='Global campaign stopped; selection retained.')
        report = self.store.reconcile_campaign(CAMPAIGN)
        self.assertEqual(report['state'], 'PAUSED')
        self.assertEqual(report['counts'][SELECTED], 1)
        self.assertEqual(self.store.get(selected['id'])['campaign_disposition'], SELECTED)
        self.assertEqual(self.store.campaign_history(CAMPAIGN), [])

    def test_unresolved_inference_pauses_reconciliation_without_advance(self):
        first, second = self.campaign(2)
        selected = self.select()
        session = self.store.start_inference_session(selected['id'])
        receipt = self.store.reserve_inference(
            selected['id'], phase=selected['phase'], prompt_digest='a' * 64,
            tools_digest='b' * 64, prompt_tokens=100, output_tokens=300,
            expected_control_generation=self.store.control_generation(),
            session_id=session['inference_session_id'])
        self.assertIsNotNone(receipt)
        self.store.update(selected['id'], status='PAUSED_ERROR')
        report = self.store.reconcile_campaign(CAMPAIGN)
        self.assertEqual(report['state'], 'PAUSED_RECONCILIATION')
        self.assertFalse(self.store.campaign_enabled())
        self.assertEqual(self.store.get(first)['campaign_disposition'], SELECTED)
        self.assertEqual(self.store.get(second)['campaign_disposition'], HELD_FOR_CAMPAIGN)
        self.assertIsNone(self.store.activate_next_campaign(CAMPAIGN, require_enabled=False))

    def test_concurrent_reconcile_is_idempotent_and_selects_no_company(self):
        task = self.campaign(1)[0]
        self.seal()
        self.store.exclude_campaign_task(task)
        stores = [Store(self.base), Store(self.base)]
        barrier = threading.Barrier(2)

        def reconcile(index):
            barrier.wait()
            return stores[index].reconcile_campaign(CAMPAIGN)

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(reconcile, (0, 1)))
        self.assertEqual({r['revision'] for r in results}, {1})
        self.assertEqual({r['reconciliation_digest'] for r in results},
                         {results[0]['reconciliation_digest']})
        self.assertEqual(len(self.store.campaign_history(CAMPAIGN)), 1)
        self.assertFalse(any(s.get('campaign_disposition') == SELECTED
                             for s in self.store.all()))

    def test_missing_registry_and_unknown_status_fail_closed(self):
        first, second = self.campaign(2)
        self.seal()
        reviewed = self.store.reconcile_campaign(CAMPAIGN)
        with self.store.connect() as db:
            db.execute('DELETE FROM campaign_company_registry WHERE company_id=?',
                       ('COMP-0001',))
            state = json.loads(db.execute(
                'SELECT state FROM tasks WHERE id=?', (second,)).fetchone()[0])
            state['status'] = 'MYSTERY_SUCCESS'
            db.execute('UPDATE tasks SET state=? WHERE id=?',
                       (json.dumps(state), second))
        report = self.store.reconcile_campaign(CAMPAIGN)
        repeated = self.store.reconcile_campaign(CAMPAIGN)
        self.assertEqual(report['state'], 'PAUSED_RECONCILIATION')
        self.assertEqual(repeated['state'], 'PAUSED_RECONCILIATION')
        self.assertEqual(report['membership_digest'], reviewed['membership_digest'])
        self.assertEqual(repeated['membership_digest'], reviewed['membership_digest'])
        self.assertNotEqual(repeated['observed_membership_digest'],
                            repeated['membership_digest'])
        self.assertFalse(self.store.queue_enabled())
        errors = ' '.join(report['errors'])
        self.assertIn('absent from current registry', errors)
        self.assertIn('Unknown lifecycle status', errors)

    def test_status_json_and_text_give_truthful_next_actions(self):
        first, second = self.campaign(2)
        self.seal()
        self.store.pause_task(first, 'Operator deferred.')
        self.store.exclude_campaign_task(second)
        self.store.configure_campaign(False, CAMPAIGN)
        result = self.coordinator().command({'action': 'campaign-status'})
        report = result['campaign_result']
        self.assertEqual(report['total'], 2)
        self.assertEqual(len(report['members']), 2)
        self.assertIn('explicitly resume', result['text'].lower())
        self.assertIn('explicitly include', result['text'].lower())
        self.assertIn('not certification', result['text'].lower())
        for member in report['members']:
            self.assertTrue(member['next_action'])

    def test_public_preseal_multibatch_status_then_start_seals_and_rejects_late_addition(self):
        first = self.store.enqueue_batch(
            'reviewed-batch-a', [self.spec(1)], held=True,
            campaign_id=CAMPAIGN)[0][0]
        self.store.configure_campaign(False, CAMPAIGN)
        before = self.coordinator().command({'action': 'campaign-status'})['campaign_result']
        self.assertEqual(before['total'], 1)
        self.assertFalse(before['membership_sealed'])
        self.assertEqual(before['state'], 'PAUSED')

        second = self.store.enqueue_batch(
            'reviewed-batch-b', [self.spec(2)], held=True,
            campaign_id=CAMPAIGN)[0][0]
        expanded = self.coordinator().command({'action': 'campaign-status'})['campaign_result']
        self.assertEqual(expanded['total'], 2)
        self.assertFalse(expanded['membership_sealed'])
        self.assertEqual({m['task_id'] for m in expanded['members']}, {first, second})

        started = self.coordinator().command({
            'action': 'campaign-start', 'campaign_id': CAMPAIGN,
        })['campaign_result']
        self.assertTrue(started['membership_sealed'])
        self.assertEqual(started['total'], 2)
        with self.assertRaisesRegex(ValueError, 'sealed'):
            self.store.enqueue_batch(
                'late-batch-c', [self.spec(3)], held=True,
                campaign_id=CAMPAIGN)
        restarted = Store(self.base)
        sealed = restarted.reconcile_campaign(CAMPAIGN)
        self.assertTrue(sealed['membership_sealed'])
        self.assertEqual(sealed['total'], 2)
        self.assertEqual(len(restarted.all()), 2)

    def test_terminal_campaign_status_is_observational_after_generic_queue_resume(self):
        task = self.campaign(1)[0]
        self.seal()
        self.store.exclude_campaign_task(task)
        drained = self.store.reconcile_campaign(CAMPAIGN)
        self.assertEqual(drained['state'], 'DRAINED_WITH_EXCEPTIONS')
        self.store.configure_queue(True)
        self.assertTrue(self.store.queue_enabled())
        repeated = self.store.reconcile_campaign(CAMPAIGN)
        self.assertEqual(repeated['state'], 'DRAINED_WITH_EXCEPTIONS')
        self.assertTrue(self.store.queue_enabled())
        self.assertFalse(self.store.campaign_enabled())

    def test_stale_worker_results_cannot_cross_pause_gate_or_stop_restart_aba(self):
        self.campaign(1)
        selected = self.select()
        before = self.store.result_snapshot(selected['id'])
        original = self.store.get(selected['id'])
        self.store.pause_task(selected['id'], 'Operator pause wins.')
        stale = self.store.publish_result(
            selected['id'], before, status='PAUSED_ERROR', phase='verify',
            reason='Late error', checkpoint={'summary': 'bounded evidence'})
        self.assertEqual(stale['campaign_disposition'], USER_PAUSED)
        self.assertEqual(stale['status'], 'PAUSING')
        self.assertEqual(stale['reason'], 'Operator pause wins.')
        self.assertEqual(stale['phase'], original['phase'])
        self.assertEqual(stale['checkpoint'], {'summary': 'bounded evidence'})

        # Restore an active selection as a fixture, then stop and restart the
        # same control mode.  The old generation must not publish after ABA.
        with self.store.connect() as db:
            state = json.loads(db.execute(
                'SELECT state FROM tasks WHERE id=?', (selected['id'],)).fetchone()[0])
            state.update(status='RUNNING', stop_requested=False,
                         campaign_disposition=SELECTED, reason='active')
            db.execute('UPDATE tasks SET state=? WHERE id=?',
                       (json.dumps(state), selected['id']))
        active = self.store.result_snapshot(selected['id'])
        self.store.configure_queue(False)
        self.store.configure_campaign(True, CAMPAIGN)
        after = self.store.publish_result(
            selected['id'], active, status='AWAITING_LIVE_VALIDATION',
            phase='verify', reason='stale success')
        self.assertEqual(after['status'], 'PAUSED')
        self.assertNotEqual(after['phase'], 'verify')

    def test_checkpoint_baseline_verify_and_error_results_all_lose_to_pause_or_gate(self):
        cases = {
            'checkpoint': {'checkpoint': {'summary': 'bounded evidence'},
                           'status': 'QUEUED', 'reason': 'late checkpoint'},
            'baseline': {'baseline_passed': True, 'phase': 'inspect',
                         'status': 'QUEUED', 'reason': 'late baseline'},
            'verify': {'phase': 'verify', 'status': 'AWAITING_LIVE_VALIDATION',
                       'reason': 'late verify'},
            'error': {'status': 'PAUSED_ERROR', 'errors': 1,
                      'reason': 'late error'},
        }
        for index, (kind, fields) in enumerate(cases.items(), 50):
            with self.subTest(kind=kind):
                state = self.store.create(**self.spec(index))
                state = self.store.update(
                    state['id'], status='RUNNING', phase='baseline',
                    stop_requested=False, reason='active')
                snapshot = self.store.result_snapshot(state['id'])
                paused = self.store.pause_task(state['id'], 'Operator pause wins.')
                final = self.store.publish_result(state['id'], snapshot, **fields)
                self.assertEqual(final['status'], paused['status'])
                self.assertEqual(final['phase'], 'baseline')
                self.assertEqual(final['reason'], 'Operator pause wins.')
                self.assertNotIn('baseline_passed', final)
                self.assertEqual(final['errors'], 0)
                if kind == 'checkpoint':
                    self.assertEqual(final['checkpoint'], fields['checkpoint'])
                else:
                    self.assertEqual(final['checkpoint'], {})

        gated = self.store.create(**self.spec(99))
        gated = self.store.update(gated['id'], status='RUNNING', phase='verify')
        snapshot = self.store.result_snapshot(gated['id'])
        self.store.update(gated['id'], status='AWAITING_LIVE_VALIDATION',
                          reason='Operator gate reached.')
        final = self.store.publish_result(
            gated['id'], snapshot, status='PAUSED_ERROR', phase='baseline',
            reason='late failure', checkpoint={'summary': 'late'})
        self.assertEqual(final['status'], 'AWAITING_LIVE_VALIDATION')
        self.assertEqual(final['phase'], 'verify')
        self.assertEqual(final['reason'], 'Operator gate reached.')
        self.assertEqual(final['checkpoint'], {})


if __name__ == '__main__':
    unittest.main()
