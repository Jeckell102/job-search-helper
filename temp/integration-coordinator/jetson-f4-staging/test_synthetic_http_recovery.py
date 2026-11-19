import ast
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import run_synthetic_http_recovery as proof


G1 = {'service': 'ollama.service', 'pid': 101, 'start_monotonic': 201}
G2 = {'service': 'ollama.service', 'pid': 102, 'start_monotonic': 202}
G3 = {'service': 'ollama.service', 'pid': 103, 'start_monotonic': 203}


class Handle:
    error = RuntimeError('synthetic transport loss')
    result = None
    def join(self, timeout): return True


class SuccessfulHandle(Handle):
    error = None
    result = {'control': {'status': 'COMPLETED'}}


class Client:
    def __init__(self):
        self.calls = []
    def start_turn(self, payload):
        self.calls.append(('turn', payload))
        return Handle()
    def status(self, binding):
        self.calls.append(('status', dict(binding)))
        return {'request_id': binding['request_id'],
                'status': 'RUNNING' if sum(c[0] == 'status' for c in self.calls) == 1 else 'UNCERTAIN'}
    def recover(self, binding, action):
        self.calls.append(('recover', action, dict(binding)))
        return {'request_id': binding['request_id'], 'status': 'UNCERTAIN' if action == 'observe' else 'FAILED'}


