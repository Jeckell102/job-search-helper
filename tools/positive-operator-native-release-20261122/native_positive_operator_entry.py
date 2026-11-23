"""Apply the pinned positive operator source package through the existing native hold."""

import argparse
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import sys
from types import ModuleType


PROJECT = Path('/home/chris/job-search-helper_old')
STAGE = Path(__file__).resolve().parent
CROWN = Path('/tmp/jsh-crown-repair-evidence/native-capsule')
PREDECESSOR = Path('/tmp/jsh-festo-native-release')
WINDOW_ID = 's7-positive-operator-20261122-26'
PACKAGE_PIN = 'b43de554d3119581cd595f5ad2635594e063d318ba4868a79d4ba9a306200c1c'
PREDECESSOR_TERMINAL = '1134c5bed7d64dbb22c7825bcce5b5b0751f9326821d87a8c154082bba9556c5'
PREDECESSOR_QUIET = '001508624fba7401ecb75c51e863c7dd523794a8fc0beeab79a8e04fe34d860c'
PREDECESSOR_RESTORATION = 'e3085365a58e9adbcfbf2dcd60bbb905d24d8becab4db5851f16d98452a54a97'
PREDECESSOR_EXCHANGE = 'bf34d231a0b39c55816c2c793fec55abb9ebbde0431e14597a7fa5dcb60b7e4d'
COORDINATOR_STORE_PIN = 'd65f1e0a37ba49cf6dcf721bd20cfe9f72017d028347f61130c22de25724ea4b'


