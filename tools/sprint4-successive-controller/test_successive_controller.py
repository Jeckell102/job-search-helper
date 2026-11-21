"""Tests only: real successive controller/installer/gate CLI, substituted host observations."""
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from zipfile import ZipFile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import test_combined_release as base

STAGE = Path('/tmp/jsh-s4-terminal-guard-staged.UKxQYcjO')
PRIOR = Path('/tmp/jsh-s4-combined-release-fixture.restoration.IIStem9T/run.f57l0fj5/frozen-tool-input')
PINS = {'controller.py': '927063a9797c121a8c6e4b73011a79ea2874d72427c64387e969355503b092eb',
        'gate.py': '7df4121796ce400461be9b4329984bc6f1ced83858588d3a63d4e5258d286537',
        'preinstall_abort.py': '5d4c94876a2b9325fc5f7f22bb4e8099a973ff66a67e642ef3ac7b56743562ea'}
base.ARTIFACTS = Path(tempfile.mkdtemp(prefix='run.', dir=ROOT))
CONTROL = base.ARTIFACTS / 'frozen-successor-tools'
CONTROL.mkdir(mode=0o700)
for name, expected in PINS.items():
    assert sha256((STAGE / name).read_bytes()).hexdigest() == expected
for name in base.TOOLS:
    shutil.copy2((PRIOR if name == 'verify_hold' else STAGE) / name, CONTROL / name)
sys.path.insert(0, str(CONTROL))
import controller as joint


def synthetic_endpoints():
    names = ('src/job_search_helper/fixture_endpoint.py', *base.WRAPPER_PATHS)
    before = {name: b'FIXTURE_GENERATION = "before"\n' for name in names}
    after = {name: b'FIXTURE_GENERATION = "after"\n' for name in names}
    rows = {name: {'before': base.pin(before[name], '0600'), 'after': base.pin(after[name], '0600'),
                   'owner': [os.getuid(), os.getgid()]} for name in names}
    return rows, before, after


base.endpoints = synthetic_endpoints


def snapshot(directory):
    return {str(p.relative_to(directory)): (p.stat().st_dev, p.stat().st_ino,
            p.stat().st_mode, p.stat().st_nlink, sha256(p.read_bytes()).hexdigest())
            for p in directory.rglob('*') if p.is_file()}


def fence(bundle, pairs, generation):
    directory = bundle / 'exchange-private'
    directory.mkdir(mode=0o700)
    policy = directory / 'policy.json'
    raw = base.encode({'fixture_only': True, 'generation': generation, 'pairs': pairs})
    base.write(policy, raw)
    return {'pairs': pairs, 'generation': generation,
            'policy_sha256': sha256(raw).hexdigest(), 'policy_file': str(policy),
            'intent_sha256': sha256(('fixture-only-intent:' + generation).encode()).hexdigest()}


def checker(bundle, protected, exchange):
    plan = json.loads((bundle / 'plan.json').read_bytes())
    policy = {'protected_pin_file': str(protected), 'protected_pin_sha256': sha256(protected.read_bytes()).hexdigest(),
              'site': {'exchange_fence': exchange, 'maintenance_bundle': str(bundle),
                       'maintenance_id': plan['hold_id'], 'project': plan['project'],
                       'manifest_sha256': plan['manifest_sha256']}}
    target = bundle / 'host-check'
    if target.exists():
        target.unlink()  # Only before this disposable capsule's first Controller enrollment.
    base.write(target, f'#!{Path(sys.executable).resolve()} -I\n'.encode(), 0o700)
    with ZipFile(target, 'a') as archive:
        archive.writestr('approved_site_policy.json', base.encode(policy))
        archive.writestr('__main__.py', 'from pathlib import Path\nimport sys\nsys.dont_write_bytecode = True\n'
                         f'sys.path.insert(0, {str(ROOT)!r})\n'
                         'from fixture_stubs import attest\nattest(Path(sys.argv[0]).resolve())\n')
    return policy


