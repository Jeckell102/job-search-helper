"""Install the exact Sprint 6 source package in its approved MuleLab window."""

import argparse
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sys
from types import ModuleType


PROJECT = Path('/home/chris/job-search-helper_old')
STAGE = Path(__file__).resolve().parent
WINDOW_STAGE = Path('/tmp/jsh-s6-native-source-window-09')
PACKAGE_PIN = 'b14f02e6d25b6aad4765ffa8313353d19d9b88ff3c9af616045542515198dccd'
PRIOR_ENTRY = Path('/tmp/jsh-amphenol-production-pacing.q7WLuQwO/release_entry.py')
PRIOR_ENTRY_PIN = '5247f191d02598f760c49e13f6b7e61aef62762b9f74459078d1778ed5f91ca7'
CUSTODY = Path('/tmp/jsh-amphenol-exact-publication-repro.oFka58ph/approved_notes_recovery_entry.py')
CUSTODY_PIN = '0ac6a0079aa9f718a8ee40718c1337bb5896fa9cd95180bc2fd4b76e56e8835f'
BOOTSTRAP = 'release_admission_bootstrap.py'


def load_measured(name, path, pin, *, reader=None):
    raw = path.read_bytes() if reader is None else reader(path, pin)
    if sha256(raw).hexdigest() != pin or name in sys.modules:
        raise ValueError('A measured maintenance entry changed or was already imported: ' + path.name)
    module = ModuleType(name)
    module.__file__ = str(path)
    sys.modules[name] = module
    exec(compile(raw, str(path), 'exec'), module.__dict__)
    return module


def load_approved_bootstrap(read):
    package = json.loads(read(STAGE / 'PREPARED_PACKAGE.json', PACKAGE_PIN, private=True))
    images = package['package_files'][BOOTSTRAP]
    path = PROJECT / BOOTSTRAP
    for endpoint in ('before', 'staged'):
        pin = images[endpoint]['sha256']
        try:
            raw = read(path, pin)
        except ValueError:
            continue
        return load_measured('release_admission_bootstrap', path, pin, reader=lambda *_: raw)
    raise ValueError('The installed admission bootstrap matches neither approved source image.')


def require_no_active_application_work(project):
    from job_search_helper.engine import State
    from job_search_helper.inbox import InventoryInbox
    from job_search_helper.retained_cycle_retirement_control import verified_retired_cycle_ids
    from job_search_helper.retained_work_runner import assert_normal_lifecycle_not_held
    from job_search_helper.runner import FINISHED, active_inbox_cycles
    from job_search_helper.scan_request import superseded_cycle_ids

    root = project / '.state'
    assert_normal_lifecycle_not_held(root, root / 'jobs.sqlite3')
    destination = InventoryInbox.destination_id(root / 'inventories.sqlite3')
    with (closing(State(root / 'state.db', readonly=True)) as state,
          closing(InventoryInbox(root / 'inventories.sqlite3', destination, readonly=True)) as inbox):
        cycles = state.cycles()
        retired = verified_retired_cycle_ids(state)
        excluded = retired | superseded_cycle_ids(cycles)
        if (any(cycle['id'] not in excluded and cycle['status'] not in FINISHED for cycle in cycles)
                or active_inbox_cycles(inbox, state)):
            raise ValueError('An unfinished scrape still owns the running application.')


