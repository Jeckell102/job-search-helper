"""Exact -12 scope over the accepted disposable exchange/quiet-window harness.

Real filesystem swaps and restoration are exercised. Services, administrator
observation and application status are substituted; no native action occurs.
"""
from copy import deepcopy
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

import native_window as n


PRIOR = Path('/tmp/jsh-s7-first-start-native-window-11/test_native_window.py')
assert sha256(PRIOR.read_bytes()).hexdigest() == '4fb9a413dc7ef7d0d53721acb83d72ed30afe23364dcb131bf379f12edc0bfae'
spec = importlib.util.spec_from_file_location('embraer_prior_window_fixture', PRIOR)
prior = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = prior
spec.loader.exec_module(prior)


class FixtureSourceOwner:
    def __init__(self):
        self.spec = json.loads(n.CANDIDATE_PACKAGE.read_bytes())
        self.pin = n.CANDIDATE_PACKAGE_SHA256
        self.release_id = n.CANDIDATE_RELEASE_ID
        self.manifest_pin = n.CANDIDATE_MANIFEST_SHA256

    def status(self):
        return {'phase': 'BEFORE', 'release_id': self.release_id,
                'manifest_sha256': self.manifest_pin, 'package_sha256': self.pin,
                'endpoints': {key: pair['before'] for key, pair in self.spec['package_files'].items()}}

    def rollback_prepared(self):
        raise AssertionError('This fixture never prepares source')


