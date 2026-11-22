"""Route one ordinary Company event from a manual bare start."""

from collections import Counter
from contextlib import ExitStack, closing
import os

from . import cli
from .company_events import (BRIDGE_CONSUMER, INELIGIBLE_STATUSES, CompanyEventBridge,
                             _json_digest, has_pending_eligible_company_event,
                             read_verified_queued_event)
from .integration_release import assert_release_settled
from .ordinary_company_event_command import (
    _has_event_provenance, _open_readers, _request_file, execute_ordinary_event,
)
from .repository import _identity_key
from .retained_work_runner import assert_normal_lifecycle_not_held
from .sheet_profile import COMPACT_PROFILE, COMPACT_SCHEMAS
from .sheets_sync import unique_rows
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


def _external_addition(repository, *, interactive=False):
    if (repository.get_meta('company_event_external_baseline') != 'yes'
            or repository.get_meta('sheets_profile') != COMPACT_PROFILE):
        return None
    remote = cli.get_remote_repository(write=False, interactive=interactive, schemas=COMPACT_SCHEMAS,
                                       evidence_archives=False)
    if remote.spreadsheet_id != repository.spreadsheet_id or remote.schemas != COMPACT_SCHEMAS:
        raise ValueError('Manual Company discovery requires the current compact workbook.')
    companies = repository.read_columns('Companies', ['Company ID', 'Company'])
    known_names = {_identity_key('Company', row['Company']) for _, row in companies}
    known_ids = {_identity_key('Company ID', row['Company ID']) for _, row in companies}
    known_ids.update(_identity_key('Company ID', company_id) for (company_id,) in
                     repository.db.execute('SELECT DISTINCT company_id FROM company_revisions'))
    rows = unique_rows('Companies', list(enumerate(remote.read('Companies'), 2)))
    sheet_names = Counter(_identity_key('Company', row.get('Company') or '') for _, row in rows)
    additions = []
    for number, row in rows:
        company_id = _identity_key('Company ID', row.get('Company ID') or '')
        name = _identity_key('Company', row.get('Company') or '')
        if not name or (company_id and company_id in known_ids) or (not company_id and name in known_names):
            continue
        status = str(row.get('Company Status') or '').strip().casefold()
        if status in INELIGIBLE_STATUSES or not str(row.get('Official Careers URL') or '').strip():
            continue
        if not company_id:
            raise ValueError('A new eligible Company in Sheets needs a stable Company ID for manual intake.')
        if status != 'active':
            raise ValueError('A new Company in Sheets needs an explicit Active status for manual intake.')
        if sheet_names[name] != 1 or repository.company_name_is_owned(name):
            raise ValueError('A new Company ID in Sheets conflicts with a current or historical Company name.')
        additions.append((number, row))
    if len(additions) > 1:
        raise ValueError('Multiple new eligible Companies in Sheets need separate scoped intake.')
    return additions[0] if additions else None


def read_manual_company_addition(database):
    """Look for a new workbook-only Company without consuming startup admission."""
    if _request_file(database.parent) is not None:
        return None
    jobs = database.with_name('jobs.sqlite3')
    with closing(SQLiteRepository(jobs, os.environ.get('SPREADSHEET_ID', ''), readonly=True)) as repository:
        return _external_addition(repository, interactive=True)


def run_manual_company_start(admission, *, external_addition=None):
    """Under inherited scraper admission, bridge and run only the exact event."""
    database, jobs, _ = admission
    root = database.parent
    with cli.writer_lock(root / 'writer.lock'), ExitStack() as readers:
        assert_release_settled(root)
        local, _ = _open_readers(readers, database, jobs, root / 'inventories.sqlite3')
        request = _request_file(root)
        if request is not None and external_addition is not None:
            raise ValueError('A different request arrived during manual Company discovery.')
        if request is None:
            with closing(SQLiteRepository(jobs, local.spreadsheet_id)) as repository:
                events = repository.pending_latest_company_events(BRIDGE_CONSUMER, limit=2)
                if external_addition is not None:
                    if events:
                        raise ValueError('A Company event arrived during manual Company discovery.')
                    assert_normal_lifecycle_not_held(root, jobs)
                    fresh = _external_addition(repository)
                    if fresh is None or fresh[1] != external_addition[1]:
                        raise ValueError('The new Company in Sheets changed during manual discovery.')
                    imported = repository.import_companies_with_events(
                        [fresh], origin='sheets-reconciliation', require_new=True)
                    events = imported['company_events']
                bridge = CompanyEventBridge(repository, root, state_database=database)
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
    scope = {'request_sha256': request_digest, 'cycle_id': result['cycle_id']}
    return {**scope, **execute_ordinary_event('publish', admission, **scope)}
