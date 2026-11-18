"""Transport regression tests for complete, bounded operator status output."""
import contextlib
import io
import json
import unittest
from unittest.mock import patch
import wrapper_task

class ShortReads(io.BytesIO):
    def read(self, size=-1):
        return super().read(min(size, 17))

class StatusResponseTests(unittest.TestCase):
    def invoke(self, payload, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(wrapper_task.Path, 'read_text', return_value='test-token'), \
                patch.object(wrapper_task.urllib.request, 'build_opener') as opener, \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            opener.return_value.open.return_value = io.BytesIO(payload)
            code = wrapper_task.main(['status', 'WRAP-test', *args])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_large_status_json_preserves_tail_and_nested_receipts(self):
        result = {'ok': True, 'text': 'Paused', 'receipts': [
            {'id': i, 'evidence': 'x' * 1024} for i in range(150)], 'tail': 'complete'}
        payload = json.dumps(result).encode()
        self.assertGreater(len(payload), 100000)
        code, stdout, stderr = self.invoke(payload, '--json')
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout), result)
        self.assertEqual(stderr, '')

    def test_large_status_summary_reads_full_object(self):
        payload = json.dumps({'ok': True, 'receipts': ['x' * 150000], 'text': 'Still paused'}).encode()
        self.assertEqual(self.invoke(payload), (0, 'Still paused\n', ''))

    def test_short_reads_do_not_truncate(self):
        result = {'ok': True, 'text': 'x' * 120000}
        self.assertEqual(wrapper_task.read_response(ShortReads(json.dumps(result).encode())), result)

    def test_exact_limit_allowed_and_one_byte_over_rejected(self):
        body = json.dumps({'ok': True}).encode()
        with patch.object(wrapper_task, 'MAX_RESPONSE_BYTES', len(body)):
            self.assertEqual(wrapper_task.read_response(io.BytesIO(body)), {'ok': True})
            with self.assertRaisesRegex(ValueError, 'safety limit'):
                wrapper_task.read_response(io.BytesIO(body + b' '))

    def test_oversized_response_fails_without_partial_status(self):
        payload = b'{"ok":true,"text":"' + b'x' * wrapper_task.MAX_RESPONSE_BYTES
        code, stdout, stderr = self.invoke(payload, '--json')
        self.assertEqual(code, 1)
        self.assertEqual(stdout, '')
        self.assertIn('exceeds the 8 MiB safety limit', stderr)

    def test_malformed_or_wrong_shape_fails_without_payload_disclosure(self):
        for payload in (b'{"secret":"do-not-print"', b'\xff', b'[]', b'null', b'{"ok":"yes"}'):
            with self.subTest(payload=payload):
                code, stdout, stderr = self.invoke(payload)
                self.assertEqual(code, 1)
                self.assertEqual(stdout, '')
                self.assertIn('no status could be verified', stderr)
                self.assertNotIn('do-not-print', stderr)

    def test_valid_coordinator_error_retains_nonzero_status(self):
        self.assertEqual(self.invoke(b'{"ok":false,"error":"Task not found"}'),
                         (1, 'Task not found\n', ''))

if __name__ == '__main__':
    unittest.main()
