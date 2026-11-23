"""Apply the pinned ATS source package through the existing native hold."""

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
    custody = load('native_ats_file_custody', legacy.CUSTODY, legacy.CUSTODY_PIN)
    read = custody.file_bytes
    approval = json.loads(read(args.approval, args.sha256, private=True))
    if (approval['maintenance_id'] != WINDOW_ID or approval['package_sha256'] != PACKAGE_PIN
            or approval['purpose'] != 'ats-owned-source-only'):
        raise ValueError('Unexpected ATS work order.')
    tool_pins = approval['tool_sha256']
    read(Path(__file__).resolve(), tool_pins['native_ats_entry.py'])
    sys.path[:0] = [str(PROJECT/'src'), str(legacy.WRAPPER_BASE/'tools')]
    load('release_admission_bootstrap', STAGE/'before/release_admission_bootstrap.py',
         '689f644523b1fa1f691eeaf863e84acfc8a39fd8974bb05721d0246b144330f9')
    from job_search_helper.cli import load_environment

    load_environment(PROJECT/'.env')
    load('native_source_advance', STAGE/'native_source_advance.py', tool_pins['native_source_advance.py'])
    source = load('ats_source_owner', STAGE/'maintenance_source_owner.py', tool_pins['maintenance_source_owner.py'])
    owner = source.MaintenanceSourceOwner(PROJECT, STAGE, PACKAGE_PIN)
    helper = load('ats_helpers', STAGE/'ats_maintenance_helpers.py', tool_pins['ats_maintenance_helpers.py'])
    checkpoint = load('ats_custody', STAGE/'ats_custody.py', tool_pins['ats_custody.py'])
    tasks = legacy.WRAPPER_BASE/'tasks/tasks.sqlite3'
    postures = ('measure', 'ready', 'apply')
    if args.action in postures:
        helper.require_no_active_application_work(PROJECT)
        before = checkpoint.measure(tasks)
        helper.measured_baseline(owner)
        if owner.status()['phase'] != 'BEFORE':
            raise ValueError('The exact installed predecessor is required.')
    if args.action == 'measure':
        print(json.dumps({'phase':'BEFORE', 'release_id':owner.release_id,
                          'manifest_sha256':owner.manifest_pin, 'coordinator':before}, sort_keys=True))
        return
    before = json.loads(read(STAGE/'COORDINATOR_BEFORE.json', approval['coordinator_before_sha256'], private=True))
    if args.action in ('ready', 'apply'):
        checkpoint.compare(before, checkpoint.measure(tasks), shutdowns=0)

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
    if args.action == 'ready':
        result = window.ready()
    else:
        ready = json.loads(read(STAGE/'READY_OBSERVED.json', approval['readiness_sha256'], private=True))
        if (ready['state'] != 'QUALIFIED_NATIVE_WINDOW_READY' or ready['maintenance_id'] != WINDOW_ID
                or ready['release_id'] != native.EMBRAER_RELEASE_ID or approval['apply'] is not True):
            raise ValueError('Expected a qualified, exact ATS readiness receipt.')
        if args.action == 'restore':
            result = window.restore()
        else:
            result = helper.apply_under_native_hold(window, owner, loaded['amphenol_operator_one_shot'],
                                                    legacy.WRAPPER_BASE, checkpoint, before)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
