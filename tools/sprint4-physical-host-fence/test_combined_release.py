"""Disposable acceptance harness for the Sprint 4 combined source controller."""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent
EARLIER = Path('/tmp/jsh-s4-scoped-release-rehearsal.lZ837nim')
QA = Path('/tmp/jsh-s4-dispatch-binding-qa.i45G33KN')
WRAPPER_BEFORE = (Path('/tmp/jsh-s4-combined-release-fixture.YsdYntjm/run.npy7t4ue')
                  / 'test_mixed_wrapper_fault_then_published_fault_reentry_and_payloadless_rollback.gp54lr2_'
                  / 'project')
TOOLS = ('controller.py', 'installer.py', 'gate.py', 'verify_hold')
WRAPPER = 'dev/wrapper-coder/tools'
WRAPPER_PATHS = tuple(f'{WRAPPER}/{name}' for name in (
    'coordinator_receipt_host_bridge.py', 'coordinator_store.py', 'host_server.py',
))
PARKED = '.s4-maintenance-package'
DROP_IN = 'zzzz-job-search-sprint4-maintenance.conf'
MANIFEST_SCHEMA = 'sprint-4-source-manifest-v1'
CONTROLLER_SCHEMA = 'sprint-4-controller-v1'
TRANSACTION_SCHEMA = 'sprint-4-transaction-v1'
HOLD_SCHEMA = 'sprint-4-hold-check-v1'
HOST_SCHEMA = 'sprint-4-host-check-v1'
CONTROL = None
ARTIFACTS = None
MARKER = 'integration-release-journal.json'
HOST_PATH = WRAPPER_PATHS[-1]
MISSING_PYTHON = {'absolute': 2, 'cwd_relative': 2}
UNITS = {
    'wrapper-development-host.service': {'active': True, 'enabled': 'enabled'},
    'job-search-sync.service': {'active': False, 'enabled': 'disabled'},
}

CONTROLLED_INTERRUPT = '''
import json
import os
from pathlib import Path
import signal
import sys

controller_path, cut, action = sys.argv[1:]
entry = Path(controller_path)
bundle = entry.parent
root = bundle.parent
assert root == Path(os.environ['JSH_COMBINED_FIXTURE_ROOT']).resolve()
assert entry == bundle.resolve() / 'controller.py'
sys.path.insert(0, str(bundle))
import controller

def record_cut(phase, host_absent):
    plan = json.loads((bundle / 'plan.json').read_bytes())
    project = Path(plan['project'])
    assert project == root / 'project'
    record = json.loads((bundle / 'controller.json').read_bytes())
    host = project / controller.installer.WRAPPER_HOST
    assert record['phase'] == phase and (not os.path.lexists(host)) == host_absent
    marker = project / '.state' / 'integration-release-journal.json'
    assert marker.exists() == (phase != 'RELEASE_REFUSED')
    with (root / 'atomic-faults.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps({'cut': cut, 'phase': phase, 'host_absent': host_absent}) + '\\n')
        stream.flush()
        os.fsync(stream.fileno())

def check_and_kill(phase, host_absent):
    record_cut(phase, host_absent)
    os.kill(os.getpid(), signal.SIGKILL)

if cut == 'close-intent-before-unlink':
    def close(*args, **kwargs):
        check_and_kill('CLOSING', False)
    controller.installer.close_host_path = close
elif cut == 'after-package-park-before-held':
    real_park = controller.gate.park
    def park(*args, **kwargs):
        real_park(*args, **kwargs)
        check_and_kill('CLOSING', True)
    controller.gate.park = park
elif cut in {'before-host-open', 'after-host-open'}:
    real_open = controller.installer.open_host_path
    def host_open(*args, **kwargs):
        if cut == 'after-host-open':
            real_open(*args, **kwargs)
        check_and_kill('HOST_REOPEN', cut == 'before-host-open')
    controller.installer.open_host_path = host_open
elif cut == 'refuse-after-host-open':
    real_open = controller.installer.open_host_path
    def host_open(*args, **kwargs):
        real_open(*args, **kwargs)
        record_cut('HOST_REOPEN', False)
        raise ValueError('fixture refusal after host atomically appeared')
    controller.installer.open_host_path = host_open
elif cut == 'after-release-refused-intent':
    real_save = controller.Controller.save
    def save(self, record, phase):
        real_save(self, record, phase)
        if phase == 'RELEASE_REFUSED':
            check_and_kill('RELEASE_REFUSED', False)
    controller.Controller.save = save
else:
    raise AssertionError(cut)

sys.argv = [controller_path, action]
controller.main()
'''


