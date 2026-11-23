"""Arm the settled ATS request using the restored source window and one slot swap."""
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
WINDOW_ID = 's6-ats-owned-source-20261122-22'
PACKAGE_PIN = '6a4f6239837ae33b309d51334d834fd0b611c2b37b0628afdb0b910b67b9ffa2'
CROWN_TERMINAL = 'e474c1bef3c194e93cccdb78b7a73177b34d57443ac0ea7c9d1d80295b817a5b'
CROWN_QUIET = '921df0d5862bd9d0c044c3686f27a9c72e86cc822d85308b47a808cf7eae2769'
CROWN_RESTORATION = 'c1cfdecfed7b58dff2e1fe3b210406b7b00f697f05097002d71f052bbe00a3d4'
CROWN_EXCHANGE = '78d250c351944960edb198ec77c11f57349a53c8545b1f08836cc015873b3878'
WRAPPER_FORWARD = '6e4f7f0bda2690cd27599c90f2b04396c42e13cbb471a37c2b3d22ab98ffcb9b'


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
APPROVAL_PIN = '0fd60a6d60aa74a37ff4b9f184a5e94563c3d75f137ee2f6db09c6184c4f113e'
ENROLLMENT_PIN = 'b1350fc595099d5d9c8a726c62a46969e2c2447f92787689a70a020c7b866c9d'
OLD_VALUE_PIN = '987c5d880b85dde79f422996737ad1db10537fd98e0e139ee9aec1a937b4d815'
SWAP_PIN = '46d1e0962ec921730e64bb275cd418fb5cd63e74aac740b20b9fdfc84fcef1ce'
READER_PIN = '9a896ed26a39c8418b2f72cb2e0d9092944c6a390615c22d287e5a9d55b7ba57'
RESTORED_PIN = 'ce26a5861716d0d3f66f16bd74ec742d3647592c2fc30e0613b9127681a9dc45'
QUIET_PIN = 'eb2fc7ec826458e1c0da5b4d19f1933bc7e80ae4afd373f0ff92960bcb94381f'
RELEASE = 'REL-aa0e7a762a8e741c03b99692'


def system(*args):
    return subprocess.check_output(['/usr/bin/systemctl', '--user', *args], text=True, timeout=30).strip()


