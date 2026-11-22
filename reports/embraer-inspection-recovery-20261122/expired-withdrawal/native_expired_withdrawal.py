"""Withdraw only the actually stopped, expired original Embraer pilot."""
import argparse
from contextlib import closing
from dataclasses import replace
import math
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time
from types import ModuleType, SimpleNamespace

HERE = Path(__file__).resolve().parent
STAGE = HERE.parents[1]
ENROLLMENT_TOOLS = STAGE / "pilot-enrollment"
MAINTENANCE = "s6-embraer-coordinator-recovery-20261122-13"
OBSERVER = Path("/run/jsh-s6-embraer-coordinator-recovery-13/observer.sock")
TASK = "WRAP-fbb9ff24d3"
REQUEST = "operator-embraer-20261122-01"
REQUEST_PIN = "19e7af99bd90d243f9b9f7465d5b6c38455ef99208cade05b7e1cfe5ca7536d2"
OUTCOME = "OUT-719882e9ec8b8ad044885426"
ORIGINAL_ACTIVATED_AT = 1795373201.1956606
ORIGINAL_PAIRED_RECEIPT = 'd3964ed3d2f3d63adb17d0af72ce616a397a3c8e8a62676ed1711b15d5a24afb'
PROJECT = Path('/home/chris/job-search-helper_old')
ROOT = PROJECT / '.state'
TOOLS = PROJECT / 'dev/wrapper-coder/tools'
DEPLOYMENT = STAGE / 'deployment'
DEPLOYMENT_ENTRY_PIN = 'fb12dc6e357baea45224114b02db0ac6f65ae660fd77675d94d659d438274e11'
APPROVAL_PIN = 'd6b2b78a3a77f4a6c431c5dac3039ee16ab35437e28a5895149f98d737b56c5b'
BOOTSTRAP_PIN = '0a1eca6877ef7b78cd851d2e5de15528c166bf31da96ca361f705cd48b7b4a00'
ACTIVE_JOURNAL_PIN = 'c47b1e8036d3145b4c016e9d398f20ca5e34a7f98bc07459ef213ad6601aa576'
ACTIVE_RECEIPT_PIN = 'e652841c669138c7b92a78135dd3735b49d27f534d4eb2ce3ca9c29c1b69da50'
UNIT_PIN = '201a985896999b4ee0c484175ed9393be0576656b4781eb2ca16db9fb1ad2c28'
PINS = {
    'embraer_pilot_environment': '2f69088e899d637759bdbe9f0984ef87259c2c2e1fc3f7e4d2ce0b7be35c87d6',
    'embraer_pilot_arming': 'bb1dc2ed88e2107fa8b2de21676ac4a2a7c61e4109a78712dabab285a1d91ba5',
    'embraer_operator_enrollment_input': '16c4c672a205881e25d2a6ea2dc9bc50b9a7d1d27eac326851907a5662c15b18',
}
RESTORED = {
    'native-window.json': '492e8d056870dac4004d01dbb39fd179ae0ac3f008aace9e5d69a0941e0d4e72',
    'operator-quiet-window.json': '5ed9e6f5e9a09ac5862015977ea2affa278d205ade47c337af3ca523390ca34f',
    'exchange-private/exchange.json': '4fe057dab5d0f15c35e102d73c776151469a59fb442067a1b3313aa36b5f83ca',
}
PYTHON_OVERRIDES = frozenset(('PYTHONPATH', 'PYTHONHOME', 'PYTHONPYCACHEPREFIX', 'PYTHONOPTIMIZE',
                              'PYTHONSAFEPATH', 'PYTHONINSPECT'))


def load(name, path, pin, reader=None):
    path = Path(path)
    if path.resolve(strict=True) != path or not path.is_file() or path.stat().st_nlink != 1:
        raise ValueError('Enrollment source custody changed.')
    raw = reader(path, pin) if reader else path.read_bytes()
    if sha256(raw).hexdigest() != pin or name in sys.modules:
        raise ValueError('Enrollment source pin or import origin changed.')
    module = ModuleType(name); module.__file__ = str(path); sys.modules[name] = module
    exec(compile(raw, str(path), 'exec'), module.__dict__)
    return module


