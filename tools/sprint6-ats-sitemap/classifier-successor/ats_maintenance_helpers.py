from contextlib import closing
from pathlib import Path
from shutil import copy2
from tempfile import TemporaryDirectory
import os
import stat


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
    name = 'ats-' + digest
    if expected['relative_path'] != 'pilot-bases/' + name:
        raise ValueError('The stage has a different ATS baseline path.')
    source = source_owner.package / 'pilot-bases' / name
    manifest = files(source)
    if (source.resolve(strict=True) != source or not source.is_dir()
            or binding(manifest)['digest'] != digest or len(manifest) != expected['file_count']
            or source_tree_digest(source) != source_owner.spec['staged_source_sha256']):
        raise ValueError('The approved ATS baseline changed.')
    return source, manifest


def install_pilot_baseline(source_owner, coordinator_base):
    from coordinator_baseline import files
    from job_search_helper.integration_release import _fsync_directory, source_tree_digest

    source, manifest = measured_baseline(source_owner)
    parent = coordinator_base / 'pilot-bases'
    parent.mkdir(mode=0o700, exist_ok=True)
    info = parent.stat(follow_symlinks=False)
    if parent.resolve(strict=True) != parent or not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise ValueError('The ATS pilot baseline needs its private directory.')
    installed = parent / source.name

    def verify(path):
        if (not path.is_dir() or path.is_symlink() or files(path) != manifest
                or source_tree_digest(path) != source_owner.spec['staged_source_sha256']):
            raise ValueError('The dedicated pilot baseline has different installed bytes.')

    if os.path.lexists(installed):
        verify(installed)
        return
    with TemporaryDirectory(dir=parent, prefix='.ats-') as temporary:
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