class SuccessiveController(unittest.TestCase):
    def prepare(self):
        f = base.Fixture(self._testMethodName, PRIOR)
        old = f.bundle
        protected = f.root / 'original-protected-pin.json'
        base.write(protected, base.encode({'fixture_only': 'original protected evidence'}))
        pairs = [[str(f.root / 'alternate-source'), str(f.root / '.exchange-park-fixture')]]
        previous = fence(old, pairs, 'a' * 32)
        checker(old, protected, previous)
        f.environment['JSH_SUCCESSOR_FIXTURE_BUNDLE'] = str(old)
        assertion = base.CombinedReleaseTests()
        assertion.assert_receipt(f, f.run('install'), 'after')
        assertion.assert_receipt(f, f.run('rollback'), 'before')
        predecessor = joint.Controller(old)
        terminal = predecessor.load(canonical=True)
        predecessor.verify_released_source(terminal)
        self.assertEqual(terminal['phase'], 'RELEASED')
        self.assertEqual(terminal['target'], 'ROLLED_BACK')
        guard = joint.gate.guard_identity(f.parked)
        # Alternate-host fence observations are fixture inputs, not real host evidence.
        exchange_raw = base.encode({'phase': 'restored', 'completed': len(pairs),
                                    'terminal_proof_sha256': 'f' * 64,
                                    'intent_sha256': previous['intent_sha256']})
        base.write(Path(previous['policy_file']).with_name('exchange.json'), exchange_raw)
        preserved = snapshot(old)

        fresh = f.root / 'successor'
        fresh.mkdir(mode=0o700)
        for name in base.TOOLS:
            shutil.copy2(CONTROL / name, fresh / name)
        shutil.copytree(old / 'candidate', fresh / 'candidate')
        shutil.copy2(old / 'manifest.json', fresh / 'manifest.json')
        plan = json.loads((old / 'plan.json').read_bytes())
        plan['hold_id'] += '-successor'
        base.write(fresh / 'plan.json', base.encode(plan))
        current = fence(fresh, pairs, 'b' * 32)
        checker(fresh, protected, current)
        observed = {'schema': 's4-observed-terminal-guard-v1', 'view': 'PREDECESSOR_ONLY',
            'guard_path': str(f.parked), 'predecessor': str(old),
            'source_identity': joint.inode(f.package),
            'protected_pin': {'path': str(protected), 'sha256': sha256(protected.read_bytes()).hexdigest()},
            'installer_journal_sha256': sha256((old / 'transaction/transaction.json').read_bytes()).hexdigest(),
            'guard': {**guard, 'mount': joint.mount(f.parked), 'parent': joint.inode(f.parked.parent),
                      'marker_sha256': sha256(joint.gate.MESSAGE).hexdigest()},
            'restored_exchange': {'journal_sha256': sha256(exchange_raw).hexdigest(),
                'terminal_sha256': 'f' * 64,
                **{k: previous[k] for k in ('generation', 'policy_sha256', 'intent_sha256')}},
            'terminal_release': {'maintenance_id': predecessor.hold_id, 'project': str(f.project),
                'source': terminal['target'], 'source_manifest_sha256': predecessor.manifest.sha256,
                'controller_journal_sha256': sha256(joint.installer.encode(terminal)).hexdigest(),
                'installer_receipt_sha256': sha256(joint.installer.encode(terminal['receipt'])).hexdigest()}}
        approval = {'schema': 's4-predecessor-guard-handoff-v1', 'observed': observed,
                    'successor': {'bundle': str(fresh), 'bundle_identity': joint.inode(fresh),
                        'hold_id': plan['hold_id'], 'checker_sha256': joint.ref(fresh / 'host-check')[-1],
                        'manifest_sha256': plan['manifest_sha256'], 'exchange': current}}
        raw = base.encode(approval)
        base.write(fresh / 'predecessor-guard.json', raw)
        plan['predecessor_guard_sha256'] = sha256(raw).hexdigest()
        base.write(fresh / 'plan.json', base.encode(plan))
        f.bundle = fresh
        f.candidate = fresh / 'candidate'
        f.environment['JSH_SUCCESSOR_FIXTURE_BUNDLE'] = str(fresh)
        self.assertNotEqual(plan['hold_id'], predecessor.hold_id)
        self.assertEqual(snapshot(old), preserved)
        return f, old, guard, preserved, assertion

    def test_successor_closing_restart_install_and_rollback_preserve_predecessor(self):
        f, old, guard, preserved, assertion = self.prepare()
        interrupted = f.run('install', cut='close-intent-before-unlink')
        self.assertEqual(interrupted.returncode, -9, interrupted.stderr)
        closing = json.loads((f.bundle / 'controller.json').read_bytes())
        self.assertEqual(closing['phase'], 'CLOSING')
        self.assertEqual(closing['guard'], guard['directory'][:2])
        self.assertEqual(joint.gate.guard_identity(f.parked), guard)
        self.assertEqual(closing['original'], joint.inode(f.package))
        self.assertNotEqual(closing['state'], joint.inode(old / 'transaction'))
        self.assertNotEqual(closing['install_gate'], joint.inode(old / 'installer.lock'))
        self.assertNotEqual(closing['controller_gate'], joint.inode(old / 'controller.lock'))
        self.assertEqual(snapshot(old), preserved)
        # The base harness tool witness is predecessor-specific; check fresh pins independently.
        f.assert_tool_bytes = lambda: self.assertEqual(
            {name: sha256((f.bundle / name).read_bytes()).hexdigest() for name in base.TOOLS},
            {name: sha256((CONTROL / name).read_bytes()).hexdigest() for name in base.TOOLS})
        assertion.assert_receipt(f, f.run('install'), 'after')
        self.assertEqual(joint.gate.guard_identity(f.parked), guard)
        self.assertEqual(snapshot(old), preserved)
        installed = (f.bundle / 'controller.json').read_bytes()
        assertion.assert_receipt(f, f.run('install'), 'after')
        self.assertEqual((f.bundle / 'controller.json').read_bytes(), installed)
        assertion.assert_receipt(f, f.run('rollback'), 'before')
        self.assertEqual(joint.gate.guard_identity(f.parked), guard)
        self.assertEqual(snapshot(old), preserved)
        rolled_back = (f.bundle / 'controller.json').read_bytes()
        assertion.assert_receipt(f, f.run('rollback'), 'before')
        self.assertEqual((f.bundle / 'controller.json').read_bytes(), rolled_back)
        self.assertEqual(snapshot(old), preserved)
        base.write(f.root / 'composed-result.json', base.encode({
            'predecessor': str(old), 'successor': str(f.bundle), 'guard': guard,
            'predecessor_files_preserved': len(preserved), 'closing_checked_before_exchange': True,
            'successor_install_and_rollback': True, 'terminal_replays_unchanged': True,
            'host_and_exchange_observations': 'SUBSTITUTED_NOT_LIVE'}))


if __name__ == '__main__':
    base.write(base.ARTIFACTS / 'pins.json', base.encode({
        'successor': {name: sha256((CONTROL / name).read_bytes()).hexdigest() for name in base.TOOLS},
        'predecessor': {name: sha256((PRIOR / name).read_bytes()).hexdigest() for name in base.TOOLS}}))
    print('Evidence:', base.ARTIFACTS, flush=True)
    unittest.main(verbosity=2)
