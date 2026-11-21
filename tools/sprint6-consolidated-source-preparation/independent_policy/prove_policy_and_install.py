"""Check exact policy and exercise the real installer only in a disposable fence."""
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
from tempfile import mkdtemp

BASE = Path(__file__).resolve().parent
STAGE = Path('/tmp/jsh-s6-maintenance-source-policy.20261121')
PREVIOUS = Path('/tmp/jsh-consolidated-installer-gate-independent.EMP9isny')
FROZEN = Path('/tmp/jsh-consolidated-scope.20261121/RESULT.json')
FREEFORM = 'a1863753a251058e1cd99266568aef3b6e9b3076e49c52dd0adff11d93f6a163'
INSTALLER_PIN = '1cf49bd23e2e82f5ce10f7e7af37f80ff8b534ebb5d5048dbca1565bf00464b4'
CONTROLLER_PIN = '75f8622a5410b7189f43b57353bca8bd3cab83459757038bfb55087d0b87157d'
SCOPE_PIN = '09e871ceb0cc91685461294abef1651766cbebcb52b5655a63940fde74db13e3'
BRIDGE = 'dev/wrapper-coder/tools/coordinator_receipt_host_bridge.py'
HOLD_ID = 'independent-synthetic-exact-paths'


def sha(data):
    return sha256(data).hexdigest()


