import importlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class WrapperControlRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        (root / 'config').mkdir()
        (root / 'config' / 'wrapper-host.json').write_text(json.dumps({'token': 'test-wrapper-token'}))
        engine = types.SimpleNamespace(Engine=object, BackendError=type('BackendError', (Exception,), {}),
                                       InputError=type('InputError', (Exception,), {}),
                                       Cancelled=type('Cancelled', (Exception,), {}))
        modules = {
            'storage': types.SimpleNamespace(ROOT=root, VERSION='test', settings=lambda: {}),
            'cluster': types.SimpleNamespace(), 'jobs': types.SimpleNamespace(), 'benchlog': types.SimpleNamespace(),
            'engine': engine, 'routing': types.SimpleNamespace(route=lambda value: value),
            'assistant_tools': types.SimpleNamespace(SCHEMAS=[], request_scope=lambda value: value,
                                                     schemas_for=lambda value: []),
            'local_tools': types.SimpleNamespace(),
            'profile_policy': types.SimpleNamespace(PROFILES={}, VISIBLE_PROFILES=(), LEGACY_ALIASES={},
                                                    resolve_profile=lambda value: None,
                                                    resolve_output_limit=lambda *args, **kwargs: 1),
        }
        self.module_patch = patch.dict(sys.modules, modules)
        self.module_patch.start()
        self.addCleanup(self.module_patch.stop)
        sys.modules.pop('server', None)
        self.server_module = importlib.import_module('server')
        self.httpd = self.server_module.Server(('127.0.0.1', 0), self.server_module.Handler, object())
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.base = 'http://127.0.0.1:%s' % self.httpd.server_address[1]

    def stop_server(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)
        sys.modules.pop('server', None)

    def request(self, method, path, *, authorized=False, data=None, binding=None):
        body = None if data is None else json.dumps(data).encode()
        headers = {'Authorization': 'Bearer test-wrapper-token'} if authorized else {}
        if binding:
            headers.update({'X-Wrapper-Request-Fingerprint': binding['request_fingerprint'],
                            'X-Wrapper-Owner-Generation': binding['owner_generation']})
        if body is not None:
            headers['Content-Type'] = 'application/json'
        request = Request(self.base + path, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=2) as response:
                return response.status, json.loads(response.read())
        except HTTPError as error:
            return error.code, json.loads(error.read())

    def test_status_and_cancellation_routes_require_wrapper_authentication(self):
        request_id = 'a' * 32
        fingerprint = 'b' * 64
        owner = 'c' * 64
        self.httpd.wrapper_control.begin(request_id, fingerprint, owner)
        status, _ = self.request('GET', '/api/wrapper-control/' + request_id)
        self.assertEqual(status, 403)
        status, _ = self.request('DELETE', '/api/wrapper-control/' + request_id,
                                 data={'request_fingerprint': fingerprint, 'owner_generation': owner})
        self.assertEqual(status, 403)
        self.assertEqual(self.httpd.wrapper_control.status(request_id)['status'], 'RUNNING')

    def test_shared_wrapper_token_and_request_id_cannot_read_control_binding_or_cancel(self):
        request_id = 'a' * 32
        fingerprint = 'b' * 64
        owner = 'c' * 64
        self.httpd.wrapper_control.begin(request_id, fingerprint, owner)
        status, payload = self.request('GET', '/api/wrapper-control/' + request_id, authorized=True)
        self.assertEqual(status, 400)
        self.assertNotIn('fingerprint', payload)
        self.assertNotIn('owner_generation', payload)
        status, _ = self.request('DELETE', '/api/wrapper-control/' + request_id, authorized=True, data={})
        self.assertEqual(status, 400)
        status, _ = self.request('DELETE', '/api/wrapper-control/' + request_id, authorized=True,
                                 data={'request_fingerprint': fingerprint, 'owner_generation': 'd' * 64})
        self.assertEqual(status, 400)
        self.assertEqual(self.httpd.wrapper_control.status(request_id)['status'], 'RUNNING')

    def test_owned_status_is_sanitized_and_cancellation_obeys_ownership(self):
        request_id = 'a' * 32
        fingerprint = 'b' * 64
        owner = 'c' * 64
        binding = {'request_fingerprint': fingerprint, 'owner_generation': owner}
        self.httpd.wrapper_control.begin(request_id, fingerprint, owner)
        status, payload = self.request('GET', '/api/wrapper-control/' + request_id, authorized=True, binding=binding)
        self.assertEqual(status, 200)
        self.assertEqual(payload['status'], 'RUNNING')
        self.assertNotIn('fingerprint', payload)
        self.assertNotIn('owner_generation', payload)
        status, payload = self.request('DELETE', '/api/wrapper-control/' + request_id, authorized=True,
                                       data={'request_fingerprint': fingerprint, 'owner_generation': owner})
        self.assertEqual(status, 200)
        self.assertTrue(payload['cancel_requested'])
        self.assertNotIn('fingerprint', payload)
        self.assertNotIn('owner_generation', payload)


if __name__ == '__main__':
    unittest.main()
