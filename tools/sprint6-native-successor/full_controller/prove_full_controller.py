"""Run the full pinned maintenance controller against the exact reviewed 38 paths."""

from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

import test_combined_release as base

ROOT = Path(__file__).resolve().parent
MANIFEST = Path('/tmp/jsh-consolidated-scope.20261121/RESULT.json')
SCOPE = json.loads(MANIFEST.read_bytes())
PINS = {
    'controller.py': '75f8622a5410b7189f43b57353bca8bd3cab83459757038bfb55087d0b87157d',
    'gate.py': '7df4121796ce400461be9b4329984bc6f1ced83858588d3a63d4e5258d286537',
    'installer.py': '1cf49bd23e2e82f5ce10f7e7af37f80ff8b534ebb5d5048dbca1565bf00464b4',
}
BRIDGE = Path(base.WRAPPER) / 'coordinator_receipt_host_bridge.py'
CONTROL = ROOT / 'frozen-tools'


def endpoints():
    rows, before, after = {}, {}, {}
    native, staged = Path(SCOPE['native']), Path(SCOPE['candidate'])
    for name, entry in SCOPE['paths'].items():
        rows[name] = {'owner': entry['after']['owner']}
        for side, tree, payload in (('before', native, before), ('after', staged, after)):
            frozen = entry[side]
            rows[name][side] = None
            if frozen is None:
                assert not (tree / name).exists() and not (tree / name).is_symlink(), name
                continue
            pin = {key: frozen[key] for key in ('mode', 'sha256')}
            payload[name] = base.source_bytes(tree / name, pin)
            rows[name][side] = pin
    assert len(rows) == 38 and len(before) == 28 and len(after) == 38
    return rows, before, after


def file_custody(path):
    info = path.stat()
    return (info.st_dev, info.st_ino, info.st_mode, sha256(path.read_bytes()).hexdigest())


def main():
    for name, pin in PINS.items():
        assert sha256((CONTROL / name).read_bytes()).hexdigest() == pin, name
    base.endpoints = endpoints
    base.ARTIFACTS = Path(tempfile.mkdtemp(prefix='run.', dir=ROOT))
    fixture = base.Fixture('exact_38', CONTROL)
    bridge_payload = (Path(SCOPE['native']) / BRIDGE).read_bytes()
    base.write(fixture.project / BRIDGE, bridge_payload)
    bridge = file_custody(fixture.project / BRIDGE)

    assertions = base.CombinedReleaseTests()
    fixture.assert_visible('before')
    stopped = fixture.run('install', cut='after-package-park-before-held')
    assert stopped.returncode == -9, (stopped.returncode, stopped.stderr)
    interrupted = json.loads((fixture.bundle / 'controller.json').read_bytes())
    assert interrupted['phase'] == 'CLOSING'
    assert not (fixture.project / base.HOST_PATH).exists()
    assert file_custody(fixture.project / BRIDGE) == bridge

    install = assertions.assert_receipt(fixture, fixture.run('install'), 'after')
    assert file_custody(fixture.project / BRIDGE) == bridge
    fixture.candidate.rename(fixture.bundle / 'candidate-unavailable')
    rollback = assertions.assert_receipt(fixture, fixture.run('rollback'), 'before')
    assert file_custody(fixture.project / BRIDGE) == bridge
    terminal = (fixture.bundle / 'controller.json').read_bytes()
    checks = len(fixture.events())
    replay = assertions.assert_receipt(fixture, fixture.run('rollback'), 'before')
    assert rollback == replay and len(fixture.events()) == checks
    assert (fixture.bundle / 'controller.json').read_bytes() == terminal

    proof = {
        'result': 'PASS_DISPOSABLE_CONTROLLER_ONLY',
        'scope_manifest_sha256': sha256(MANIFEST.read_bytes()).hexdigest(),
        'real_controller_installer_and_gate': True,
        'before_image_count': 28,
        'after_image_count': 38,
        'original_absences_restored': 10,
        'scope_payload_bytes_exact_before_and_after': True,
        'restart_phase': interrupted['phase'],
        'installed_receipt': install['receipt']['phase'],
        'rollback_receipt': rollback['receipt']['phase'],
        'candidate_unavailable_for_rollback': True,
        'terminal_replay_read_only': True,
        'bridge_inode_mode_and_bytes_unchanged': True,
        'fixture_host_attestations': checks,
        'protected_fixture_paths_unchanged': len(fixture.witnesses),
        'witness_and_services': 'SUBSTITUTED_PRIVATE_FIXTURE',
        'predecessor_enrolled': False,
    }
    base.write(ROOT / 'RESULT.json', base.encode(proof))
    print(json.dumps(proof, indent=2))


if __name__ == '__main__':
    main()
