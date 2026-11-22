"""Install the exact Crown admission package in its approved MuleLab window."""

import argparse
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
from shutil import copy2
import os
import stat
from tempfile import TemporaryDirectory
import sys
from types import ModuleType


PROJECT = Path('/home/chris/job-search-helper_old')
STAGE = Path(__file__).resolve().parent
WINDOW_STAGE = STAGE
WINDOW_ID = 's6-crown-owned-source-20261122-18'
WINDOW_ROOT = WINDOW_STAGE / 'active-window'
WRAPPER_BASE = PROJECT / 'dev/wrapper-coder'
PACKAGE_PIN = 'a58de91c7d5e7e9b9cf624db5649b693ca723ba90c0f581e339032d04e70cdfa'
PRIOR_ENTRY = Path('/tmp/jsh-amphenol-production-pacing.q7WLuQwO/release_entry.py')
PRIOR_ENTRY_PIN = '5247f191d02598f760c49e13f6b7e61aef62762b9f74459078d1778ed5f91ca7'
CUSTODY = Path('/tmp/jsh-amphenol-exact-publication-repro.oFka58ph/approved_notes_recovery_entry.py')
CUSTODY_PIN = '0ac6a0079aa9f718a8ee40718c1337bb5896fa9cd95180bc2fd4b76e56e8835f'
BOOTSTRAP_PIN = '0a1eca6877ef7b78cd851d2e5de15528c166bf31da96ca361f705cd48b7b4a00'


def load_measured(name, path, pin, *, reader=None):
    raw = path.read_bytes() if reader is None else reader(path, pin)
    if sha256(raw).hexdigest() != pin or name in sys.modules:
        raise ValueError('A measured maintenance entry changed or was already imported: ' + path.name)
    module = ModuleType(name)
    module.__file__ = str(path)
    sys.modules[name] = module
    exec(compile(raw, str(path), 'exec'), module.__dict__)
    return module


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



def measured_baseline(source_owner):
    from coordinator_baseline import binding, files
    from job_search_helper.integration_release import source_tree_digest

    expected = source_owner.spec['pilot_baseline']
    digest = expected['sha256']
    name = 'crown-' + digest
    if expected['relative_path'] != 'pilot-bases/' + name:
        raise ValueError('The stage has a different Crown baseline path.')
    source = source_owner.package / 'pilot-bases' / name
    manifest = files(source)
    if (source.resolve(strict=True) != source or not source.is_dir()
            or binding(manifest)['digest'] != digest or len(manifest) != expected['file_count']
            or source_tree_digest(source) != source_owner.spec['staged_source_sha256']):
        raise ValueError('The approved Crown baseline changed.')
    return source, manifest


def install_pilot_baseline(source_owner, coordinator_base):
    from coordinator_baseline import files
    from job_search_helper.integration_release import _fsync_directory, source_tree_digest

    source, manifest = measured_baseline(source_owner)
    parent = coordinator_base / 'pilot-bases'
    parent.mkdir(mode=0o700, exist_ok=True)
    info = parent.stat(follow_symlinks=False)
    if parent.resolve(strict=True) != parent or not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise ValueError('The Crown pilot baseline needs its private directory.')
    installed = parent / source.name

    def verify(path):
        if (not path.is_dir() or path.is_symlink() or files(path) != manifest
                or source_tree_digest(path) != source_owner.spec['staged_source_sha256']):
            raise ValueError('The dedicated pilot baseline has different installed bytes.')

    if os.path.lexists(installed):
        verify(installed)
        return
    with TemporaryDirectory(dir=parent, prefix='.crown-') as temporary:
        staged = Path(temporary) / 'baseline'
        for name in sorted(manifest):
            dest = staged / name
            dest.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            copy2(source / name, dest)
            with dest.open('rb') as file:
                os.fsync(file.fileno())
        verify(staged)
        for directory, _, _ in os.walk(staged, topdown=False):
            _fsync_directory(Path(directory))
        staged.rename(installed)
        _fsync_directory(parent)
    _fsync_directory(coordinator_base)
    verify(installed)


