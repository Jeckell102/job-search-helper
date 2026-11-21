"""Disposable SQLite/thread integration for the exact restored-only checker.

Run with /usr/bin/python3 -I -B. No application, service or network entry runs.
Only the outer native process/unit/listener observations are fixture substitutes.
"""

from contextlib import ExitStack, closing, contextmanager
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import queue
import sqlite3
import sys
import threading
import time as wall_time
from types import SimpleNamespace
import unittest
from unittest.mock import patch


CHECKER = Path('/tmp/jsh-s4-restored-witness.KT8wKPcI')
SUPERVISION = Path('/tmp/job-search-helper-integration-automation/temp/integration-coordinator/tools/coordinator_supervision.py')
sys.path.insert(0, str(CHECKER))
import host_check_main as entry
import host_checkpoint as checkpoint
import protected_continuity as continuity
import protected_state as protected
from alternate_writer_witness import CoverPin
import test_protected_state as state_fixtures

spec = importlib.util.spec_from_file_location('fixture_coordinator_supervision', SUPERVISION)
supervision_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(supervision_module)

SOURCE_PINS = {
    'host_check_main.py': '562c0cd36119f0575f9b87f3ec5a59287ebcb35ff479b8b06df751061a220ab9',
    'host_checkpoint.py': 'fe5ac8bed3ab1e88ff645859ba6f156229694643d3b3549415748c8952016e43',
    'protected_state.py': '9c317392293dd245fab3a73c24a4075d9f65ca5b4fe53378f35df710dce446e3',
    'protected_continuity.py': '66b8334311cb2fd593947548ff47137bb0fa9a6a3b408d6b2d7b0da31af0e9ca',
    'physical_protected_witness.py': '546b4fdee2b2768ff01086e8dc962408563c83657d68fe736220a8f14fcc4201',
    'test_protected_state.py': '042074ae118ae3d19786065d5c30e759e3e70657756ea1660335c3a304c6e564',
}


def artifact_state(path):
    result = {}
    for suffix in ('', '-wal', '-shm', '-journal'):
        member = Path(str(path) + suffix)
        try:
            info = member.stat()
        except FileNotFoundError:
            result[suffix or 'database'] = None
        else:
            result[suffix or 'database'] = (
                info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns,
            )
    return result


class FixtureStore:
    """Same connect-through-close SQLite lifetime as the reviewed Store seam."""

    def __init__(self, path):
        self.path = path
        self.base = path.parent
        self.observed = []

    @contextmanager
    def connect(self):
        before = artifact_state(self.path)
        db = sqlite3.connect(self.path, timeout=2)
        db.execute('PRAGMA synchronous=FULL')
        try:
            with db:
                yield db
                during = artifact_state(self.path)
        finally:
            db.close()
            self.observed.append((before, during, artifact_state(self.path)))


class AsyncStartup:
    """Real Supervision.start thread; deterministic scheduling replaces wall sleeps."""

    def __init__(self, stores, *, after_tick=None):
        self.stores = stores
        self.commands = queue.Queue()
        self.completed = queue.Queue()
        self.observations = []
        self.ticks = 0
        self.after_tick = after_tick
        self.store = FixtureStore(stores['coordinator'])
        self.retention_observations = []

        def retention():
            before = {role: artifact_state(stores[role]) for role in ('jobs', 'inbox')}
            result = supervision_module.external_retention_snapshot(
                stores['jobs'], company_consumer='fixture-company', outcome_consumer='fixture-outcome',
            )
            after = {role: artifact_state(stores[role]) for role in ('jobs', 'inbox')}
            self.retention_observations.append((before, after))
            return result

        coordinator = SimpleNamespace(store=self.store, wake=threading.Event())
        self.supervision = supervision_module.CoordinatorSupervision(
            coordinator, lambda: {'observed': 0},
            disk_usage=lambda _: SimpleNamespace(free=10**12, total=2 * 10**12),
            retention_probe=retention, clock=lambda: float(self.ticks + 1),
        )
        actual_tick = self.supervision.tick

        def tick():
            command = self.commands.get(timeout=5)
            if command == 'stop':
                return
            try:
                before = {role: artifact_state(path) for role, path in stores.items()}
                result = actual_tick()
                self.ticks += 1
                if self.after_tick is not None:
                    self.after_tick(self.ticks)
                after = {role: artifact_state(path) for role, path in stores.items()}
                self.observations.append((before, after))
                self.completed.put(result)
            except BaseException as exc:
                self.completed.put(exc)

        self.supervision.tick = tick
        self.supervision.start(interval=0)

    def step(self):
        self.commands.put('tick')
        result = self.completed.get(timeout=5)
        if isinstance(result, BaseException):
            raise result
        if result['state'] != 'ACTIVE' or result['retention'].get('external_probe_error'):
            raise AssertionError(result)

    def close(self):
        self.supervision.stop.set()
        self.commands.put('stop')
        self.supervision.thread.join(5)
        if self.supervision.thread.is_alive():
            raise AssertionError('Fixture supervision did not stop')


