import tempfile
import unittest
from pathlib import Path
import sqlite3

from inference_control_store import InferenceControlStore


REQUEST = 'a' * 32
FINGERPRINT = 'b' * 64
OWNER = 'c' * 64
RESPONSE = 'd' * 64


class InferenceControlStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.clock = [1000.0]
        self.store = InferenceControlStore(Path(self.temp.name) / 'control.sqlite3', now=lambda: self.clock[0])

    def test_duplicate_request_cannot_start_twice_and_conflict_is_rejected(self):
        self.assertTrue(self.store.begin(REQUEST, FINGERPRINT, OWNER)['start'])
        self.assertFalse(self.store.begin(REQUEST, FINGERPRINT, OWNER)['start'])
        with self.assertRaisesRegex(ValueError, 'conflicts'):
            self.store.begin(REQUEST, 'e' * 64, OWNER)

    def test_completed_control_retains_only_digest_usage_and_no_prompt(self):
        self.store.begin(REQUEST, FINGERPRINT, OWNER)
        self.clock[0] += 1
        finished = self.store.finish(REQUEST, response_digest=RESPONSE,
                                     usage={'prompt_eval_count': 12, 'eval_count': 8, 'done_reason': 'stop'})
        self.assertEqual(finished['status'], 'COMPLETED')
        self.assertEqual(finished['response_digest'], RESPONSE)
        self.assertNotIn('prompt', finished)
        self.assertFalse(self.store.begin(REQUEST, FINGERPRINT, OWNER)['start'])

    def test_second_distinct_request_cannot_start_while_one_is_running(self):
        self.assertTrue(self.store.begin(REQUEST, FINGERPRINT, OWNER)['start'])
        self.assertEqual(self.store.begin('e' * 32, 'f' * 64, OWNER)['status'], 'BUSY')

    def test_cancel_requires_ownership_then_reaches_terminal_acknowledgement(self):
        self.store.begin(REQUEST, FINGERPRINT, OWNER)
        with self.assertRaisesRegex(ValueError, 'does not own'):
            self.store.cancel(REQUEST, FINGERPRINT, 'e' * 64)
        pending = self.store.cancel(REQUEST, FINGERPRINT, OWNER)
        self.assertEqual(pending['status'], 'RUNNING')
        self.assertTrue(pending['cancel_requested'])
        finished = self.store.finish(REQUEST, cancelled=True)
        self.assertEqual(finished['status'], 'CANCELLED')
        self.assertEqual(self.store.cancel(REQUEST, FINGERPRINT, OWNER)['status'], 'CANCELLED')

    def test_unknown_or_malformed_request_fails_closed(self):
        self.assertIsNone(self.store.cancel('f' * 32, FINGERPRINT, OWNER))
        with self.assertRaisesRegex(ValueError, 'Invalid'):
            self.store.begin('short', FINGERPRINT, OWNER)

    def test_usage_rejects_arbitrary_content_before_it_reaches_the_database(self):
        self.store.begin(REQUEST, FINGERPRINT, OWNER)
        for usage in ({'done_reason': 'prompt text with spaces', 'prompt_eval_count': 1, 'eval_count': 2},
                      {'done_reason': 'stop', 'prompt_eval_count': True, 'eval_count': 2},
                      {'done_reason': 'stop', 'prompt_eval_count': 1, 'eval_count': {'private': 'source'}}):
            with self.subTest(usage=usage):
                with self.assertRaisesRegex(ValueError, 'usage'):
                    self.store.finish(REQUEST, usage=usage)
        with sqlite3.connect(self.store.path) as db:
            raw = db.execute('SELECT usage FROM wrapper_inference_control WHERE request_id=?', (REQUEST,)).fetchone()[0]
        self.assertIsNone(raw)


if __name__ == '__main__':
    unittest.main()