def controls(connection, *, allowed_pilot=None):
    """Read only; never acquire or retain the wrapper scheduler lease."""
    settings = {key: json.loads(value) for key, value in connection.execute(
        "SELECT key,value FROM settings WHERE key IN ('queue_enabled','campaign_enabled','autopilot_enabled','pilot_task')")}
    tasks = [json.loads(row[0]) for row in connection.execute('SELECT state FROM tasks')]
    if (settings.get('queue_enabled', True) or settings.get('campaign_enabled', False)
            or settings.get('autopilot_enabled', False)
            or settings.get('pilot_task') not in (None, allowed_pilot)
            or any(task['status'] in ('RUNNING', 'QUEUED', 'PAUSING') for task in tasks)
            or connection.execute("SELECT 1 FROM inference_receipts WHERE status IN ('DISPATCHING','UNCERTAIN') LIMIT 1").fetchone()
            or connection.execute('SELECT 1 FROM receipts WHERE result IS NULL LIMIT 1').fetchone()):
        raise ValueError('Coordinator controls or unfinished work prevent enrollment restart.')


def process_scope(raw, scoped):
    result, seen = {}, set()
    for item in raw.split(b'\0'):
        if not item:
            continue
        key, separator, value = item.partition(b'=')
        name = key.decode()
        if not separator or name in seen or name in PYTHON_OVERRIDES:
            raise ValueError('Unexpected wrapper startup environment.')
        seen.add(name)
        if name in scoped:
            result[name] = value.decode()
    return result



def require_expired_stopped(task, *, now):
    """Accept real supported pause + pilot-stop, never a translated status."""
    activated = task.get('activated_at') if isinstance(task, dict) else None
    if (not isinstance(task, dict) or task.get('id') != TASK
            or task.get('status') != 'PAUSED' or task.get('stop_requested') is not True
            or task.get('mode') != 'develop' or task.get('phase') != 'inspect'
            or task.get('workflow_version') != 2
            or task.get('time_budget_policy') != 'one_hour_from_first_assignment_including_pauses'
            or type(activated) not in (int, float) or not math.isfinite(activated)
            or activated != ORIGINAL_ACTIVATED_AT
            or type(now) not in (int, float) or not math.isfinite(now) or now < activated + 3600
            or type(task.get('sessions')) is not int or task['sessions'] < 1):
        raise ValueError('The exact actually stopped task must exhaust its original hour.')
    return activated + 3600


def expired_owner(armer, *, root, request_id, request_sha256, terminal_proof, now):
    if request_id != REQUEST or request_sha256 != REQUEST_PIN:
        raise ValueError('Only the original Embraer request can be withdrawn.')
    path = armer._owner_path(root, request_id)
    existing = armer._read_owner(path)
    enrollment = existing.get('enrollment')
    if (not isinstance(enrollment, dict) or enrollment.get('request_id') != REQUEST
            or enrollment.get('request_sha256') != REQUEST_PIN or existing.get('outcome_id') != OUTCOME):
        raise ValueError('Original enrollment ownership differs.')
    proof = terminal_proof(enrollment=enrollment, outcome_id=OUTCOME)
    if (not isinstance(proof, dict) or proof.get('request_id') != REQUEST
            or proof.get('outcome_id') != OUTCOME or proof.get('unresolved_inferences') != 0
            or any(proof.get(key) != ORIGINAL_PAIRED_RECEIPT
                   for key in ('sender_receipt_sha256', 'receiver_receipt_sha256'))):
        raise ValueError('Original settled sender and receiver proof is required.')
    require_expired_stopped(proof.get('task'), now=now)
    receipts = {key: proof[key] for key in ('sender_receipt_sha256', 'receiver_receipt_sha256')}
    if existing.get('disarm_receipts', receipts) != receipts:
        raise ValueError('Previously saved withdrawal receipts differ.')
    return path, existing, proof, receipts


def withdraw_expired(armer, environment, *, root, request_id, request_sha256,
                     terminal_proof, system, inspect_wrapper, check_quiescent, now):
    # Preserve the original owner receipt/environment replay convention.  No
    # coordinator state is written and no value is translated for its old gate.
    check_quiescent()
    path, existing, proof, receipts = expired_owner(armer, root=root,
        request_id=request_id, request_sha256=request_sha256, terminal_proof=terminal_proof, now=now)
    if 'disarm_receipts' not in existing:
        armer._replace_private(path, {**existing, 'disarm_receipts': receipts})
    result = environment.reconcile_enrollment(existing['enrollment'], enabled=False,
        system=system, inspect_wrapper=inspect_wrapper, check_quiescent=check_quiescent)
    check_quiescent()
    return {**result, 'outcome_id': OUTCOME, 'owner_record': str(path), 'task_id': TASK,
            'original_deadline': proof['task']['activated_at'] + 3600}