class VirtualTime:
    """Advance the checker's real deadline arithmetic while a worker does real IO."""

    def __init__(self, startup, steps):
        self.startup = startup
        self.steps = steps
        self.elapsed = 0.0
        self.sleeps = 0

    def monotonic(self):
        return self.elapsed

    def sleep(self, delay):
        self.sleeps += 1
        if self.steps is None or self.startup.ticks < self.steps:
            self.startup.step()
        self.elapsed += delay


class RealTimeStartup:
    """Real 1.5-second checker waits while startup ticks independently."""

    def __init__(self, startup):
        self.begin = threading.Event()
        self.done = threading.Event()
        self.error = None

        def run():
            try:
                if not self.begin.wait(5):
                    raise AssertionError('No real checker sleep occurred')
                for _ in range(3):
                    startup.step()
                    self.done.wait(0.05)
            except BaseException as exc:
                self.error = exc
            finally:
                self.done.set()

        self.thread = threading.Thread(target=run, name='fixture-async-startup', daemon=True)
        self.thread.start()

    def monotonic(self):
        return wall_time.monotonic()

    def sleep(self, delay):
        self.begin.set()
        wall_time.sleep(delay)

    def close(self):
        self.begin.set()
        self.thread.join(5)
        if self.thread.is_alive():
            raise AssertionError('Real startup fixture did not finish')
        if self.error is not None:
            raise self.error