def apply_under_native_hold(window, source_owner, coordinator_gate, coordinator_base):
    if source_owner.status()['phase'] != 'BEFORE':
        raise ValueError('The approved predecessor is required before opening a new maintenance window.')
    with window.hold():
        base = coordinator_gate._physical_directory(coordinator_base / 'tasks')
        tasks = coordinator_gate._physical_file(base / 'tasks.sqlite3') if base else None
        if tasks is None:
            raise ValueError('The current coordinator store is unavailable.')
        with coordinator_gate._coordinator_lease(base):
            if not coordinator_gate._coordinator_is_idle(tasks):
                raise ValueError('The current coordinator still has active or enabled work.')
            try:
                source_owner.advance(check_idle=require_no_active_application_work)
            except Exception:
                if source_owner.status()['phase'] == 'PREPARED':
                    source_owner.rollback_prepared()
                raise
            if source_owner.status()['phase'] != 'STAGED':
                raise ValueError('The expected successor runtime was not admitted.')
    return {'state': 'NATIVE_SOURCE_ADVANCE_CONFIRMED', 'release_id': source_owner.release_id}


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument('action', choices=('measure', 'ready', 'apply', 'restore'))
    parser.add_argument('--approval', type=Path, required=True)
    parser.add_argument('--approval-sha256', required=True)
    args = parser.parse_args()
    if (not sys.flags.isolated or not sys.flags.dont_write_bytecode or sys.pycache_prefix != '/dev/null'
            or Path(sys.prefix).resolve(strict=True) != PROJECT / '.venv'):
        raise ValueError('Use the installed release Python in isolated, no-cache mode.')
    custody = load_measured('checked_native_source_custody', CUSTODY, CUSTODY_PIN)
    read = custody.file_bytes
    approval = json.loads(read(args.approval, args.approval_sha256, private=True))
    schemas = {'s6-native-source-advance-approval-v1'}
    if args.action == 'measure':
        schemas.add('s6-native-source-advance-measurement-v1')
    if args.action == 'ready':
        schemas.add('s6-native-source-advance-readiness-v1')
    if approval['schema'] not in schemas or approval['package_sha256'] != PACKAGE_PIN:
        raise ValueError('The exact source package needs separate approval for native access.')
    pins = approval['tool_sha256']
    read(Path(__file__).resolve(), pins['native_source_release_entry.py'])
    load_approved_bootstrap(read)
    prior = load_measured('checked_native_source_predecessor', PRIOR_ENTRY, PRIOR_ENTRY_PIN, reader=read)
    prior.NATIVE_STAGE = WINDOW_STAGE
    loaded = prior.verify_tool_origins()
    from job_search_helper.cli import load_environment
    from job_search_helper.integration_release import digest

    load_environment(PROJECT / '.env')
    load_measured('native_source_advance', STAGE / 'native_source_advance.py',
                  pins['native_source_advance.py'], reader=read)
    transition = load_measured('maintenance_source_owner', STAGE / 'maintenance_source_owner.py',
                               pins['maintenance_source_owner.py'], reader=read)
    source_owner = transition.MaintenanceSourceOwner(PROJECT, STAGE, PACKAGE_PIN)
    if args.action == 'measure':
        measurement = source_owner.status()
        print(json.dumps({key: measurement[key] for key in ('phase', 'release_id', 'manifest_sha256')}, sort_keys=True))
        return 0

    native = approval['native']
    read(Path(native['independent_review_path']), native['independent_review_sha256'])
    qualification_type = loaded['amphenol_retry_completion'].RetryReleaseApproval
    qualification = qualification_type.from_json(read(
        Path(approval['predecessor_qualification_path']), approval['predecessor_qualification_sha256'],
        private=True).decode())
    _, manifest = qualification.read_install_inputs()
    if manifest['release_id'] != prior.RELEASE_ID or digest(manifest) != prior.MANIFEST_SHA:
        raise ValueError('The original independently qualified Amphenol predecessor changed.')

    def predecessor_check():
        _, current = qualification.read_install_inputs()
        if current != manifest:
            raise ValueError('The independently qualified predecessor changed during maintenance.')
        return {'release_id': prior.RELEASE_ID, 'manifest_sha256': prior.MANIFEST_SHA}

    module, modules = prior.load_native_window(loaded, native['window_sha256'])
    window = module.create_window(
        release_id=prior.RELEASE_ID, manifest_sha256=prior.MANIFEST_SHA, manifest=manifest,
        qualification_check=predecessor_check, native_modules=modules,
        wrapper_scope_sha256=native['wrapper_scope_sha256'], window_root=Path(native['window_root']),
        resume_complete=True, source_owner=source_owner,
    )
    if args.action == 'ready':
        if source_owner.status()['phase'] != 'BEFORE':
            raise ValueError('The approved predecessor is no longer the active MuleLab version.')
        result = window.ready()
    elif args.action == 'restore':
        result = window.restore()
    else:
        result = apply_under_native_hold(window, source_owner, loaded['amphenol_operator_one_shot'],
                                         loaded['host_server'].BASE)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
