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

    def test_orphan_recovery_requires_two_distinct_post_restart_generations(self):
        request_id, fingerprint, owner = 'a' * 32, 'b' * 64, 'c' * 64
        binding = {'request_fingerprint': fingerprint, 'owner_generation': owner}
        g1 = {'service': 'ollama.service', 'pid': 101, 'start_monotonic': 201}
        g2 = {'service': 'ollama.service', 'pid': 102, 'start_monotonic': 202}
        g3 = {'service': 'ollama.service', 'pid': 103, 'start_monotonic': 203}
        self.httpd.wrapper_control.begin(request_id, fingerprint, owner, backend_generation=g1)
        control_path = self.httpd.wrapper_control.path
        self.httpd.wrapper_control = self.server_module.InferenceControlStore(control_path)
        generation = [g2]
        self.httpd.backend_generation = lambda: generation[0]
        path = '/api/wrapper-control/' + request_id + '/orphan-recovery'
        with patch.object(self.server_module.os.path, 'exists', return_value=False):
            status, _ = self.request('POST', path, authorized=True,
                                     binding={'request_fingerprint': fingerprint, 'owner_generation': 'd' * 64},
                                     data={'action': 'observe'})
            self.assertEqual(status, 400)
            status, _ = self.request('POST', path, authorized=True, binding=binding,
                                     data={'action': 'observe', 'backend_generation': g3})
            self.assertEqual(status, 400)
            status, payload = self.request('POST', path, authorized=True, binding=binding,
                                           data={'action': 'observe'})
            self.assertEqual((status, payload['status']), (200, 'UNCERTAIN'))
            status, payload = self.request('POST', path, authorized=True, binding=binding,
                                           data={'action': 'settle'})
            self.assertEqual((status, payload['status']), (200, 'UNCERTAIN'))
            generation[0] = g3
            status, payload = self.request('POST', path, authorized=True, binding=binding,
                                           data={'action': 'settle'})
        self.assertEqual((status, payload['status']), (200, 'FAILED'))
        self.assertNotIn('fingerprint', payload)
        self.assertNotIn('owner_generation', payload)

    def test_orphan_recovery_rejects_non_post_methods_without_state_change(self):
        request_id, fingerprint, owner = 'a' * 32, 'b' * 64, 'c' * 64
        binding = {'request_fingerprint': fingerprint, 'owner_generation': owner}
        g1 = {'service': 'ollama.service', 'pid': 101, 'start_monotonic': 201}
        self.httpd.wrapper_control.begin(request_id, fingerprint, owner, backend_generation=g1)
        control_path = self.httpd.wrapper_control.path
        self.httpd.wrapper_control = self.server_module.InferenceControlStore(control_path)
        self.httpd.backend_generation = lambda: {'service': 'ollama.service', 'pid': 102, 'start_monotonic': 202}
        path = '/api/wrapper-control/' + request_id + '/orphan-recovery'
        for method in ('GET', 'DELETE'):
            with self.subTest(method=method):
                status, _ = self.request(method, path, authorized=True, binding=binding,
                                         data={'action': 'observe'} if method == 'DELETE' else None)
                self.assertEqual(status, 405)
        self.assertIsNone(self.httpd.wrapper_control.status(request_id)['_recovery_generation'])


if __name__ == '__main__':
    unittest.main()