def main():
    if (not sys.flags.isolated or not sys.flags.dont_write_bytecode or sys.pycache_prefix != '/dev/null'
            or Path(sys.prefix).resolve() != PROJECT / '.venv'):
        raise ValueError('Use isolated production Python without bytecode.')
    legacy = load('legacy_crown_entry', CROWN/'native_crown_entry.py',
                  '855a58916417150541afa7f2879688c34727ed82d2fdd378e720d037ec137f67')
    custody = load('native_ats_file_custody', legacy.CUSTODY, legacy.CUSTODY_PIN)
    read = custody.file_bytes
    approval = json.loads(read(STAGE / 'APPLY_APPROVAL.json', APPROVAL_PIN, private=True))
    if (approval['maintenance_id'] != WINDOW_ID or approval['package_sha256'] != PACKAGE_PIN
            or approval['purpose'] != 'ats-owned-source-only'):
        raise ValueError('Unexpected ATS work order.')
    tool_pins = approval['tool_sha256']
    read(STAGE / 'native_ats_entry.py', tool_pins['native_ats_entry.py'])
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
        'host_server.py': status['endpoints'][host]['sha256'],
        'coordinator_store.py': 'e8d56f641b3f4ae5a4b5cd8aa3729b4ef27fdff3489ab615faf8b18416a4a9ee',
    }
    loaded = prior.verify_tool_origins()
    native, modules = prior.load_native_window(loaded, '29278c28f637457a1d1b0f21c7e8f18a97b4cb45dbee601bef1b0eb4274ba0f6')
    native.MAINTENANCE_ID = WINDOW_ID
    native.OBSERVER = Path('/run/jsh-maintenance-observer/observer.sock')
    native.EMBRAER_RELEASE_ID = owner.spec['live_runtime']['release_id']
    native.EMBRAER_MANIFEST_SHA256 = 'ede347339c8faf180658381064f131ed749fde5aac87211f4e43d00e407051f9'
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
            previous = CROWN/'active-window'
            terminal = json.loads(read(previous/'native-window.json', CROWN_TERMINAL, private=True))
            quiet = json.loads(read(previous/'operator-quiet-window.json', CROWN_QUIET, private=True))
            exchange = json.loads(read(previous/'exchange-private/exchange.json', CROWN_EXCHANGE, private=True))
            wrapper = json.loads(read(CROWN.parent/'edit-only/LIVE_FORWARD.json', WRAPPER_FORWARD, private=True))
            if (terminal['phase'] != quiet['phase'] or terminal['phase'] != 'RESTORED'
                    or exchange['phase'] != 'restored'
                    or terminal['restoration_sha256'] != CROWN_RESTORATION
                    or exchange['terminal_proof_sha256'] != CROWN_RESTORATION
                    or terminal['terminal']['release_id'] != native.EMBRAER_RELEASE_ID
                    or wrapper['state'] != 'CROWN_ONE_EDIT_FORWARD_INSTALLED'):
                raise ValueError('The previous Crown maintenance proof differs.')
            return terminal

        def _lineage(self, *, check_restored=True):
            terminal = self._embraer_predecessor()
            self.old = self.c.Controller(native.BUNDLE)
            historical = self.c.installer.encode(self.old.load(canonical=True))
            if sha256(historical).hexdigest() != native.CONTROLLER_RECORD:
                raise ValueError('The original native controller record differs.')
            previous = CROWN/'active-window/exchange-private'
            self.historical_exchange = self.x.HostExchange(previous/'policy.json', terminal['exchange']['policy_sha256'])
            if check_restored and self.historical_exchange.witness('restored').terminal_proof_sha256 != terminal['restoration_sha256']:
                raise ValueError('The previously restored routes moved.')
            state = self._source_status({'BEFORE'} if check_restored else {'BEFORE', 'PREPARED', 'STAGED'})
            self._wrapper_custody(state)
            policy, *_ = self.modules['site_policy'].load_policy(str(native.BUNDLE/'host-check'))
            installed = owner.spec['package_files'][host]
            self.policy = replace(policy, maintenance_id=WINDOW_ID, ancillary_process_evidence=native.OBSERVER,
                                  before_host=replace(policy.before_host, digest=installed['before']['sha256']),
                                  after_host=replace(policy.after_host, digest=installed['staged']['sha256']))

    root = STAGE/'active-window'
    window = ATSWindow(release_id=owner.release_id, manifest_sha256=owner.manifest_pin,
                       manifest=owner.manifest, approval_check=lambda: approval['source_approval'],
                       native_modules=modules, wrapper_scope_sha256=approval['wrapper_scope_sha256'],
                       window_root=root, source_owner=owner, resume_complete=True)
    swap = load('ats_scope_swap', ACTIVATION / 'swap_ats_enrollment.py', SWAP_PIN)
    extractor = load('ats_app_enrollment', ACTIVATION / 'read_ats_enrollment.py', READER_PIN)
    enrollment = json.loads(read(ACTIVATION / 'LIVE_ENROLLMENT.json', ENROLLMENT_PIN, private=True))
    if owner.release_id != RELEASE or status['phase'] != 'STAGED':
        raise ValueError('The complete ATS source release is no longer installed.')
    expected = json.loads(read(STAGE/'COORDINATOR_BEFORE.json', approval['coordinator_before_sha256'], private=True))
    legacy_env = Path('/tmp/jsh-embraer-owned-pilot.xXaXrqW0/successor-enrollment/native')
    environment = load('ats_scoped_environment', legacy_env/'successor_environment.py',
                       'f86bb7e48d0c36f2fe5edb47baba1544b91ed7ec9df4be46a65018b188f610fc')
    scope = load('ats_process_scope', legacy_env/'native_runtime.py',
                 '05377be0ff3124e2fb641b378443251f63ec415d9de3dddc11e7bb12913f7521')
    environment.SCOPED |= {swap.OLD_ENV, swap.ATS_ENV}
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
        record = json.loads(read(window.root/'native-window.json', RESTORED_PIN, private=True))
        quiet = json.loads(read(window.root/'operator-quiet-window.json', QUIET_PIN, private=True))
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
        target = {swap.ATS_ENV: json.dumps(enrollment, sort_keys=True, separators=(',', ':'))}
        manager = read_manager()
        pid, process = read_process()
        if manager == process == target and pid != 799207:
            result = {'state':'ATS_PILOT_ARMED', 'wrapper_pid':pid}
        else:
            old = manager.get(swap.OLD_ENV)
            if not isinstance(old, str) or sha256(old.encode()).hexdigest() != OLD_VALUE_PIN:
                raise ValueError('Current manager no longer has the exact terminal Crown enrollment.')
            result = swap.arm_ats(enrollment, old, system=system, read_manager=read_manager,
                                  read_process=read_process, check_quiescent=release_terminal_slot)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
