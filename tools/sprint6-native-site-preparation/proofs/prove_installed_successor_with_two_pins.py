"""Run actual Freeform-to-consolidated maintenance on a disposable source tree."""

from hashlib import sha256
import json
from pathlib import Path
import shutil
import sys
import tempfile
from zipfile import ZipFile

import prove_full_controller as exact
import test_combined_release as base

ROOT = Path(__file__).resolve().parent
LEGACY = Path('/home/chris/.local/state/job-search-helper-maintenance/s4-freeform-20261120-01')
FIX = Path('/tmp/jsh-s6-current-site-pin.kzzbe44q')
OLD_SCHEMA = 'sprint-4-source-manifest-v1'
NEW_SCHEMA = 'sprint-6-consolidated-source-manifest-v1'
OLD_MANIFEST_SHA = 'a1863753a251058e1cd99266568aef3b6e9b3076e49c52dd0adff11d93f6a163'


def legacy_endpoints():
    raw = (LEGACY / 'manifest.json').read_bytes()
    assert sha256(raw).hexdigest() == OLD_MANIFEST_SHA
    rows = json.loads(raw)['paths']
    assert len(rows) == 47
    before, after = {}, {}
    for number, (name, row) in enumerate(sorted(rows.items())):
        for side, payload in (('before', before), ('after', after)):
            if row[side] is None:
                continue
            source = (LEGACY / f'wrapper-host-{side}.sealed' if name == base.HOST_PATH
                      else LEGACY / 'transaction' / f'{side}-{number:02d}')
            data = source.read_bytes()
            assert sha256(data).hexdigest() == row[side]['sha256'], name
            payload[name] = data
    return rows, before, after


def pin(path):
    return sha256(path.read_bytes()).hexdigest()


def fixture_fence(bundle, paths, generation):
    location = bundle / 'exchange-private/policy.json'
    raw = base.encode({'fixture_only': True, 'generation': generation, 'pairs': paths})
    base.write(location, raw)
    return {'pairs': paths, 'generation': generation, 'policy_sha256': sha256(raw).hexdigest(),
            'policy_file': str(location),
            'intent_sha256': sha256(('fixture-only-intent:' + generation).encode()).hexdigest()}


def fixture_checker(bundle, fixture, plan, protected, fence):
    path = bundle / 'host-check'
    if path.exists():
        path.unlink()
    base.write(path, f'#!{Path(sys.executable).resolve()} -I\n'.encode(), 0o700)
    payload = {'protected_pin_file': str(protected), 'protected_pin_sha256': pin(protected),
               'site': {'exchange_fence': fence, 'maintenance_bundle': str(bundle),
                        'maintenance_id': plan['hold_id'], 'project': str(fixture.project),
                        'manifest_sha256': plan['manifest_sha256']}}
    with ZipFile(path, 'a') as archive:
        archive.writestr('approved_site_policy.json', base.encode(payload))
        archive.writestr('__main__.py', 'from pathlib import Path\nimport sys\nsys.dont_write_bytecode = True\n'
                         f'sys.path.insert(0, {str(ROOT)!r})\n'
                         'from fixture_stubs import attest\nattest(Path(sys.argv[0]).resolve())\n')
    return path


def snapshot(directory):
    return {str(path.relative_to(directory)): exact.file_custody(path)
            for path in directory.rglob('*') if path.is_file()}


