import json
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

import gate
import controller as joint


def fixture_source(tmp_path):
    project = tmp_path / 'project'
    (project / 'src').mkdir(parents=True)
    package, parked = gate.paths(project)
    package.mkdir()
    (package / '__init__.py').write_text('original = True\n')
    return project, package, parked


def test_predecessor_guard_survives_a_second_exchange_and_replay(tmp_path):
    project, package, parked = fixture_source(tmp_path)
    original = package.stat().st_ino
    gate.park(project, original)
    gate.publish(project, original)
    inherited = gate.guard_identity(parked)
    gate.park(project, original, approved_guard=inherited)
    assert parked.stat().st_ino == original and gate.guard_identity(package) == inherited
    gate.park(project, original, approved_guard=inherited)
    gate.publish(project, original)
    assert package.stat().st_ino == original and gate.guard_identity(parked) == inherited


def test_inherited_guard_cannot_be_recreated_if_missing(tmp_path):
    project, package, parked = fixture_source(tmp_path)
    original = package.stat().st_ino
    missing = {'directory': [1, 2, 0o555, 1000, 1000], 'marker': [1, 3, 0o444, 1000, 1000]}
    with pytest.raises(FileNotFoundError):
        gate.park(project, original, approved_guard=missing)
    assert package.stat().st_ino == original and not parked.exists()


def test_replaced_guard_file_with_identical_bytes_is_rejected(tmp_path):
    project, package, parked = fixture_source(tmp_path)
    original = package.stat().st_ino
    gate.create_marker(parked)
    inherited = gate.guard_identity(parked)
    new = Path(tmp_path / 'new')
    new.write_bytes(gate.MESSAGE)
    new.chmod(0o444)
    parked.chmod(0o755)
    new.replace(parked / '__init__.py')
    parked.chmod(0o555)
    with pytest.raises(ValueError, match='maintenance marker identity changed'):
        gate.park(project, original, approved_guard=inherited)
    assert package.stat().st_ino == original


