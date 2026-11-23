"""Install the approved offline runner helper under the existing wrapper hold."""
import argparse
from contextlib import ExitStack, closing
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from types import ModuleType


PROJECT = Path('/home/chris/job-search-helper_old')
DEPLOY = Path(__file__).resolve().parent
STAGE = Path("/tmp/jsh-ats-native-package")
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

ACTIVATION = STAGE/'activation'
APPROVAL_PIN = '0fd60a6d60aa74a37ff4b9f184a5e94563c3d75f137ee2f6db09c6184c4f113e'
ENROLLMENT_PIN = 'b1350fc595099d5d9c8a726c62a46969e2c2447f92787689a70a020c7b866c9d'
SWAP_PIN = '46d1e0962ec921730e64bb275cd418fb5cd63e74aac740b20b9fdfc84fcef1ce'
RESTORED_PIN = 'ce26a5861716d0d3f66f16bd74ec742d3647592c2fc30e0613b9127681a9dc45'
QUIET_PIN = 'eb2fc7ec826458e1c0da5b4d19f1933bc7e80ae4afd373f0ff92960bcb94381f'
RELEASE = 'REL-aa0e7a762a8e741c03b99692'


def system(*args):
    return subprocess.check_output(['/usr/bin/systemctl', '--user', *args], text=True, timeout=30).strip()


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument('action', choices=('check', 'apply', 'recover'))
    args = parser.parse_args()
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
    native.MAINTENANCE_ID = 's6-ats-offline-runner-20261122-23'
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
            self.policy = replace(policy, maintenance_id=native.MAINTENANCE_ID, ancillary_process_evidence=native.OBSERVER,
                                  before_host=replace(policy.before_host, digest=installed['before']['sha256']),
                                  after_host=replace(policy.after_host, digest=installed['staged']['sha256']))

    root = STAGE/'active-window'
    window = ATSWindow(release_id=owner.release_id, manifest_sha256=owner.manifest_pin,
                       manifest=owner.manifest, approval_check=lambda: approval['source_approval'],
                       native_modules=modules, wrapper_scope_sha256=approval['wrapper_scope_sha256'],
                       window_root=root, source_owner=owner, resume_complete=True)
    swap = load('ats_scope_swap', ACTIVATION / 'swap_ats_enrollment.py', SWAP_PIN)
    enrollment = json.loads(read(ACTIVATION / 'LIVE_ENROLLMENT.json', ENROLLMENT_PIN, private=True))
    if owner.release_id != RELEASE or status['phase'] != 'STAGED':
        raise ValueError('The complete ATS source release is no longer installed.')
    legacy_env = Path('/tmp/jsh-embraer-owned-pilot.xXaXrqW0/successor-enrollment/native')
    environment = load('ats_scoped_environment', legacy_env/'successor_environment.py',
                       'f86bb7e48d0c36f2fe5edb47baba1544b91ed7ec9df4be46a65018b188f610fc')
    scope = load('ats_process_scope', legacy_env/'native_runtime.py',
                 '05377be0ff3124e2fb641b378443251f63ec415d9de3dddc11e7bb12913f7521')
    environment.SCOPED |= {swap.OLD_ENV, swap.ATS_ENV}
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

    from job_search_helper import integration_release as release

    target = legacy.WRAPPER_BASE/'tools/coding_sandbox.py'
    candidate = DEPLOY/target.name
    old_pin = '9416388917a9c6487ad87e33d138972a5423dcfeadef4d75f7d328243329740c'
    new_pin = '3309cff389adc446c21f84bb787e946bfb47ff986624c374b6947fdf859067cd'
    task_id = 'WRAP-9db6388719'
    task_pin = '50ed539b887ccbdef1270dfe95783bbb523615f0a2c4a91a712d0b61bad51a1d'
    request_id = '22a2ecf17cf744298a39f10418af7f5c'
    wrapper_base = legacy.WRAPPER_BASE

    def snapshot():
        with closing(sqlite3.connect(tasks.as_uri()+'?mode=ro',uri=True)) as db:
            db.execute('BEGIN')
            scope.controls(db, allowed_pilot=task_id)
            state, = db.execute('SELECT state FROM tasks WHERE id=?', (task_id,)).fetchone()
            if (db.execute("SELECT value FROM settings WHERE key='pilot_task'").fetchone()
                    != (json.dumps(task_id),)
                    or sha256(state.encode()).hexdigest() != task_pin
                    or db.execute('SELECT request_id,status FROM inference_receipts WHERE task=?',(task_id,)).fetchall()
                    != [(request_id,'COMPLETED')]):
                raise ValueError('The exact terminal ATS task changed.')
            schema = db.execute('SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name').fetchall()
            tables = {}
            generation = None
            for kind, name, *_ in schema:
                if kind != 'table':
                    continue
                quoted = '"' + name.replace('"','""') + '"'
                digest = sha256()
                for row in db.execute(f'SELECT * FROM {quoted} ORDER BY rowid'):
                    if name == 'settings' and row[0] in ('supervision_status','control_generation'):
                        if row[0] == 'control_generation':
                            generation = json.loads(row[1])
                        continue
                    digest.update(json.dumps(row,separators=(',',':')).encode()+b'\n')
                tables[name] = digest.hexdigest()
        if type(generation) is not int:
            raise ValueError('Coordinator generation is absent.')
        return {'generation':generation, 'schema_sha256':release.digest(schema), 'tables':tables}

    approved = release.metadata(candidate)
    current = release.metadata(target)
    before_image = DEPLOY/'LIVE_BEFORE_coding_sandbox.py'
    intent_path = DEPLOY/'LIVE_INTENT.json'
    receipt_path = DEPLOY/'LIVE_RECEIPT.json'
    intent = json.loads(read(intent_path, private=True)) if args.action == 'recover' else None
    old_metadata = release.metadata(before_image) if intent else current
    if (approved['sha256'] != new_pin or old_metadata['sha256'] != old_pin
            or approved['mode'] != old_metadata['mode'] or current not in (old_metadata, approved)
            or (intent is not None and (intent['before'] != old_metadata or intent['after'] != approved))):
        raise ValueError('Approved or current runner bytes differ.')
    if args.action == 'apply' and intent_path.exists():
        raise ValueError('The earlier runner intent must be observed with recover.')

    window._approval()
    window._modules()
    controller = window.c.Controller(native.BUNDLE)
    with ExitStack() as leases:
        deployment = legacy.WRAPPER_BASE/'repairs/deployment.lock'
        for path in (deployment, controller.controller_gate, *controller.locks, controller.install_gate):
            leases.enter_context(window.c.lock(path))
        if {str(path): window.c.inode(path) for path in controller.locks} != controller.binding['locks']:
            raise ValueError('Original application locks changed.')
        original_scope = window.wrapper_scope_sha256
        if intent:
            native.CHANGED_WRAPPER_TOOLS |= {target.name}
            window.wrapper_scope_sha256 = intent['unchanged_wrapper_scope']
        window._lineage(check_restored=False)
        record = json.loads(read(window.root/'native-window.json', RESTORED_PIN, private=True))
        quiet = json.loads(read(window.root/'operator-quiet-window.json', QUIET_PIN, private=True))
        if (record['phase'] != 'RESTORED' or quiet['phase'] != 'RESTORED'
                or record['binding'] != {**window._binding(), 'maintenance_id': WINDOW_ID,
                                        'wrapper_scope_sha256': original_scope}
                or record['terminal'] != window._terminal()):
            raise ValueError('Native release window is not restored.')
        exchange = window.x.HostExchange(window.root/'exchange-private/policy.json', record['exchange']['policy_sha256'])
        if exchange.witness('restored').terminal_proof_sha256 != record['restoration_sha256']:
            raise ValueError('Restored alternate routes changed.')
        for unit in (native.SYNC, native.TIMER):
            if (system('show', unit, '-p', 'ActiveState', '--value') != 'inactive'
                    or system('show', unit, '-p', 'UnitFileState', '--value') != 'disabled'):
                raise ValueError('Scheduled sync must remain disabled.')
        expected_scope = {swap.ATS_ENV: json.dumps(enrollment, sort_keys=True, separators=(',', ':'))}
        if read_manager() != expected_scope:
            raise ValueError('The known ATS-only manager enrollment moved.')
        helper.require_no_active_application_work(PROJECT)
        if (PROJECT/'.state/next-scan.json').exists():
            raise ValueError('A company request is queued.')
        coordinator_lease = loaded['amphenol_operator_one_shot']._coordinator_lease

        def require_no_tests():
            if system('list-units','--type=service','--state=active','--no-legend','wrapper-test-*.service'):
                raise ValueError('An offline wrapper test is still active.')

        def finish(pid, state):
            output = {'state':state,'wrapper_pid':pid,'source_sha256':release.metadata(target)['sha256'],
                      'application_release_id':owner.release_id,'task_preserved':task_id}
            if receipt_path.exists() and json.loads(read(receipt_path, private=True)) != output:
                raise ValueError('The saved runner receipt differs.')
            if not receipt_path.exists():
                release._write_json(receipt_path,output)
            print(json.dumps(output,sort_keys=True))

        if intent:
            before = intent['custody']
            expected = {**before, 'generation':before['generation']+1}
            service = window.h.unit_status(window.policy.systemctl,swap.WRAPPER)
            if service['ActiveState'] == 'inactive' and service['MainPID'] == '0':
                window._observer()
                with coordinator_lease(wrapper_base/'tasks'):
                    require_no_tests()
                    if snapshot() != expected or release.metadata(target) not in (old_metadata,approved):
                        raise ValueError('Stopped runner custody differs from the saved intent.')
                    if release.metadata(target) == approved:
                        release._atomic_copy(before_image,target,old_metadata)
                system('start',swap.WRAPPER)
            pid, observed = read_process()
            actual = release.metadata(target)
            allowed = (expected,) if actual == approved else (before,expected)
            if (actual not in (old_metadata,approved) or observed != expected_scope
                    or read_manager() != expected_scope or snapshot() not in allowed):
                raise ValueError('Runner restart or unchanged custody could not be verified.')
            finish(pid, 'OFFLINE_RUNNER_INSTALLED' if actual == approved else 'OFFLINE_RUNNER_RESTORED')
            return

        wrapper_pid, actual_scope = read_process()
        if actual_scope != expected_scope or read_manager() != expected_scope:
            raise ValueError('The known ATS-only worker enrollment moved.')
        before = snapshot()
        if args.action == 'check':
            print(json.dumps({'state':'OFFLINE_RUNNER_READY','wrapper_pid':wrapper_pid,'custody':before},sort_keys=True))
            return
        if release.metadata(target) != old_metadata:
            raise ValueError('Application or runner state changed before installation.')
        require_no_tests()
        release._atomic_copy(target,before_image,old_metadata)
        unchanged = window.c.unscoped(controller.wrapper_tools,native.CHANGED_WRAPPER_TOOLS | {target.name})
        release._write_json(intent_path, {'before':old_metadata,'after':approved,'custody':before,
                                         'old_pid':wrapper_pid,'unchanged_wrapper_scope':unchanged})
        expected_custody = {**before,'generation':before['generation']+1}
        try:
            system('stop',swap.WRAPPER)
            stopped = window.h.unit_status(window.policy.systemctl,swap.WRAPPER)
            if stopped['ActiveState'] != 'inactive' or stopped['MainPID'] != '0':
                raise ValueError('Wrapper service did not settle after stop.')
            with coordinator_lease(wrapper_base/'tasks'):
                require_no_tests()
                if snapshot() != expected_custody or release.metadata(target) != old_metadata:
                    raise ValueError('Protected state moved under the wrapper lease.')
                release._atomic_copy(candidate,target,approved)
            system('start',swap.WRAPPER)
            pid, observed = read_process()
            if (pid == wrapper_pid or observed != expected_scope or read_manager() != expected_scope
                    or release.metadata(target) != approved or snapshot() != expected_custody):
                raise ValueError('Runner source, worker custody or service restoration could not be confirmed.')
        except BaseException:
            state = window.h.unit_status(window.policy.systemctl,swap.WRAPPER)
            if state['ActiveState'] == 'inactive' and state['MainPID'] == '0':
                with coordinator_lease(wrapper_base/'tasks'):
                    if snapshot() != expected_custody:
                        raise ValueError('Stopped coordinator custody differs from the saved intent.')
                    actual = release.metadata(target)
                    if actual == approved:
                        release._atomic_copy(before_image,target,old_metadata)
                    elif actual != old_metadata:
                        raise ValueError('Unexpected runner bytes prevent rollback.')
                system('start',swap.WRAPPER)
            raise
        finish(pid,'OFFLINE_RUNNER_INSTALLED')


if __name__ == '__main__':
    main()