def apply_under_native_hold(window, source_owner, coordinator_gate, coordinator_base, custody, before):
    if source_owner.status()['phase'] != 'BEFORE':
        raise ValueError('The approved predecessor is required before opening a new maintenance window.')
    measured_baseline(source_owner)
    with window.hold():
        base = coordinator_gate._physical_directory(coordinator_base / 'tasks')
        tasks = coordinator_gate._physical_file(base / 'tasks.sqlite3') if base else None
        if tasks is None:
            raise ValueError('The current coordinator store is unavailable.')
        with coordinator_gate._coordinator_lease(base):
            custody.compare(before, custody.measure(tasks, require_active=False), shutdowns=1)
            try:
                install_pilot_baseline(source_owner, coordinator_base)
                source_owner.advance(check_idle=require_no_active_application_work)
            except Exception:
                if source_owner.status()['phase'] == 'PREPARED':
                    source_owner.rollback_prepared()
                raise
            if source_owner.status()['phase'] != 'STAGED':
                raise ValueError('The expected successor runtime was not admitted.')
    custody.compare(before, custody.measure(tasks), shutdowns=1)
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
    schemas = {'s6-crown-source-advance-approval-v1'}
    if args.action == 'measure':
        schemas.add('s6-crown-source-advance-measurement-v1')
    if args.action == 'ready':
        schemas.add('s6-crown-source-advance-readiness-v1')
    if approval['schema'] not in schemas or approval['package_sha256'] != PACKAGE_PIN:
        raise ValueError('The exact source package needs separate approval for native access.')
    pins = approval['tool_sha256']
    read(Path(__file__).resolve(), pins['native_crown_entry.py'])
    # The approved before-image has identical runtime measurement semantics on
    # both sides and during rollback, while the installed launcher may be mixed.
    load_measured('release_admission_bootstrap', STAGE / 'before/release_admission_bootstrap.py',
                  BOOTSTRAP_PIN, reader=read)
    sys.path[:0] = [str(PROJECT / 'src'), str(WRAPPER_BASE / 'tools')]
    from job_search_helper.cli import load_environment

    load_environment(PROJECT / '.env')
    load_measured('native_source_advance', STAGE / 'native_source_advance.py',
                  pins['native_source_advance.py'], reader=read)
    transition = load_measured('maintenance_source_owner', STAGE / 'maintenance_source_owner.py',
                               pins['maintenance_source_owner.py'], reader=read)
    source_owner = transition.MaintenanceSourceOwner(PROJECT, STAGE, PACKAGE_PIN)
    custody_check = load_measured('crown_release_custody', STAGE / 'crown_custody.py',
                                  pins['crown_custody.py'], reader=read)
    before = json.loads(read(STAGE / 'COORDINATOR_BEFORE.json',
                             approval['coordinator_before_sha256'], private=True))
    tasks = WRAPPER_BASE / 'tasks/tasks.sqlite3'
    if args.action in {'measure', 'ready', 'apply'}:
        custody_check.compare(before, custody_check.measure(tasks), shutdowns=0)
        require_no_active_application_work(PROJECT)
    if args.action == 'measure':
        measured_baseline(source_owner)
        measurement = source_owner.status()
        print(json.dumps({key: measurement[key] for key in ('phase', 'release_id', 'manifest_sha256')}, sort_keys=True))
        return 0

    native = approval['native']
    if Path(native['window_root']) != WINDOW_ROOT:
        raise ValueError('The exact private Crown window is required.')
    read(Path(native['independent_review_path']), native['independent_review_sha256'])
    prior = load_measured('checked_native_source_predecessor', PRIOR_ENTRY, PRIOR_ENTRY_PIN, reader=read)
    prior.NATIVE_STAGE = WINDOW_STAGE
    host = 'dev/wrapper-coder/tools/host_server.py'
    actual = source_owner.status()['endpoints'][host]
    prior.INSTALLED_PINS = {
        **prior.INSTALLED_PINS, 'host_server.py': actual['sha256'],
        'coordinator_store.py': '028bb731ddf9cfce1ec9e228dd1ab8d6c4511aae94117e2e1243778f6b57d1f4',
    }
    loaded = prior.verify_tool_origins()
    scope = {
        'schema': 's6-crown-source-maintenance-approval-v1',
        'release_id': source_owner.release_id,
        'manifest_sha256': source_owner.manifest_pin,
        'package_sha256': source_owner.pin,
        'source_sha256': source_owner.spec['staged_source_sha256'],
        'predecessor_release_id': source_owner.spec['live_runtime']['release_id'],
        'predecessor_journal_sha256': source_owner.spec['live_journal_sha256'],
    }
    if approval.get('source_approval') != scope:
        raise ValueError('The supervisor record does not bind this exact predecessor and candidate.')
    if args.action in {'apply', 'restore'}:
        if (approval.get('operator_confirmed') is not True
                or approval.get('maintenance_window') != WINDOW_ID):
            raise ValueError('The operator confirmation for the exact quiet window is required.')
        ready = json.loads(read(Path(approval['ready_path']), approval['ready_sha256'], private=True))
        if (ready.get('state') != 'QUALIFIED_NATIVE_WINDOW_READY'
                or ready.get('maintenance_id') != approval['maintenance_window']
                or ready.get('release_id') != scope['predecessor_release_id']):
            raise ValueError('The exact native readiness record is required for application or recovery.')

    baseline = source_owner.spec['pilot_baseline']
    if approval.get('pilot_baseline') != baseline:
        raise ValueError('The supervisor record does not bind the dedicated pilot baseline.')

    def source_approval():
        return json.loads(read(args.approval, args.approval_sha256, private=True))['source_approval']

    module, modules = prior.load_native_window(loaded, native['window_sha256'])
    window = module.create_window(
        release_id=source_owner.release_id, manifest_sha256=source_owner.manifest_pin,
        manifest=source_owner.manifest, approval_check=source_approval, native_modules=modules,
        wrapper_scope_sha256=native['wrapper_scope_sha256'], window_root=Path(native['window_root']),
        resume_complete=True, source_owner=source_owner,
    )
    if args.action == 'ready':
        if source_owner.status()['phase'] != 'BEFORE':
            raise ValueError('The approved predecessor is no longer the active MuleLab version.')
        measured_baseline(source_owner)
        result = window.ready()
    elif args.action == 'restore':
        result = window.restore()
    else:
        result = apply_under_native_hold(window, source_owner, loaded['amphenol_operator_one_shot'],
                                         loaded['host_server'].BASE, custody_check, before)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
