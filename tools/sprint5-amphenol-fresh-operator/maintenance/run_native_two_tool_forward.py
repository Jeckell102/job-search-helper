"""Preflight or run exactly the default-off MuleLab wrapper tool update."""

import argparse
from contextlib import closing
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


HERE = Path(__file__).resolve().parent
PROJECT = Path('/home/chris/job-search-helper_old')
BUNDLE = Path('/home/chris/.local/state/job-search-helper-maintenance/s5-operator-trigger-20261121-03')
FORWARD = BUNDLE.with_name('s5-amphenol-host-source-20261121-04') / 'host-forward-receipt.json'
MAINTENANCE_ID = 's5-amphenol-two-tool-20261121-05'
DESTINATION = BUNDLE.with_name(MAINTENANCE_ID)
OBSERVER = Path('/run/jsh-s5-amphenol-two-tool-05/observer.sock')
TOOLS = PROJECT / 'dev/wrapper-coder/tools'
DATABASE = TOOLS.parent / 'tasks/tasks.sqlite3'
PROC = Path('/proc')
WRAPPER = 'wrapper-development-host.service'
SYNC = 'job-search-sync.service'
TIMER = 'job-search-sync-expiry.timer'
BRIDGE = 'jetson-assistant-bridge.service'
MANIFEST = '8c73be2432fdc49485f426f5be77d6588ea1e13f7b659595f6a4dad16710c57e'
CONTROLLER = '0f2543519bbd7dcf9737533c3e2caebf62e2e8a8cc1574d09287e21055ed1793'
CHECKER = 'c0bec31ab59dbdc1064e2ee7003b9aa68e115d5902c34e43ebbe75058bf2a53e'
EXCHANGE = 'e35dac07cceb74964349c0daf14524e2555e213bb27ae740edc24e320765cd7b'
RESTORATION = 'c092dfc357a96f13c4b8c02740e89caa6430228239630edb80a1acadf82dcb25'
UNIT_SHA = '201a985896999b4ee0c484175ed9393be0576656b4781eb2ca16db9fb1ad2c28'
ADAPTER = 'a95953afe2bc10138714f6b11af22572b17ab344bf61d78b834647895025aa61'
COORDINATOR = 'dcf6f14ea4ff15e6c221ff3f46c29523419d931dfbf0dffe6e2edd6b0f427a91'
TASK = 'WRAP-6a3a372032'
INFERENCE = '2b444fe8f48a4c6e9638f1c6a7acb40c'
CONTROLS = ('WRAPPER_AMPHENOL_OPERATOR_RECIPE_ENROLLMENT', 'WRAPPER_AMPHENOL_RECIPE_ENROLLMENT',
            'WRAPPER_AMPHENOL_RETRY_APPROVAL', 'WRAPPER_AMPHENOL_ACTIVATE_APPROVED_RELEASE',
            'WRAPPER_SELECTED_OUTCOME_ID', 'WRAPPER_SELECTED_COMPANY_EVENT_ID')
PYTHON_OVERRIDES = ('PYTHONPATH', 'PYTHONHOME', 'PYTHONPYCACHEPREFIX', 'PYTHONOPTIMIZE',
                    'PYTHONSAFEPATH', 'PYTHONINSPECT')
TOOL_PINS = {
    'deploy_two_tool_forward.py': 'cf9f82f6b85f441ab2e0fdd9bfee1448aa6c1e444ade09a3e66e2748ebb75597',
    'current_tool_guard.py': '11cd0a2a9e7d7c11317706c61390eb613cccfe3a59458062503a32a4d755f9cd',
}
HISTORICAL_PINS = {
    'controller.py': 'f63f9399f3fcdec3d3b46a6d5e14fc3d1d78e420234b357b0adf44bd68a53ff8',
    'gate.py': '7df4121796ce400461be9b4329984bc6f1ced83858588d3a63d4e5258d286537',
    'installer.py': 'd85405266310a425bcc49027b5629cfb81dcc89f391cfbf75df33da7ac2a0920',
    'host-check': CHECKER, 'manifest.json': MANIFEST, 'controller.json': CONTROLLER,
}