def write(path, raw, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    path.chmod(mode)


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result


def main():
    assert sha((STAGE / 'installer.py').read_bytes()) == INSTALLER_PIN
    assert sha((STAGE / 'controller.py').read_bytes()) == CONTROLLER_PIN
    assert sha(FROZEN.read_bytes()) == SCOPE_PIN
    original = PREVIOUS / 'accepted_freeform_manifest.json'
    root = Path(mkdtemp(prefix='transaction-', dir=BASE))
    print(root, flush=True)
    for name in ('installer.py', 'gate.py'):
        shutil.copy2(STAGE / name, root / name)
    tool = module(root / 'installer.py', 'installer')
    gate = module(root / 'gate.py', 'gate')
    old = module(PREVIOUS / 'accepted_freeform_installer.py', 'accepted_freeform')
    a, b = old.load_manifest(original, FREEFORM), tool.load_manifest(original, FREEFORM)
    assert len(a.paths) == 47 and (a.before, a.after, a.owners) == (b.before, b.after, b.owners)
    exact = json.loads((PREVIOUS / 'consolidated_exact_38_manifest.json').read_bytes())
    frozen = json.loads(FROZEN.read_bytes())
    for name, item in frozen['paths'].items():
        assert exact['paths'][name] == {'before': None if item['before'] is None else
            {k: item['before'][k] for k in ('mode','sha256')},
            'after': {k: item['after'][k] for k in ('mode','sha256')}, 'owner': item['after']['owner']}
    exact['schema'] = tool.CONSOLIDATED_SCHEMA
    exact_raw = tool.encode(exact)
    exact_path = root / 'exact-38-metadata.json'
    write(exact_path, exact_raw)
    parsed = tool.load_manifest(exact_path, sha(exact_raw))
    assert set(parsed.paths) == set(frozen['paths']) == tool.CONSOLIDATED_PATHS and len(parsed.paths) == 38
    assert BRIDGE not in parsed.paths
    refusals = {}
    examples = {
        'expanded paths in v1': {**exact, 'schema': 'sprint-4-source-manifest-v1'},
        'protected bridge in v2': {**exact, 'paths': {**exact['paths'], BRIDGE: {'before': None}}},
        'missing reviewed path': {**exact, 'paths': {k: v for k, v in exact['paths'].items() if k != 'job-search-scraper'}},
        'missing existing store': {**exact, 'paths': {**exact['paths'],
            'dev/wrapper-coder/tools/coordinator_store.py': {**exact['paths']['dev/wrapper-coder/tools/coordinator_store.py'],
                                                             'before': None}}},
    }
    for label, value in examples.items():
        path = root / 'parser-negative.json'
        raw = tool.encode(value)
        write(path, raw)
        try:
            tool.load_manifest(path, sha(raw))
        except ValueError as exc:
            refusals[label] = str(exc)
        else:
            raise AssertionError(label)

    project, candidate, tx, sealed = [root / p for p in ('project', 'candidate', 'tx', 'sealed')]
    tx.mkdir(mode=0o700)
    sealed.mkdir(mode=0o700)
    pairs, original_bytes = {}, {}
    real_candidate = Path(frozen['candidate'])
    for name, q in exact['paths'].items():
        source = real_candidate / name
        after = source.read_bytes()
        assert sha(after) == q['after']['sha256']
        write(candidate / name, after, int(q['after']['mode'], 8))
        before = None
        if q['before'] is not None:
            raw = f'# private fixture before {name}\n'.encode()
            before = {**q['before'], 'sha256': sha(raw)}
            original_bytes[name] = raw
            write(project / name, raw, int(before['mode'], 8))
        pairs[name] = {**q, 'before': before, 'owner': [os.getuid(), os.getgid()]}
    fixture_manifest = tool.encode({'schema': tool.CONSOLIDATED_SCHEMA, 'paths': pairs})
    manifest = root / 'fixture-manifest.json'
    write(manifest, fixture_manifest)
    fixture = tool.load_manifest(manifest, sha(fixture_manifest))
    bridge = project / BRIDGE
    write(bridge, b'# protected receipt bridge scratch witness\n')
    bridge_before = bridge.stat().st_ino, bridge.stat().st_mode, sha(bridge.read_bytes())
    guard = project / 'src/job_search_helper'
    write(guard / '__init__.py', b'# original unscoped package initializer\n')
    original_inode = guard.stat().st_ino
    lock = root / 'installer.lock'
    write(lock, b'')
    marker = project / '.state/integration-release-journal.json'
    write(marker, tool.encode({'schema': 'integration-release-journal-v1', 'state': 'FOUNDATION_MAINTENANCE',
                              'maintenance_id': HOLD_ID}))
    verifier = root / 'fixture-verifier'
    verifier_code = f'''#!{sys.executable} -I
from pathlib import Path
import fcntl, hashlib, json, os, sys
root = Path({str(root)!r})
raw = json.load(sys.stdin)
assert set(raw) == {{'schema','project','state','gate','marker','maintenance_id','source_manifest_sha256','checkpoint','nonce'}}
assert raw['schema'] == 'sprint-4-hold-check-v1' and raw['maintenance_id'] == {HOLD_ID!r}
assert raw['source_manifest_sha256'] == {sha(fixture_manifest)!r}
for key, suffix in (('project','project'),('gate','installer.lock'),('state','tx'),('marker','project/.state/integration-release-journal.json')):
    assert Path(raw[key]) == root / suffix
assert len(raw['nonce']) == 32
assert not (root / 'project/dev/wrapper-coder/tools/host_server.py').exists()
assert (root / 'project/src/job_search_helper/__init__.py').read_bytes() == {gate.MESSAGE!r}
assert (root / 'project/src/.s4-maintenance-package').stat().st_ino == {original_inode}
assert json.loads(Path(raw['marker']).read_text())['state'] == 'FOUNDATION_MAINTENANCE'
with open(raw['gate'], 'rb') as lock:
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        pass
    else:
        raise AssertionError('Installer did not own the fixture gate')
with (root / 'fixture-verified.jsonl').open('a') as output:
    output.write(json.dumps(raw['checkpoint']) + chr(10))
print(json.dumps({{**raw, 'verified': True}}))
'''
    write(verifier, verifier_code.encode(), 0o700)
    host = tool.WRAPPER_HOST
    owner = fixture.owners[host]
    with tool.directory(sealed) as sealed_fd:
        tool.seal_host_image(sealed_fd, 'before', original_bytes[host], fixture.before[host])
        tool.seal_host_image(sealed_fd, 'after', (candidate / host).read_bytes(), fixture.after[host])
    gate.park(project, original_inode)
    wrapper_dir = (project / host).parent
    wrapper_ident = wrapper_dir.stat().st_dev, wrapper_dir.stat().st_ino

    def prove_parent():
        st = wrapper_dir.stat()
        assert (st.st_dev, st.st_ino) == wrapper_ident

    def close_host(side):
        with tool.directory(wrapper_dir) as parent:
            tool.close_host_path(parent, getattr(fixture, side)[host], owner, prove_parent)

    def open_host(side):
        with tool.directory(sealed) as archive, tool.directory(wrapper_dir) as parent:
            tool.open_host_path(archive, parent, side, getattr(fixture, side)[host], owner, prove_parent)

    def invoke(action, *extra):
        inputs = {'project': project, 'state': tx, 'gate': lock, 'marker': marker,
                  'verifier': verifier, 'manifest': manifest, 'hold-id': HOLD_ID,
                  'manifest-sha256': sha(fixture_manifest)}
        argv = [sys.executable, '-I', '-B', str(root / 'installer.py'), action, '--parked-package', '--fenced-host']
        for key, value in inputs.items():
            argv.extend(('--' + key, str(value)))
        result = subprocess.run([*argv, *extra], cwd=root, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0 and not result.stderr, (action, result.stdout, result.stderr)
        return json.loads(result.stdout)

    def endpoints(side):
        with tool.source_tree(project, True) as tree:
            measured = {path: tool.optional_version(tool.read_optional(*tool.entry(tree, path))) for path in fixture.paths}
            assert measured == getattr(fixture, side)
            for path in fixture.paths:
                item = tool.read_optional(*tool.entry(tree, path))
                assert item is None or tool.ownership(item[1]) == fixture.owners[path]
        assert bridge_before == (bridge.stat().st_ino, bridge.stat().st_mode, sha(bridge.read_bytes()))

    close_host('before')
    installed = invoke('install', '--candidate', str(candidate))
    assert installed['phase'] == 'INSTALLED' and installed == invoke('verify')
    assert not (project / host).exists()
    open_host('after')
    endpoints('after')
    close_host('after')
    candidate.rename(root / 'no-longer-addressable-candidate')
    rolled_back = invoke('rollback')
    assert rolled_back['phase'] == 'ROLLED_BACK' and rolled_back == invoke('verify')
    assert not (project / host).exists()
    open_host('before')
    endpoints('before')
    gate.publish(project, original_inode)
    assert guard.stat().st_ino == original_inode and marker.exists()
    count = len((root / 'fixture-verified.jsonl').read_text().splitlines())
    result = {'result': 'ACCEPT_PARSER_AND_DISPOSABLE_INSTALL_ROLLBACK', 'exact_38_metadata_sha256': sha(exact_raw),
              'fixture_manifest_sha256': sha(fixture_manifest), 'parsed_paths': len(parsed.paths),
              'unchanged_freeform_v1_paths': len(a.paths), 'refused': refusals,
              'installed_phase': installed['phase'], 'rollback_phase': rolled_back['phase'],
              'verified_hold_checkpoints': count, 'candidate_absent_on_rollback': True,
              'all_exact_candidate_after_images_verified': True, 'synthetic_original_images': True,
              'before_posts_and_original_ten_absences_restored': True, 'protected_bridge_inode_mode_bytes_preserved': True,
              'actual_native_controller_or_observer_executed': False}
    (root / 'RESULT.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