def load_runtime(entry_pin):
    deployment = load('embraer_deployment_entry', DEPLOYMENT / 'native_source_release_entry.py', DEPLOYMENT_ENTRY_PIN)
    custody = load('embraer_enrollment_custody', deployment.CUSTODY, deployment.CUSTODY_PIN)
    read = custody.file_bytes
    read(Path(__file__).resolve(), entry_pin)
    approval = json.loads(read(DEPLOYMENT / 'APPLY_APPROVAL.json', APPROVAL_PIN, private=True))
    bootstrap = load('release_admission_bootstrap', PROJECT / 'release_admission_bootstrap.py', BOOTSTRAP_PIN, read)
    bootstrap._load_environment(PROJECT / '.env')
    runtime = bootstrap._validate_runtime(PROJECT, ROOT)
    if (runtime.get('state') != 'COMPLETE' or runtime.get('release_id') != approval['source_approval']['release_id']
            or runtime.get('source_manifest_sha256') != approval['source_approval']['source_sha256']):
        raise ValueError('The exact deployed Embraer runtime is required before application imports.')
    read(ROOT / 'integration-release-journal.json', ACTIVE_JOURNAL_PIN, private=True)
    read(ROOT / 'native-runtime-releases' / runtime['release_id'] / 'receipt.json', ACTIVE_RECEIPT_PIN, private=True)
    package = json.loads(read(DEPLOYMENT / 'PREPARED_PACKAGE.json', approval['package_sha256'], private=True))
    for name, pair in package['package_files'].items():
        read(PROJECT / name, pair['staged']['sha256'])
    sys.path[:0] = [str(PROJECT / 'src'), str(TOOLS)]
    from job_search_helper.cli import load_environment
    load_environment(PROJECT / '.env')
    load('native_source_advance', DEPLOYMENT / 'native_source_advance.py',
         approval['tool_sha256']['native_source_advance.py'], read)
    owner_module = load('maintenance_source_owner', DEPLOYMENT / 'maintenance_source_owner.py',
                       approval['tool_sha256']['maintenance_source_owner.py'], read)
    owner = owner_module.MaintenanceSourceOwner(PROJECT, DEPLOYMENT, approval['package_sha256'])
    if owner.status()['phase'] != 'STAGED':
        raise ValueError('Embraer source transaction is not complete.')
    prior = load('embraer_enrollment_native_loader', deployment.PRIOR_ENTRY, deployment.PRIOR_ENTRY_PIN, read)
    prior.NATIVE_STAGE = STAGE / 'native-window'
    prior.INSTALLED_PINS = {**prior.INSTALLED_PINS,
                           'host_server.py': package['package_files']['dev/wrapper-coder/tools/host_server.py']['staged']['sha256']}
    loaded = prior.verify_tool_origins()
    native, modules = prior.load_native_window(loaded, approval['native']['window_sha256'])
    window = native.create_window(release_id=owner.release_id, manifest_sha256=owner.manifest_pin,
        manifest=owner.manifest, approval_check=lambda: json.loads(read(
            DEPLOYMENT / 'APPLY_APPROVAL.json', APPROVAL_PIN, private=True))['source_approval'],
        window_root=Path(approval['native']['window_root']), native_modules=modules,
        wrapper_scope_sha256=approval['native']['wrapper_scope_sha256'], source_owner=owner, resume_complete=True)
    libraries = {name: load(name, ENROLLMENT_TOOLS / (name + '.py'), pin, read) for name, pin in PINS.items()}
    return deployment, read, owner, native, window, libraries