def checked(path, digest):
    if path.resolve(strict=True) != path or not path.is_file():
        raise ValueError(f'Expected physical file {path.name}')
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != digest:
        raise ValueError(f'Changed approved file {path.name}')
    return raw


def system(*args):
    return subprocess.check_output(['/usr/bin/systemctl', '--user', *args], text=True, timeout=25).strip()


def unit_field(unit, field):
    return system('show', unit, '-p', field, '--value')


def verify_source_selection(forward_paths):
    """Measure the two startup files with the exact default import path."""
    checked(TOOLS / 'coordinator.py', COORDINATOR)
    for filename in ('coordinator.py', 'coordinator_store.py'):
        source = TOOLS / filename
        module = PathFinder.find_spec(source.stem, [str(TOOLS)])
        if (module is None or module.origin != str(source) or not isinstance(module.loader, SourceFileLoader)):
            raise ValueError(f'Unexpected import source for {filename}')
        if any(os.path.lexists(path) for path in (cache_from_source(str(source), optimization=''),
                                                 source.with_suffix('.pyc'))):
            raise ValueError(f'Unexpected eligible bytecode cache for {filename}')
    digests = {}
    for relative, mode in forward_paths.items():
        path = PROJECT / relative
        if path.resolve(strict=True) != path:
            raise ValueError(f'Unexpected path for {path.name}')
        before = path.stat()
        raw = path.read_bytes()
        after = path.stat()
        if (not stat.S_ISREG(after.st_mode) or stat.S_IMODE(after.st_mode) != mode
                or after.st_uid != os.getuid() or after.st_nlink != 1 or not os.path.samestat(before, after)
                or before.st_mtime_ns != after.st_mtime_ns or before.st_ctime_ns != after.st_ctime_ns
                or len(raw) != after.st_size):
            raise ValueError(f'Changed source custody for {path.name}')
        digests[relative] = sha256(raw).hexdigest()
    return digests


