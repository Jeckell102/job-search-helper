"""Independent event-driven callback tests; no network or production writes."""
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'wrapper-workflow-20261118/host'))
import coding_tools as code
import test_campaign_completion_qa as fixtures

class IndependentCallbackTests(unittest.TestCase):
    def exercise(self, interrupt):
        case = fixtures.CampaignCompletionQATests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        root = Path(case.tmp.name)/'repo'
        (root/'docs').mkdir(parents=True)
        (root/'docs/wrapper-development-test-protocol.md').write_text('# Required wrapper development and test protocol\nFollow tests.\n')
        started, release = threading.Event(), threading.Event()
        errors, calls = [], []
        with patch.object(code, 'ROOT', root):
            case.campaign(2)
            state = case.select()
            coordinator = case.coordinator()
            def model(*_):
                calls.append(1)
                started.set()
                if not release.wait(5):
                    raise RuntimeError('test release timeout')
                return {'message': {'content': 'Bounded response'}, 'usage': {'prompt_eval_count': 100, 'eval_count': 50}}
            coordinator.model = model
            def work():
                try:
                    coordinator.session(state)
                except BaseException as exc:
                    errors.append(repr(exc))
            worker = threading.Thread(target=work)
            worker.start()
            try:
                self.assertTrue(started.wait(5), errors)
                self.assertEqual(case.store.inference_receipts(state['id'])[0]['status'], 'DISPATCHING')
                if interrupt == 'pause':
                    coordinator.command({'action': 'campaign-stop'})
                else:
                    case.store.recover()
                for alias in ('campaign-status', 'autopilot-status', 'queue', 'list', 'health', 'status'):
                    coordinator.command({'action': alias, 'id': state['id']})
                    self.assertFalse(case.store.campaign_control()['enabled'])
                    self.assertIsNone(case.store.activate_next_campaign(fixtures.CAMPAIGN))
            finally:
                release.set()
                worker.join(5)
            self.assertFalse(worker.is_alive())
            self.assertFalse(errors, errors)
            self.assertEqual(len(calls), 1)
            expected = 'RESPONSE_DROPPED' if interrupt == 'pause' else 'UNCERTAIN'
            self.assertEqual(case.store.inference_receipts(state['id'])[0]['status'], expected)
            self.assertFalse(case.store.campaign_control()['enabled'])
            self.assertIsNone(case.store.activate_next_campaign(fixtures.CAMPAIGN))
            self.assertIsNone(case.store.start_inference_session(state['id']))
            self.assertEqual(case.store.get(state['id'])['calls'], 1)
    def test_public_pause_during_callback_status_cannot_revive_it(self):
        self.exercise('pause')
    def test_recovery_during_callback_status_cannot_replay_it(self):
        self.exercise('recover')

if __name__ == '__main__':
    unittest.main()