class SyntheticHttpRecoveryTests(unittest.TestCase):
    def test_real_http_contract_precedes_owner_bound_three_generation_settlement(self):
        client = Client()
        generations = iter((G2, G3))
        checkpoints = []
        with patch.object(proof.os.path, 'exists', return_value=False):
            result = proof.run_proof(client, restart=lambda: next(generations),
                                     get_generation=lambda: G1, checkpoint=checkpoints.append)
        self.assertEqual(result['settled_status'], 'FAILED')
        self.assertEqual([call[0] for call in client.calls], ['turn', 'status', 'status', 'recover', 'recover'])
        payload = client.calls[0][1]
        self.assertEqual(set(payload), {'messages', 'tools', 'max_tokens', 'request_id',
                                        'request_fingerprint', 'owner_generation'})
        self.assertEqual(payload['request_fingerprint'], proof.digest({
            key: payload[key] for key in ('messages', 'tools', 'max_tokens')}))
        self.assertEqual([value['stage'] for value in checkpoints],
                         ['request_started', 'running_observed', 'backend_interrupted',
                          'settlement_authorized', 'complete'])
        self.assertNotIn('g1', result)

    def test_acceptance_script_cannot_seed_or_mutate_the_receipt_store_directly(self):
        source = Path(proof.__file__).read_text()
        tree = ast.parse(source)
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        self.assertNotIn('InferenceControlStore', names)
        self.assertTrue({'begin', 'uncertain', 'finish'}.isdisjoint(attributes))
        self.assertNotIn('sqlite3', source)

    def test_successful_request_is_rejected_as_no_transport_loss(self):
        client = Client()
        client.start_turn = lambda payload: SuccessfulHandle()
        with self.assertRaisesRegex(RuntimeError, 'unexpectedly returned successfully'):
            proof.run_proof(client, restart=lambda: G2, get_generation=lambda: G1)
        self.assertFalse(any(call[0] == 'recover' for call in client.calls))

    def test_same_generation_fails_before_recovery_can_release_hold(self):
        client = Client()
        with self.assertRaisesRegex(RuntimeError, 'distinct'):
            proof.run_proof(client, restart=lambda: G1, get_generation=lambda: G1)
        self.assertFalse(any(call[0] == 'recover' for call in client.calls))

    def test_runtime_endpoint_comes_from_private_local_settings(self):
        self.assertEqual(proof.local_service_url({'listen_host': '192.168.50.2', 'listen_port': 8787}),
                         'http://192.168.50.2:8787')
        for settings in ({'listen_host': '8.8.8.8', 'listen_port': 8787},
                         {'listen_host': '0.0.0.0', 'listen_port': 8787},
                         {'listen_host': 'host.example', 'listen_port': 8787},
                         {'listen_host': '127.0.0.1', 'listen_port': True}):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                proof.local_service_url(settings)
        previously_deployed = '.'.join(('192', '168', '1', '146'))
        self.assertNotIn(previously_deployed, Path(proof.__file__).read_text())

    def test_sanitized_checkpoint_is_atomic_and_excludes_request_identity(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'evidence.json'
            with patch.object(proof.os, 'fsync', wraps=os.fsync) as sync:
                proof.write_checkpoint({'test': 'synthetic-http-orphan-recovery',
                                        'stage': 'failed', 'failure_type': 'RuntimeError'}, path)
            self.assertGreaterEqual(sync.call_count, 2)
            value = json.loads(path.read_text())
            self.assertEqual(value['stage'], 'failed')
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(ValueError):
                proof.write_checkpoint({'stage': 'failed', 'request_id': 'secret'}, path)

    def test_checkpoint_failure_after_request_start_records_failure_and_never_recovers(self):
        import tempfile
        client = Client()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'evidence.json'
            calls = []
            def flaky_writer(value, selected):
                calls.append(dict(value))
                if len(calls) == 1:
                    raise OSError('injected checkpoint failure')
                proof.write_checkpoint(value, selected)
            with self.assertRaisesRegex(OSError, 'checkpoint failure'):
                proof.run_recorded_proof(client, path=path, writer=flaky_writer,
                                         restart=lambda: G2, get_generation=lambda: G1)
            saved = json.loads(path.read_text())
            self.assertEqual(saved, {'test': 'synthetic-http-orphan-recovery',
                                     'stage': 'failed', 'failed_after': 'request_started',
                                     'failure_type': 'OSError'})
            self.assertEqual([call[0] for call in client.calls], ['turn'])
            self.assertFalse(any(call[0] == 'recover' for call in client.calls))

    def test_settlement_checkpoint_failure_never_calls_settle_or_releases_lane(self):
        import tempfile
        client = Client()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'evidence.json'
            def guarded_writer(value, selected):
                if value.get('stage') == 'settlement_authorized':
                    raise OSError('injected pre-settlement persistence failure')
                proof.write_checkpoint(value, selected)
            generations = iter((G2, G3))
            with patch.object(proof.os.path, 'exists', return_value=False):
                with self.assertRaisesRegex(OSError, 'pre-settlement'):
                    proof.run_recorded_proof(client, path=path, writer=guarded_writer,
                        restart=lambda: next(generations), get_generation=lambda: G1)
            self.assertEqual([call[1] for call in client.calls if call[0] == 'recover'], ['observe'])
            saved = json.loads(path.read_text())
            self.assertEqual(saved['stage'], 'failed')
            self.assertEqual(saved['failed_after'], 'settlement_authorized')

    def test_post_settlement_evidence_failure_records_boundary_without_false_hold_claim(self):
        import tempfile
        client = Client()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'evidence.json'
            def final_writer(value, selected):
                if value.get('stage') == 'complete':
                    raise OSError('injected post-settlement persistence failure')
                proof.write_checkpoint(value, selected)
            generations = iter((G2, G3))
            with patch.object(proof.os.path, 'exists', return_value=False):
                with self.assertRaisesRegex(OSError, 'post-settlement'):
                    proof.run_recorded_proof(client, path=path, writer=final_writer,
                        restart=lambda: next(generations), get_generation=lambda: G1)
            self.assertEqual([call[1] for call in client.calls if call[0] == 'recover'],
                             ['observe', 'settle'])
            saved = json.loads(path.read_text())
            self.assertEqual(saved['stage'], 'failed')
            self.assertEqual(saved['failed_after'], 'complete')


if __name__ == '__main__':
    unittest.main()
