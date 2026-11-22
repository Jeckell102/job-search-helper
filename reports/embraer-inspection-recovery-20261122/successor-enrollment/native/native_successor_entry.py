"""Measured wrapper-only coordinator update; inspect is the default action."""
import argparse
from contextlib import ExitStack, closing, contextmanager
from dataclasses import replace
from hashlib import sha256
from importlib.machinery import PathFinder, SourceFileLoader
from importlib.util import cache_from_source
import json
import os
import shutil
from tempfile import TemporaryDirectory
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
REQUEST = 'operator-embraer-20261122-02'
REQUEST_SHA = 'bea920fe5fbea9382a180bbffd4534dd4ac7dc7608b5a0c7a4021eec11dd4e4b'
OUTCOME = 'OUT-f5084fdec013f314e5353c0c'
MAINTENANCE = 's6-embraer-successor-20261122-14'
OBSERVER = Path('/run/jsh-s6-embraer-successor-14/observer.sock')
ENTRY = HERE/'native_runtime.py'
ENTRY_PIN = '05377be0ff3124e2fb641b378443251f63ec415d9de3dddc11e7bb12913f7521'
ATOMIC = Path('/tmp/jsh-amphenol-native-two-tool.HQkjpe8m/deploy_two_tool_forward.py')
ATOMIC_PIN = 'cf9f82f6b85f441ab2e0fdd9bfee1448aa6c1e444ade09a3e66e2748ebb75597'
FORWARD_PIN = 'a91aa6f7c67948415a346215ca5e51fd6a652dd23b697662ccafb3a6ae8d287a'
PROJECTION_PIN = '64f4a0372603faf4ae2b9c5c33950a4bf836979cae774749d79c430e21fecd12'
ENVIRONMENT_PIN = 'f86bb7e48d0c36f2fe5edb47baba1544b91ed7ec9df4be46a65018b188f610fc'
INPUT_PIN = 'f71c9ce417967b1cb27f083ae3f95577d5b88c41bc69087f4bb2bf5283f4165b'
PRIOR = STAGE/'inspection-recovery/forward'
PRIOR_RECEIPT = '9d3798a65d403743a84e4fee3783f86df1e80d9c2f9e5e8e16849aa8ffbcb48b'
CANDIDATE = HERE/'embraer_operator_pilot.py'


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