def load(name, path, expected):
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != expected or name in sys.modules:
        raise ValueError(f'Maintenance source changed: {path}')
    module = ModuleType(name)
    module.__file__ = str(path)
    sys.modules[name] = module
    exec(compile(raw, str(path), 'exec'), module.__dict__)
    return module


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument('action', choices=('measure', 'ready', 'apply', 'restore'))
    parser.add_argument('--approval', type=Path, required=True)
    parser.add_argument('--sha256', required=True)
    args = parser.parse_args()
    if (not sys.flags.isolated or not sys.flags.dont_write_bytecode or sys.pycache_prefix != '/dev/null'
            or Path(sys.prefix).resolve() != PROJECT / '.venv'):
        raise ValueError('Isolated production Python with bytecode disabled is required.')
    legacy = load('legacy_crown_entry', CROWN/'native_crown_entry.py',
                  '855a58916417150541afa7f2879688c34727ed82d2fdd378e720d037ec137f67')
    custody = load('native_festo_file_custody', legacy.CUSTODY, legacy.CUSTODY_PIN)
    read = custody.file_bytes
    approval = json.loads(read(args.approval, args.sha256, private=True))
    if (approval['maintenance_id'] != WINDOW_ID or approval['package_sha256'] != PACKAGE_PIN
            or approval['purpose'] != 'positive-operator-company-only'):
        raise ValueError('Unexpected positive operator work order.')
    tool_pins = approval['tool_sha256']
    read(Path(__file__).resolve(), tool_pins['native_positive_operator_entry.py'])
    sys.path[:0] = [str(PROJECT/'src'), str(legacy.WRAPPER_BASE/'tools')]
    bootstrap = PROJECT / 'release_admission_bootstrap.py'
    before_bootstrap = '05f1e8f994d90a1f0d46cd880e425a596de98444af36bc73afa641f999bfa14e'
    bootstrap_pin = sha256(bootstrap.read_bytes()).hexdigest()
    allowed_bootstrap = {before_bootstrap}
    if args.action == 'restore':
        allowed_bootstrap.add('fb18d988bfbaaca369a3d8d36a9d187bd8c5eafa1bfe04870ff8f1cad33ab084')
    if bootstrap_pin not in allowed_bootstrap:
        raise ValueError('The stable admission bootstrap differs from the reviewed images.')
    load('release_admission_bootstrap', bootstrap, bootstrap_pin)
    from job_search_helper.cli import load_environment

    load_environment(PROJECT/'.env')
    load('native_source_advance', STAGE/'native_source_advance.py', tool_pins['native_source_advance.py'])
    source = load('festo_source_owner', STAGE/'maintenance_source_owner.py', tool_pins['maintenance_source_owner.py'])
    owner = source.MaintenanceSourceOwner(PROJECT, STAGE, PACKAGE_PIN)
    helper = load('festo_idle_checks', STAGE/'application_idle.py', tool_pins['application_idle.py'])
    checkpoint = load('festo_coordinator_custody', STAGE/'coordinator_custody.py', tool_pins['coordinator_custody.py'])
    tasks = legacy.WRAPPER_BASE/'tasks/tasks.sqlite3'
    postures = ('measure', 'ready', 'apply')
    if args.action in postures:
        helper.require_no_active_application_work(PROJECT)
        before = checkpoint.measure(tasks)
        if owner.status()['phase'] != 'BEFORE':
            raise ValueError('The exact installed predecessor is required.')
    prior = load('festo_native_loader', legacy.PRIOR_ENTRY, legacy.PRIOR_ENTRY_PIN)
    prior.NATIVE_STAGE = CROWN
    prior.INSTALLED_PINS = {
        'host_server.py': 'a235e814a794af95fad5773f8688c877d4ba0e04a12c1ec1405f026a3fa406aa',
        'coordinator_store.py': COORDINATOR_STORE_PIN,
    }
    loaded = prior.verify_tool_origins()
    native, modules = prior.load_native_window(loaded, '29278c28f637457a1d1b0f21c7e8f18a97b4cb45dbee601bef1b0eb4274ba0f6')
    native.MAINTENANCE_ID = WINDOW_ID
    native.OBSERVER = Path('/run/jsh-maintenance-observer/observer.sock')
    native.EMBRAER_RELEASE_ID = owner.spec['live_runtime']['release_id']
    native.EMBRAER_MANIFEST_SHA256 = 'e91024875ba7d854b83c33f8a8ddee450fcc1f4537474a4f5b4f43e9e8f8853f'
    native.EMBRAER_JOURNAL_SHA256 = owner.spec['live_journal_sha256']
    native.WRAPPER_RECEIPT_SHA256 = PREDECESSOR_TERMINAL
    native.EXCHANGE_TERMINAL = PREDECESSOR_RESTORATION
    native.CANDIDATE_PACKAGE_SHA256 = PACKAGE_PIN
    native.CANDIDATE_SOURCE_SHA256 = owner.spec['staged_source_sha256']
    native.CANDIDATE_RELEASE_ID = owner.release_id
    native.CANDIDATE_MANIFEST_SHA256 = owner.manifest_pin
    native.CHANGED_WRAPPER_TOOLS = frozenset()
    controller = modules['controller']
    historical = controller.Controller(native.BUNDLE)
    before_terminal = json.loads(read(PREDECESSOR/'active-window/native-window.json', PREDECESSOR_TERMINAL, private=True))
    wrapper_scope = controller.unscoped(historical.wrapper_tools, native.CHANGED_WRAPPER_TOOLS)
    if wrapper_scope != before_terminal['binding']['wrapper_scope_sha256']:
        raise ValueError('The exact restored wrapper source differs.')
    if args.action == 'measure':
        print(json.dumps({'phase':'BEFORE', 'release_id':owner.release_id,
                          'manifest_sha256':owner.manifest_pin, 'wrapper_scope_sha256':wrapper_scope,
                          'coordinator':before}, sort_keys=True))
        return
    if approval['wrapper_scope_sha256'] != wrapper_scope:
        raise ValueError('The measured full wrapper source changed.')
    before = json.loads(read(STAGE/'COORDINATOR_BEFORE.json', approval['coordinator_before_sha256'], private=True))
    if args.action in ('ready', 'apply'):
        checkpoint.compare(before, checkpoint.measure(tasks), shutdowns=0)

    class PositiveOperatorWindow(native.NativeWindow):
        """Reuse the verified service and route fences for an app-only release."""

        def _source_status(self, allowed):
            state = owner.status()
            if state['phase'] not in allowed:
                raise ValueError('Unexpected positive operator source phase.')
            return state

        def _embraer_predecessor(self):
            previous = PREDECESSOR/'active-window'
            terminal = json.loads(read(previous/'native-window.json', PREDECESSOR_TERMINAL, private=True))
            quiet = json.loads(read(previous/'operator-quiet-window.json', PREDECESSOR_QUIET, private=True))
            exchange = json.loads(read(previous/'exchange-private/exchange.json', PREDECESSOR_EXCHANGE, private=True))
            if (terminal['phase'] != quiet['phase'] or terminal['phase'] != 'RESTORED'
                    or exchange['phase'] != 'restored'
                    or terminal['restoration_sha256'] != PREDECESSOR_RESTORATION
                    or exchange['terminal_proof_sha256'] != PREDECESSOR_RESTORATION
                    or terminal['terminal']['release_id'] != native.EMBRAER_RELEASE_ID
                    or terminal['terminal']['manifest_sha256'] != native.EMBRAER_MANIFEST_SHA256):
                raise ValueError('The previous Festo maintenance restoration proof differs.')
            return terminal

        def _wrapper_custody(self, status):
            if self.c.unscoped(self.old.wrapper_tools, native.CHANGED_WRAPPER_TOOLS) != self.wrapper_scope_sha256:
                raise ValueError('Wrapper sources changed during app-only maintenance.')

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
    window = PositiveOperatorWindow(release_id=owner.release_id, manifest_sha256=owner.manifest_pin,
                       manifest=owner.manifest, approval_check=lambda: approval['source_approval'],
                       native_modules=modules, wrapper_scope_sha256=approval['wrapper_scope_sha256'],
                       window_root=root, source_owner=owner, resume_complete=True)
    if args.action == 'ready':
        result = window.ready()
    else:
        ready = json.loads(read(STAGE/'READY_OBSERVED.json', approval['readiness_sha256'], private=True))
        if (ready['state'] != 'QUALIFIED_NATIVE_WINDOW_READY' or ready['maintenance_id'] != WINDOW_ID
                or ready['release_id'] != native.EMBRAER_RELEASE_ID or approval['apply'] is not True):
            raise ValueError('Expected a qualified, exact positive operator readiness receipt.')
        if args.action == 'restore':
            result = window.restore()
        else:
            gate = loaded['amphenol_operator_one_shot']
            with window.hold():
                base = gate._physical_directory(legacy.WRAPPER_BASE / 'tasks')
                if base is None or gate._physical_file(base / 'tasks.sqlite3') != tasks:
                    raise ValueError('The current coordinator store is unavailable.')
                with gate._coordinator_lease(base):
                    checkpoint.compare(before, checkpoint.measure(tasks, require_active=False), shutdowns=1)
                    try:
                        owner.advance(check_idle=helper.require_no_active_application_work)
                    except Exception:
                        if owner.status()['phase'] == 'PREPARED':
                            owner.rollback_prepared()
                        raise
                    if owner.status()['phase'] != 'STAGED':
                        raise ValueError('The expected successor runtime was not admitted.')
            checkpoint.compare(before, checkpoint.measure(tasks), shutdowns=1)
            result = {'state': 'NATIVE_SOURCE_ADVANCE_CONFIRMED', 'release_id': owner.release_id}
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