def main():
    base.ARTIFACTS = Path(tempfile.mkdtemp(prefix='run.', dir=ROOT))
    base.endpoints, base.MANIFEST_SCHEMA = legacy_endpoints, OLD_SCHEMA
    fixture = base.Fixture('installed_predecessor', LEGACY)
    initial = fixture.bundle
    predecessor_manifest = fixture.manifest
    for name in base.TOOLS:
        assert pin(initial / name) == pin(LEGACY / name), name
    # The earlier fixture copies only its 47 mutations. Seed known existing
    # successor-only endpoints before the predecessor measures its siblings.
    current, before, after = exact.endpoints()
    for name, value in before.items():
        if name not in fixture.manifest:
            base.write(fixture.project / name, value, int(current[name]['before']['mode'], 8))
    protected = fixture.root / 'protected-pin.json'
    base.write(protected, base.encode({'fixture_only': True, 'protected': 'immutable baseline'}))
    routes = [[str(fixture.root / 'alternate-checkout'), str(fixture.root / '.alternate-park')]]
    old_fence = fixture_fence(initial, routes, 'b' * 32)
    old_plan = json.loads((initial / 'plan.json').read_bytes())
    initial_checker = fixture_checker(initial, fixture, old_plan, protected, old_fence)
    fixture.environment['JSH_RELEASE_FIXTURE_BUNDLE'] = str(initial)
    assertions = base.CombinedReleaseTests()
    prior = assertions.assert_receipt(fixture, fixture.run('install'), 'after')

    # This receipt and exchange proof substitute the already independently
    # verified host observations; the controller/source transactions are real.
    old_policy = Path(old_fence['policy_file'])
    old_restoration = {'phase': 'restored', 'completed': len(routes), 'terminal_proof_sha256': 'e' * 64,
                       'intent_sha256': old_fence['intent_sha256']}
    exchange_journal = old_policy.with_name('exchange.json')
    base.write(exchange_journal, base.encode(old_restoration))
    continuity = initial / 'protected-continuity.json'
    protected_ref = {'path': str(protected), 'sha256': pin(protected)}
    base.write(continuity, base.encode({
        'schema': 'sprint-4-protected-continuity-v1', 'state': 'verified', 'target': 'INSTALLED',
        'maintenance_id': old_plan['hold_id'], 'project': str(fixture.project),
        'source_manifest_sha256': old_plan['manifest_sha256'],
        'protected_pin_sha256': pin(protected), 'verifier_sha256': pin(initial_checker),
    }))
    predecessor = snapshot(initial)
    assert pin(fixture.project / exact.BRIDGE) == fixture.manifest[str(exact.BRIDGE)]['after']['sha256']
    bridge = exact.file_custody(fixture.project / exact.BRIDGE)

    fresh = fixture.root / 'successor'
    fresh.mkdir(mode=0o700)
    for name in base.TOOLS:
        source = (LEGACY if name == 'verify_hold' else FIX) / name
        shutil.copy2(source, fresh / name)
        assert pin(fresh / name) == pin(source)
    for name, raw in after.items():
        base.write(fresh / 'candidate' / name, raw, int(current[name]['after']['mode'], 8))
    raw_manifest = base.encode({'schema': NEW_SCHEMA, 'paths': current})
    base.write(fresh / 'manifest.json', raw_manifest)
    plan = {**old_plan, 'hold_id': old_plan['hold_id'] + '-successor',
            'manifest_sha256': sha256(raw_manifest).hexdigest()}
    fence = fixture_fence(fresh, routes, 'c' * 32)
    current_protected = fixture.root / 'current-protected-pin.json'
    base.write(current_protected, base.encode({'fixture_only': True, 'protected': 'separately approved current snapshot'}))
    checker = fixture_checker(fresh, fixture, plan, current_protected, fence)

    # Import the exact patched tool only to measure this fixture's guard.
    sys.path.insert(0, str(FIX))
    from controller import Controller, gate, inode, mount

    prior_record = json.loads((initial / 'controller.json').read_bytes())
    inherited = gate.guard_identity(fixture.parked)
    observed = {'schema': 's4-observed-terminal-guard-v1', 'view': 'PREDECESSOR_ONLY',
                'predecessor': str(initial), 'guard_path': str(fixture.parked),
                'guard': {**inherited, 'parent': inode(fixture.parked.parent), 'mount': mount(fixture.parked),
                          'marker_sha256': pin(fixture.parked / '__init__.py')},
                'installer_journal_sha256': pin(initial / 'transaction/transaction.json'),
                'protected_pin': protected_ref, 'source_identity': prior_record['original'],
                'installed_continuity_sha256': pin(continuity),
                'terminal_release': {'maintenance_id': old_plan['hold_id'], 'project': str(fixture.project),
                                     'source': 'INSTALLED', 'source_manifest_sha256': old_plan['manifest_sha256'],
                                     'controller_journal_sha256': pin(initial / 'controller.json'),
                                     'installer_receipt_sha256': sha256(base.encode(prior['receipt'])).hexdigest()},
                'restored_exchange': {'generation': old_fence['generation'], 'intent_sha256': old_fence['intent_sha256'],
                                      'journal_sha256': pin(exchange_journal), 'policy_sha256': old_fence['policy_sha256'],
                                      'terminal_sha256': old_restoration['terminal_proof_sha256']}}
    approved = base.encode({'schema': 's4-predecessor-guard-handoff-v1', 'observed': observed,
                            'successor': {'bundle': str(fresh), 'bundle_identity': inode(fresh), 'hold_id': plan['hold_id'],
                                          'checker_sha256': pin(checker), 'manifest_sha256': plan['manifest_sha256'],
                                          'exchange': fence,
                                          'protected_pin': {'path': str(current_protected),
                                                            'sha256': pin(current_protected)}}})
    base.write(fresh / 'predecessor-guard.json', approved)
    plan['predecessor_guard_sha256'] = sha256(approved).hexdigest()
    base.write(fresh / 'plan.json', base.encode(plan))

    fixture.bundle, fixture.candidate, fixture.manifest = fresh, fresh / 'candidate', current
    fixture.environment['JSH_RELEASE_FIXTURE_BUNDLE'] = str(fresh)
    new_tool_pins = {name: pin(fresh / name) for name in base.TOOLS}
    fixture.assert_tool_bytes = lambda: assertions.assertEqual(
        {name: pin(fresh / name) for name in base.TOOLS}, new_tool_pins)
    fixture.assert_visible('before')
    installed = assertions.assert_receipt(fixture, fixture.run('install'), 'after')
    assert snapshot(initial) == predecessor
    assert exact.file_custody(fixture.project / exact.BRIDGE) == bridge
    assert gate.guard_identity(fixture.parked) == inherited
    fixture.candidate.rename(fresh / 'candidate-unavailable')
    rolled_back = assertions.assert_receipt(fixture, fixture.run('rollback'), 'before')
    assert snapshot(initial) == predecessor
    assert exact.file_custody(fixture.project / exact.BRIDGE) == bridge
    assert gate.guard_identity(fixture.parked) == inherited
    latest = Controller(fresh)
    latest.verify_released_source(latest.load(canonical=True))
    # The latest receipt owns restored inode custody. The historical receipt
    # still pins exact bytes and remains immutable.
    for name, endpoints in predecessor_manifest.items():
        base.source_bytes(fixture.project / name, endpoints['after'])
    assert snapshot(initial) == predecessor
    result = {'result': 'PASS_DISPOSABLE_SUCCESSOR_ONLY',
              'actual_predecessor_source_count': len(predecessor_manifest),
              'all_predecessor_after_bytes_restored': True,
              'current_rollback_source_verified': True,
              'historical_and_current_protected_pin_digests_differ': pin(protected) != pin(current_protected),
              'predecessor': [prior['phase'], prior['source']],
              'successor': [installed['phase'], installed['source']],
              'rollback': [rolled_back['phase'], rolled_back['source']],
              'successor_source_count': len(current), 'restored_absences': 10,
              'predecessor_artifacts_unchanged': len(predecessor),
              'inherited_import_guard_and_receipt_bridge_unchanged': True,
              'physical_site_exchange_continuity_services': 'SUBSTITUTED_FIXTURE'}
    base.write(ROOT / 'RESULT.json', base.encode(result))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