class EmbraerNativeWindow(prior.NativeComposition):
    def setUp(self):
        super().setUp()
        self.w.source_owner = FixtureSourceOwner()

    def test_first_start_approval_and_candidate_package_are_exact(self):
        self.w.release_id = n.CANDIDATE_RELEASE_ID
        self.w.manifest_sha256 = n.CANDIDATE_MANIFEST_SHA256
        self.w.approval_check = lambda: {
            'schema': 's6-embraer-source-maintenance-approval-v1',
            'release_id': self.w.release_id, 'manifest_sha256': self.w.manifest_sha256,
            'package_sha256': n.CANDIDATE_PACKAGE_SHA256, 'source_sha256': n.CANDIDATE_SOURCE_SHA256,
            'predecessor_release_id': n.FIRST_START_RELEASE_ID,
            'predecessor_journal_sha256': n.FIRST_START_JOURNAL_SHA256}
        n.NativeWindow._approval(self.w)
        self.w.approval_check = lambda: {}
        with self.assertRaisesRegex(ValueError, 'supervisor approval'):
            n.NativeWindow._approval(self.w)
        candidate = n.NativeWindow._candidate_package()
        self.assertEqual(len(candidate['groups']['app_and_launchers']), 10)
        self.assertEqual(len(candidate['groups']['wrapper_tools']), 3)
        candidate['package_files'].pop(next(iter(n.CANDIDATE_PATHS)))
        with patch.object(n, 'read_private', return_value=n.encode(candidate)):
            with self.assertRaisesRegex(ValueError, 'Thirteen-endpoint candidate'):
                n.NativeWindow._candidate_package()

    def test_saved_first_start_layer_is_the_actual_latest_parent(self):
        package = self.w._first_start_predecessor()
        expected, owners = {}, {}
        n.merge_endpoint_layer(expected, owners, self.w._ga_predecessor(), label='GA predecessor')
        n.merge_endpoint_layer(expected, owners, self.w._allen_predecessor(), label='Allen predecessor')
        n.merge_endpoint_layer(expected, owners, package, label='First-Start predecessor')
        runner = 'src/job_search_helper/runner.py'
        self.assertEqual(expected[runner], (package['package_files'][runner]['staged']['mode'],
                                           package['package_files'][runner]['staged']['sha256']))
        n.merge_endpoint_layer(expected, owners, self.w.source_owner.spec, label='Embraer successor')
        self.assertEqual(expected[runner], (self.w.source_owner.spec['package_files'][runner]['staged']['mode'],
                                           self.w.source_owner.spec['package_files'][runner]['staged']['sha256']))
        self.assertIn('src/job_search_helper/source_configuration_manifest.json', expected)

    def test_prior_11_exact_terminal_is_required(self):
        terminal = {'state': 'APPROVED_SOURCE_SETTLED', 'release_id': n.FIRST_START_RELEASE_ID,
                    'manifest_sha256': n.FIRST_START_MANIFEST_SHA256}
        values = {
            'native-window.json': {'phase': 'RESTORED', 'terminal': terminal,
                'binding': {'source_package_sha256': n.FIRST_START_PACKAGE_SHA256},
                'restoration_sha256': n.PREDECESSOR_11_TERMINAL},
            'operator-quiet-window.json': {'phase': 'RESTORED'},
            'exchange.json': {'phase': 'restored', 'terminal_proof_sha256': n.PREDECESSOR_11_TERMINAL},
        }
        pins = {'native-window.json': n.PREDECESSOR_11_NATIVE,
                'operator-quiet-window.json': n.PREDECESSOR_11_QUIET,
                'exchange.json': n.PREDECESSOR_11_EXCHANGE}
        def read(path, digest):
            self.assertEqual(digest, pins[Path(path).name])
            self.assertTrue(Path(path).is_relative_to(n.PREDECESSOR_11))
            return n.encode(values[Path(path).name])
        with patch.object(n, 'read_private', read):
            n.NativeWindow._require_predecessor_11_restored()
            values['native-window.json']['terminal']['release_id'] = n.ALLEN_RELEASE_ID
            with self.assertRaisesRegex(ValueError, 'Prior -11'):
                n.NativeWindow._require_predecessor_11_restored()

    def test_full_source_owner_vector_and_candidate_pin_are_required(self):
        status = n.NativeWindow._source_status(self.w, {'BEFORE'})
        self.assertEqual(set(status['endpoints']), n.CANDIDATE_PATHS)
        saved = self.w.source_owner.spec
        self.w.source_owner.spec = {**saved, 'staged_source_sha256': 'f' * 64}
        with self.assertRaisesRegex(ValueError, 'Source owner package differs'):
            n.NativeWindow._source_status(self.w, {'BEFORE'})
        self.w.source_owner.spec = saved
        self.w.source_owner.release_id = n.FIRST_START_RELEASE_ID
        with self.assertRaisesRegex(ValueError, 'transition status differs'):
            n.NativeWindow._source_status(self.w, {'BEFORE'})

    def test_wrapper_phase_and_only_three_exclusions_survive_restoration(self):
        tools = self.project / 'dev/wrapper-coder/tools'; tools.mkdir(parents=True)
        host, store, untouched = tools / 'host_server.py', tools / 'coordinator_store.py', tools / 'untouched.py'
        host.write_bytes(b'old host\n'); store.write_bytes(b'store\n'); untouched.write_bytes(b'keep\n')
        owner = [host.stat().st_uid, host.stat().st_gid]
        def metadata(path):
            return {'mode': path.stat().st_mode & 0o777, 'sha256': sha256(path.read_bytes()).hexdigest(),
                    'size': path.stat().st_size}
        before = metadata(host)
        host.write_bytes(b'new host\n'); after = metadata(host); host.write_bytes(b'old host\n')
        pair = {'before': before, 'staged': after, 'owner': owner}
        scope_calls = []
        def unscoped(path, excluded):
            scope_calls.append(set(excluded))
            return sha256(n.encode({p.name: metadata(p) for p in path.iterdir() if p.name not in excluded})).hexdigest()
        current = {'paths': {n.HOST: {'after_sha256': before['sha256'], 'mode': oct(before['mode'])},
                             n.STORE: {'after_sha256': metadata(store)['sha256'], 'mode': oct(metadata(store)['mode'])}}}
        self.w.c = SimpleNamespace(ref=prior.Files.ref, unscoped=unscoped)
        self.w.old = SimpleNamespace(wrapper_tools=tools)
        self.w.source_owner = SimpleNamespace(spec={'package_files': {n.HOST: pair}})
        self.w.wrapper_scope_sha256 = unscoped(tools, n.CHANGED_WRAPPER_TOOLS)
        current_pins = {key: value['after_sha256'] for key, value in current['paths'].items()}
        with patch.object(n, 'CURRENT_TOOLS', current_pins), patch.object(n, 'read_private', return_value=n.encode(current)):
            n.NativeWindow._wrapper_custody(self.w, {'phase': 'BEFORE', 'endpoints': {n.HOST: before}})
            host.write_bytes(b'new host\n')
            (tools / 'embraer_operator_pilot.py').write_bytes(b'new approved helper\n')
            n.NativeWindow._wrapper_custody(self.w, {'phase': 'STAGED', 'endpoints': {n.HOST: after}})
            with self.assertRaisesRegex(ValueError, 'before-image'):
                n.NativeWindow._wrapper_custody(self.w, {'phase': 'BEFORE', 'endpoints': {n.HOST: after}})
            untouched.write_bytes(b'changed\n')
            with self.assertRaisesRegex(ValueError, 'unscoped wrapper'):
                n.NativeWindow._wrapper_custody(self.w, {'phase': 'STAGED', 'endpoints': {n.HOST: after}})
        self.assertTrue(all(value == {'coordinator_workspace.py', 'embraer_operator_pilot.py', 'host_server.py'}
                            for value in scope_calls))

    def test_terminal_rereads_wrapper_custody_after_source_advance(self):
        self.w.source_owner = FixtureSourceOwner()
        status = self.w.source_owner.status()
        status['phase'] = 'STAGED'
        seen = []
        with patch.object(self.w, '_source_status', return_value=status), \
                patch.object(self.w, '_wrapper_custody', side_effect=lambda s: seen.append(deepcopy(s))):
            terminal = n.NativeWindow._terminal(self.w)
        self.assertEqual(seen, [status])
        self.assertEqual(terminal['release_id'], n.CANDIDATE_RELEASE_ID)
