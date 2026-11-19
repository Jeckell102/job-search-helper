import tempfile
import unittest
from pathlib import Path

from inference_control_store import InferenceControlStore


class OrphanRecoveryTests(unittest.TestCase):
    def test_reopened_running_receipt_is_orphaned_and_blocks_until_safe_reconciliation(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'control.sqlite3'
            first = InferenceControlStore(path)
            request_id, fingerprint, owner = 'a' * 32, 'b' * 64, 'c' * 64
            self.assertTrue(first.begin(request_id, fingerprint, owner)['start'])
            self.assertTrue(first.lane_blocked())
            restarted = InferenceControlStore(path)
            self.assertEqual(restarted.status(request_id)['status'], 'UNCERTAIN')
            restarted.cancel(request_id, fingerprint, owner)
            self.assertEqual(restarted.reconcile_orphan(request_id, fingerprint, owner, execution_inactive=False)['status'], 'UNCERTAIN')
            self.assertEqual(restarted.begin('d' * 32, 'e' * 64, owner)['status'], 'BUSY')
            with self.assertRaisesRegex(ValueError, 'does not own'):
                restarted.reconcile_orphan(request_id, fingerprint, 'f' * 64, execution_inactive=True)
            self.assertEqual(restarted.reconcile_orphan(request_id, fingerprint, owner, execution_inactive=True)['status'], 'CANCELLED')
            self.assertFalse(restarted.lane_blocked())
            self.assertTrue(restarted.begin('d' * 32, 'e' * 64, owner)['start'])

    def test_done_reason_is_an_explicit_metadata_enum(self):
        with tempfile.TemporaryDirectory() as temp:
            store = InferenceControlStore(Path(temp) / 'control.sqlite3')
            store.begin('a' * 32, 'b' * 64, 'c' * 64)
            with self.assertRaisesRegex(ValueError, 'usage'):
                store.finish('a' * 32, usage={'prompt_eval_count': 1, 'eval_count': 1, 'done_reason': 'private_marker'})


if __name__ == '__main__':
    unittest.main()
