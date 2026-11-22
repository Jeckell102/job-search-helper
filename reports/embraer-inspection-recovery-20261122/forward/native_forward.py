"""Measured wrapper-only coordinator update; inspect is the default action."""
import argparse
from contextlib import ExitStack, closing, contextmanager
from dataclasses import replace
from hashlib import sha256
from importlib.machinery import PathFinder, SourceFileLoader
from importlib.util import cache_from_source
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
import time
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
STAGE = HERE.parents[1]
PROJECT = Path('/home/chris/job-search-helper_old')
TOOLS = PROJECT/'dev/wrapper-coder/tools'
STATE = PROJECT/'.state'
TASK = 'WRAP-fbb9ff24d3'
REQUEST = 'operator-embraer-20261122-01'
REQUEST_SHA = '19e7af99bd90d243f9b9f7465d5b6c38455ef99208cade05b7e1cfe5ca7536d2'
OUTCOME = 'OUT-719882e9ec8b8ad044885426'
MAINTENANCE = 's6-embraer-coordinator-recovery-20261122-13'
OBSERVER = Path('/run/jsh-s6-embraer-coordinator-recovery-13/observer.sock')
ENTRY = STAGE/'pilot-enrollment/native_embraer_enrollment_entry.py'
ENTRY_PIN = '211e71de4fb93a3132f8eaa63c3cd4e9a9e2f8626f00c3bc8a2233da4b33496c'
ATOMIC = Path('/tmp/jsh-amphenol-native-two-tool.HQkjpe8m/deploy_two_tool_forward.py')
ATOMIC_PIN = 'cf9f82f6b85f441ab2e0fdd9bfee1448aa6c1e444ade09a3e66e2748ebb75597'
FORWARD_PIN = 'd96d3da055571ebd7528adb6bb61a0b3e82387bef5eef4c96838826aa63e8437'


def require(test, message):
    if not test: raise ValueError(message)


def admit_process_boundary(action, intent, unit, active, stopped):
    if action == 'rollback' and intent is not None and unit.get('ActiveState') == 'inactive':
        require(stopped() is True, 'Owned rollback has no exact stopped process proof')
    else:
        active()


def load(name, path, pin):
    from types import ModuleType
    require(path.resolve(strict=True) == path and path.is_file() and path.stat().st_nlink == 1,
            'Expected physical measured maintenance source')
    raw = path.read_bytes()
    require(sha256(raw).hexdigest() == pin and name not in sys.modules, 'Maintenance source pin differs')
    module = ModuleType(name); module.__file__ = str(path); sys.modules[name] = module
    exec(compile(raw, str(path), 'exec'), module.__dict__)
    return module


def wrapper_map(c, root, excluded):
    """The existing Controller.unscoped representation, retaining all metadata."""
    result = {}
    for parent, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(name for name in dirs if name != '__pycache__')
        for name in sorted(dirs + files):
            path = Path(parent)/name; relative = path.relative_to(root).as_posix()
            if relative in excluded or relative.endswith('.pyc'): continue
            info = path.lstat()
            result[relative] = (['directory', *c.installer.identity(info), stat.S_IMODE(info.st_mode),
                                 *c.installer.ownership(info)] if stat.S_ISDIR(info.st_mode)
                                else [*c.ref(path), info.st_mtime_ns])
    return result


