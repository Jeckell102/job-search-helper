"""Use the independently approved release from a fresh admitted scraper."""

import json
import os
from pathlib import Path
import subprocess
from contextlib import closing

from .release_controller import release_and_schedule_qualified
from .release_qualification import open_release_qualification_owner


_WORKER_REPORT = 'Qualified repair retry: '
_SCHEDULE_STATES = {
    'REQUEST_WRITTEN', 'REQUEST_ALREADY_DURABLE', 'REQUEST_ALREADY_ADMITTED',
    'WAITING_SAFE_REQUEST_BOUNDARY',
}
_WORKER_STATES = {
    'COMPLETE', 'WAITING_FOR_EXACT_RETRY', 'RETRY_INVENTORY_HELD', 'RETRY_PUBLICATION_HELD',
}


class UnfinishedScrapeWork(ValueError):
    """Saved work still owns the shared runtime."""


def release_and_continue_qualified(project_root, candidate_root, database, record_root, manifest,
                                   *, approval_path, approval_fd, owner_identity, approval_sha256,
                                   current_source_revision, dependency_digest, verify):
    """Install the approved release, then follow its retry in the measured launcher."""
    project_root = Path(project_root).resolve()
    launcher = project_root / 'job-search-scraper'
    if launcher.is_symlink() or not launcher.is_file() or not os.access(launcher, os.X_OK):
        raise ValueError('Qualified retry requires the installed scraper launcher')
    with open_release_qualification_owner(
        approval_path, approval_fd, expected_owner_identity=owner_identity,
        approved_receipt_sha256=approval_sha256,
    ) as qualification_owner:
        release = release_and_schedule_qualified(
            project_root, candidate_root, database, record_root, manifest,
            qualification_owner=qualification_owner, current_source_revision=current_source_revision,
            dependency_digest=dependency_digest, verify=verify,
            preinstall_guard=lambda exact: _require_idle_installation(Path(database), exact),
        )
        if release['state'] not in _SCHEDULE_STATES:
            return {'release': release, 'retry': None}
        execution = subprocess.run(
            [str(launcher), 'continue-qualified-repair',
             '--attempt-id', release['attempt_id'],
             '--qualification-owner-path', str(approval_path),
             '--qualification-owner-fd', str(approval_fd),
             '--qualification-owner-device', str(owner_identity[0]),
             '--qualification-owner-inode', str(owner_identity[1]),
             '--qualification-receipt-sha256', approval_sha256],
            cwd=project_root, pass_fds=(approval_fd,), text=True, capture_output=True, check=True,
        )
    reports = [line.removeprefix(_WORKER_REPORT) for line in execution.stdout.splitlines()
               if line.startswith(_WORKER_REPORT)]
    if len(reports) != 1:
        raise RuntimeError('Qualified retry worker did not return one scoped report')
    retry = json.loads(reports[0])
    if not isinstance(retry, dict) or retry.get('state') not in _WORKER_STATES:
        raise RuntimeError('Qualified retry worker returned an invalid state')
    if retry['state'] == 'COMPLETE':
        outcome = retry.get('outcome', {})
        identity = outcome.get('identity', {})
        if outcome.get('outcome') != 'COMPLETE' or any(
                identity.get(key) != release[source] for key, source in (
                    ('attempt_id', 'attempt_id'), ('release_version', 'release_id'),
                    ('failed_request_id', 'failed_request_id'), ('company_id', 'company_id'),
                    ('source_revision', 'source_revision'))):
            raise RuntimeError('Qualified retry worker completed a different release or attempt')
    return {'release': release, 'retry': retry}


def _require_idle_installation(database, manifest):
    """Never replace the runtime of any saved unfinished application cycle."""
    from .cli import job_database_path, state_path, writer_lock
    from .engine import State
    from .inbox import InventoryInbox
    from .integration_release import assert_release_settled
    from .retained_work_runner import assert_normal_lifecycle_not_held
    from .scan_request import _cycle_views, _unfinished_from_views
    from .sqlite_repository import SQLiteRepository

    database = database.resolve(strict=True)
    root = database.parent
    jobs = job_database_path() if database == state_path().resolve() else root / 'jobs.sqlite3'
    with writer_lock(root / 'writer.lock'):
        assert_normal_lifecycle_not_held(root, jobs)
        active = assert_release_settled(root)
        if active and active['state'] == 'COMPLETE' and active['release_id'] == manifest['release_id']:
            # An idempotent activation replay replaces no files.
            return
        destination = InventoryInbox.destination_id(root / 'inventories.sqlite3')
        with (closing(State(database, readonly=True)) as state,
              closing(SQLiteRepository(jobs, destination, readonly=True)) as repository):
            if _unfinished_from_views(*_cycle_views(repository, state)):
                raise UnfinishedScrapeWork('Unfinished scrape work keeps the current runtime on hold')