def main(argv=None):
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument('action', choices=('prepare-baseline', 'inspect', 'apply-and-arm', 'arm', 'rollback'), nargs='?', default='inspect')
    parser.add_argument('--entry-sha256', required=True)
    parser.add_argument('--approved-snapshot-sha256')
    args = parser.parse_args(argv)
    require(sys.flags.isolated and sys.flags.dont_write_bytecode and sys.pycache_prefix == '/dev/null'
            and Path(sys.prefix).resolve() == PROJECT/'.venv', 'Use installed Python -I -B -X pycache_prefix=/dev/null')
    require(sha256(Path(__file__).read_bytes()).hexdigest() == args.entry_sha256, 'Reviewed native entry differs')
    entry = load('embraer_successor_native_runtime', ENTRY, ENTRY_PIN)
    forward = load('embraer_successor_forward', HERE/'successor_tool_forward.py', FORWARD_PIN)
    atomic = load('embraer_successor_atomic', ATOMIC, ATOMIC_PIN)
    projection_module = load('embraer_successor_projection', HERE/'native_projection.py', PROJECTION_PIN)
    root = HERE/'transaction'
    require(root.resolve(strict=True) == root and stat.S_IMODE(root.stat().st_mode) == 0o700,
            'Prepared private transaction directory required')
    intent = json.loads(atomic._read(root/'intent.json')[0]) if (root/'intent.json').exists() else None
    terminal = json.loads(atomic._read(root/'receipt.json')[0]) if (root/'receipt.json').exists() else None
    authority = {'intent':intent,'receipt':terminal}
    _, read, owner, native, window, libraries, projection = entry.load_runtime(ENTRY_PIN,forward,authority,projection_module)
    prior = load('embraer_prior_forward', PRIOR/'coordinator_forward.py','d96d3da055571ebd7528adb6bb61a0b3e82387bef5eef4c96838826aa63e8437')
    prior_native = load('embraer_prior_native', PRIOR/'native_forward.py','971c5a0469ad650fcd0d4640a73812c4d8806c1008ed21b03ac6cfc10e048261')
    receipt_reader = load('embraer_prior_receipt_reader',STAGE/'inspection-recovery/disarm/native_embraer_disarm.py','eb5fe67a0b13f120109e1bf337cd409758664fa2c6963a9ff2bef26af0874003')
    window._modules()
    prior_receipt=receipt_reader.verified_forward_receipt(read,window,prior,PRIOR_RECEIPT)
    window=prior_native.extended_window(window,native,prior,prior_receipt['transition'])
    window=projection.wrap_window(window)
    environment=load('embraer_successor_environment',HERE/'successor_environment.py',ENVIRONMENT_PIN)
    inputs=load('embraer_successor_input',HERE.parent/'embraer_successor_enrollment_input.py',INPUT_PIN)
    from job_search_helper.inbox import InventoryInbox
    from job_search_helper.operator_embraer_settlement import read_operator_embraer_source
    from job_search_helper.sqlite_repository import SQLiteRepository
    from coordinator_baseline import files, binding
    destination=InventoryInbox.destination_id(STATE/'inventories.sqlite3')
    original_reader=libraries['embraer_operator_enrollment_input'].read_operator_embraer_enrollment
    def selected_input():
        value,outcome=inputs.read_operator_embraer_successor_enrollment(state_root=STATE,wrapper_base=TOOLS.parent,
            expected_source_manifest_sha256=owner.spec['staged_source_sha256'],original_reader=original_reader,
            repository_factory=lambda p:SQLiteRepository(p,destination,readonly=True),
            source_reader=read_operator_embraer_source,baseline_files=files,baseline_binding=binding)
        require(outcome==OUTCOME,'Fresh successor outcome differs')
        return value
    selected=None
    expected_environment={}
    database=TOOLS.parent/'tasks/tasks.sqlite3'
    native.physical(database)
    def stopped_snapshot():
        with closing(sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)) as db:
            db.execute('BEGIN'); entry.controls(db)
            rows=db.execute('SELECT state FROM tasks WHERE id=?',(TASK,)).fetchall()
            require(len(rows)==1,'Predecessor task is not unique')
            task=json.loads(rows[0][0])
            require(sha256(json.dumps(task,sort_keys=True,separators=(',',':')).encode()).hexdigest()==inputs.OWNER_PINS['predecessor_task_state_sha256'],
                    'Stopped predecessor task changed')
            inf=db.execute('SELECT request_id,status,data FROM inference_receipts WHERE task=? ORDER BY request_id',(TASK,)).fetchall()
            require(len(inf)==6 and all(row[1]=='COMPLETED' for row in inf),'Original six receipts differ')
            receipts=db.execute('SELECT * FROM receipts WHERE task=? ORDER BY id',(TASK,)).fetchall()
        return {'task_sha256':inputs.OWNER_PINS['predecessor_task_state_sha256'],
                'inference_sha256':forward.digest(inf),'tool_receipts_sha256':forward.digest(receipts)}
    def snapshot():
        return {**stopped_snapshot(),'enrollment':selected_input(),'prior_forward_receipt_sha256':PRIOR_RECEIPT}

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
        require(environment.manager_scope(system) in ({},expected_environment), 'Manager enrollment changed')

    def active():
        h, policy = window.h, window.policy
        unit = h.unit_status(policy.systemctl, native.WRAPPER); pid = int(unit['MainPID'])
        require(pid > 0 and unit['ActiveState'] == 'active' and unit['UnitFileState'] == 'enabled'
                and unit['FragmentPath'] == str(policy.wrapper_unit_file), 'Wrapper is not active on exact unit')
        identity = h.verify_wrapper_process(policy, pid, Path('/proc'))
        services(pid, active=True)
        require(entry.process_scope((Path('/proc')/str(pid)/'environ').read_bytes(), environment.SCOPED)
                in ({},expected_environment), 'Wrapper process enrollment changed')
        require(h.verify_wrapper_process(policy, pid, Path('/proc')) == identity, 'Wrapper changed during readback')
        return pid, int(system('show', native.WRAPPER, '-p', 'ExecMainStartTimestampMonotonic', '--value'))

    def source_selection(expected):
        path = PROJECT/forward.RELATIVE
        PathFinder.invalidate_caches()
        found = PathFinder.find_spec('embraer_operator_pilot', [str(TOOLS)])
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
            receipt_reader.verified_forward_receipt(read,window,prior,PRIOR_RECEIPT)
            projection.verify()
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
                       restored_records=entry.RESTORED, original_wrapper_scope_sha256=window.wrapper_scope_sha256,
                       prior_forward_receipt_sha256=PRIOR_RECEIPT)

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
        authority['intent']=transition
        projection.verify()
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
                            enrollment_sha256=forward.digest(selected_input()))
            except (OSError, ValueError):
                if time.monotonic() >= deadline: raise
                time.sleep(.3)

    def publish_baseline():
        source=STAGE/'successor-evidence'/('embraer-'+inputs.BASELINE)
        target=TOOLS.parent/'pilot-bases'/source.name
        require(source.resolve(strict=True)==source and binding(files(source))['digest']==inputs.BASELINE,
                'Approved private baseline changed')
        if target.exists() or target.is_symlink():
            require(target.resolve(strict=True)==target and binding(files(target))['digest']==inputs.BASELINE,
                    'Existing successor baseline differs')
            return
        require(target.parent.resolve(strict=True)==target.parent,'Canonical pilot baseline parent differs')
        with TemporaryDirectory(prefix='.successor-',dir=target.parent) as temporary:
            staged=Path(temporary)/'baseline'; shutil.copytree(source,staged,symlinks=False)
            require(binding(files(staged))['digest']==inputs.BASELINE,'Copied baseline differs')
            for path in staged.rglob('*'):
                if path.is_file():
                    with path.open('rb') as stream:os.fsync(stream.fileno())
            for parent,_,_ in os.walk(staged,topdown=False):
                fd=os.open(parent,os.O_RDONLY|os.O_DIRECTORY)
                try:os.fsync(fd)
                finally:os.close(fd)
            require(not os.path.lexists(target),'Baseline appeared during preparation')
            os.rename(staged,target); fd=os.open(target.parent,os.O_RDONLY|os.O_DIRECTORY)
            try:os.fsync(fd)
            finally:os.close(fd)
    if args.action=='prepare-baseline':
        with atomic._deployment_lock(PROJECT),guard():
            before=stopped_snapshot();publish_baseline();selected=selected_input()
            require(stopped_snapshot()==before,'Predecessor changed while preparing baseline')
            print(json.dumps({'state':'SUCCESSOR_BASELINE_PREPARED','baseline_sha256':inputs.BASELINE},sort_keys=True))
        return 0
    selected=selected_input()
    if args.action=='arm':
        expected_environment={environment.ENROLLMENT:json.dumps(selected,sort_keys=True,separators=(',',':'))}
    candidate=read(CANDIDATE,forward.AFTER)
    if args.action=='inspect':
        with atomic._deployment_lock(PROJECT),guard() as predecessor:
            value=snapshot();source_selection(forward.BEFORE if intent is None else sha256((PROJECT/forward.RELATIVE).read_bytes()).hexdigest())
            print(json.dumps({'state':'SUCCESSOR_FORWARD_INSPECTED','snapshot':value,'snapshot_sha256':forward.digest(value),'predecessor':predecessor},sort_keys=True))
        return 0
    require(isinstance(args.approved_snapshot_sha256,str) and len(args.approved_snapshot_sha256)==64,
            'Exact independently read stopped snapshot pin is required')
    if args.action!='arm':
        require(args.action in ('apply-and-arm','rollback'),'Unknown successor action')
        result=forward.apply(project=PROJECT,candidate=candidate,receipt_directory=root,atomic=atomic,
            guard=guard,snapshot=snapshot,approved_snapshot_sha256=args.approved_snapshot_sha256,
            stop=stop,stopped=stopped,start=start,ready=ready,
            reference=lambda p:[*window.c.ref(p),p.stat().st_mtime_ns],rollback_only=args.action=='rollback')
        authority['receipt']=result;authority['intent']=result['transition']
        if args.action=='rollback':
            print(json.dumps({'state':'ROLLED_BACK','receipt_sha256':forward.digest(result)},sort_keys=True));return 0
    # No enclosing rollback handler exists after the source receipt is terminal.
    with atomic._deployment_lock(PROJECT),guard() as predecessor:
        result=json.loads(atomic._read(root/'receipt.json')[0])
        require(result==authority['receipt'] and result['status']=='INSTALLED','Arm requires exact installed source receipt')
        require(result['transition']['predecessor']==predecessor,'Installed source predecessor changed')
        projection.verify();current=snapshot()
        require(result['transition']['snapshot']==current,'Installed source snapshot differs from arm owner')
        require(forward.digest(current)==args.approved_snapshot_sha256,'Successor input changed before arm')
        selected=current['enrollment'];expected_environment={environment.ENROLLMENT:json.dumps(selected,sort_keys=True,separators=(',',':'))}
        armer=libraries['embraer_pilot_arming'];path=armer._owner_path(STATE,REQUEST)
        owner_record={'schema':armer._SCHEMA,'enrollment':selected,'outcome_id':OUTCOME}
        if path.exists():require(armer._read_owner(path)==owner_record,'Fresh successor enrollment owner differs')
        else:armer._write_new_private(path,owner_record)
        def quiet():
            require(snapshot()==current,'Stopped successor authority changed')
            projection.verify();window._terminal()
        def inspect_scoped():
            pid,_=active()
            return pid,entry.process_scope((Path('/proc')/str(pid)/'environ').read_bytes(),environment.SCOPED)
        armed=environment.reconcile_enrollment(selected,enabled=True,system=system,
            inspect_wrapper=inspect_scoped,check_quiescent=quiet)
        require(stopped_snapshot()=={k:current[k] for k in ('task_sha256','inference_sha256','tool_receipts_sha256')},
                'Predecessor changed before releasing application ownership')
        arm_raw=forward.canonical({**armed,'state':'EMBRAER_SUCCESSOR_ARMED',
            'outcome_id':OUTCOME,'source_receipt_sha256':forward.digest(result),'enrollment_sha256':forward.digest(selected)})
        if (root/'armed.json').exists():
            require(atomic._visible_exact(root/'armed.json',arm_raw),'Existing arm receipt differs')
        else:atomic._write_new_private(root/'armed.json',arm_raw)
        print(json.dumps({'state':'EMBRAER_SUCCESSOR_ARMED','outcome_id':OUTCOME,'source_receipt_sha256':forward.digest(result)},sort_keys=True))
    return 0


if __name__=='__main__':raise SystemExit(main())