@pytest.mark.parametrize(('schema', 'target'), [
    ('sprint-4-source-manifest-v1', 'ROLLED_BACK'),
    ('sprint-4-source-manifest-v1', 'INSTALLED'),
    (joint.installer.CONSOLIDATED_SCHEMA, 'INSTALLED'),
])
def test_successor_uses_only_the_complete_pinned_predecessor(tmp_path, monkeypatch, schema, target):
    project, package, parked = fixture_source(tmp_path)
    gate.create_marker(parked)
    original_class = joint.Controller
    successor = object.__new__(original_class)
    old_bundle, new_bundle = (tmp_path / label for label in ('earlier', 'successor'))
    for root in (old_bundle, new_bundle):
        root.mkdir(mode=0o700)
    (old_bundle / 'transaction').mkdir(mode=0o700)
    prior_receipt = {'phase': target, 'test': 'exact old installer receipt'}
    prior_raw = joint.installer.encode(prior_receipt)
    old_tx = old_bundle / 'transaction' / joint.installer.JOURNAL
    old_tx.write_bytes(prior_raw)
    preserved = tmp_path / 'protected-pin.json'
    preserved.write_bytes(b'original protected witness')
    pinned = {"path": str(preserved), 'sha256': joint.installer.digest(preserved.read_bytes())}
    fence_pairs = [[str(tmp_path / 'alternate'), str(tmp_path / '.exchange-park-fixture')]]

    def fake_fence(bundle, byte):
        directory = bundle / 'exchange-private'
        directory.mkdir(mode=0o700)
        policy = directory / 'policy.json'
        policy.write_bytes(byte.encode())
        return {'pairs': fence_pairs, 'generation': byte * 32, 'policy_sha256': joint.installer.digest(policy.read_bytes()),
                'intent_sha256': byte * 64, 'policy_file': str(policy)}

    before, after = fake_fence(old_bundle, 'b'), fake_fence(new_bundle, 'a')
    old_exchange = Path(before['policy_file']).with_name('exchange.json')
    exchange_raw = joint.installer.encode({'phase': 'restored', 'completed': 1,
        'terminal_proof_sha256': 'f' * 64, 'intent_sha256': before['intent_sha256']})
    old_exchange.write_bytes(exchange_raw)

    def fake_checker(bundle, hold, fence, protected_pin=pinned):
        checker = bundle / 'host-check'
        with ZipFile(checker, 'w') as file:
            file.writestr('approved_site_policy.json', json.dumps({
                'protected_pin_file': protected_pin['path'], 'protected_pin_sha256': protected_pin['sha256'],
                'site': {'exchange_fence': fence, 'maintenance_bundle': str(bundle),
                         'maintenance_id': hold, 'project': str(project), 'manifest_sha256': 'a' * 64},
            }))
        return checker

    checker_old = fake_checker(old_bundle, 'previous', before)
    current_protected = tmp_path / 'current-protected-pin.json'
    current_protected.write_bytes(b'newly reviewed current snapshot after authorized changes')
    current_protected.chmod(0o600)
    current_pin = {'path': str(current_protected), 'sha256': joint.installer.digest(current_protected.read_bytes())}
    consolidated_install = schema == joint.installer.CONSOLIDATED_SCHEMA and target == 'INSTALLED'
    checker_new = fake_checker(new_bundle, 'new', after, current_pin if consolidated_install else pinned)
    source_identity = joint.inode(package)
    guard = gate.guard_identity(parked)
    terminal = {'phase': 'RELEASED', 'target': target, 'receipt': prior_receipt,
                'original': source_identity, 'guard': guard['directory'][:2]}
    verified = []
    predecessor = SimpleNamespace(project=project, hold_id='previous', manifest=SimpleNamespace(sha256='b' * 64),
                                  state=old_bundle / 'transaction', checker=checker_old,
                                  binding={'files': {str(checker_old): joint.ref(checker_old)}},
                                  load=lambda **_: terminal, verify_released_source=verified.append,
                                  checked_tool=lambda path: path.read_bytes())

    def approved_previous(path):
        assert path == old_bundle
        return predecessor

    monkeypatch.setattr(joint, 'Controller', approved_previous)
    successor.bundle, successor.hold_id, successor.project = new_bundle, 'new', project
    successor.checker, successor.canonical, successor.parked = checker_new, package, parked
    successor.manifest = SimpleNamespace(sha256='a' * 64, schema=schema)
    observed = {'schema': 's4-observed-terminal-guard-v1', 'view': 'PREDECESSOR_ONLY', 'guard_path': str(parked),
        'predecessor': str(old_bundle), 'source_identity': source_identity,
        'protected_pin': pinned, 'installer_journal_sha256': joint.installer.digest(prior_raw),
        'guard': {**guard, 'mount': joint.mount(parked), 'parent': joint.inode(parked.parent),
                  'marker_sha256': joint.installer.digest(gate.MESSAGE)},
        'restored_exchange': {'journal_sha256': joint.installer.digest(exchange_raw), 'terminal_sha256': 'f' * 64,
            **{key: before[key] for key in ('generation', 'policy_sha256', 'intent_sha256')}},
        'terminal_release': {'maintenance_id': 'previous', 'project': str(project), 'source': target,
            'source_manifest_sha256': 'b' * 64,
            'controller_journal_sha256': joint.installer.digest(joint.installer.encode(terminal)),
            'installer_receipt_sha256': joint.installer.digest(prior_raw)}}
    if target == 'INSTALLED':
        continuity = old_bundle / 'protected-continuity.json'
        continuity_record = {'schema': 'sprint-4-protected-continuity-v1', 'state': 'verified',
                             'target': target, 'maintenance_id': 'previous', 'project': str(project),
                             'source_manifest_sha256': 'b' * 64, 'protected_pin_sha256': pinned['sha256'],
                             'verifier_sha256': joint.ref(checker_old)[-1]}
        continuity_raw = joint.installer.encode(continuity_record)
        continuity.write_bytes(continuity_raw)
        continuity.chmod(0o600)
        observed['installed_continuity_sha256'] = joint.installer.digest(continuity_raw)
    authority = {'bundle': str(new_bundle), 'bundle_identity': joint.inode(new_bundle), 'hold_id': 'new',
                 'checker_sha256': joint.ref(checker_new)[-1], 'manifest_sha256': 'a' * 64, 'exchange': after}
    if consolidated_install:
        authority['protected_pin'] = current_pin
    handoff = new_bundle / 'predecessor-guard.json'
    successor.predecessor = {'schema': 's4-predecessor-guard-handoff-v1', 'observed': observed, 'successor': authority}
    handoff.write_bytes(joint.installer.encode(successor.predecessor))
    successor.binding = {'files': {str(path): joint.ref(path) for path in (handoff, checker_new)}}

    if schema != joint.installer.CONSOLIDATED_SCHEMA and target == 'INSTALLED':
        with pytest.raises(ValueError, match='did not complete an approved terminal release'):
            successor.verify_preinstall_parked()
        assert not verified
        return

    assert successor.verify_preinstall_parked() == guard['directory'][:2]
    assert verified == [terminal]
    if consolidated_install:
        frozen = current_protected.read_bytes()
        current_protected.write_bytes(frozen + b' ')
        with pytest.raises(ValueError, match='differs from the approved current pin'):
            successor.verify_preinstall_parked()
        current_protected.write_bytes(frozen)
        current_protected.chmod(0o644)
        with pytest.raises(ValueError, match='differs from the approved current pin'):
            successor.verify_preinstall_parked()
        current_protected.chmod(0o600)
        approved_bytes = handoff.read_bytes()
        approved_reference = successor.binding['files'][str(handoff)]
        authority.pop('protected_pin')
        handoff.write_bytes(joint.installer.encode(successor.predecessor))
        successor.binding['files'][str(handoff)] = joint.ref(handoff)
        with pytest.raises(ValueError, match='Handoff belongs to another successor'):
            successor.verify_preinstall_parked()
        authority['protected_pin'] = current_pin
        handoff.write_bytes(approved_bytes)
        successor.binding['files'][str(handoff)] = joint.ref(handoff)
        assert successor.binding['files'][str(handoff)] == approved_reference
    if target == 'INSTALLED':
        continuity.write_bytes(continuity_raw + b' ')
        with pytest.raises(ValueError, match='protected continuity did not match'):
            successor.verify_preinstall_parked()
        continuity.write_bytes(continuity_raw)
        continuity.chmod(0o644)
        with pytest.raises(ValueError, match='protected continuity did not match'):
            successor.verify_preinstall_parked()
        continuity.chmod(0o600)
    terminal['phase'] = 'RELEASING'
    with pytest.raises(ValueError, match='did not complete an approved terminal release'):
        successor.verify_preinstall_parked()
    terminal['phase'] = 'RELEASED'
    prior_receipt['phase'] = 'ROLLING_BACK'
    with pytest.raises(ValueError, match='did not complete an approved terminal release'):
        successor.verify_preinstall_parked()
    prior_receipt['phase'] = target
    assert gate.guard_identity(parked) == guard and old_tx.read_bytes() == prior_raw
    old_exchange.write_bytes(exchange_raw + b' ')
    with pytest.raises(ValueError, match='Predecessor restored alternate evidence changed'):
        successor.verify_preinstall_parked()
    old_exchange.write_bytes(exchange_raw)
    prior_policy = Path(before['policy_file'])
    policy_raw = prior_policy.read_bytes()
    prior_policy.write_bytes(b'different fence')
    with pytest.raises(ValueError, match='exchange policy changed or was reused'):
        successor.verify_preinstall_parked()
    prior_policy.write_bytes(policy_raw)
    old_tx.write_bytes(prior_raw + b' ')
    with pytest.raises(ValueError, match='Predecessor protected or installer journal bytes changed'):
        successor.verify_preinstall_parked()
    old_tx.write_bytes(prior_raw)
    handoff.write_bytes(handoff.read_bytes() + b' ')
    with pytest.raises(ValueError, match='Handoff file or current checker changed'):
        successor.verify_preinstall_parked()
