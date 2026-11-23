"""Arm the settled ATS request using the restored source window and one slot swap."""
import argparse
from contextlib import ExitStack, closing, redirect_stdout
from dataclasses import replace
from hashlib import sha256
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from types import ModuleType


PROJECT = Path('/home/chris/job-search-helper_old')
STAGE = Path(__file__).resolve().parent.parent
CROWN = Path('/tmp/jsh-crown-repair-evidence/native-capsule')
PREDECESSOR = Path('/tmp/jsh-ats-native-package')
RUNNER_RECEIPT = Path('/tmp/jsh-ats-thread-runner/LIVE_RECEIPT.json')
WINDOW_ID = 's6-ats-classifier-source-20261122-24'
PACKAGE_PIN = '28b6f49a46dac2896b68501542630cf47a42c0bf68dcc4ea38ea6a88bd2f209e'
CROWN_TERMINAL = 'ce26a5861716d0d3f66f16bd74ec742d3647592c2fc30e0613b9127681a9dc45'
CROWN_QUIET = 'eb2fc7ec826458e1c0da5b4d19f1933bc7e80ae4afd373f0ff92960bcb94381f'
CROWN_RESTORATION = 'f8092370563227ca5107342ced894ee1845c7ebd5478858ebd4a93b72ce86f90'
CROWN_EXCHANGE = '555165f8599cb7f3e6e4c0f9ca9ddc48b1f3756d7e417fd795b9fcb9e70a5c1b'
WRAPPER_FORWARD = '677b96299d39faf80e5c4267badfbc4e2859209588466ef755759e810b5f12a6'


def load(name, path, expected):
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != expected or name in sys.modules:
        raise ValueError(f'Maintenance source changed: {path}')
    module = ModuleType(name)
    module.__file__ = str(path)
    sys.modules[name] = module
    exec(compile(raw, str(path), 'exec'), module.__dict__)
    return module


ACTIVATION = Path(__file__).resolve().parent
RELEASE = 'REL-4141919bb885000b0e7244c2'
OLD_ENROLLMENT_PIN = 'b1350fc595099d5d9c8a726c62a46969e2c2447f92787689a70a020c7b866c9d'
TERMINAL_PIN = 'd0c78a0abac89438b87a91829ed0587657551f0fb28ebc417522690f9c970911'
SWAP_PIN = 'bf25a0b9d0ac75942d15e3e0295c7d96cfb10327dba64768c379fca53a06a363'
READER_PIN = '38bed11f4887ca9a9dff2ef72d3024d124d8b5bf1280e956de2798b7e8f247ef'
NATIVE_ENTRY_PIN = '701f7c8e68941e6349fa8c40907e18223d25c1a4a7bce829e52fd1a7980515ba'