def encode(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()


def write(path, value, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)
    path.chmod(mode)


def source_bytes(path, expected):
    assert path.parent.resolve() == path.parent, path
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as stream:
        first = os.fstat(stream.fileno())
        assert stat.S_ISREG(first.st_mode) and first.st_nlink == 1, path
        data = stream.read()
        current = path.lstat()
        assert (first.st_dev, first.st_ino, first.st_mtime_ns, first.st_ctime_ns, first.st_size) == (
            current.st_dev, current.st_ino, current.st_mtime_ns, current.st_ctime_ns, current.st_size), path
    assert first.st_mode & 0o7777 == int(expected['mode'], 8), path
    assert sha256(data).hexdigest() == expected['sha256'], path
    return data


def pin(data, mode):
    return {'mode': mode, 'sha256': sha256(data).hexdigest()}


def endpoints():
    """Recover pinned earlier old images and freeze the specified newer QA after-images."""
    earlier = json.loads((EARLIER / 'source-inventory.json').read_bytes())
    old_fixture = EARLIER / 'fresh-namespace/project'
    manifest, before, after = {}, {}, {}
    source_changes = []
    for name, row in earlier['supported_endpoints'].items():
        previous = row['before']
        if previous is not None:
            before[name] = source_bytes(old_fixture / name, previous)
        else:
            assert not os.path.lexists(old_fixture / name), name
        path = QA / name
        actual = pin(path.read_bytes(), f'{path.stat().st_mode & 0o7777:04o}')
        after[name] = source_bytes(path, actual)
        if actual != row['after']:
            source_changes.append(name)
        manifest[name] = {'before': previous, 'after': actual, 'owner': [os.getuid(), os.getgid()]}
    for name in WRAPPER_PATHS:
        expected = earlier['outside_transaction'][name]
        previous = {k: v for k, v in expected['before'].items() if k != 'owner'}
        current = {k: v for k, v in expected['after'].items() if k != 'owner'}
        # Use the earlier combined fixture's restored before-images and reject
        # any divergence from their originally accepted pins.
        before[name] = source_bytes(WRAPPER_BEFORE / name, previous)
        after[name] = source_bytes(QA / name, current)
        manifest[name] = {'before': previous, 'after': current, 'owner': [os.getuid(), os.getgid()]}
    assert len(manifest) == 47
    assert set(source_changes) == {
        'src/job_search_helper/company_intake_dispatcher.py',
        'src/job_search_helper/ordinary_event_settlement.py',
    }, source_changes
    assert all(row['before'] != row['after'] for row in manifest.values())
    return manifest, before, after


def script(path, code):
    write(path, (f'#!{Path(sys.executable).resolve()} -I\n' + code).encode(), 0o700)


class Fixture:
    def __init__(self, test_name, controller_source, *, legacy=False):
        self.root = Path(tempfile.mkdtemp(prefix=test_name + '.', dir=ARTIFACTS))
        self.project = self.root / 'project'
        self.bundle = self.root / 'capsule'
        self.bundle.mkdir(mode=0o700)
        self.candidate = self.bundle / 'candidate'
        self.package = self.project / 'src/job_search_helper'
        self.parked = self.package.with_name(PARKED)
        self.wrapper = self.project / WRAPPER
        self.state = self.project / '.state'
        self.marker = self.state / MARKER
        self.unit_directory = self.root / 'units'
        self.fault = self.root / 'fixture-fault.json'
        self.hold = self.root / 'direct-admission-closed'
        self.fake_systemctl = self.root / 'fake-systemctl'
        self.manifest, before, after = endpoints()
        self.hold_id = 's4-combined-disposable-' + self.root.name
        for side, root, payloads in (('before', self.project, before), ('after', self.candidate, after)):
            for name, data in payloads.items():
                write(root / name, data, int(self.manifest[name][side]['mode'], 8))
        write(self.package / '__init__.py', b'OFFLINE_FIXTURE_ONLY = True\n')
        write(self.package / 'host_server.py', b'# same basename in package, preserve this file\n')
        write(self.wrapper / 'unrelated_runtime.py', b'# preserve this fourth wrapper endpoint\n')
        write(self.project / 'job-search-helper', b'# out-of-scope launcher witness\n', 0o755)
        write(self.project / '.storage-backend', b'sqlite\n')
        for previous in ('.s3-maintenance-package', '.f3-maintenance-package'):
            write(self.package.with_name(previous) / '__init__.py', b'# previous namespace witness\n')
        for name in ('state.db', 'jobs.sqlite3', 'inventories.sqlite3', 'retained-publication.lock',
                     'scraper.lock', 'writer.lock', 'review-writeback.lock'):
            write(self.state / name, f'opaque protected fixture {name}\n'.encode())
        write(self.project / '.integration-install.lock', b'opaque fixture install lock\n')
        for name in UNITS:
            write(self.unit_directory / name, b'fake unit file\n')
        write(self.unit_directory / 'job-search-sync.service.d/expiry.conf', b'keep expiry bytes\n')
        write(self.root / 'services.json', encode(UNITS))
        write(self.root / 'fixture-id', encode({'root': str(self.root), 'hold_id': self.hold_id, 'legacy': legacy}))
        for name in TOOLS:
            source = controller_source / name
            assert source.is_file() and not source.is_symlink(), source
            shutil.copy2(source, self.bundle / name)
        tool_witness = {name: sha256((self.bundle / name).read_bytes()).hexdigest() for name in TOOLS}
        write(self.root / 'tool-witness.json', encode(tool_witness))
        manifest_schema = 'sprint-3-source-manifest-v1' if legacy else MANIFEST_SCHEMA
        raw = encode({'schema': manifest_schema, 'paths': self.manifest})
        write(self.bundle / 'manifest.json', raw)
        write(self.bundle / 'plan.json', encode({
            'project': str(self.project), 'hold_id': self.hold_id, 'unit_directory': str(self.unit_directory),
            'systemctl': str(self.fake_systemctl), 'pycache_prefixes': [], 'manifest_sha256': sha256(raw).hexdigest(),
        }))
        for filename, entry in (('fake-systemctl', 'systemctl'), ('capsule/host-check', 'attest'),
                                ('route-probe', 'route_cli')):
            script(self.root / filename,
                   'from pathlib import Path\nimport sys\n'
                   'sys.dont_write_bytecode = True\n'
                   f'sys.path.insert(0, {str(ROOT)!r})\n'
                   f'from fixture_stubs import {entry}\n{entry}(Path(__file__).resolve())\n')
        (self.root / 'home').mkdir()
        self.environment = {'PATH': '/usr/bin:/bin', 'HOME': str(self.root / 'home'), 'TMPDIR': str(self.root),
                            'LC_ALL': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1',
                            'JSH_COMBINED_FIXTURE_ROOT': str(self.root)}
        self.package_inode = self.package.stat().st_ino
        self.witnesses = self.protected()

    def protected(self):
        paths = [
            self.package / '__init__.py', self.package / 'host_server.py', self.wrapper / 'unrelated_runtime.py',
            self.package.with_name('.s3-maintenance-package') / '__init__.py',
            self.package.with_name('.f3-maintenance-package') / '__init__.py',
            self.unit_directory / 'job-search-sync.service.d/expiry.conf',
            self.project / 'job-search-helper', self.project / '.storage-backend',
            self.project / '.integration-install.lock',
        ]
        paths += [self.state / name for name in ('state.db', 'jobs.sqlite3', 'inventories.sqlite3',
                                                'retained-publication.lock', 'scraper.lock', 'writer.lock',
                                                'review-writeback.lock')]
        return {str(path.relative_to(self.root)): (path.stat().st_ino, path.stat().st_mode,
                                                  sha256(path.read_bytes()).hexdigest()) for path in paths}

    def invoke(self, command, *args, timeout=120):
        result = subprocess.run([*command, *args], cwd=self.root, env=self.environment,
                                capture_output=True, text=True, timeout=timeout)
        with (self.root / 'invocations.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps({'command': [*command, *args], 'returncode': result.returncode,
                                     'stdout': result.stdout, 'stderr': result.stderr}) + '\n')
        return result

    def run(self, action, *, cut=None):
        command = [sys.executable, '-I', '-B']
        entry = str(self.bundle / 'controller.py')
        command += ['-c', CONTROLLED_INTERRUPT, entry, cut] if cut else [entry]
        return self.invoke(command, action)

    def probe(self, route, side):
        return self.invoke([str(self.root / 'route-probe')], route, side, timeout=10)

    def arm(self, stage):
        write(self.fault, encode({'stage': stage, 'action': 'install'}))

    def disarm(self):
        self.fault.unlink()

    def events(self):
        path = self.root / 'attestations.jsonl'
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def service_starts(self):
        path = self.root / 'routes.jsonl'
        return [row['side'] for line in path.read_text().splitlines()
                if (row := json.loads(line))['route'] == 'stub-service-start'] if path.exists() else []

    def assert_tool_bytes(self):
        witness = json.loads((self.root / 'tool-witness.json').read_bytes())
        assert all(sha256((self.bundle / name).read_bytes()).hexdigest() == digest
                   for name, digest in witness.items())

    def assert_visible(self, side):
        for name, row in self.manifest.items():
            path = self.project / name
            if row[side] is None:
                assert not os.path.lexists(path), path
            else:
                source_bytes(path, row[side])
                assert (path.stat().st_uid, path.stat().st_gid) == tuple(row['owner']), path
        assert self.package.stat().st_ino == self.package_inode
        assert self.protected() == self.witnesses
        assert not self.marker.exists() and not (self.package / '__init__.so').exists()
        assert json.loads((self.root / 'services.json').read_bytes()) == UNITS
        assert all(not (self.unit_directory / (name + '.d') / DROP_IN).exists() for name in UNITS)
        self.assert_tool_bytes()