class RealisticReadinessTests(unittest.TestCase):
    def setUp(self):
        self.assertEqual({name: sha256((CHECKER / name).read_bytes()).hexdigest()
                          for name in SOURCE_PINS}, SOURCE_PINS)
        self.saved = state_fixtures.ProtectedWitnessTests()
        self.saved.setUp()
        self.addCleanup(self.saved.doCleanups)
        self.root = self.saved.root
        self.paths = self.saved.dbpaths
        # Add only schema needed by the real retention query, before the original pin.
        self.saved.sql('jobs', 'ALTER TABLE company_event_outbox ADD COLUMN event_id TEXT')
        self.saved.sql('jobs', 'ALTER TABLE company_event_deliveries ADD COLUMN event_id TEXT')
        self.saved.sql('jobs', 'ALTER TABLE company_event_deliveries ADD COLUMN consumer TEXT')
        self.saved.sql('inbox', 'ALTER TABLE publication_receipts ADD COLUMN state TEXT')
        # Set all actual fixture stores to WAL and close each writer before pinning.
        for role in ('jobs', 'inbox', 'coordinator'):
            with closing(sqlite3.connect(self.paths[role])) as db:
                self.assertEqual(db.execute('PRAGMA journal_mode=WAL').fetchone(), ('wal',))
        self.saved.seal()
        self.original_pin = self.saved.pin.read_bytes()
        self.owner = ('fixture-boot', 9191, 'fixture-controller-start')
        self.attempts = []
        self.boundaries = []
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(supervision_module, 'support_matrix', lambda: {
            'automatic_profiles': [], 'engineering_review': 'all unmatched capabilities',
        }))
        # Never invoke the real platform/service/network observers.
        for name, action in (
            ('verify_cover', lambda *_: self.boundaries.append('cover')),
            ('verify_listener', lambda *_: self.boundaries.append('listener') or {83}),
            ('verify_route_drain', lambda *_: self.boundaries.append('routes')),
            ('verify_wrapper_process', lambda *_: self.boundaries.append('process') or 'fixture-start'),
            ('authenticated_maintenance', lambda *_: {9191: ('fixture-controller-start', 'controller.py')}),
        ):
            self.stack.enter_context(patch.object(checkpoint, name, action))

    def site(self, target):
        wrapper = self.root / 'dev/wrapper-coder/tools'
        old, new = b'prior fixture wrapper', b'new fixture wrapper'
        host = wrapper / 'host_server.py'
        host.write_bytes(new if target == 'INSTALLED' else old)
        host.chmod(0o600)
        base = self.root.parent
        bundle = base / 'fixture-bundle'
        bundle.mkdir(mode=0o700)
        alternate = base / 'alternate'
        uid = os.geteuid()
        policy = checkpoint.SitePolicy(
            project=self.root, marker=self.root / '.state/integration-release-journal.json',
            lock_paths=(self.root / '.state/scraper.lock',), cache_prefixes=(),
            maintenance_id='fixture-maintenance', manifest_sha256='a' * 64,
            systemctl=base / 'never-run-systemctl', maintenance_bundle=bundle,
            maintenance_exe=base / 'never-run-python', launch_uid=uid, wrapper_active=True,
            wrapper_enabled='enabled', wrapper_unit_file=base / 'wrapper.service',
            sync_unit_file=base / 'sync.service', wrapper_args=('fixture-python', str(host)),
            wrapper_cwd=wrapper, wrapper_exe=base / 'fixture-python', wrapper_port=18789,
            wrapper_cgroup=Path('/fixture/wrapper'), network_namespace=(1, 20),
            before_host=checkpoint.SourceFile(sha256(old).hexdigest(), 0o600, uid),
            after_host=checkpoint.SourceFile(sha256(new).hexdigest(), 0o600, uid),
            alternate_roots=(alternate,),
            covers=(CoverPin(alternate, (1, 20), 42, (1, 40), uid, ('fixture-launcher',)),),
            source_paths=frozenset({'src/job_search_helper/runner.py'}),
        )
        request = {
            'schema': 'sprint-4-host-check-v1', 'nonce': 'f' * 32,
            'checkpoint': 'restored', 'project': str(self.root),
            'package': str(self.root / 'src/job_search_helper'), 'marker': str(policy.marker),
            'backend': 'sqlite', 'target': target, 'maintenance_id': policy.maintenance_id,
            'locks': list(map(str, policy.lock_paths)), 'pycache_prefixes': [],
            'source_manifest_sha256': policy.manifest_sha256,
        }

        def unit_status(_executable, name):
            wrapper_unit = name == checkpoint.WRAPPER_UNIT
            return {
                'ActiveState': 'active' if wrapper_unit else 'inactive',
                'MainPID': '21' if wrapper_unit else '0',
                'UnitFileState': 'enabled' if wrapper_unit else 'disabled',
                'FragmentPath': str(policy.wrapper_unit_file if wrapper_unit else policy.sync_unit_file),
                'ControlGroup': str(policy.wrapper_cgroup) if wrapper_unit else '',
            }

        self.stack.enter_context(patch.object(checkpoint, 'unit_status', unit_status))
        return policy, request

    def verify(self, target, startup, clock, *, late_tick=False):
        policy, request = self.site(target)
        full = protected.bind_host_witness(
            self.root, self.saved.pin, self.saved.digest, maintenance_id=policy.maintenance_id,
            verify_release_hold=lambda *_: True,
        )

        def once():
            proof = continuity.ProtectedContinuity(
                policy=policy, protected_pin=self.saved.pin, pin_digest=self.saved.digest,
                executable_digest=SOURCE_PINS['host_check_main.py'], request=request,
                owner=lambda _: self.owner, full_check=full,
            )
            self.attempts.append(proof)

            def launcher(_stage, _target):
                self.boundaries.append('launcher')
                if late_tick and len(self.attempts) == 1:
                    startup.step()

            result = checkpoint.attest(request, policy, proof, verify_launcher=launcher)
            proof.finalize()
            return result

        with patch.object(entry, 'time', clock):
            result = entry.wait_for_restored_stability(self.root, lambda: self.owner, once)
        self.assertEqual(result, {**request, 'verified': True})
        return result

    def startup(self, *, after_tick=None):
        worker = AsyncStartup({role: self.paths[role] for role in ('jobs', 'inbox', 'coordinator')},
                              after_tick=after_tick)
        self.addCleanup(worker.close)
        return worker

    def assert_artifact_activity(self, worker):
        self.assertGreater(worker.ticks, 0)
        self.assertTrue(any(before['-wal'] is None and during['-wal'] is not None
                            and after['-wal'] is None
                            for before, during, after in worker.store.observed))
        self.assertTrue(any(before['jobs']['-wal'] is None and after['jobs']['-wal'] is not None
                            and before['inbox']['-wal'] is None and after['inbox']['-wal'] is not None
                            for before, after in worker.retention_observations))

    def settled(self, target):
        worker = self.startup()
        clock = VirtualTime(worker, steps=3)
        self.verify(target, worker, clock)
        self.assertEqual(worker.ticks, 3)
        self.assertEqual(clock.elapsed, 6.0)
        self.assertEqual(len(self.attempts), 1)
        self.assertEqual(self.saved.pin.read_bytes(), self.original_pin)
        self.assertTrue(self.saved.verify())
        self.assert_artifact_activity(worker)
        self.assertEqual(self.boundaries.count('listener'), 2)

    def settled_wall_clock(self, target):
        worker = self.startup()
        clock = RealTimeStartup(worker)
        self.addCleanup(clock.close)
        started = wall_time.monotonic()
        self.verify(target, worker, clock)
        elapsed = wall_time.monotonic() - started
        self.assertTrue(clock.done.is_set())
        self.assertIsNone(clock.error)
        self.assertEqual(worker.ticks, 3)
        self.assertGreaterEqual(elapsed, 3.0)
        self.assertLess(elapsed, 20.0)
        self.assertEqual(len(self.attempts), 1)
        self.assertEqual(self.saved.pin.read_bytes(), self.original_pin)
        self.assertTrue(self.saved.verify())
        self.assert_artifact_activity(worker)

    def prolonged(self, target):
        worker = self.startup()
        clock = VirtualTime(worker, steps=None)
        with self.assertRaisesRegex(protected.WitnessHold, 'did not reach a stable protected checkpoint'):
            self.verify(target, worker, clock)
        self.assertEqual(clock.elapsed, 69.0)
        self.assertEqual(worker.ticks, 46)
        self.assertEqual(self.attempts, [])
        self.assertEqual(self.saved.pin.read_bytes(), self.original_pin)
        self.assertTrue(self.saved.verify())
        self.assert_artifact_activity(worker)

    def changed_logical(self, target):
        def changed(count):
            if count == 2:
                self.saved.sql('jobs', 'INSERT INTO manual_choices VALUES (?)', ('changed-protected-choice',))

        worker = self.startup(after_tick=changed)
        clock = VirtualTime(worker, steps=2)
        with self.assertRaisesRegex(protected.WitnessHold, 'protected state differs from private pin'):
            self.verify(target, worker, clock)
        self.assertEqual(clock.elapsed, 4.5)
        self.assertEqual(len(self.attempts), 1)
        self.assertEqual(self.saved.pin.read_bytes(), self.original_pin)

    def late_churn(self, target):
        worker = self.startup()
        clock = VirtualTime(worker, steps=0)
        self.verify(target, worker, clock, late_tick=True)
        self.assertEqual(worker.ticks, 1)
        self.assertEqual(clock.elapsed, 4.5)
        self.assertEqual(len(self.attempts), 2)
        self.assertIsNot(self.attempts[0], self.attempts[1])
        self.assertEqual(self.boundaries.count('listener'), 4)
        self.assertEqual(self.boundaries.count('launcher'), 2)
        self.assertEqual(self.saved.pin.read_bytes(), self.original_pin)
        self.assertTrue(self.saved.verify())
        self.assert_artifact_activity(worker)


for scenario in ('settled', 'settled_wall_clock', 'prolonged', 'changed_logical', 'late_churn'):
    for target in ('INSTALLED', 'ROLLED_BACK'):
        def test(self, scenario=scenario, target=target):
            getattr(self, scenario)(target)
        setattr(RealisticReadinessTests, f'test_{scenario}_{target.lower()}', test)


if __name__ == '__main__':
    unittest.main(verbosity=2)
