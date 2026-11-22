"""One guarded source-only forward for the exact held Embraer #03 task."""
import argparse
from contextlib import ExitStack, closing, contextmanager
from dataclasses import replace
from hashlib import sha256
from importlib.machinery import PathFinder, SourceFileLoader
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
STAGE = Path('/tmp/jsh-embraer-owned-pilot.xXaXrqW0')
PROJECT = Path('/home/chris/job-search-helper_old')
TOOLS = PROJECT/'dev/wrapper-coder/tools'
STATE = PROJECT/'.state'
TASK = 'WRAP-250158dc79'
REQUEST = 'operator-embraer-20261122-03'
REQUEST_SHA = 'cfec4cac835ece828aeb3c1a583441b272c1dab3c764382b39c112651d2789d0'
OUTCOME = 'OUT-89a8561a79f99e2b3c3eb243'
MAINTENANCE = 's6-embraer-continuation-20261122-16'
OBSERVER = Path('/run/jsh-s6-embraer-continuation-16/observer.sock')
CURRENT = STAGE/'successor-enrollment/native'
ENTRY = CURRENT/'native_runtime.py'
CHAIN_PIN = '1cba4ef8cd7443cf06ce62ffc99101b843da56d968ec7ee893d2e2cbef9947e1'
ENTRY_PIN = '05377be0ff3124e2fb641b378443251f63ec415d9de3dddc11e7bb12913f7521'
ATOMIC = Path('/tmp/jsh-amphenol-native-two-tool.HQkjpe8m/deploy_two_tool_forward.py')
ATOMIC_PIN = 'cf9f82f6b85f441ab2e0fdd9bfee1448aa6c1e444ade09a3e66e2748ebb75597'
FORWARD_PIN = '521949832311937c8848018f9bad85c90ada6c9ce36bab68551150e2d6dcb11f'


def require(test, message):
    if not test: raise ValueError(message)


def load(name, path, pin):
    from types import ModuleType
    require(path.resolve(strict=True) == path and path.is_file() and path.stat().st_nlink == 1,
            'Expected physical measured maintenance source')
    raw = path.read_bytes()
    require(sha256(raw).hexdigest() == pin and name not in sys.modules, 'Maintenance source pin differs')
    module = ModuleType(name); module.__file__ = str(path); sys.modules[name] = module
    exec(compile(raw, str(path), 'exec'), module.__dict__)
    return module


CURRENT_RECEIPT = '97c83a0eacab6d960ae3e5e12507394d0bd4b2da1cedb0351b483a68377eb0a9'
TASK_STATE_PIN = 'a3382522f213eb3c82716bbb69d9c335ec4b7d11f458e6c8fb5828922a73b4e1'
PAIRED_RECEIPT = '590131cc1750e08c2eaf087046cec4a90ee5be3642c79d905ffff52ba1744b2b'
def require_held(task):
    require(isinstance(task, dict) and task.get('id') == TASK
            and task.get('status') == 'PAUSED_BUDGET' and task.get('phase') == 'implement'
            and task.get('mode') == 'develop' and task.get('inference_session_open') is False
            and tuple(task.get(key) for key in ('sessions', 'calls', 'tokens')) == (7, 15, 118059),
            'Exact settled budget-held #03 parent is required')


