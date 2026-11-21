"""One additional nested-predecessor scenario, entirely disposable."""
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_successive_controller as earlier

base, joint = earlier.base, earlier.joint


class ThirdGeneration(unittest.TestCase):
    def test_third_generation_closing(self):
        f, first, guard, first_saved, assertion = earlier.SuccessiveController.prepare(self)
        second = f.bundle
        f.assert_tool_bytes = lambda: self.assertEqual(
            {name: sha256((f.bundle / name).read_bytes()).hexdigest() for name in base.TOOLS},
            {name: sha256((earlier.CONTROL / name).read_bytes()).hexdigest() for name in base.TOOLS})
        assertion.assert_receipt(f, f.run('install'), 'after')
        assertion.assert_receipt(f, f.run('rollback'), 'before')
        predecessor = joint.Controller(second)
        terminal = predecessor.load(canonical=True)
        self.assertEqual(predecessor.inherited_guard(), guard)
        old_policy = predecessor.checker_policy((second / 'host-check').read_bytes())
        previous = old_policy['site']['exchange_fence']
        restored = base.encode({'phase': 'restored', 'completed': len(previous['pairs']),
                               'terminal_proof_sha256': 'e' * 64,
                               'intent_sha256': previous['intent_sha256']})
        base.write(Path(previous['policy_file']).with_name('exchange.json'), restored)
        second_saved = earlier.snapshot(second)

        third = f.root / 'third'
        third.mkdir(mode=0o700)
        for name in base.TOOLS:
            shutil.copy2(earlier.CONTROL / name, third / name)
        shutil.copytree(second / 'candidate', third / 'candidate')
        shutil.copy2(second / 'manifest.json', third / 'manifest.json')
        plan = json.loads((second / 'plan.json').read_bytes())
        plan.pop('predecessor_guard_sha256')
        plan['hold_id'] += '-third'
        base.write(third / 'plan.json', base.encode(plan))
        fresh = earlier.fence(third, previous['pairs'], 'c' * 32)
        earlier.checker(third, Path(old_policy['protected_pin_file']), fresh)
        # Preserve physical guard identity while rebinding history to immediate second.
        observed = json.loads((second / 'predecessor-guard.json').read_bytes())['observed']
        observed.update(predecessor=str(second),
            installer_journal_sha256=sha256((second / 'transaction/transaction.json').read_bytes()).hexdigest(),
            restored_exchange={'journal_sha256': sha256(restored).hexdigest(), 'terminal_sha256': 'e' * 64,
                **{k: previous[k] for k in ('generation', 'policy_sha256', 'intent_sha256')}},
            terminal_release={'maintenance_id': predecessor.hold_id, 'project': str(f.project),
                'source': terminal['target'], 'source_manifest_sha256': predecessor.manifest.sha256,
                'controller_journal_sha256': sha256(joint.installer.encode(terminal)).hexdigest(),
                'installer_receipt_sha256': sha256(joint.installer.encode(terminal['receipt'])).hexdigest()})
        approval = {'schema': 's4-predecessor-guard-handoff-v1', 'observed': observed,
            'successor': {'bundle': str(third), 'bundle_identity': joint.inode(third),
                'hold_id': plan['hold_id'], 'checker_sha256': joint.ref(third / 'host-check')[-1],
                'manifest_sha256': plan['manifest_sha256'], 'exchange': fresh}}
        raw = base.encode(approval)
        base.write(third / 'predecessor-guard.json', raw)
        plan['predecessor_guard_sha256'] = sha256(raw).hexdigest()
        base.write(third / 'plan.json', base.encode(plan))
        current = joint.Controller(third)
        self.assertEqual(current.verify_preinstall_parked(), guard['directory'][:2])
        f.bundle, f.candidate = third, third / 'candidate'
        f.environment['JSH_SUCCESSOR_FIXTURE_BUNDLE'] = str(third)
        stopped = f.run('install', cut='close-intent-before-unlink')
        self.assertEqual(stopped.returncode, -9, stopped.stderr)
        closing = json.loads((third / 'controller.json').read_bytes())
        self.assertEqual(closing['phase'], 'CLOSING')
        self.assertEqual(closing['guard'], guard['directory'][:2])
        self.assertEqual(joint.gate.guard_identity(f.parked), guard)
        self.assertEqual(closing['original'], joint.inode(f.package))
        self.assertNotEqual(closing['state'], terminal['state'])
        self.assertNotEqual(closing['install_gate'], terminal['install_gate'])
        self.assertNotEqual(closing['controller_gate'], terminal['controller_gate'])
        self.assertEqual(earlier.snapshot(first), first_saved)
        self.assertEqual(earlier.snapshot(second), second_saved)
        base.write(f.root / 'third-generation-result.json', base.encode({
            'first': str(first), 'immediate_predecessor': str(second), 'third': str(third),
            'same_physical_guard': guard, 'immediate_predecessor_had_inherited_guard': True,
            'third_closing_before_exchange': True,
            'first_preserved_files': len(first_saved), 'second_preserved_files': len(second_saved),
            'host_services_exchange_observations': 'SUBSTITUTED_NOT_LIVE'}))


if __name__ == '__main__':
    print('Evidence:', base.ARTIFACTS, flush=True)
    unittest.main(verbosity=2)