def system(*args):
    return subprocess.check_output(['/usr/bin/systemctl', '--user', *args], text=True, timeout=30).strip()


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument('--old-pid', type=int, required=True)
    for name in ('apply-approval', 'apply-observed', 'enrollment', 'restored', 'quiet'):
        parser.add_argument('--' + name + '-sha256', required=True)
    args = parser.parse_args()
    if (not sys.flags.isolated or not sys.flags.dont_write_bytecode or sys.pycache_prefix != '/dev/null'
            or Path(sys.prefix).resolve() != PROJECT / '.venv'):
        raise ValueError('Isolated production Python with bytecode disabled is required.')
    legacy = load('legacy_crown_entry', CROWN/'native_crown_entry.py',
                  '855a58916417150541afa7f2879688c34727ed82d2fdd378e720d037ec137f67')
    custody = load('native_ats_file_custody', legacy.CUSTODY, legacy.CUSTODY_PIN)
    read = custody.file_bytes
    approval = json.loads(read(STAGE/'APPLY_APPROVAL.json', args.apply_approval_sha256, private=True))
    if (approval['maintenance_id'] != WINDOW_ID or approval['package_sha256'] != PACKAGE_PIN
            or approval['purpose'] != 'ats-classifier-source-only'):
        raise ValueError('Unexpected ATS work order.')
    tool_pins = approval['tool_sha256']
    if tool_pins['native_ats_entry.py'] != NATIVE_ENTRY_PIN or approval['apply'] is not True:
        raise ValueError('The reviewed ATS classifier apply approval is required.')
    read(STAGE/'native_ats_entry.py', NATIVE_ENTRY_PIN)
    ready = json.loads(read(STAGE/'READY_OBSERVED.json', approval['readiness_sha256'], private=True))
    applied = json.loads(read(STAGE/'APPLY_OBSERVED.json', args.apply_observed_sha256, private=True))
    if (ready.get('state') != 'QUALIFIED_NATIVE_WINDOW_READY' or ready.get('maintenance_id') != WINDOW_ID
            or ready.get('release_id') != 'REL-aa0e7a762a8e741c03b99692'
            or applied != {'state': 'NATIVE_SOURCE_ADVANCE_CONFIRMED', 'release_id': RELEASE}):
        raise ValueError('Expected restored, verified ATS classifier installation.')
    sys.path[:0] = [str(PROJECT/'src'), str(legacy.WRAPPER_BASE/'tools')]
    load('release_admission_bootstrap', PROJECT/'release_admission_bootstrap.py',
         '05f1e8f994d90a1f0d46cd880e425a596de98444af36bc73afa641f999bfa14e')
    from job_search_helper.cli import load_environment

    load_environment(PROJECT/'.env')
    load('native_source_advance', STAGE/'native_source_advance.py', tool_pins['native_source_advance.py'])
    source = load('ats_source_owner', STAGE/'maintenance_source_owner.py', tool_pins['maintenance_source_owner.py'])
    owner = source.MaintenanceSourceOwner(PROJECT, STAGE, PACKAGE_PIN)
    helper = load('ats_helpers', STAGE/'ats_maintenance_helpers.py', tool_pins['ats_maintenance_helpers.py'])
    checkpoint = load('ats_custody', STAGE/'ats_custody.py', tool_pins['ats_custody.py'])
    tasks = legacy.WRAPPER_BASE/'tasks/tasks.sqlite3'
    prior = load('ats_native_loader', legacy.PRIOR_ENTRY, legacy.PRIOR_ENTRY_PIN)
    prior.NATIVE_STAGE = CROWN
    status = owner.status()
    host = 'dev/wrapper-coder/tools/host_server.py'
    prior.INSTALLED_PINS = {
        'host_server.py': 'a235e814a794af95fad5773f8688c877d4ba0e04a12c1ec1405f026a3fa406aa',
        'coordinator_store.py': status['endpoints']['dev/wrapper-coder/tools/coordinator_store.py']['sha256'],
    }
    loaded = prior.verify_tool_origins()
    native, modules = prior.load_native_window(loaded, '29278c28f637457a1d1b0f21c7e8f18a97b4cb45dbee601bef1b0eb4274ba0f6')
    native.MAINTENANCE_ID = WINDOW_ID
    native.OBSERVER = Path('/run/jsh-maintenance-observer/observer.sock')
    native.EMBRAER_RELEASE_ID = owner.spec['live_runtime']['release_id']
    native.EMBRAER_MANIFEST_SHA256 = 'aa0e7a762a8e741c03b996925964c300776927ea91b1358226780500d5b2f282'
    native.EMBRAER_JOURNAL_SHA256 = owner.spec['live_journal_sha256']
    native.WRAPPER_RECEIPT_SHA256 = WRAPPER_FORWARD
    native.EXCHANGE_TERMINAL = CROWN_RESTORATION
    native.CANDIDATE_PACKAGE_SHA256 = PACKAGE_PIN
    native.CANDIDATE_SOURCE_SHA256 = owner.spec['staged_source_sha256']
    native.CANDIDATE_RELEASE_ID = owner.release_id
    native.CANDIDATE_MANIFEST_SHA256 = owner.manifest_pin
    native.CHANGED_WRAPPER_TOOLS = frozenset(Path(name).name for name in owner.spec['groups']['wrapper_tools'])

    class ATSWindow(native.NativeWindow):
        """Reuse service and route fencing with the current Crown predecessor."""

        def _source_status(self, allowed):
            state = owner.status()
            if state['phase'] not in allowed:
                raise ValueError('Unexpected ATS source phase.')
            return state

        def _embraer_predecessor(self):
            previous = PREDECESSOR/'active-window'
            terminal = json.loads(read(previous/'native-window.json', CROWN_TERMINAL, private=True))
            quiet = json.loads(read(previous/'operator-quiet-window.json', CROWN_QUIET, private=True))
            exchange = json.loads(read(previous/'exchange-private/exchange.json', CROWN_EXCHANGE, private=True))
            wrapper = json.loads(read(RUNNER_RECEIPT, WRAPPER_FORWARD, private=True))
            if (terminal['phase'] != quiet['phase'] or terminal['phase'] != 'RESTORED'
                    or exchange['phase'] != 'restored'
                    or terminal['restoration_sha256'] != CROWN_RESTORATION
                    or exchange['terminal_proof_sha256'] != CROWN_RESTORATION
                    or terminal['terminal']['release_id'] != native.EMBRAER_RELEASE_ID
                    or wrapper['state'] != 'OFFLINE_RUNNER_INSTALLED'
                    or wrapper['application_release_id'] != native.EMBRAER_RELEASE_ID):
                raise ValueError('The previous ATS maintenance or runner proof differs.')
            return terminal

        def _lineage(self, *, check_restored=True):
            terminal = self._embraer_predecessor()
            self.old = self.c.Controller(native.BUNDLE)
            historical = self.c.installer.encode(self.old.load(canonical=True))
            if sha256(historical).hexdigest() != native.CONTROLLER_RECORD:
                raise ValueError('The original native controller record differs.')
            previous = PREDECESSOR/'active-window/exchange-private'
            self.historical_exchange = self.x.HostExchange(previous/'policy.json', terminal['exchange']['policy_sha256'])
            if check_restored and self.historical_exchange.witness('restored').terminal_proof_sha256 != terminal['restoration_sha256']:
                raise ValueError('The previously restored routes moved.')
            state = self._source_status({'BEFORE'} if check_restored else {'BEFORE', 'PREPARED', 'STAGED'})
            self._wrapper_custody(state)
            policy, *_ = self.modules['site_policy'].load_policy(str(native.BUNDLE/'host-check'))
            installed_host = prior.INSTALLED_PINS['host_server.py']
            self.policy = replace(policy, maintenance_id=WINDOW_ID, ancillary_process_evidence=native.OBSERVER,
                                  before_host=replace(policy.before_host, digest=installed_host),
                                  after_host=replace(policy.after_host, digest=installed_host))

    root = STAGE/'active-window'
    window = ATSWindow(release_id=owner.release_id, manifest_sha256=owner.manifest_pin,
                       manifest=owner.manifest, approval_check=lambda: approval['source_approval'],
                       native_modules=modules, wrapper_scope_sha256=approval['wrapper_scope_sha256'],
                       window_root=root, source_owner=owner, resume_complete=True)
    swap = load('ats_scope_swap', ACTIVATION / 'swap_ats_enrollment.py', SWAP_PIN)
    extractor = load('ats_app_enrollment', ACTIVATION / 'read_ats_enrollment.py', READER_PIN)
    enrollment = json.loads(read(ACTIVATION / 'LIVE_ENROLLMENT.json', args.enrollment_sha256, private=True))
    if owner.release_id != RELEASE or status['phase'] != 'STAGED':
        raise ValueError('The complete ATS source release is no longer installed.')
    expected = json.loads(read(STAGE/'COORDINATOR_BEFORE.json', approval['coordinator_before_sha256'], private=True))
    legacy_env = Path('/tmp/jsh-embraer-owned-pilot.xXaXrqW0/successor-enrollment/native')
    environment = load('ats_scoped_environment', legacy_env/'successor_environment.py',
                       'f86bb7e48d0c36f2fe5edb47baba1544b91ed7ec9df4be46a65018b188f610fc')
    scope = load('ats_process_scope', legacy_env/'native_runtime.py',
                 '05377be0ff3124e2fb641b378443251f63ec415d9de3dddc11e7bb12913f7521')
    environment.SCOPED |= {'WRAPPER_CROWN_OPERATOR_PILOT_ENROLLMENT', swap.ATS_ENV}
    client = load('ats_existing_coordinator_cli', legacy.WRAPPER_BASE/'tools/wrapper_task.py',
                  'a4e61105917dea6fb963f4a1a81e3b0745f863c529aa0a0affabd32b9ab0d1c7')

    def read_manager():
        return environment.manager_scope(system)

    def read_process():
        state = window._running_ready(bridge_allowed=True)
        pid = int(state['MainPID'])
        path = Path('/proc') / str(pid)
        generation = window.h.process_start(path)
        values = scope.process_scope((path/'environ').read_bytes(), environment.SCOPED)
        if window.h.process_start(path) != generation:
            raise ValueError('Wrapper changed during process enrollment readback.')
        return pid, values

    def read_custody():
        # Reconcile the one permitted slot setting to its original value for
        # comparison with the already sealed logical database snapshot.
        with closing(sqlite3.connect(tasks.as_uri() + '?mode=ro', uri=True)) as db:
            db.execute('BEGIN')
            scope.controls(db, allowed_pilot=checkpoint.TERMINAL_PILOT)
            settings = {k: json.loads(v) for k, v in db.execute('SELECT key,value FROM settings')}
            slot = settings['pilot_task']
            if slot not in (None, checkpoint.TERMINAL_PILOT):
                raise ValueError('Unexpected pilot owner.')
            if settings['control_generation'] != expected['control_generation'] + (2 if slot is None else 1):
                raise ValueError('Unexpected coordinator control generation.')
            schema = db.execute('SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name').fetchall()
            if sha256(json.dumps(schema,separators=(',', ':')).encode()).hexdigest() != expected['schema_sha256']:
                raise ValueError('Unexpected coordinator schema.')
            for name, previous in expected['tables'].items():
                quoted = '"' + name.replace('"', '""') + '"'
                count, digest = 0, sha256()
                for row in db.execute(f'SELECT * FROM {quoted} ORDER BY rowid'):
                    if name == 'settings':
                        if row[0] in ('supervision_status', 'control_generation'):
                            continue
                        if row[0] == 'pilot_task':
                            row = ('pilot_task', json.dumps(checkpoint.TERMINAL_PILOT))
                    digest.update(json.dumps(row, separators=(',', ':')).encode() + b'\n')
                    count += 1
                if previous != {'row_count':count, 'rows_sha256':digest.hexdigest()}:
                    raise ValueError(f'Protected coordinator history changed in {name}.')
            return slot

    def release_terminal_slot():
        helper.require_no_active_application_work(PROJECT)
        if (PROJECT/'.state/next-scan.json').exists():
            raise ValueError('A company request is queued.')
        slot = read_custody()
        if slot == checkpoint.TERMINAL_PILOT:
            checkpoint.compare(expected, checkpoint.measure(tasks), shutdowns=1)
            try:
                with redirect_stdout(io.StringIO()):
                    rc = client.main(['pilot-stop'])
            except (OSError, ValueError):
                rc = 1
            if read_custody() is not None:
                raise ValueError(f'Terminal pilot stop did not produce an empty slot (response {rc}).')
        if read_custody() is not None:
            raise ValueError('Empty pilot slot was not confirmed.')

    window._approval()
    window._modules()
    controller = window.c.Controller(native.BUNDLE)
    with ExitStack() as leases:
        for path in (controller.controller_gate, *controller.locks, controller.install_gate):
            leases.enter_context(window.c.lock(path))
        if {str(path): window.c.inode(path) for path in controller.locks} != controller.binding['locks']:
            raise ValueError('Original application locks changed.')
        window._lineage(check_restored=False)
        record = json.loads(read(window.root/'native-window.json', args.restored_sha256, private=True))
        quiet = json.loads(read(window.root/'operator-quiet-window.json', args.quiet_sha256, private=True))
        if (record['phase'] != 'RESTORED' or quiet['phase'] != 'RESTORED'
                or record['binding'] != window._binding() or record['terminal'] != window._terminal()):
            raise ValueError('Native release window is not restored.')
        exchange = window.x.HostExchange(window.root/'exchange-private/policy.json', record['exchange']['policy_sha256'])
        if exchange.witness('restored').terminal_proof_sha256 != record['restoration_sha256']:
            raise ValueError('Restored alternate routes changed.')
        for unit in (native.SYNC, native.TIMER):
            if (system('show', unit, '-p', 'ActiveState', '--value') != 'inactive'
                    or system('show', unit, '-p', 'UnitFileState', '--value') != 'disabled'):
                raise ValueError('Scheduled sync must remain disabled.')
        from job_search_helper.inbox import InventoryInbox
        from job_search_helper.sqlite_repository import SQLiteRepository
        app = PROJECT/'.state'
        with closing(SQLiteRepository(app/'jobs.sqlite3', InventoryInbox.destination_id(app/'inventories.sqlite3'),
                                      readonly=True)) as repository:
            baseline = legacy.WRAPPER_BASE / 'pilot-bases' / ('ats-' + extractor.BASELINE_PIN)
            actual = extractor.build_enrollment(repository, app, PROJECT, baseline, extractor.BASELINE_PIN, extractor.REQUEST_ID)
        if actual != enrollment:
            raise ValueError('Application-derived ATS enrollment differs.')
        previous = PREDECESSOR / 'activation'
        historical = json.loads(read(previous/'INDEPENDENT_TERMINAL.json', TERMINAL_PIN, private=True))
        if (historical['task_id'] != checkpoint.TERMINAL_PILOT
                or historical['task_state_sha256'] != enrollment['successor']['predecessor_task_state_sha256']
                or historical['outcome_id'] != enrollment['successor']['predecessor_outcome_id']
                or historical['task_status'] != 'PAUSED_TEST_FAILURE'):
            raise ValueError('The original ATS task or its terminal receipt changed.')
        old = json.loads(read(previous/'LIVE_ENROLLMENT.json', OLD_ENROLLMENT_PIN, private=True))
        old_value = json.dumps(old, sort_keys=True, separators=(',', ':'))
        result = swap.arm_ats(enrollment, old_value, args.old_pid, system=system,
                              read_manager=read_manager, read_process=read_process,
                              check_quiescent=release_terminal_slot)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