def main(argv=None):
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument('inspection', type=Path)
    parser.add_argument('--entry-sha256', required=True)
    parser.add_argument('--inspection-file-sha256', required=True)
    parser.add_argument('--approved-snapshot-sha256', required=True)
    args = parser.parse_args(argv)
    require(sys.flags.isolated and sys.flags.dont_write_bytecode and sys.pycache_prefix == '/dev/null'
            and Path(sys.prefix).resolve() == PROJECT/'.venv', 'Use installed Python -I -B -X pycache_prefix=/dev/null')
    require(sha256(Path(__file__).read_bytes()).hexdigest() == args.entry_sha256, 'Reviewed native entry differs')
    entry = load('embraer_context_runtime',ENTRY,ENTRY_PIN)
    forward = load('embraer_context_forward',STAGE/'successor-context-repair/native/coordinator_forward.py',FORWARD_PIN)
    atomic = load('embraer_context_atomic',ATOMIC,ATOMIC_PIN)
    tool = load('embraer_current_tool_forward',CURRENT/'successor_tool_forward.py','a91aa6f7c67948415a346215ca5e51fd6a652dd23b697662ccafb3a6ae8d287a')
    projection_module=load('embraer_current_projection',CURRENT/'native_projection.py','64f4a0372603faf4ae2b9c5c33950a4bf836979cae774749d79c430e21fecd12')
    root=STAGE/'successor-context-repair/native/transaction'
    require(sha256((root/'receipt.json').read_bytes()).hexdigest()==CURRENT_RECEIPT, 'Current coordinator terminal receipt changed')
    require(root.resolve(strict=True)==root and stat.S_IMODE(root.stat().st_mode)==0o700,'Private transaction required')
    intent=json.loads(atomic._read(root/'intent.json')[0]) if (root/'intent.json').exists() else None
    own_receipt=json.loads(atomic._read(root/'receipt.json')[0]) if (root/'receipt.json').exists() else None
    authority={'intent':intent,'receipt':own_receipt}
    raw=(CURRENT/'transaction/receipt.json').read_bytes()
    require(sha256(raw).hexdigest()=='5f65476a121019f8beb573b40333dddd092de71b2c9521e71e16c68f1befb7c4','Installed helper receipt changed')
    tool_receipt=json.loads(raw)
    _,read,owner,native,window,libraries,projection=entry.load_runtime(ENTRY_PIN,tool,
        {'intent':tool_receipt['transition'],'receipt':tool_receipt},projection_module)
    previous=load('embraer_previous_coordinator',STAGE/'inspection-recovery/forward/coordinator_forward.py','d96d3da055571ebd7528adb6bb61a0b3e82387bef5eef4c96838826aa63e8437')
    previous_native=load('embraer_previous_native',STAGE/'inspection-recovery/forward/native_forward.py','971c5a0469ad650fcd0d4640a73812c4d8806c1008ed21b03ac6cfc10e048261')
    chain=load('embraer_context_chain',STAGE/'successor-context-repair/native/coordinator_chain.py',CHAIN_PIN)
    previous_receipt=json.loads(read(STAGE/'inspection-recovery/forward/transaction/receipt.json',
        '9d3798a65d403743a84e4fee3783f86df1e80d9c2f9e5e8e16849aa8ffbcb48b',private=True))
    window._modules()
    window,verify_coordinator=chain.chain_window(window,native,previous,previous_native,
        previous_receipt,forward,authority,PROJECT)
    window=projection.wrap_window(window)
    environment=load('embraer_context_environment',CURRENT/'successor_environment.py','f86bb7e48d0c36f2fe5edb47baba1544b91ed7ec9df4be46a65018b188f610fc')
    five = load('five', Path('/tmp/jsh-embraer-03-continuation-release/five_tool_forward.py'), '6d0e16123ddee3e48e37ad0707a70b117e8770f0f49054187ed6cae860ff24f6')
    custody = load('custody', Path('/tmp/jsh-embraer-03-live-readiness/measure_coordinator_custody.py'), '22d8d9011df6291d67b684bd57a654546be230308146cb338a84a3d5bc6c5d15')
    from job_search_helper.inbox import InventoryInbox
    from coordinator_store import Store
    from embraer_operator_pilot import EmbraerOperatorEnrollment
    destination=InventoryInbox.destination_id(STATE/'inventories.sqlite3')
    armer=libraries['embraer_pilot_arming']
    owner_record=armer._read_owner(armer._owner_path(STATE,REQUEST))
    selected=owner_record.get('enrollment')
    require(owner_record.get('outcome_id')==OUTCOME and selected.get('request_id')==REQUEST
            and selected.get('request_sha256')==REQUEST_SHA and len(selected)==7,
            'Current armed successor owner differs')
    arm_inspect=json.loads(read(Path('/tmp/jsh-embraer-owned-pilot.xXaXrqW0/implementation-recovery/arm-next/LIVE_INSPECT.json'),
        '3fb2aa483ed86d2d0e75b9b03c51df1e5c07ae16aa72cfca3f60528693dc243c', private=True))
    arm_receipt=json.loads(read(Path('/tmp/jsh-embraer-owned-pilot.xXaXrqW0/implementation-recovery/arm-next/LIVE_ARM_RECEIPT.json'),
        '8e4b51732b72c69ce9c404fb39c10f01e56c8dcbdae3dbc799c8695743ff74bf', private=True))
    require(selected==arm_inspect['snapshot']['next_enrollment']
            and OUTCOME==arm_receipt['outcome_id'] and REQUEST==arm_receipt['request_id']
            and forward.digest(selected)==arm_receipt['enrollment_sha256'],
            'Current enrollment differs from the measured #03 arm receipt')
    enrollment=EmbraerOperatorEnrollment.from_process_environment({environment.ENROLLMENT:json.dumps(selected)})
    expected_environment={environment.ENROLLMENT:json.dumps(selected,sort_keys=True,separators=(',',':'))}
    database=TOOLS.parent/'tasks/tasks.sqlite3';native.physical(database)

    def snapshot():
        current_owner=armer._read_owner(armer._owner_path(STATE,REQUEST))
        require(current_owner == owner_record, 'Exact #03 owner record changed')
        source = enrollment._source(STATE/'jobs.sqlite3', destination)
        exact_key = Store._operator_successor_repair_key(enrollment.successor.predecessor_repair_key)
        paired = enrollment._paired(SimpleNamespace(path=database), source, exact_repair_key=exact_key) if source else None
        require(paired is not None and source['record']['outcome_id'] == OUTCOME
                and enrollment._sources_match(PROJECT)
                and enrollment._task_matches(*paired, enrollment._proposal(paired[0], source['company'])),
                'Current paired owned Embraer task is unavailable')
        with closing(sqlite3.connect(database.as_uri()+'?mode=ro', uri=True)) as db:
            db.execute('BEGIN')
            entry.controls(db, allowed_pilot=TASK)
            require(db.execute("SELECT value FROM settings WHERE key='pilot_task'").fetchone() == (json.dumps(TASK),),
                    'Exact idle #03 pilot does not own the lane')
            rows = db.execute('SELECT state FROM tasks WHERE id=?', (TASK,)).fetchall()
            require(len(rows) == 1, 'Selected task is not unique')
            task = json.loads(rows[0][0])
            require(sha256(json.dumps(task,sort_keys=True,separators=(',',':')).encode()).hexdigest()==TASK_STATE_PIN,
                    'Current stopped task differs from independently read canonical snapshot')
            require(task == paired[1], 'Selected task differs from paired owner')
            require_held(task)
            inference = db.execute('SELECT request_id,status,data FROM inference_receipts WHERE task=? ORDER BY request_id', (TASK,)).fetchall()
            require(len(inference) == 15 and all(row[1] == 'COMPLETED' for row in inference), 'Selected inference did not settle')
            receipts = db.execute('SELECT * FROM receipts WHERE task=? ORDER BY id', (TASK,)).fetchall()
            settings = db.execute("SELECT key,value FROM settings WHERE key IN ('queue_enabled','campaign_enabled','autopilot_enabled','pilot_task') ORDER BY key").fetchall()
            pair=db.execute('SELECT receipt_sha256 FROM scrape_outcome_delivery_receipts WHERE outcome_id=?',(OUTCOME,)).fetchall()
            require(pair==[(PAIRED_RECEIPT,)] and source['row'][7]==PAIRED_RECEIPT, 'Original paired successor receipts differ')
        return dict(task_sha256=sha256(rows[0][0].encode()).hexdigest(),
            inference_sha256=forward.digest(inference), tool_receipts_sha256=forward.digest(receipts),
            controls=settings, enrollment=selected, source_proof_sha256=forward.digest(source['proof']),
            outcome_id=OUTCOME, sender_receipt_sha256=source['row'][7],
            existing_coordinator=custody.measure(database))

    def system(*args):
        return subprocess.run([str(window.policy.systemctl), '--user', *args],
            check=True, capture_output=True, text=True, timeout=70).stdout.strip()

    bridge_identity = None
    bridge_unit = None

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

    @contextmanager
    def guard():
        nonlocal bridge_identity, bridge_unit
        c = window.c
        old = c.Controller(native.BUNDLE)
        with ExitStack() as held:
            for path in (old.controller_gate, *old.locks, old.install_gate): held.enter_context(c.lock(path))
            require({str(p): c.inode(p) for p in old.locks} == old.binding['locks'], 'Application lock identity changed')
            window._approval();window._lineage(check_restored=False)
            projection.verify();verify_coordinator()
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
            active()
            yield dict(application_journal_sha256=entry.ACTIVE_JOURNAL_PIN,
                       application_receipt_sha256=entry.ACTIVE_RECEIPT_PIN,
                       restored_records=entry.RESTORED,original_wrapper_scope_sha256=window.wrapper_scope_sha256,
                       coordinator_receipt_sha256=CURRENT_RECEIPT,
                       previous_coordinator_receipt_sha256='9d3798a65d403743a84e4fee3783f86df1e80d9c2f9e5e8e16849aa8ffbcb48b',
                       helper_receipt_sha256='5f65476a121019f8beb573b40333dddd092de71b2c9521e71e16c68f1befb7c4')

    inspection = json.loads(read(args.inspection, args.inspection_file_sha256, private=True))
    evidence = {key: inspection[key] for key in ('snapshot', 'scope', 'predecessor')}
    require(inspection.get('state') == 'EMBRAER_CONTINUATION_NATIVE_FORWARD_INSPECTED'
            and inspection.get('authorization_issued') is False
            and inspection.get('snapshot_sha256') == args.approved_snapshot_sha256 == five.digest(evidence),
            'Exact separately approved native inspection is required')
    scope = five.validate_scope(evidence['scope'])
    candidates = {relative: read(Path('/tmp/jsh-embraer-03-continuation/tools') / Path(relative).name,
                                 scope[relative]['after']['sha256'])
                  for relative in five.PATHS}
    transaction = HERE / 'transaction'
    require(not (transaction/'intent.json').exists(), 'Interrupted source-forward needs exact rollback review')
    new_authority = {}
    start_facts = None

    def reference(path):
        return [*window.c.ref(path), path.stat().st_mtime_ns]

    def existing_snapshot():
        value = snapshot()
        value['existing_coordinator'].pop('continuation_table_exists_and_empty')
        return value

    @contextmanager
    def approved_guard():
        with guard() as predecessor:
            require(five.digest(predecessor) == five.digest(evidence['predecessor'])
                    and five.digest(snapshot()) == five.digest(evidence['snapshot']),
                    'Native custody changed after inspection')
            five.install_custody_projection(window, projection, new_authority, PROJECT, reference)
            yield predecessor

    def stop(service):
        require(service == native.WRAPPER, 'Only the wrapper service is in scope')
        system('stop', service)

    def stopped():
        unit = window.h.unit_status(window.policy.systemctl, native.WRAPPER)
        require(unit['ActiveState'] == 'inactive' and unit['MainPID'] == unit['ControlPID'] == '0',
                'Wrapper stop did not settle')
        services(0, active=False)
        return True

    def source_selection(expected):
        PathFinder.invalidate_caches()
        references = {}
        for relative, pin in expected.items():
            path = PROJECT / relative
            found = PathFinder.find_spec(path.stem, [str(TOOLS)])
            if pin is None:
                require(found is None and not os.path.lexists(path), 'Unexpected prompt module after rollback')
                references[relative] = None
                continue
            require(found is not None and found.origin == str(path) and isinstance(found.loader, SourceFileLoader),
                    'Wrapper would load a different tool source')
            caches = (path.with_suffix('.pyc'), path.parent/'__pycache__'/(path.stem+'.'+sys.implementation.cache_tag+'.pyc'))
            require(not any(os.path.lexists(cache) for cache in caches), 'Eligible bytecode would bypass new source')
            read(path, pin)
            references[relative] = reference(path)
        return references

    def start(service):
        nonlocal start_facts
        require(service == native.WRAPPER and 'intent' in new_authority,
                'Wrapper restart has no exact new transition')
        current = five.verify_transition(PROJECT, new_authority['intent'], reference)
        pins = {relative: ref[5] if ref else None for relative, ref in current.items()}
        start_facts = (time.monotonic_ns() // 1000, source_selection(pins))
        system('start', service)

    def ready(expected, transition):
        deadline = time.monotonic() + 12
        while True:
            try:
                pid, started = active()
                require(new_authority['intent'] == transition and start_facts is not None
                        and started >= start_facts[0] and source_selection(expected) == start_facts[1],
                        'Restarted wrapper does not bind the exact restored or installed source')
                window._terminal()
                read(STATE/'integration-release-journal.json', entry.ACTIVE_JOURNAL_PIN, private=True)
                post = snapshot()
                if expected[five.PREFIX+'embraer_compact_prompt.py'] is not None:
                    require(post['existing_coordinator']['continuation_table_exists_and_empty'],
                            'Source-only restart did not open the empty continuation schema')
                return {'pid': pid, 'started_monotonic_us': started,
                        'source_references': start_facts[1], 'authorization_issued': False}
            except (OSError, ValueError):
                if time.monotonic() >= deadline:
                    raise
                time.sleep(.3)

    normalized = {**evidence['snapshot'], 'existing_coordinator': {
        key: value for key, value in evidence['snapshot']['existing_coordinator'].items()
        if key != 'continuation_table_exists_and_empty'}}
    result = five.apply_five_tool_forward(
        project=PROJECT, candidates=candidates, scope=scope, receipt_directory=transaction,
        approved_snapshot_sha256=five.digest(normalized), atomic=atomic, guard=approved_guard,
        snapshot=existing_snapshot, stop=stop, stopped=stopped, start=start, ready=ready,
        reference=reference, authority=new_authority)
    print(json.dumps({'state': result['status'], 'receipt_sha256': five.digest(result),
                      'authorization_issued': False}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
