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
            or approval['purpose'] != 'ats-classifier-source-only'):
        raise ValueError('Unexpected ATS work order.')
    tool_pins = approval['tool_sha256']
    read(Path(__file__).resolve(), tool_pins['native_ats_entry.py'])
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