class CombinedReleaseTests(unittest.TestCase):
    def fixture(self):
        return Fixture(self._testMethodName, CONTROL)

    def assert_holds(self, fixture, *, package_guard, host_absent=True, probe_direct=True):
        self.assertTrue(fixture.marker.is_file())
        self.assertTrue(fixture.hold.is_file())
        self.assertEqual(not os.path.lexists(fixture.project / HOST_PATH), host_absent)
        self.assertFalse(any(row['active'] for row in json.loads((fixture.root / 'services.json').read_bytes()).values()))
        for unit in UNITS:
            self.assertTrue((fixture.unit_directory / (unit + '.d') / DROP_IN).is_file())
        routes = ('worker', 'direct-wrapper', 'supervised-wrapper') if probe_direct else ('worker', 'supervised-wrapper')
        for route in routes:
            probe = fixture.probe(route, 'after')
            self.assertEqual(probe.returncode, 23, (probe.stdout, probe.stderr))
            if route == 'direct-wrapper' and host_absent:
                self.assertEqual(json.loads(probe.stdout), MISSING_PYTHON)
        if package_guard == 'parked':
            self.assertIn('raise ImportError', (fixture.package / '__init__.py').read_text())
        elif package_guard == 'published':
            self.assertEqual(b'', (fixture.package / '__init__.so').read_bytes())
        else:
            self.assertEqual(package_guard, 'admitted')
            self.assertFalse((fixture.package / '__init__.so').exists())
            self.assertEqual(fixture.package.stat().st_ino, fixture.package_inode)
        force = fixture.invoke([str(fixture.fake_systemctl)], '--user', 'start', 'wrapper-development-host.service')
        self.assertNotEqual(force.returncode, 0)
        self.assertIn('fixture unit condition held', force.stderr)

    def assert_receipt(self, fixture, reply, side):
        self.assertEqual(reply.returncode, 0, reply.stderr)
        value = json.loads(reply.stdout)
        expected = 'INSTALLED' if side == 'after' else 'ROLLED_BACK'
        self.assertEqual(value['phase'], 'RELEASED')
        self.assertEqual(value['source'], expected)
        receipt = value['receipt']
        self.assertEqual(receipt['phase'], expected)
        self.assertEqual(receipt['schema'], TRANSACTION_SCHEMA)
        self.assertIs(receipt['wrapper_host_fenced'], True)
        self.assertEqual(receipt['source_manifest_sha256'],
                         sha256((fixture.bundle / 'manifest.json').read_bytes()).hexdigest())
        directories = receipt['source_directories']
        self.assertIsInstance(directories, dict)
        self.assertTrue({'root', 'src', 'package', 'dev', 'wrapper', 'tools'} <= directories.keys())
        for name, path in {'root': fixture.project, 'src': fixture.package.parent, 'package': fixture.package,
                           'dev': fixture.project / 'dev', 'wrapper': fixture.wrapper.parent,
                           'tools': fixture.wrapper}.items():
            actual = path.stat()
            self.assertEqual(directories[name]['identity'], [actual.st_dev, actual.st_ino])
        self.assertEqual(len({row['mount'] for row in directories.values()}), 1)
        controller_record = json.loads((fixture.bundle / 'controller.json').read_bytes())
        self.assertEqual(controller_record['binding']['schema'], CONTROLLER_SCHEMA)
        fixture.assert_visible(side)
        return value

    def test_mixed_wrapper_fault_then_published_fault_reentry_and_payloadless_rollback(self):
        fixture = self.fixture()
        fixture.assert_visible('before')
        for route in ('worker', 'direct-wrapper', 'supervised-wrapper'):
            self.assertEqual(fixture.probe(route, 'before').returncode, 0)
        fixture.arm('after-one-wrapper')
        interrupted = fixture.run('install')
        self.assertNotEqual(interrupted.returncode, 0)
        interruptions = [row for row in fixture.events() if row.get('fault') == 'after-one-wrapper']
        self.assertEqual(len(interruptions), 1, interrupted.stderr)
        self.assertEqual(interruptions[0]['wrapper_after_count'], 1)
        changed = []
        for name in WRAPPER_PATHS:
            path = fixture.project / name
            if path.is_file() and sha256(path.read_bytes()).hexdigest() == fixture.manifest[name]['after']['sha256']:
                changed.append(name)
        self.assertEqual(len(changed), 1)
        self.assert_holds(fixture, package_guard='parked')
        self.assertFalse((fixture.root / 'unexpected-execution').exists())

        fixture.arm('after-package-publication')
        published = fixture.run('install')
        self.assertEqual(published.returncode, -9, (published.stdout, published.stderr))
        events = [row for row in fixture.events() if row.get('fault') == 'after-package-publication']
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['wrapper_after_count'], 2)
        self.assertTrue(events[0]['host_absent'])
        self.assert_holds(fixture, package_guard='published')
        self.assertFalse((fixture.root / 'unexpected-execution').exists())
        fixture.disarm()
        installed = self.assert_receipt(fixture, fixture.run('install'), 'after')
        self.assertEqual(installed, self.assert_receipt(fixture, fixture.run('install'), 'after'))
        fixture.hold.unlink()
        for route in ('worker', 'direct-wrapper', 'supervised-wrapper'):
            self.assertEqual(fixture.probe(route, 'after').returncode, 0)

        # Remove the exact candidate tree. Revert solely from durable held payloads.
        shutil.rmtree(fixture.candidate)
        cache = fixture.wrapper / '__pycache__'
        scoped_pycs = [cache / (Path(name).stem + '.cpython-311.pyc') for name in WRAPPER_PATHS]
        for path in scoped_pycs:
            write(path, b'stale scoped fixture bytecode')
        keep_cache = cache / 'unrelated_runtime.cpython-311.pyc'
        write(keep_cache, b'untouched fixture bytecode')
        rolled_back = self.assert_receipt(fixture, fixture.run('rollback'), 'before')
        self.assertEqual(rolled_back, self.assert_receipt(fixture, fixture.run('rollback'), 'before'))
        self.assertTrue(all(not path.exists() for path in scoped_pycs))
        self.assertEqual(keep_cache.read_bytes(), b'untouched fixture bytecode')
        fixture.hold.unlink()
        for route in ('worker', 'direct-wrapper', 'supervised-wrapper'):
            self.assertEqual(fixture.probe(route, 'before').returncode, 0)
        self.assertFalse((fixture.root / 'unexpected-execution').exists())

    def test_wrong_wrapper_directory_symlink_refused_without_source_writes(self):
        for side in ('project', 'candidate'):
            with self.subTest(side=side):
                fixture = self.fixture()
                root = fixture.project if side == 'project' else fixture.candidate
                directory = root / WRAPPER
                reference = directory.with_name('alias-target')
                directory.rename(reference)
                directory.symlink_to(reference, target_is_directory=True)
                witness = {p.name: p.read_bytes() for p in reference.iterdir()}
                reply = fixture.run('install')
                self.assertNotEqual(reply.returncode, 0)
                self.assertEqual({p.name: p.read_bytes() for p in reference.iterdir()}, witness)
                self.assertFalse(any(row.get('fault') for row in fixture.events()))
                for name, row in fixture.manifest.items():
                    if not name.startswith(WRAPPER):
                        path = fixture.project / name
                        if row['before'] is None:
                            self.assertFalse(os.path.lexists(path))
                        else:
                            source_bytes(path, row['before'])

    def test_reopened_wrapper_parent_inode_substitution_refused_under_hold(self):
        fixture = self.fixture()
        fixture.arm('after-one-wrapper')
        self.assertNotEqual(fixture.run('install').returncode, 0)
        self.assertTrue(any(row.get('fault') == 'after-one-wrapper' for row in fixture.events()))
        fixture.disarm()
        moved = fixture.wrapper.with_name('original-wrapper-tools')
        fixture.wrapper.rename(moved)
        shutil.copytree(moved, fixture.wrapper, copy_function=shutil.copy2)
        try:
            old_vector = {path.name: path.read_bytes() for path in moved.iterdir()}
            reply = fixture.run('install')
            self.assertNotEqual(reply.returncode, 0)
            self.assert_holds(fixture, package_guard='parked')
            self.assertEqual({path.name: path.read_bytes() for path in moved.iterdir()}, old_vector)
            self.assertEqual({path.name: path.read_bytes() for path in fixture.wrapper.iterdir()}, old_vector)
        finally:
            shutil.rmtree(fixture.wrapper)
            moved.rename(fixture.wrapper)

    def test_reopened_wrapper_ancestor_alias_refused_with_original_tools_inode(self):
        fixture = self.fixture()
        fixture.arm('after-one-wrapper')
        self.assertNotEqual(fixture.run('install').returncode, 0)
        self.assertTrue(any(row.get('fault') == 'after-one-wrapper' for row in fixture.events()))
        fixture.disarm()
        dev = fixture.project / 'dev'
        moved = dev.with_name('original-dev-ancestor')
        original_tools_inode = fixture.wrapper.stat().st_ino
        vector = {path.name: path.read_bytes() for path in fixture.wrapper.iterdir()}
        dev.rename(moved)
        dev.symlink_to(moved, target_is_directory=True)
        try:
            self.assertEqual(fixture.wrapper.stat().st_ino, original_tools_inode)
            reply = fixture.run('install')
            self.assertNotEqual(reply.returncode, 0)
            # The missing-file subprocess deliberately refuses aliased parents.
            self.assert_holds(fixture, package_guard='parked', probe_direct=False)
            self.assertEqual({path.name: path.read_bytes() for path in fixture.wrapper.iterdir()}, vector)
            self.assertEqual(fixture.service_starts(), [])
        finally:
            dev.unlink()
            moved.rename(dev)

    def test_endpoint_mount_mismatch_rejected_even_with_matching_file_bytes(self):
        fixture = self.fixture()
        script = '''
from pathlib import Path
import os
import sys
bundle, parent = map(Path, sys.argv[1:])
assert bundle.parent == parent.parents[3]
sys.path.insert(0, str(bundle))
import installer
with installer.directory(parent) as fd:
    good, _ = installer.read_file(fd, 'host_server.py')
    assert good == (parent / 'host_server.py').read_bytes()
    original_mount_id = installer.mount_id
    expected = parent / 'host_server.py'
    seen = []
    def mismatched_mount_id(opened):
        path = Path(os.readlink(f'/proc/self/fd/{opened}'))
        real = original_mount_id(opened)
        if path == expected:
            seen.append(path)
            return real + 1
        return real
    installer.mount_id = mismatched_mount_id
    try:
        installer.read_file(fd, 'host_server.py')
    except ValueError as exc:
        assert 'same-mount file' in str(exc), exc
    else:
        raise AssertionError('a physical endpoint mount mismatch was accepted')
    assert seen == [expected], seen
'''
        reply = fixture.invoke([sys.executable, '-I', '-B', '-c', script], str(fixture.bundle), str(fixture.wrapper))
        self.assertEqual(reply.returncode, 0, reply.stderr)
        fixture.assert_visible('before')

    def test_absolute_directory_open_refuses_same_inode_through_an_ancestor_alias(self):
        fixture = self.fixture()
        alias = fixture.root / 'project-alias'
        alias.symlink_to(fixture.project, target_is_directory=True)
        through_alias = alias / WRAPPER
        self.assertEqual(through_alias.stat().st_ino, fixture.wrapper.stat().st_ino)
        script = '''
from pathlib import Path
import sys
bundle, physical, alias = map(Path, sys.argv[1:])
assert bundle.parent == physical.parents[3] == alias.parents[3]
sys.path.insert(0, str(bundle))
import installer
with installer.directory(physical):
    pass
try:
    with installer.directory(alias):
        raise AssertionError('absolute directory opened through a symlink ancestor')
except OSError:
    pass
'''
        reply = fixture.invoke([sys.executable, '-I', '-B', '-c', script], str(fixture.bundle),
                               str(fixture.wrapper), str(through_alias))
        self.assertEqual(reply.returncode, 0, reply.stderr)
        fixture.assert_visible('before')

    def test_interrupted_after_restoration_replays_without_duplicate_service_start(self):
        fixture = self.fixture()
        fixture.arm('after-restoration-before-commit')
        interrupted = fixture.run('install')
        self.assertEqual(interrupted.returncode, -9, (interrupted.stdout, interrupted.stderr))
        journal = fixture.bundle / 'controller.json'
        self.assertEqual(json.loads(journal.read_bytes())['phase'], 'RELEASING')
        self.assertFalse(fixture.marker.exists())
        self.assertTrue(fixture.hold.is_file())
        interrupted_callbacks = [row for row in fixture.events() if row['checkpoint'] in {'restoring', 'restored'}]
        self.assertEqual([(row['checkpoint'], row['marker_present'], row['wrapper_active'])
                          for row in interrupted_callbacks], [('restoring', True, False), ('restored', False, True)])
        self.assertEqual(interrupted_callbacks[-1]['fault'], 'after-restoration-before-commit')
        self.assertEqual(fixture.service_starts(), ['after'])
        for route in ('worker', 'direct-wrapper', 'supervised-wrapper'):
            self.assertEqual(fixture.probe(route, 'after').returncode, 23)

        refused_direction = fixture.run('rollback')
        self.assertNotEqual(refused_direction.returncode, 0)
        self.assertIn('Finish the recorded release', refused_direction.stderr)
        self.assertEqual(fixture.service_starts(), ['after'])
        fixture.disarm()
        result = self.assert_receipt(fixture, fixture.run('install'), 'after')
        callbacks = [row for row in fixture.events() if row['checkpoint'] in {'restoring', 'restored'}]
        self.assertEqual([(row['checkpoint'], row['marker_present'], row['wrapper_active']) for row in callbacks[-2:]],
                         [('restoring', False, True), ('restored', False, True)])
        self.assertEqual(len({row['nonce'] for row in callbacks}), 4)
        self.assertEqual(fixture.service_starts(), ['after'])
        self.assertEqual(result, self.assert_receipt(fixture, fixture.run('install'), 'after'))

    def test_physical_host_absence_through_persisted_close_and_reopen_interruptions(self):
        fixture = self.fixture()
        host = fixture.project / HOST_PATH
        journal = fixture.bundle / 'controller.json'
        record = lambda: json.loads(journal.read_bytes())
        after_intent = fixture.run('install', cut='close-intent-before-unlink')
        self.assertEqual(after_intent.returncode, -9, after_intent.stderr)
        self.assertEqual(record()['phase'], 'CLOSING')
        source_bytes(host, fixture.manifest[HOST_PATH]['before'])
        self.assert_holds(fixture, package_guard='admitted', host_absent=False)

        fixture.arm('after-host-absence')
        absent = fixture.run('install')
        self.assertEqual(absent.returncode, -9, absent.stderr)
        self.assertEqual(record()['phase'], 'CLOSING')
        self.assert_holds(fixture, package_guard='admitted')
        closure = fixture.events()[-1]
        self.assertEqual(closure['checkpoint'], 'host-fenced')
        self.assertEqual(closure['package_name'], 'job_search_helper')
        self.assertEqual(closure['missing_python'], MISSING_PYTHON)
        self.assertEqual(closure['fault'], 'after-host-absence')
        fixture.disarm()

        parked = fixture.run('install', cut='after-package-park-before-held')
        self.assertEqual(parked.returncode, -9, parked.stderr)
        self.assertEqual(record()['phase'], 'CLOSING')
        self.assert_holds(fixture, package_guard='parked')

        before_open = fixture.run('install', cut='before-host-open')
        self.assertEqual(before_open.returncode, -9, before_open.stderr)
        self.assertEqual(record()['phase'], 'HOST_REOPEN')
        self.assert_holds(fixture, package_guard='admitted')
        reopens = [event for event in fixture.events() if event['checkpoint'] == 'before-host-reopen']
        self.assertTrue(reopens)
        self.assertEqual(reopens[-1]['phase'], 'HOST_REOPEN')
        self.assertEqual(reopens[-1]['missing_python'], MISSING_PYTHON)
        self.assertTrue(any(event['checkpoint'] == 'host-fenced' and event['package_name'] == PARKED
                            and event['missing_python'] == MISSING_PYTHON for event in fixture.events()))

        after_open = fixture.run('install', cut='after-host-open')
        self.assertEqual(after_open.returncode, -9, after_open.stderr)
        self.assertEqual(record()['phase'], 'HOST_REOPEN')
        self.assert_holds(fixture, package_guard='admitted', host_absent=False)
        source_bytes(host, fixture.manifest[HOST_PATH]['after'])
        opened_identity = (host.stat().st_dev, host.stat().st_ino, host.stat().st_ctime_ns)
        reopen_calls = len([event for event in fixture.events() if event['checkpoint'] == 'before-host-reopen'])

        self.assert_receipt(fixture, fixture.run('install'), 'after')
        self.assertEqual((host.stat().st_dev, host.stat().st_ino, host.stat().st_ctime_ns), opened_identity)
        self.assertEqual(len([event for event in fixture.events() if event['checkpoint'] == 'before-host-reopen']),
                         reopen_calls)
        self.assertEqual(fixture.service_starts(), ['after'])
        self.assertFalse((fixture.root / 'unexpected-execution').exists())

    def test_restored_attestation_refusal_reinstates_marker_and_unit_holds(self):
        fixture = self.fixture()
        fixture.arm('refuse-restored-host')
        refusal = fixture.run('install')
        self.assertNotEqual(refusal.returncode, 0)
        self.assertIn('fixture restored host attestation refused', refusal.stderr)
        self.assertEqual(json.loads((fixture.bundle / 'controller.json').read_bytes())['phase'], 'RELEASE_REFUSED')
        self.assertEqual(json.loads(fixture.marker.read_bytes()), {
            'maintenance_id': fixture.hold_id, 'schema': 'integration-release-journal-v1',
            'state': 'FOUNDATION_MAINTENANCE',
        })
        self.assertTrue((fixture.bundle / 'service-hold').is_file())
        self.assert_holds(fixture, package_guard='admitted')
        self.assertEqual(fixture.service_starts(), ['after'])
        refusal_event, refenced = fixture.events()[-2:]
        self.assertEqual(refusal_event['fault'], 'refuse-restored-host')
        self.assertTrue(refusal_event['wrapper_active'])
        self.assertEqual(refenced['checkpoint'], 'host-fenced')
        self.assertEqual(refenced['phase'], 'RELEASE_REFUSED')
        self.assertEqual(refenced['missing_python'], MISSING_PYTHON)

        fixture.disarm()
        self.assert_receipt(fixture, fixture.run('install'), 'after')
        callbacks = [row for row in fixture.events() if row['checkpoint'] in {'restoring', 'restored'}]
        self.assertEqual([(row['checkpoint'], row['marker_present'], row['wrapper_active']) for row in callbacks[-2:]],
                         [('restoring', True, False), ('restored', False, True)])
        self.assertEqual(fixture.service_starts(), ['after', 'after'])

    def test_persisted_release_refusal_resumes_holds_before_allowing_reopen(self):
        fixture = self.fixture()
        fixture.arm('refuse-restored-host')
        interruption = fixture.run('install', cut='after-release-refused-intent')
        self.assertEqual(interruption.returncode, -9, interruption.stderr)
        journal = fixture.bundle / 'controller.json'
        self.assertEqual(json.loads(journal.read_bytes())['phase'], 'RELEASE_REFUSED')
        self.assertFalse(fixture.marker.exists())
        source_bytes(fixture.project / HOST_PATH, fixture.manifest[HOST_PATH]['after'])
        self.assertEqual(fixture.service_starts(), ['after'])
        fixture.arm('interrupt-refusal-rehold')
        recovery = fixture.run('install')
        self.assertEqual(recovery.returncode, -9, recovery.stderr)
        self.assertEqual(json.loads(journal.read_bytes())['phase'], 'RELEASE_REFUSED')
        self.assert_holds(fixture, package_guard='admitted')
        self.assertEqual(fixture.events()[-1]['missing_python'], MISSING_PYTHON)
        self.assertEqual(fixture.service_starts(), ['after'])

        fixture.disarm()
        self.assert_receipt(fixture, fixture.run('install'), 'after')
        self.assertEqual(fixture.service_starts(), ['after', 'after'])

    def test_payloadless_rollback_after_refusal_or_unfinished_host_reopen(self):
        for reason in ('restored-refusal', 'host-reopen'):
            with self.subTest(reason=reason):
                fixture = self.fixture()
                journal = fixture.bundle / 'controller.json'
                if reason == 'restored-refusal':
                    fixture.arm('refuse-restored-host')
                    failure = fixture.run('install')
                    self.assertNotEqual(failure.returncode, 0)
                    self.assertIn('fixture restored host attestation refused', failure.stderr)
                    self.assertEqual(json.loads(journal.read_bytes())['phase'], 'RELEASE_REFUSED')
                    fixture.disarm()
                    self.assert_holds(fixture, package_guard='admitted')
                    prior_start = ['after']
                else:
                    interruption = fixture.run('install', cut='after-host-open')
                    self.assertEqual(interruption.returncode, -9, interruption.stderr)
                    self.assertEqual(json.loads(journal.read_bytes())['phase'], 'HOST_REOPEN')
                    prior_start = []
                    self.assert_holds(fixture, package_guard='admitted', host_absent=False)
                self.assertEqual(fixture.service_starts(), prior_start)
                shutil.rmtree(fixture.candidate)
                rollback = self.assert_receipt(fixture, fixture.run('rollback'), 'before')
                self.assertEqual(rollback, self.assert_receipt(fixture, fixture.run('rollback'), 'before'))
                self.assertEqual(fixture.service_starts(), [*prior_start, 'before'])
                self.assertTrue(any(row['checkpoint'] == 'host-fenced' and row['phase'] == 'RELEASE_REFUSED'
                                    and row['missing_python'] == MISSING_PYTHON for row in fixture.events()))
                self.assertFalse((fixture.root / 'unexpected-execution').exists())

    def test_post_open_refusal_reestablishes_physical_absence_before_next_command(self):
        fixture = self.fixture()
        failure = fixture.run('install', cut='refuse-after-host-open')
        self.assertNotEqual(failure.returncode, 0)
        self.assertIn('fixture refusal after host atomically appeared', failure.stderr)
        self.assertEqual(json.loads((fixture.bundle / 'controller.json').read_bytes())['phase'], 'RELEASE_REFUSED')
        self.assert_holds(fixture, package_guard='admitted')
        self.assertEqual(fixture.service_starts(), [])
        observed = json.loads((fixture.root / 'atomic-faults.jsonl').read_text())
        self.assertEqual(observed, {'cut': 'refuse-after-host-open', 'phase': 'HOST_REOPEN', 'host_absent': False})
        self.assertEqual(fixture.events()[-1]['missing_python'], MISSING_PYTHON)
        self.assert_receipt(fixture, fixture.run('install'), 'after')
        self.assertEqual(fixture.service_starts(), ['after'])

    def test_occupied_new_namespace_refused_and_previous_names_preserved(self):
        fixture = self.fixture()
        occupant = fixture.parked / '__init__.py'
        write(occupant, b'foreign namespace occupant\n')
        reply = fixture.run('install')
        self.assertNotEqual(reply.returncode, 0)
        fixture.assert_visible('before')
        self.assertEqual(occupant.read_bytes(), b'foreign namespace occupant\n')
        self.assertFalse((fixture.bundle / 'controller.json').exists())

    def test_missing_realistic_direct_fence_refuses_preflight(self):
        fixture = self.fixture()
        write(fixture.root / 'disable-direct-fence', b'explicit stub refusal\n')
        reply = fixture.run('install')
        self.assertNotEqual(reply.returncode, 0)
        self.assertIn('direct route cannot be durably closed', reply.stderr)
        fixture.assert_visible('before')


