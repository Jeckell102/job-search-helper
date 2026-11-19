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
            first_generation = {'service': 'ollama.service', 'pid': 101, 'start_monotonic': 201}
            recovered_generation = {'service': 'ollama.service', 'pid': 102, 'start_monotonic': 202}
            restarted_generation = {'service': 'ollama.service', 'pid': 103, 'start_monotonic': 203}
            self.assertTrue(first.begin(request_id, fingerprint, owner,
                                        backend_generation=first_generation)['start'])
            self.assertTrue(first.lane_blocked())
            restarted = InferenceControlStore(path)
            self.assertEqual(restarted.status(request_id)['status'], 'UNCERTAIN')
            restarted.cancel(request_id, fingerprint, owner)
            # The first post-restart observation is not proof that the prior
            # backend process did not accept the request just before restart.
            self.assertEqual(restarted.observe_orphan(request_id, fingerprint, owner,
                                                       backend_generation=recovered_generation)['status'], 'UNCERTAIN')
            self.assertEqual(restarted.reconcile_orphan(request_id, fingerprint, owner,
                                                         backend_generation=recovered_generation,
                                                         execution_inactive=True)['status'], 'UNCERTAIN')
            self.assertEqual(restarted.begin('d' * 32, 'e' * 64, owner)['status'], 'BUSY')
            with self.assertRaisesRegex(ValueError, 'does not own'):
                restarted.reconcile_orphan(request_id, fingerprint, 'f' * 64,
                                            backend_generation=restarted_generation, execution_inactive=True)
            self.assertEqual(restarted.reconcile_orphan(request_id, fingerprint, owner,
                                                         backend_generation=restarted_generation,
                                                         execution_inactive=False)['status'], 'UNCERTAIN')
            self.assertEqual(restarted.reconcile_orphan(request_id, fingerprint, owner,
                                                         backend_generation=restarted_generation,
                                                         execution_inactive=True)['status'], 'CANCELLED')
            self.assertFalse(restarted.lane_blocked())
            self.assertTrue(restarted.begin('d' * 32, 'e' * 64, owner)['start'])

    def test_done_reason_is_an_explicit_metadata_enum(self):
        with tempfile.TemporaryDirectory() as temp:
            store = InferenceControlStore(Path(temp) / 'control.sqlite3')
            store.begin('a' * 32, 'b' * 64, 'c' * 64)
            with self.assertRaisesRegex(ValueError, 'usage'):
                store.finish('a' * 32, usage={'prompt_eval_count': 1, 'eval_count': 1, 'done_reason': 'private_marker'})

    def test_backend_generation_is_a_bounded_service_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            store = InferenceControlStore(Path(temp) / 'control.sqlite3')
            with self.assertRaisesRegex(ValueError, 'generation'):
                store.begin('a' * 32, 'b' * 64, 'c' * 64,
                            backend_generation={'service': 'other.service', 'pid': 1, 'start_monotonic': 2})


if __name__ == '__main__':
    unittest.main()