def retained_task():
    wal = DATABASE.with_name(DATABASE.name + '-wal')

    def signature():
        main = DATABASE.stat()
        try:
            pending = wal.stat()
        except FileNotFoundError:
            pending = None
        if pending is not None and pending.st_size:
            raise ValueError('Coordinator database has an unsettled WAL snapshot')
        return (main.st_dev, main.st_ino, main.st_size, main.st_mtime_ns, main.st_ctime_ns,
                None if pending is None else (pending.st_ino, pending.st_mtime_ns, pending.st_ctime_ns))

    before = signature()
    with closing(sqlite3.connect(DATABASE.as_uri() + '?mode=ro&immutable=1', uri=True, timeout=5)) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        controls = {key: json.loads(value) for key, value in db.execute(
            "SELECT key,value FROM settings WHERE key IN ('pilot_task','queue_enabled','campaign_enabled','autopilot_enabled')"
        )}
        state, = db.execute('SELECT state FROM tasks WHERE id=?', (TASK,)).fetchone()
        (request, status, receipt), = db.execute('SELECT request_id,status,data FROM inference_receipts WHERE task=?',
                                                 (TASK,)).fetchall()
        (open_count,) = db.execute("SELECT count(*) FROM inference_receipts WHERE status IN ('DISPATCHING','UNCERTAIN')").fetchone()
        active_tasks = any(json.loads(raw).get('status') in ('RUNNING', 'QUEUED', 'PAUSING')
                           for (raw,) in db.execute('SELECT state FROM tasks'))
    if signature() != before:
        raise ValueError('Coordinator database changed during read-only inspection')
    expected = {'pilot_task': None, 'queue_enabled': False, 'campaign_enabled': False, 'autopilot_enabled': False}
    if controls != expected or open_count or active_tasks or request != INFERENCE or status != 'COMPLETED':
        raise ValueError('Production repair controls or the historical task are outside the accepted quiet state')
    return sha256(state.encode()).hexdigest(), sha256(receipt.encode()).hexdigest(), open_count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    for filename, digest in TOOL_PINS.items():
        checked(HERE / filename, digest)
    for filename, digest in HISTORICAL_PINS.items():
        checked(BUNDLE / filename, digest)
    for parent, names in ((HERE, TOOL_PINS), (BUNDLE, ('controller.py', 'gate.py', 'installer.py'))):
        for filename in names:
            if os.path.lexists(cache_from_source(str(parent / filename), optimization='')):
                raise ValueError(f'Unexpected cached maintenance module {filename}')
    sys.path[:0] = [str(HERE), str(BUNDLE), str(BUNDLE / 'host-check')]
    import controller as historical
    import deploy_two_tool_forward as updater
    from current_tool_guard import CurrentToolGuard, FORWARD_RECEIPT_SHA256
    from host_checkpoint import unit_status, verify_listener, verify_route_drain, verify_wrapper_process
    from host_exchange import HostExchange
    from site_policy import load_policy

    controller = historical.Controller(BUNDLE)
    policy, *_ = load_policy(str(BUNDLE / 'host-check'))
    policy = replace(policy, maintenance_id=MAINTENANCE_ID, ancillary_process_evidence=OBSERVER)
    if sys.implementation.cache_tag != 'cpython-311' or Path('/proc/self/exe').resolve() != policy.wrapper_exe:
        raise ValueError('Use the enrolled production Python interpreter in isolated no-cache mode')
    if not sys.flags.isolated or not sys.flags.dont_write_bytecode:
        raise ValueError('Run the maintenance entry with Python -I -B')
    candidates = {path: checked(HERE / Path(path).name, pin) for path, pin in updater.TWO_TOOL_AFTER.items()}
    remaining = {path: digest for path, (_, digest) in controller.manifest.after.items()
                 if path != updater.HOST_RELATIVE}
    file_modes = {updater.HOST_RELATIVE: 0o600, updater.STORE_RELATIVE: 0o644}
    bridge_start = unit_field(BRIDGE, 'ExecMainStartTimestampMonotonic')
    if not bridge_start.isdecimal() or int(bridge_start) <= 0:
        raise ValueError('Expected the existing Jetson bridge to be running')
    start_facts = None

    def verify_other_services():
        sync = unit_status(policy.systemctl, SYNC)
        if (sync['FragmentPath'] != str(policy.sync_unit_file) or sync['ActiveState'] != 'inactive'
                or sync['MainPID'] != '0' or sync['UnitFileState'] != 'disabled'
                or unit_field(TIMER, 'ActiveState') != 'inactive' or unit_field(TIMER, 'UnitFileState') != 'disabled'
                or unit_field(BRIDGE, 'ActiveState') != 'active'
                or unit_field(BRIDGE, 'ExecMainStartTimestampMonotonic') != bridge_start):
            raise ValueError('Scheduled sync or the existing Jetson bridge changed state')

    def active_wrapper():
        verify_other_services()
        unit = unit_status(policy.systemctl, WRAPPER)
        if (unit['ActiveState'] != 'active' or unit['UnitFileState'] != 'enabled'
                or Path(unit['FragmentPath']) != policy.wrapper_unit_file or int(unit['MainPID']) <= 0):
            raise ValueError('Expected the default wrapper service')
        checked(policy.wrapper_unit_file, UNIT_SHA)
        pid = int(unit['MainPID'])
        identity = verify_wrapper_process(policy, pid, PROC)
        verify_listener(policy, pid, PROC)
        verify_route_drain(policy, pid, PROC)
        started = int(unit_field(WRAPPER, 'ExecMainStartTimestampMonotonic'))
        keys = {item.split(b'=', 1)[0].decode() for item in (PROC / str(pid) / 'environ').read_bytes().split(b'\0') if item}
        if keys.intersection(CONTROLS + PYTHON_OVERRIDES):
            raise ValueError('The wrapper is enrolled or has an unapproved startup import override')
        if verify_wrapper_process(policy, pid, PROC) != identity or unit_status(policy.systemctl, WRAPPER) != unit:
            raise ValueError('The wrapper identity changed during inspection')
        return pid, started

    def prove_exclusive():
        active_wrapper()
        return True

    def idle():
        pid, started = active_wrapper()
        hashes = verify_source_selection(file_modes)
        checked(PROJECT / 'src/job_search_helper/acquiretm.py', ADAPTER)
        task, receipt, open_count = retained_task()
        if start_facts is not None:
            minimum_time, start_hashes = start_facts
            if started < minimum_time or hashes != start_hashes:
                raise ValueError('The running wrapper was not started on the measured files')
        return {'service': WRAPPER, 'pid': pid, 'started_monotonic_us': started, 'open_inference': open_count,
                'task_sha256': task, 'receipt_sha256': receipt, 'loaded_hashes': hashes,
                'controls': {'queue': False, 'campaign': False, 'autopilot': False, 'unqualified_release': False}}

    def exchange_probe(terminal):
        if terminal['controller_journal_sha256'] != CONTROLLER or terminal['source_manifest_sha256'] != MANIFEST:
            raise ValueError('The historical predecessor changed')
        witness = HostExchange(BUNDLE / 'exchange-private/policy.json', EXCHANGE).witness('restored')
        if witness.terminal_proof_sha256 != RESTORATION or len(witness.pairs) != 3:
            raise ValueError('The predecessor checkout routes are outside the restored state')
        return {'restored_exchange': True, 'predecessor_receipt_sha256': FORWARD_RECEIPT_SHA256,
                'historical_predecessor_receipt_sha256': updater.HISTORICAL_PREDECESSOR_RECEIPT_SHA256,
                'exchange_sha256': EXCHANGE, 'terminal_proof_sha256': RESTORATION}

    def stop(unit):
        if unit != WRAPPER:
            raise ValueError('Only the wrapper host is in scope')
        system('stop', unit)

    def stopped():
        verify_other_services()
        unit = unit_status(policy.systemctl, WRAPPER)
        if unit['ActiveState'] != 'inactive' or unit['MainPID'] != '0':
            raise ValueError('Wrapper stop has not settled')
        verify_listener(policy, 0, PROC)
        verify_route_drain(policy, 0, PROC)
        return True

    def start(unit):
        nonlocal start_facts
        if unit != WRAPPER:
            raise ValueError('Only the wrapper host is in scope')
        hashes = verify_source_selection(file_modes)
        if hashes not in (updater.TWO_TOOL_BEFORE, updater.TWO_TOOL_AFTER):
            raise ValueError('Refusing to start the wrapper on mixed source')
        start_facts = time.monotonic_ns() // 1000, hashes
        system('start', unit)

    def ready():
        deadline = time.monotonic() + 12
        while True:
            try:
                return idle()
            except (OSError, ValueError):
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.3)

    guard = CurrentToolGuard(controller, historical, FORWARD, prove_exclusive)
    with guard.terminal() as terminal:
        exchange_probe(terminal)
        status = idle()
        updater._verify_idle(status, updater.TWO_TOOL_BEFORE)
    if not args.apply:
        print(json.dumps({'status': 'PREFLIGHT_ONLY', 'maintenance_id': MAINTENANCE_ID, 'idle': status}, sort_keys=True))
        return
    DESTINATION.mkdir(mode=0o700, exist_ok=False)
    result = updater.apply_two_tool_forward(project=PROJECT, successor_guard=guard, candidates=candidates,
        before_sha256=updater.TWO_TOOL_BEFORE, after_sha256=updater.TWO_TOOL_AFTER,
        predecessor_receipt_sha256=FORWARD_RECEIPT_SHA256, remaining_scope=remaining,
        idle_probe=idle, exchange_probe=exchange_probe, stop_service=stop, stopped_probe=stopped,
        start_service=start, restart_probe=ready, receipt_directory=DESTINATION)
    print(json.dumps({'status': result['status'], 'receipt_directory': str(DESTINATION), 'idle': idle()}, sort_keys=True))


if __name__ == '__main__':
    main()