def main(argv=None):
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument('action', choices=('inspect', 'disarm'))
    parser.add_argument('--request-id', required=True)
    parser.add_argument('--request-sha256', required=True)
    parser.add_argument('--entry-sha256', required=True)
    args = parser.parse_args(argv)
    if (not sys.flags.isolated or not sys.flags.dont_write_bytecode or sys.pycache_prefix != '/dev/null'
            or Path(sys.prefix).resolve(strict=True) != PROJECT / '.venv'):
        raise ValueError('Use installed Python -I -B -X pycache_prefix=/dev/null.')
    if (args.request_id != REQUEST or args.request_sha256 != REQUEST_PIN
            or any(not re.fullmatch(r'[0-9a-f]{64}', value) for value in (args.request_sha256, args.entry_sha256))):
        raise ValueError('Exact operator request and reviewed entry pins are required.')
    deployment, read, owner, native, window, libs = load_runtime(args.entry_sha256)
    environment, armer, inputs = (libs[name] for name in
        ('embraer_pilot_environment', 'embraer_pilot_arming', 'embraer_operator_enrollment_input'))
    from job_search_helper.inbox import InventoryInbox
    from job_search_helper.operator_embraer_settlement import read_operator_embraer_source
    from job_search_helper.sqlite_repository import SQLiteRepository
    from embraer_operator_pilot import EmbraerOperatorEnrollment

    database = TOOLS.parent / 'tasks/tasks.sqlite3'
    def open_receiver():
        native.physical(database)
        db = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)
        db.execute('BEGIN')
        return db
    destination = InventoryInbox.destination_id(ROOT / 'inventories.sqlite3')
    def read_enrollment(**selected):
        return inputs.read_operator_embraer_enrollment(state_root=ROOT,
            expected_source_manifest_sha256=owner.spec['staged_source_sha256'],
            repository_factory=lambda path: SQLiteRepository(path, destination, readonly=True),
            source_reader=read_operator_embraer_source, **selected)

    # These existing physical locks are held across the targeted restart.
    # The restarted host can acquire its own scheduler lease immediately;
    # its selected application catch-up waits for our scraper lease to exit.
    window._modules()
    with window.c.lock(native.physical(PROJECT / 'dev/wrapper-coder/repairs/deployment.lock')), \
            window.c.lock(native.physical(ROOT / 'scraper.lock')):
        window._approval()
        window._lineage(check_restored=False)
        restored = {name: json.loads(read(window.root / name, pin, private=True)) for name, pin in RESTORED.items()}
        record = restored['native-window.json']
        if (record['phase'] != 'RESTORED' or record['binding'] != window._binding()
                or restored['operator-quiet-window.json']['phase'] != 'RESTORED'
                or restored['exchange-private/exchange.json']['phase'] != 'restored'
                or record['terminal'] != window._terminal()):
            raise ValueError('The exact source deployment window is not restored.')
        exchange = window.x.HostExchange(window.root / 'exchange-private/policy.json', record['exchange']['policy_sha256'])
        if exchange.witness('restored').terminal_proof_sha256 != record['restoration_sha256']:
            raise ValueError('The original checkout routes are not restored.')
        window.policy = replace(window.policy, maintenance_id=MAINTENANCE,
                                ancillary_process_evidence=OBSERVER)
        policy, h, route = window.policy, window.h, window.r
        bridge_unit = h.unit_status(policy.systemctl, native.BRIDGE)
        bridge_pid = int(bridge_unit['MainPID'])
        if (bridge_pid <= 0 or bridge_unit['ActiveState'] != 'active'
                or bridge_unit['UnitFileState'] != 'enabled'
                or bridge_unit['FragmentPath'] != str(native.BRIDGE_UNIT)
                or bridge_unit['ControlGroup'] != route.BRIDGE_CGROUP):
            raise ValueError('The existing assistant bridge identity differs.')
        bridge = (bridge_pid, h.process_start(Path('/proc') / str(bridge_pid)))
        for path, pin in ((native.BRIDGE_UNIT, native.BRIDGE_UNIT_SHA), (native.BRIDGE_SOURCE, native.BRIDGE_SOURCE_SHA),
                          (policy.wrapper_unit_file, UNIT_PIN)):
            read(path, pin)

        selected, outcome_id = read_enrollment(request_id=args.request_id, request_sha256=args.request_sha256)
        if outcome_id != OUTCOME:
            raise ValueError('Unexpected original operator outcome.')
        enrollment = EmbraerOperatorEnrollment(**selected)
        if not enrollment._sources_match(PROJECT):
            raise ValueError('The installed pilot baseline changed.')

        def terminal_proof(*, enrollment, outcome_id):
            if enrollment != selected:
                raise ValueError('The terminal proof belongs to another enrollment.')
            actor = EmbraerOperatorEnrollment(**enrollment)
            source = actor._source(ROOT / 'jobs.sqlite3', destination)
            paired = actor._paired(SimpleNamespace(path=database), source) if source else None
            if (not paired or source['record']['outcome_id'] != outcome_id
                    or not actor._task_matches(*paired, actor._proposal(paired[0], source['company']))):
                raise ValueError('The exact paired terminal task is unavailable.')
            task = paired[1]
            with closing(open_receiver()) as db:
                current = db.execute('SELECT state FROM tasks WHERE id=?', (task['id'],)).fetchone()
                if current is None or json.loads(current[0]) != task:
                    raise ValueError('The terminal task changed during readback.')
                controls(db)
                inference = db.execute('SELECT status FROM inference_receipts WHERE task=?', (TASK,)).fetchall()
                if not inference or any(row[0] != 'COMPLETED' for row in inference):
                    raise ValueError('The original task inference receipts must all be completed.')
                receipt = db.execute('SELECT receipt_sha256 FROM scrape_outcome_delivery_receipts '
                    'WHERE consumer=? AND outcome_id=?', ('repair-coordinator', outcome_id)).fetchone()
            return {'request_id': args.request_id, 'outcome_id': outcome_id, 'task': task,
                    'unresolved_inferences': 0, 'sender_receipt_sha256': source['row'][7],
                    'receiver_receipt_sha256': receipt[0]}

        _, _, proof, _ = expired_owner(armer, root=ROOT, request_id=args.request_id,
            request_sha256=args.request_sha256, terminal_proof=terminal_proof, now=time.time())

        def system(*arguments):
            return subprocess.run([str(policy.systemctl), '--user', *arguments], check=True,
                                  capture_output=True, text=True, timeout=70).stdout

        def check_quiescent():
            if owner.status()['phase'] != 'STAGED':
                raise ValueError('The installed source owner changed.')
            window._terminal()
            read(ROOT / 'integration-release-journal.json', ACTIVE_JOURNAL_PIN, private=True)
            for unit in (native.SYNC, native.TIMER):
                if (system('show', unit, '-p', 'ActiveState', '--value').strip() != 'inactive'
                        or system('show', unit, '-p', 'UnitFileState', '--value').strip() != 'disabled'):
                    raise ValueError('Scheduled synchronization must remain disabled.')
            with closing(open_receiver()) as db:
                controls(db)
            if terminal_proof(enrollment=selected, outcome_id=outcome_id) != proof:
                raise ValueError('The stopped task or original receipt pair changed.')
            require_expired_stopped(proof['task'], now=time.time())

        def inspect_wrapper_once():
            if h.unit_status(policy.systemctl, native.BRIDGE) != bridge_unit:
                raise ValueError('The assistant bridge changed during enrollment.')
            for path, pin in ((native.BRIDGE_UNIT, native.BRIDGE_UNIT_SHA), (native.BRIDGE_SOURCE, native.BRIDGE_SOURCE_SHA),
                              (policy.wrapper_unit_file, UNIT_PIN)):
                read(path, pin)
            wrapper = h.unit_status(policy.systemctl, native.WRAPPER)
            pid = int(wrapper['MainPID'])
            if (pid <= 0 or wrapper['ActiveState'] != 'active' or wrapper['UnitFileState'] != 'enabled'
                    or wrapper['FragmentPath'] != str(policy.wrapper_unit_file)):
                raise ValueError('The expected wrapper is not ready.')
            start = h.verify_wrapper_process(policy, pid, Path('/proc'))
            listening = h.verify_listener(policy, pid, Path('/proc'))
            for helper in (1249, 4467):
                if h.verify_ancillary_process(OBSERVER, Path('/proc') / str(helper),
                    policy.launch_uid, MAINTENANCE, h.checkout_routes(policy),
                    listener=(policy.wrapper_port, listening)) is not True:
                    raise ValueError('Current authenticated writer-exclusion observer is required.')
            route.verify_two_tool_route_drain(policy, pid, Path('/proc'), bridge)
            scoped = process_scope((Path('/proc') / str(pid) / 'environ').read_bytes(), environment.SCOPED)
            if h.verify_wrapper_process(policy, pid, Path('/proc')) != start:
                raise ValueError('Wrapper identity changed during inspection.')
            return pid, scoped

        def inspect_wrapper():
            deadline = time.monotonic() + 12
            while True:
                try:
                    return inspect_wrapper_once()
                except (OSError, ValueError):
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(0.3)

        check_quiescent()
        pid, process = inspect_wrapper()
        manager = environment.manager_scope(system)
        expected = {environment.ENROLLMENT: json.dumps(selected, sort_keys=True, separators=(',', ':'))}
        if manager not in ({}, expected) or process not in ({}, expected):
            raise ValueError('A foreign scope owns the wrapper environment.')
        if args.action == 'inspect':
            result = {'state': 'EMBRAER_EXPIRED_WITHDRAWAL_INSPECTED', 'request_id': args.request_id,
                      'outcome_id': outcome_id, 'wrapper_pid': pid, 'scope_present': bool(process),
                      'release_id': owner.release_id, 'task_id': TASK,
                      'original_deadline': proof['task']['activated_at'] + 3600}
        else:
            result = withdraw_expired(armer, environment, root=ROOT, request_id=args.request_id,
                request_sha256=args.request_sha256, terminal_proof=terminal_proof,
                system=system, inspect_wrapper=inspect_wrapper, check_quiescent=check_quiescent, now=time.time())
        print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
