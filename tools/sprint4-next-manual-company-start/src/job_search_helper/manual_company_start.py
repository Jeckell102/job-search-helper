"""Route one ordinary Company event from a manual bare start."""

from contextlib import ExitStack, closing
import os

from . import cli
from .company_events import (BRIDGE_CONSUMER, CompanyEventBridge, _json_digest,
                             has_pending_eligible_company_event, read_verified_queued_event)
from .integration_release import assert_release_settled
from .ordinary_company_event_command import (
    _has_event_provenance, _open_readers, _request_file, execute_ordinary_event,
)
from .retained_work_runner import assert_normal_lifecycle_not_held
from .sqlite_repository import SQLiteRepository


def manual_company_start_pending(database):
    """Check for work without consuming the startup lease or opening a workbook."""
    request = _request_file(database.parent)
    if request is not None:
        return 'manual_retained' not in request and _has_event_provenance(request, request_field='request_id')
    jobs = cli.job_database_path()
    if (cli.storage_backend() != 'sqlite' or jobs != database.with_name('jobs.sqlite3')
            or jobs.resolve(strict=True) != jobs):
        raise ValueError('Manual Company selection requires the admitted local SQLite layout')
    with closing(SQLiteRepository(jobs, os.environ.get('SPREADSHEET_ID', ''), readonly=True)) as repository:
        return has_pending_eligible_company_event(repository)


def run_manual_company_start(admission):
    """Under inherited scraper admission, bridge and run only the exact event."""
    database, jobs, _ = admission
    root = database.parent
    with cli.writer_lock(root / 'writer.lock'), ExitStack() as readers:
        assert_release_settled(root)
        local, _ = _open_readers(readers, database, jobs, root / 'inventories.sqlite3')
        request = _request_file(root)
        if request is None:
            with closing(SQLiteRepository(jobs, local.spreadsheet_id)) as repository:
                bridge = CompanyEventBridge(repository, root, state_database=database)
                events = repository.pending_latest_company_events(BRIDGE_CONSUMER, limit=2)
                if len(events) != 1 or events[0]['kind'] != 'company.eligible':
                    return {'state': 'HELD_MANUAL_EVENT_NOT_UNIQUE'}
                [observed] = bridge.observe_pending()['events']
                if observed['state'] != 'PROPOSED_COMPANY_ONLY_SCRAPE':
                    return {'state': 'HELD_MANUAL_EVENT_STALE'}
                assert_normal_lifecycle_not_held(root, jobs)
                [delivery] = bridge.process_pending(limit=1, writer_lock_held=True)
                if delivery['state'] != 'REQUEST_WRITTEN' or delivery['event_id'] != events[0]['event_id']:
                    return {'state': 'HELD_MANUAL_EVENT_BRIDGE', 'bridge': delivery}
                _, request = read_verified_queued_event(repository, root)
        else:
            _, request = read_verified_queued_event(local, root)
        request_digest = _json_digest(request)

    result = execute_ordinary_event('admit-fetch', admission, request_sha256=request_digest)
    if result['state'] != 'INVENTORY_FROZEN':
        return result
    return execute_ordinary_event('publish', admission, request_sha256=request_digest, cycle_id=result['cycle_id'])
