import io
import json
import unittest
import urllib.error
from unittest.mock import Mock, patch
import coordinator as c


class InferenceErrorTests(unittest.TestCase):
    def failure(self, message):
        return urllib.error.HTTPError('http://127.0.0.1:18790/api/wrapper-turn', 503, 'Unavailable', {},
            io.BytesIO(json.dumps({'error': {'message': message}}).encode()))

    def test_gateway_machine_error_is_visible_without_executing_tools(self):
        opener = Mock()
        opener.open.side_effect = self.failure('too_many_tool_calls')
        with patch.object(c.code.Path, 'read_text', return_value='fixture-token'), \
             patch.object(c.urllib.request, 'build_opener', return_value=opener):
            with self.assertRaisesRegex(RuntimeError, 'Jetson inference HTTP 503: too_many_tool_calls'):
                c.infer([], [], 2000)

    def test_arbitrary_backend_text_is_not_copied_to_task_reason(self):
        opener = Mock()
        opener.open.side_effect = self.failure('Sensitive source or prompt text.')
        with patch.object(c.code.Path, 'read_text', return_value='fixture-token'), \
             patch.object(c.urllib.request, 'build_opener', return_value=opener):
            with self.assertRaises(RuntimeError) as caught:
                c.infer([], [], 2000)
        self.assertEqual(str(caught.exception), 'Jetson inference HTTP 503')


if __name__ == '__main__':
    unittest.main()
