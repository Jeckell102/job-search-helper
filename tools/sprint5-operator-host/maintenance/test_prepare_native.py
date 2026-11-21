"""Disposable preparation proof; native source/service/witness checks are substituted."""
from contextlib import contextmanager, redirect_stderr
from hashlib import sha256
from io import StringIO
import json
import os
from pathlib import Path
import stat
import subprocess
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch
from zipfile import ZipFile

import prepare_native as prep


class PrepareNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = prep.approved_payload()
        cls.real = prep.native_dependencies()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='jsh-prepare-proof.')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_explicit_native_flag_required_before_opening_any_input(self):
        with patch.object(prep, 'approved_payload') as payload, redirect_stderr(StringIO()):
            with self.assertRaises(SystemExit) as error:
                prep.main(['--current-pin', '/not-opened', '--current-pin-sha256', 'a' * 64])
        self.assertEqual(error.exception.code, 2)
        payload.assert_not_called()

    def test_exact_payload_is_frozen_before_native_dependencies(self):
        self.assertEqual(len(self.files), 29)  # 28 payload members plus approved catalog.
        self.assertEqual(prep.digest(self.files['manifest.json'][0]), prep.MANIFEST_SHA)
        self.assertEqual(prep.digest(self.files['OFFLINE_PAYLOAD_PROOF.json'][0]), prep.PAYLOAD_PROOF_SHA)

    def fixture(self):
        real = self.real
        project = self.root / 'project'
        project.mkdir()
        (project / 'src/job_search_helper').mkdir(parents=True)
        parked = project / 'src/.s4-maintenance-package'
        real.joint.gate.create_marker(parked)
        parent = self.root / 'maintenance'
        parent.mkdir(mode=0o700)
        old_root = parent / 'freeform-fixture'
        old_root.mkdir(mode=0o700)
        destination = parent / prep.FRESH_ID
        attempt = parent / (prep.FRESH_ID + '-attempt')
        launchers = {}
        for name in ('job-search-helper', 'job-search-scraper', 'release_admission_bootstrap.py'):
            raw = ('fixture current ' + name).encode()
            prep.private_write(project / name, raw)
            launchers[name] = prep.digest(raw)
        control = old_root / 'exchange-private'
        control.mkdir(mode=0o700)
        prep.private_write(control / 'exchange.lock', b'')
        routes = self.root / 'routes'
        routes.mkdir()
        canonical, sentinel = routes / 'alternate', routes / '.exchange-park-fixture'
        canonical.mkdir()
        sentinel.mkdir(mode=0o500)
        exchange_policy = {'schema': real.exchange.POLICY_SCHEMA, 'mode': 'host',
            'generation': 'b' * 32, 'mount_namespace': os.readlink('/proc/self/ns/mnt'),
            'control': str(control), 'control_pin': prep.physical_pin(control, real.exchange, directory=True),
            'lock_pin': prep.physical_pin(control / 'exchange.lock', real.exchange),
            'pairs': [{'parent': str(routes), 'canonical': canonical.name, 'parked': sentinel.name,
                'parent_pin': prep.physical_pin(routes, real.exchange, directory=True),
                'original_pin': prep.physical_pin(canonical, real.exchange, directory=True),
                'sentinel_pin': prep.physical_pin(sentinel, real.exchange, directory=True)}]}
        exchange_raw = real.exchange.encode(exchange_policy)
        prep.private_write(control / 'policy.json', exchange_raw)
        old_exchange = real.exchange.HostExchange(control / 'policy.json', prep.digest(exchange_raw), enable_host_writes=True)
        intent = old_exchange.prepare()
        # Saved restored observation is a fixture input, no actual restoration is claimed.
        journal = json.loads((control / 'exchange.json').read_bytes())
        journal.update(phase='restored', completed=1, terminal_proof_sha256='c' * 64)
        (control / 'exchange.json').write_bytes(real.exchange.encode(journal))
        fence = {'policy_file': str(control / 'policy.json'), 'policy_sha256': prep.digest(exchange_raw),
                 'generation': 'b' * 32, 'intent_sha256': intent,
                 'launch_uid': os.geteuid(), 'pairs': [[str(canonical), str(sentinel)]]}
        historical = old_root / 'historical-protected.json'
        prep.private_write(historical, b'fixture approved old protected history')
        policy = {'schema': 'sprint-4-site-policy-v1',
            'protected_pin_file': str(historical), 'protected_pin_sha256': prep.digest(historical.read_bytes()),
            'site': {'project': str(project), 'exchange_fence': fence},
            'launchers': {'before': {}, 'after': launchers}}
        with ZipFile(old_root / 'host-check', 'w') as archive:
            archive.writestr('approved_site_policy.json', json.dumps(policy))
        receipt = {'phase': 'INSTALLED', 'fixture': True}
        record = {'phase': 'RELEASED', 'target': 'INSTALLED', 'receipt': receipt,
                  'original': real.joint.inode(project / 'src/job_search_helper')}
        plan = {'project': str(project), 'hold_id': old_root.name, 'manifest_sha256': 'b' * 64}
        (old_root / 'transaction').mkdir()
        for name, value in (('controller.json', record), ('plan.json', plan),
                            ('protected-continuity.json', {'state': 'verified', 'fixture': True}),
                            ('transaction/transaction.json', receipt), ('manifest.json', {'fixture': True})):
            prep.private_write(old_root / name, real.joint.installer.encode(value))
        pins = {name: prep.digest((old_root / name).read_bytes()) for name in prep.PRIOR_PINS}
        terminal = {'maintenance_id': old_root.name, 'project': str(project), 'source': 'INSTALLED',
            'source_manifest_sha256': 'b' * 64,
            'controller_journal_sha256': prep.digest(real.joint.installer.encode(record)),
            'installer_receipt_sha256': prep.digest(real.joint.installer.encode(receipt))}
        leases = []
        @contextmanager
        def ownership():
            leases.append('entered')
            try:
                yield terminal
            finally:
                leases.append('exited')
        old = SimpleNamespace(project=project, parked=parked, checker=old_root / 'host-check',
            load=lambda **kw: record, checker_policy=real.joint.Controller.checker_policy,
            checked_tool=lambda path: path.read_bytes(), restoration_terminal=ownership)
        manifest = real.joint.installer.load_manifest(prep.PAYLOAD / 'manifest.json', prep.MANIFEST_SHA)
        joint = SimpleNamespace(Controller=Mock(return_value=old), installer=real.joint.installer,
            scope=Mock(return_value=manifest.before), gate=real.joint.gate,
            inode=real.joint.inode, mount=real.joint.mount, read=real.joint.read)
        witness = {'fixture': 'independently settled'}
        current = self.root / 'current.json'
        prep.private_write(current, json.dumps({'schema': 'protected-site-witness-v1',
            'project': str(project), 'witness': witness}).encode())
        current_sha = prep.digest(current.read_bytes())
        checked = []
        def enroll(bundle, *, attempt_directory, approved_checker_sha256, approved_protected_pin_sha256):
            checked.append(bundle)
            self.assertEqual(leases, ['entered'])
            self.assertEqual(prep.digest((bundle / 'host-check').read_bytes()), approved_checker_sha256)
            self.assertEqual(approved_protected_pin_sha256, current_sha)
            self.assertEqual(set(p.name for p in attempt_directory.iterdir()), {'attempt.lock'})
            self.assertFalse((bundle / 'transaction').exists())
            controller = bundle / 'controller.py'
            self.assertEqual(stat.S_IMODE(controller.stat().st_mode), 0o700)
            self.assertEqual(controller.read_bytes().splitlines()[0], b'#!/usr/bin/python3 -I')
            with ZipFile(bundle / 'host-check') as archive:
                self.assertEqual(set(archive.namelist()), real.bundle.BUNDLE_ENTRIES)
                new_policy = json.loads(archive.read('approved_site_policy.json'))
            self.assertEqual(set(new_policy['site']['source_paths']), set(manifest.paths))
            self.assertEqual(new_policy['site']['manifest_sha256'], prep.MANIFEST_SHA)
            self.assertEqual(new_policy['site']['ancillary_process_evidence'], prep.SOCKET)
            self.assertEqual(new_policy['launchers']['before'], launchers)
            self.assertEqual(new_policy['launchers']['after']['job-search-scraper'], manifest.after['job-search-scraper'][1])
            self.assertEqual(new_policy['launchers']['after']['job-search-helper'], launchers['job-search-helper'])
            approval = json.loads((bundle / 'predecessor-guard.json').read_bytes())
            self.assertEqual(approval['observed']['protected_pin']['path'], str(historical))
            self.assertEqual(approval['successor']['protected_pin'], {'path': str(current), 'sha256': current_sha})
            self.assertEqual(approval['observed']['installed_continuity_sha256'], pins['protected-continuity.json'])
            new_plan = json.loads((bundle / 'plan.json').read_bytes())
            self.assertEqual(new_plan['manifest_sha256'], prep.MANIFEST_SHA)
            self.assertEqual(new_plan['predecessor_guard_sha256'], prep.digest((bundle / 'predecessor-guard.json').read_bytes()))
            return real.joint.installer.encode({'fixture_enrollment': True, 'approved_checker_sha256': approved_checker_sha256})
        dependencies = SimpleNamespace(joint=joint, exchange=real.exchange, bundle=real.bundle,
            protected=SimpleNamespace(measure_for_private_review=Mock(return_value=witness)),
            abort=SimpleNamespace(enroll_abort=Mock(side_effect=enroll)))
        inputs = prep.Inputs(project, old_root, destination, attempt, pins)
        return SimpleNamespace(inputs=inputs, deps=dependencies, current=current, current_sha=current_sha,
                               leases=leases, checked=checked, routes=(canonical, sentinel))

    def test_prepare_binds_current_and_historical_evidence_without_exchange_or_receipt_mutation(self):
        case = self.fixture()
        old_files = {str(p): p.read_bytes() for p in case.inputs.predecessor.rglob('*') if p.is_file()}
        routes = [(p.stat().st_dev, p.stat().st_ino) for p in case.routes]
        with patch.object(case.deps.exchange.HostExchange, 'close', side_effect=AssertionError('No closure')), \
             patch.object(case.deps.exchange.HostExchange, 'restore', side_effect=AssertionError('No restoration')):
            result = prep.prepare(case.inputs, self.files, case.current, case.current_sha, case.deps)
        self.assertEqual(result['state'], 'PREPARED_NOT_INSTALLED')
        self.assertEqual(result['source_count'], 9)
        self.assertEqual(case.leases, ['entered', 'exited'])
        self.assertEqual(case.deps.protected.measure_for_private_review.call_count, 2)
        self.assertEqual(case.checked, [case.inputs.destination])
        self.assertEqual(old_files, {str(p): p.read_bytes() for p in case.inputs.predecessor.rglob('*') if p.is_file()})
        self.assertEqual(routes, [(p.stat().st_dev, p.stat().st_ino) for p in case.routes])
        journal = json.loads((case.inputs.destination / 'exchange-private/exchange.json').read_bytes())
        self.assertEqual((journal['phase'], journal['completed'], journal['terminal_proof_sha256']), ('closing', 0, None))
        with self.assertRaisesRegex(ValueError, 'Fresh successor'):
            prep.prepare(case.inputs, self.files, case.current, case.current_sha, case.deps)

    def test_private_controller_is_directly_executable_for_harmless_help_smoke(self):
        case = self.fixture()
        prep.prepare(case.inputs, self.files, case.current, case.current_sha, case.deps)
        controller = case.inputs.destination / 'controller.py'
        completed = subprocess.run([str(controller), '--help'], text=True,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   check=False, timeout=10)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn('usage:', completed.stdout)

    def test_wrong_current_digest_refuses_before_owner_or_outputs(self):
        case = self.fixture()
        with self.assertRaisesRegex(ValueError, 'checksum differs'):
            prep.prepare(case.inputs, self.files, case.current, '0' * 64, case.deps)
        case.deps.joint.Controller.assert_not_called()
        self.assertFalse(case.inputs.destination.exists())
        self.assertFalse(case.inputs.attempt.exists())

    def test_still_unsettled_native_witness_never_creates_preparation(self):
        case = self.fixture()
        case.deps.protected.measure_for_private_review.side_effect = ValueError('legacy restart backlog')
        with self.assertRaisesRegex(ValueError, 'legacy restart backlog'):
            prep.prepare(case.inputs, self.files, case.current, case.current_sha, case.deps)
        self.assertFalse(case.inputs.destination.exists())
        self.assertFalse(case.inputs.attempt.exists())
        case.deps.abort.enroll_abort.assert_not_called()
        self.assertEqual(case.leases, ['entered', 'exited'])

    def test_current_drift_and_foreign_project_hold(self):
        for failure in ('drift', 'foreign', 'public'):
            with self.subTest(failure=failure):
                path = self.root / (failure + '.json')
                value = {'schema': 'protected-site-witness-v1', 'project': str(self.root), 'witness': {'valid': True}}
                if failure == 'foreign':
                    value['project'] = '/foreign'
                prep.private_write(path, json.dumps(value).encode(), 0o644 if failure == 'public' else 0o600)
                deps = SimpleNamespace(protected=SimpleNamespace(measure_for_private_review=lambda p: {'valid': False}))
                with self.assertRaises(ValueError):
                    prep.current_witness(path, prep.digest(path.read_bytes()), self.root, deps)


if __name__ == '__main__':
    unittest.main()