def extended_window(window, native, forward, intent):
    """Keep -12 immutable; prove only the independently approved coordinator delta.

    A later disarm owner can reuse this exact adapter with a hash-approved
    terminal receipt's transition. It must separately pin current_reference.
    """
    if intent is None: return window
    forward.transition_record(intent)

    class ToolForwardWindow(native.NativeWindow):
        def _wrapper_custody(self, status):
            current = json.loads(native.read_private(native.CURRENT/'two-tool-forward-receipt.json', native.RECEIPT_05))
            for relative, digest in native.CURRENT_TOOLS.items():
                info = current['paths'][relative]
                native.require(info['after_sha256'] == digest, 'Historical tool lineage differs')
                actual = self.c.ref(PROJECT/relative)
                if relative in self.source_owner.spec['package_files']:
                    pair = self.source_owner.spec['package_files'][relative]
                    endpoint = status['endpoints'][relative]
                    native.require_endpoint_phase(pair, endpoint, status['phase'])
                    require(endpoint is not None and actual[-1] == endpoint['sha256']
                            and actual[2] == endpoint['mode'] and actual[3:5] == pair['owner'],
                            'Changed wrapper endpoint differs from its original source owner')
                else:
                    require(actual[-1] == digest and actual[2] == int(info['mode'], 8)
                            and actual[3] == os.geteuid(), 'Unrelated current tool differs')
            vector = wrapper_map(self.c, self.old.wrapper_tools, native.CHANGED_WRAPPER_TOOLS)
            before = intent['before_reference']
            actual = vector.get('coordinator.py')
            require(isinstance(actual, list) and len(actual) == 7
                    and actual[2:5] == before[2:5] and actual[5] in {forward.BEFORE, forward.AFTER},
                    'Coordinator is outside exact approved before/after custody')
            vector['coordinator.py'] = before
            require(self.c.installer.digest(self.c.installer.encode(vector)) == self.wrapper_scope_sha256,
                    'Unscoped wrapper custody differs beyond the one approved coordinator')

    result = ToolForwardWindow.__new__(ToolForwardWindow)
    result.__dict__.update(window.__dict__)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument('action', choices=('inspect', 'apply', 'rollback'), nargs='?', default='inspect')
    parser.add_argument('--entry-sha256', required=True)
    parser.add_argument('--approved-snapshot-sha256')
    args = parser.parse_args(argv)
    require(sys.flags.isolated and sys.flags.dont_write_bytecode and sys.pycache_prefix == '/dev/null'
            and Path(sys.prefix).resolve() == PROJECT/'.venv', 'Use installed Python -I -B -X pycache_prefix=/dev/null')
    require(sha256(Path(__file__).read_bytes()).hexdigest() == args.entry_sha256, 'Reviewed native entry differs')
    entry = load('embraer_enrollment_native', ENTRY, ENTRY_PIN)
    _, read, owner, native, window, libraries = entry.load_runtime(ENTRY_PIN)
    forward = load('embraer_coordinator_forward', HERE/'coordinator_forward.py', FORWARD_PIN)
    atomic = load('embraer_forward_atomic', ATOMIC, ATOMIC_PIN)
    root = HERE/'transaction'
    require(root.resolve(strict=True) == root and stat.S_IMODE(root.stat().st_mode) == 0o700,
            'Prepared private transaction directory required')
    intent = json.loads(atomic._read(root/'intent.json')[0]) if (root/'intent.json').exists() else None
    window = extended_window(window, native, forward, intent)
    window._modules()
    environment = libraries['embraer_pilot_environment']
    from job_search_helper.inbox import InventoryInbox
    from job_search_helper.operator_embraer_settlement import read_operator_embraer_source
    from job_search_helper.sqlite_repository import SQLiteRepository
    from embraer_operator_pilot import EmbraerOperatorEnrollment
    destination = InventoryInbox.destination_id(STATE/'inventories.sqlite3')
    selected, outcome = libraries['embraer_operator_enrollment_input'].read_operator_embraer_enrollment(
        state_root=STATE, request_id=REQUEST, request_sha256=REQUEST_SHA,
        expected_source_manifest_sha256=owner.spec['staged_source_sha256'],
        repository_factory=lambda path: SQLiteRepository(path, destination, readonly=True),
        source_reader=read_operator_embraer_source)
    require(outcome == OUTCOME, 'Unexpected operator outcome')
    enrollment = EmbraerOperatorEnrollment(**selected)
    expected_environment = {environment.ENROLLMENT: json.dumps(selected, sort_keys=True, separators=(',', ':'))}
    database = TOOLS.parent/'tasks/tasks.sqlite3'
    native.physical(database)
    initial_snapshot = True

    def snapshot():
        nonlocal initial_snapshot
        source = enrollment._source(STATE/'jobs.sqlite3', destination)
        paired = enrollment._paired(SimpleNamespace(path=database), source) if source else None
        require(paired is not None and source['record']['outcome_id'] == OUTCOME
                and enrollment._sources_match(PROJECT)
                and enrollment._task_matches(*paired, enrollment._proposal(paired[0], source['company'])),
                'Current paired owned Embraer task is unavailable')
        with closing(sqlite3.connect(database.as_uri()+'?mode=ro', uri=True)) as db:
            db.execute('BEGIN')
            entry.controls(db, allowed_pilot=TASK)
            rows = db.execute('SELECT state FROM tasks WHERE id=?', (TASK,)).fetchall()
            require(len(rows) == 1, 'Selected task is not unique')
            task = json.loads(rows[0][0])
            require(task == paired[1] and task['status'] == 'PAUSED_BLOCKED' and task['phase'] == 'inspect'
                    and task['mode'] == 'develop' and task.get('stop_requested') is False,
                    'Selected paused task changed')
            if initial_snapshot and args.action != 'rollback':
                require(task['sessions'] < task['max_sessions'] and task['calls'] < 48 and task['tokens'] < 120000
                        and task.get('activated_at') is not None and time.time() < task['activated_at']+3600,
                        'Same task is outside its unchanged original budget')
            inference = db.execute('SELECT request_id,status,data FROM inference_receipts WHERE task=? ORDER BY request_id', (TASK,)).fetchall()
            require(inference and all(row[1] == 'COMPLETED' for row in inference), 'Selected inference did not settle')
            receipts = db.execute('SELECT * FROM receipts WHERE task=? ORDER BY id', (TASK,)).fetchall()
            settings = db.execute("SELECT key,value FROM settings WHERE key IN ('queue_enabled','campaign_enabled','autopilot_enabled','pilot_task') ORDER BY key").fetchall()
        initial_snapshot = False
        return dict(task_sha256=sha256(rows[0][0].encode()).hexdigest(),
            inference_sha256=forward.digest(inference), tool_receipts_sha256=forward.digest(receipts),
            controls=settings, enrollment=selected, source_proof_sha256=forward.digest(source['proof']),
            outcome_id=OUTCOME, sender_receipt_sha256=source['row'][7])

    def system(*args):
        return subprocess.run([str(window.policy.systemctl), '--user', *args],
            check=True, capture_output=True, text=True, timeout=70).stdout.strip()

    bridge_identity = None
    bridge_unit = None
    start_facts = None

    def services(pid, *, active):
        h, policy = window.h, window.policy
        require(h.unit_status(policy.systemctl, native.BRIDGE) == bridge_unit, 'Assistant bridge changed')
        for path, pin in ((native.BRIDGE_UNIT, native.BRIDGE_UNIT_SHA),
                          (native.BRIDGE_SOURCE, native.BRIDGE_SOURCE_SHA),
                          (policy.wrapper_unit_file, entry.UNIT_PIN)):
            read(path, pin)
        for unit in (native.SYNC, native.TIMER):
            require(system('show', unit, '-p', 'ActiveState', '--value') == 'inactive'
                    and system('show', unit, '-p', 'UnitFileState', '--value') == 'disabled',
                    'Scheduled synchronization must remain disabled')
        listening = h.verify_listener(policy, pid, Path('/proc'))
        for helper in (1249, 4467):
            require(h.verify_ancillary_process(OBSERVER, Path('/proc')/str(helper), policy.launch_uid,
                MAINTENANCE, h.checkout_routes(policy),
                listener=(policy.wrapper_port, listening) if active else None) is True,
                'Fresh administrator writer-exclusion observation is required')
        window.r.verify_two_tool_route_drain(policy, pid, Path('/proc'), bridge_identity)
        require(environment.manager_scope(system) == expected_environment, 'Manager enrollment changed')

    def active():
        h, policy = window.h, window.policy
        unit = h.unit_status(policy.systemctl, native.WRAPPER); pid = int(unit['MainPID'])
        require(pid > 0 and unit['ActiveState'] == 'active' and unit['UnitFileState'] == 'enabled'
                and unit['FragmentPath'] == str(policy.wrapper_unit_file), 'Wrapper is not active on exact unit')
        identity = h.verify_wrapper_process(policy, pid, Path('/proc'))
        services(pid, active=True)
        require(entry.process_scope((Path('/proc')/str(pid)/'environ').read_bytes(), environment.SCOPED)
                == expected_environment, 'Wrapper process enrollment changed')
        require(h.verify_wrapper_process(policy, pid, Path('/proc')) == identity, 'Wrapper changed during readback')
        return pid, int(system('show', native.WRAPPER, '-p', 'ExecMainStartTimestampMonotonic', '--value'))

    def source_selection(expected):
        path = PROJECT/forward.RELATIVE
        PathFinder.invalidate_caches()
        found = PathFinder.find_spec('coordinator', [str(TOOLS)])
        require(found is not None and found.origin == str(path) and isinstance(found.loader, SourceFileLoader),
                'Wrapper would select another coordinator import')
        require(not any(os.path.lexists(p) for p in (path.parent/'__pycache__'/(path.stem+'.'+sys.implementation.cache_tag+'.pyc'), path.with_suffix('.pyc'))),
                'Eligible coordinator bytecode must not override source')
        read(path, expected)
        return [*window.c.ref(path), path.stat().st_mtime_ns]

    @contextmanager
    def guard():
        nonlocal bridge_identity, bridge_unit
        c = window.c
        old = c.Controller(native.BUNDLE)
        with ExitStack() as held:
            for path in (old.controller_gate, *old.locks, old.install_gate): held.enter_context(c.lock(path))
            require({str(p): c.inode(p) for p in old.locks} == old.binding['locks'], 'Application lock identity changed')
            window._approval(); window._lineage(check_restored=False)
            restored = {name: json.loads(read(window.root/name, pin, private=True)) for name,pin in entry.RESTORED.items()}
            original = restored['native-window.json']
            require(original['phase'] == restored['operator-quiet-window.json']['phase'] == 'RESTORED'
                    and restored['exchange-private/exchange.json']['phase'] == 'restored'
                    and original['binding'] == window._binding() and original['terminal'] == window._terminal(),
                    'Original -12 deployment is not exactly restored')
            exchange = window.x.HostExchange(window.root/'exchange-private/policy.json', original['exchange']['policy_sha256'])
            require(exchange.witness('restored').terminal_proof_sha256 == original['restoration_sha256'],
                    'Canonical routes differ from original restoration')
            window.policy = replace(window.policy, maintenance_id=MAINTENANCE, ancillary_process_evidence=OBSERVER)
            bridge_unit = window.h.unit_status(window.policy.systemctl, native.BRIDGE)
            bridge_pid = int(bridge_unit['MainPID'])
            require(bridge_pid > 0 and bridge_unit['ActiveState'] == 'active' and bridge_unit['UnitFileState'] == 'enabled'
                    and bridge_unit['FragmentPath'] == str(native.BRIDGE_UNIT), 'Expected existing bridge unavailable')
            bridge_identity = (bridge_pid, window.h.process_start(Path('/proc')/str(bridge_pid)))
            admit_process_boundary(args.action, intent,
                window.h.unit_status(window.policy.systemctl, native.WRAPPER), active, stopped)
            yield dict(application_journal_sha256=entry.ACTIVE_JOURNAL_PIN,
                       application_receipt_sha256=entry.ACTIVE_RECEIPT_PIN,
                       restored_records=entry.RESTORED, original_wrapper_scope_sha256=window.wrapper_scope_sha256)

    def stop(service):
        require(service == native.WRAPPER, 'Only wrapper service is in maintenance scope')
        system('stop', service)

    def stopped():
        unit = window.h.unit_status(window.policy.systemctl, native.WRAPPER)
        require(unit['ActiveState'] == 'inactive' and unit['MainPID'] == unit['ControlPID'] == '0', 'Wrapper stop has not settled')
        services(0, active=False)
        return True

    def start(service):
        nonlocal start_facts
        require(service == native.WRAPPER, 'Only wrapper service is in maintenance scope')
        pin = sha256((PROJECT/forward.RELATIVE).read_bytes()).hexdigest()
        require(pin in (forward.BEFORE, forward.AFTER), 'Mixed coordinator source')
        ref = source_selection(pin)
        start_facts = time.monotonic_ns()//1000, ref
        system('start', service)

    def ready(expected, transition):
        nonlocal window
        window = extended_window(window, native, forward, transition)
        deadline = time.monotonic()+12
        while True:
            try:
                pid, started = active()
                actual = source_selection(expected)
                require(start_facts is not None and started >= start_facts[0] and actual == start_facts[1],
                        'Wrapper did not start on exact measured coordinator')
                window._terminal()
                read(STATE/'integration-release-journal.json', entry.ACTIVE_JOURNAL_PIN, private=True)
                return dict(pid=pid, started_monotonic_us=started, coordinator_reference=actual,
                            enrollment_sha256=forward.digest(selected))
            except (OSError, ValueError):
                if time.monotonic() >= deadline: raise
                time.sleep(.3)

    candidate = read(HERE.parent/'coordinator.py', forward.AFTER)
    if args.action == 'inspect':
        with atomic._deployment_lock(PROJECT), guard() as predecessor:
            value = snapshot()
            source_selection(forward.BEFORE if intent is None else sha256((PROJECT/forward.RELATIVE).read_bytes()).hexdigest())
            print(json.dumps(dict(state='COORDINATOR_FORWARD_INSPECTED', snapshot=value,
                snapshot_sha256=forward.digest(value), predecessor=predecessor), sort_keys=True))
        return 0
    require(isinstance(args.approved_snapshot_sha256, str) and len(args.approved_snapshot_sha256) == 64,
            'Exact independently read paused snapshot pin is required')
    result = forward.apply(project=PROJECT, candidate=candidate, receipt_directory=root,
        atomic=atomic, guard=guard, snapshot=snapshot, approved_snapshot_sha256=args.approved_snapshot_sha256,
        stop=stop, stopped=stopped, start=start, ready=ready,
        reference=lambda path: [*window.c.ref(path), path.stat().st_mtime_ns], rollback_only=args.action=='rollback')
    print(json.dumps(dict(state=result['status'], receipt_sha256=forward.digest(result),
                         receipt_path=str(root/'receipt.json')), sort_keys=True))
    return 0


if __name__ == '__main__': raise SystemExit(main())
