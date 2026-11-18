"""Observational commands preserve only a fully owned single inference."""
import json
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import coding_tools as code
import test_campaign_completion_qa as fixtures
CAMPAIGN = fixtures.CAMPAIGN


class InflightStatusTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.CampaignCompletionQATests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.store = self.fixture.store

    def reserve(self):
        self.fixture.campaign(2)
        state = self.fixture.select()
        state = self.store.start_inference_session(state['id'])
        receipt = self.store.reserve_inference(state['id'], phase=state['phase'],
            prompt_digest='prompt', tools_digest='tools', prompt_tokens=100,
            output_tokens=1000, expected_control_generation=self.store.control_generation(),
            session_id=state['inference_session_id'])
        return self.store.get(state['id']), receipt

    def test_all_observational_commands_allow_actual_callback_response(self):
        root = Path(self.fixture.tmp.name) / 'repo'
        (root / 'docs').mkdir(parents=True)
        (root / 'docs/wrapper-development-test-protocol.md').write_text('# Required wrapper development and test protocol\nFollow the tests.\n')
        started, release = threading.Event(), threading.Event()
        failures = []
        with patch.object(code, 'ROOT', root):
            self.fixture.campaign(2)
            state = self.fixture.select()
            coordinator = self.fixture.coordinator()
            def model(*_):
                started.set()
                if not release.wait(10):
                    raise RuntimeError('callback release timeout')
                return {'message': {'content': 'Bounded healthy response'},
                        'usage': {'prompt_eval_count': 100, 'eval_count': 50}}
            coordinator.model = model
            def session():
                try:
                    coordinator.session(state)
                except BaseException as exc:
                    failures.append(exc)
            thread = threading.Thread(target=session)
            thread.start()
            try:
                self.assertTrue(started.wait(5), failures)
                generation = self.store.control_generation()
                for action in ('campaign-status', 'autopilot-status', 'queue', 'list', 'health', 'status'):
                    coordinator.command({'action': action, 'id': state['id']})
                    self.assertEqual(self.store.control_generation(), generation, action)
                    self.assertTrue(self.store.campaign_control()['enabled'], action)
                    self.assertIsNone(self.store.activate_next_campaign(CAMPAIGN))
                    self.assertEqual(self.store.get(state['id'])['status'], 'RUNNING')
                    self.assertEqual(len(self.store.unresolved_inferences()), 1)
            finally:
                release.set()
                thread.join(5)
            self.assertFalse(thread.is_alive())
            self.assertFalse(failures, failures)
            self.assertEqual(self.store.inference_receipts(state['id'])[0]['status'], 'COMPLETED')
            self.assertEqual(self.store.get(state['id'])['status'], 'QUEUED')
            self.assertEqual(self.store.get(state['id'])['tokens'], 150)

    def test_healthy_reservation_is_observational_but_still_blocks_selection(self):
        state, receipt = self.reserve()
        generation = self.store.control_generation()
        report = self.store.reconcile_campaign(CAMPAIGN)
        self.assertEqual(report['state'], 'RUNNING')
        self.assertFalse(report['errors'])
        self.assertEqual(self.store.control_generation(), generation)
        self.assertIsNone(self.store.activate_next_campaign(CAMPAIGN))
        self.assertIsNone(self.store.start_inference_session(state['id']))
        self.assertEqual(self.store.unresolved_inferences()[0]['request_id'], receipt['request_id'])

    def test_mismatched_reservation_fields_fail_closed(self):
        state, original = self.reserve()
        fields = {'request_id': 'other', 'task': 'missing', 'status': 'COMPLETED',
            'finished': 1, 'session_id': 'other', 'phase': 'other',
            'campaign_id': 'other', 'campaign_run_id': 'other', 'company_id': 'other',
            'identity_digest': 'other', 'integration_identity_digest': 'other',
            'control_generation': -1, 'reserved_tokens': 2,
            'pre_counters': {'sessions': 1, 'calls': 100, 'tokens': 0}}
        for field, value in fields.items():
            with self.subTest(field=field):
                damaged = dict(original, **{field: value})
                with self.store.connect() as db:
                    db.execute('UPDATE inference_receipts SET data=?', (json.dumps(damaged),))
                    row = db.execute('SELECT request_id,task,status,data FROM inference_receipts').fetchone()
                    self.assertFalse(self.store._owned_inflight_dispatch(db, row, 1))
        with self.store.connect() as db:
            db.execute('UPDATE inference_receipts SET data=?', (json.dumps(damaged),))
        self.assertEqual(self.store.reconcile_campaign(CAMPAIGN)['state'], 'PAUSED_RECONCILIATION')
        self.assertFalse(self.store.campaign_control()['enabled'])

    def test_closed_session_or_orphan_or_multiple_dispatches_fail_closed(self):
        state, receipt = self.reserve()
        with self.store.connect() as db:
            row = db.execute('SELECT request_id,task,status,data FROM inference_receipts').fetchone()
            self.assertFalse(self.store._owned_inflight_dispatch(db, row, 2))
        self.store.update(state['id'], inference_session_open=False)
        self.assertEqual(self.store.reconcile_campaign(CAMPAIGN)['state'], 'PAUSED_RECONCILIATION')
        self.assertIsNone(self.store.activate_next_campaign(CAMPAIGN))

    def test_malformed_receipt_fails_closed_without_status_exception(self):
        self.reserve()
        with self.store.connect() as db:
            db.execute("UPDATE inference_receipts SET data='not-json'")
        report = self.store.reconcile_campaign(CAMPAIGN)
        self.assertEqual(report['state'], 'PAUSED_RECONCILIATION')
        self.assertFalse(self.store.campaign_control()['enabled'])

    def test_duplicate_pending_receipt_stops_controls_and_cannot_advance(self):
        state, receipt = self.reserve()
        with self.store.connect() as db:
            other = dict(receipt, request_id='duplicate')
            db.execute('INSERT INTO inference_receipts VALUES (?,?,?,?)',
                       ('duplicate', state['id'], 'DISPATCHING', json.dumps(other)))
        self.assertEqual(self.store.reconcile_campaign(CAMPAIGN)['state'], 'PAUSED_RECONCILIATION')
        self.assertFalse(self.store.campaign_control()['enabled'])
        self.assertIsNone(self.store.activate_next_campaign(CAMPAIGN))

    def test_orphaned_dispatch_stops_controls(self):
        state, receipt = self.reserve()
        self.store.update(state['id'], status='PAUSED_ERROR')
        self.assertEqual(self.store.reconcile_campaign(CAMPAIGN)['state'], 'PAUSED_RECONCILIATION')
        self.assertIsNone(self.store.activate_next_campaign(CAMPAIGN))

    def test_expired_reservation_stops_controls(self):
        state, receipt = self.reserve()
        self.store.update(state['id'], activated_at=1)
        self.assertEqual(self.store.reconcile_campaign(CAMPAIGN)['state'], 'PAUSED_RECONCILIATION')
        self.assertFalse(self.store.campaign_control()['enabled'])

    def test_restart_converts_dispatch_to_uncertain_and_never_replays(self):
        state, receipt = self.reserve()
        self.store.recover()
        self.assertEqual(self.store.inference_receipts(state['id'])[0]['status'], 'UNCERTAIN')
        self.assertEqual(self.store.reconcile_campaign(CAMPAIGN)['state'], 'PAUSED_RECONCILIATION')
        self.assertIsNone(self.store.activate_next_campaign(CAMPAIGN))
        self.assertIsNone(self.store.start_inference_session(state['id']))

    def test_explicit_pause_still_drops_callback_response(self):
        state, receipt = self.reserve()
        self.store.configure_campaign(False, CAMPAIGN)
        self.assertEqual(self.store.reconcile_campaign(CAMPAIGN)['state'], 'PAUSED_RECONCILIATION')
        result = self.store.finalize_inference(receipt['request_id'],
            {'message': {'content': 'late'}, 'usage': {'prompt_eval_count': 100, 'eval_count': 50}})
        self.assertFalse(result['tools_allowed'])
        self.assertEqual(result['receipt']['status'], 'RESPONSE_DROPPED')


if __name__ == '__main__':
    unittest.main()