def main():
    global CONTROL, ARTIFACTS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--controller-source', type=Path, required=True)
    parser.add_argument('--legacy-negative-control', action='store_true')
    parser.add_argument('tests', nargs='*', metavar='TEST')
    args = parser.parse_args()
    assert ROOT.parent == Path('/tmp') and ROOT.name.startswith('jsh-s4-combined-release-fixture.')
    source = args.controller_source.resolve(strict=True)
    ARTIFACTS = Path(tempfile.mkdtemp(prefix='run.', dir=ROOT))
    CONTROL = ARTIFACTS / 'frozen-tool-input'
    CONTROL.mkdir(mode=0o700)
    tool_pins = {}
    for name in TOOLS:
        path = source / name
        expected = pin(path.read_bytes(), f'{path.stat().st_mode & 0o7777:04o}')
        write(CONTROL / name, source_bytes(path, expected), int(expected['mode'], 8))
        tool_pins[name] = expected
    write(ARTIFACTS / 'frozen-tool-input.json', encode(tool_pins))
    print(f'Fixture evidence: {ARTIFACTS}', flush=True)
    if args.legacy_negative_control:
        fixture = Fixture('legacy', CONTROL, legacy=True)
        fixture.assert_visible('before')
        for route in ('worker', 'direct-wrapper', 'supervised-wrapper'):
            assert fixture.probe(route, 'before').returncode == 0
        refused = fixture.run('install')
        assert refused.returncode and 'outside the allowed scope' in refused.stderr, refused
        fixture.assert_visible('before')
        assert not fixture.events()
        print('Legacy control refused real wrapper scope before writes; original pair remained available.')
        return
    names = [f'CombinedReleaseTests.{name}' for name in args.tests]
    unittest.main(argv=[__file__, '-v', *names])


if __name__ == '__main__':
    main()
