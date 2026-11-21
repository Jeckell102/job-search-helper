"""Read the progress of one exact release retry from existing local records."""

from contextlib import closing
from pathlib import Path
import sqlite3
import stat

from .company_events import current_company_source_revision
from .engine import State
from .exact_cycle_receipt import (
    REPAIR_RETRY_PLAN_BINDING, repair_retry_has_confirmed_publication, repair_retry_receipt_binding,
)
from .inbox import InventoryInbox
from .integration_release import assert_active_release_binding
from .release_controller import _read_qualified_retry_intent
from .repair_retry import retry_request
from .scan_request import _read_request, request_fingerprint, superseded_cycle_ids
from .sqlite_repository import SQLiteRepository


def read_repair_retry_status(database, jobs_path, attempt_id):
    """Report local evidence without claiming a release or opening a remote client."""
    database = Path(database).resolve(strict=True)
    root = database.parent
    binding = _read_qualified_retry_intent(database, attempt_id)
    jobs_path = Path(jobs_path).resolve(strict=True)
    inbox_path = root / 'inventories.sqlite3'
    paths = (database, jobs_path, inbox_path)
    before = _checkpointed_store_snapshot(paths)
    if before is not None:
        try:
            report = _read_checkpointed_retry_status(database, jobs_path, inbox_path, binding)
        except sqlite3.DatabaseError:
            if _checkpointed_store_snapshot(paths) == before:
                raise
        else:
            if _checkpointed_store_snapshot(paths) == before:
                return report
    return {
        'attempt_id': attempt_id, 'company_id': binding['company_id'],
        'release_id': binding['release']['release_id'], 'cycle_id': None,
        'status': 'STATUS_SNAPSHOT_BUSY',
        'message': 'SQLite still has pending journal data or the local stores changed during this check.',
    }


def _checkpointed_store_snapshot(paths):
    snapshot = []
    for path in paths:
        attrs = path.lstat()
        if not stat.S_ISREG(attrs.st_mode):
            raise ValueError('Local retry status requires ordinary SQLite files.')
        for suffix in ('-wal', '-journal'):
            try:
                journal = path.with_name(path.name + suffix).lstat()
            except FileNotFoundError:
                continue
            if not stat.S_ISREG(journal.st_mode) or journal.st_size:
                return None
        snapshot.append((attrs.st_dev, attrs.st_ino, attrs.st_size, attrs.st_mtime_ns, attrs.st_ctime_ns))
    return snapshot


def _read_checkpointed_retry_status(database, jobs_path, inbox_path, binding):
    root = database.parent
    attempt_id = binding['attempt_id']
    company = binding['company_id']
    release = binding['release']
    request = retry_request(binding, enqueued_at=binding['activated_at'])
    fingerprint = request_fingerprint(request, [company])
    destination = InventoryInbox.destination_id(inbox_path, immutable=True)
    scope = {'attempt_id': attempt_id, 'company_id': company, 'release_id': release['release_id']}

    def result(status, message, *, cycle=None):
        return {**scope, 'cycle_id': cycle, 'status': status, 'message': message}

    with (closing(State(database, readonly=True, immutable=True)) as state,
          closing(SQLiteRepository(jobs_path, destination, readonly=True, immutable=True)) as jobs,
          closing(InventoryInbox(inbox_path, destination, readonly=True, immutable=True)) as inbox):
        cycles = state.cycles()
        owners = [cycle for cycle in cycles
                  if (cycle.get('start_request_id') == request['request_id']
                      or cycle.get('request_fingerprint') == fingerprint
                      or isinstance(cycle.get('repair_retry'), dict)
                      and cycle['repair_retry'].get('attempt_id') == attempt_id)]
        if len(owners) > 1:
            return result('HELD_OWNERSHIP', 'More than one saved cycle claims this retry.')
        cycle = owners[0] if owners else None
        cycle_id = cycle['id'] if cycle is not None else None
        receipt = None
        if cycle is not None:
            if (cycle.get('start_request_id') != request['request_id']
                    or cycle.get('request_fingerprint') != fingerprint or cycle.get('repair_retry') != binding):
                return result('HELD_OWNERSHIP', 'The saved cycle disagrees with this retry.', cycle=cycle_id)
            try:
                receipt_binding = repair_retry_receipt_binding(cycle, company)
            except ValueError:
                return result('HELD_OWNERSHIP', 'The saved Company or runtime binding changed.',
                              cycle=cycle_id)
            if (cycle['companies'][company].get('stage') == 'complete'
                    and repair_retry_has_confirmed_publication(inbox, jobs, cycle, company)):
                return result('SYNC_CONFIRMED', 'Jobs and Sheets were confirmed for this retry.', cycle=cycle_id)
            receipt = inbox.receipt({'binding': receipt_binding})

        try:
            assert_active_release_binding(root, release)
        except ValueError:
            return result('HELD_RELEASE', 'This retry’s exact release is no longer active.', cycle=cycle_id)
        if current_company_source_revision(jobs, company) != binding['source_revision']:
            return result('HELD_SOURCE', 'The Company source changed or is paused.', cycle=cycle_id)
        matches = jobs.matches('Companies', {'Company ID': company})
        if len(matches) != 1:
            return result('HELD_SOURCE', 'The Company source is no longer unique.', cycle=cycle_id)
        company_row = matches[0][1]
        if (company_row.get('Claimed By') or company_row.get('Claim Token')
                or cycle_id is not None and company_row.get('Active Cycle ID') != cycle_id):
            return result('HELD_OWNERSHIP', 'The Company is no longer available to this retry.', cycle=cycle_id)
        if cycle is None:
            path = root / 'next-scan.json'
            if path.is_file() and _read_request(path) == (request, [company]):
                return result('WAITING_TO_SCRAPE', 'The exact Company retry is queued for safe admission.')
            return result('WAITING_FOR_QUEUE', 'This retry is recorded and is waiting for its queue slot.')
        if cycle_id in superseded_cycle_ids(cycles):
            return result('HELD_OWNERSHIP', 'A later cycle superseded this retry.', cycle=cycle_id)
        if receipt is not None and receipt['binding'] == receipt_binding:
            if receipt['state'] == 'SYNC_CONFIRMED':
                return result('CLOSEOUT_PENDING', 'Final local closeout is still unverified.', cycle=cycle_id)
            local_plan = inbox.exact_local_state(cycle_id, company)
            if local_plan is not None and local_plan['state'] == 'LOCAL_VERIFIED':
                plan, _ = inbox.plan(cycle_id, company)
                verified = jobs.db.execute(
                    'SELECT state,plan_digest FROM exact_local_applications '
                    'WHERE apply_id=? AND cycle=? AND company=?',
                    (local_plan['local_apply_id'], cycle_id, company),
                ).fetchone()
                if (verified == ('VERIFIED', local_plan['plan_digest'])
                        and plan.get(REPAIR_RETRY_PLAN_BINDING) == receipt_binding):
                    return result('SAVED_SYNC_PENDING',
                                  'Jobs are recorded locally. Sheets confirmation is pending.', cycle=cycle_id)
        inventory = inbox.get(cycle_id, company)
        if inventory is not None:
            saved, blocked = inventory
            if (blocked or saved.get('inventory_status') != 'complete' or not saved.get('jobs')
                    or saved.get('browser_pending_urls') or saved.get('browser_discovery_incomplete')):
                return result('HELD_INVENTORY', 'The saved inventory is incomplete or needs review.',
                              cycle=cycle_id)
            return result('INVENTORY_SAVED', 'Inventory is saved. Jobs and Sheets are still pending.',
                          cycle=cycle_id)
        if cycle['status'] == 'In Progress' and cycle['companies'][company].get('stage') == 'queued':
            return result('AWAITING_INVENTORY', 'The Company is admitted. Its inventory is still pending.',
                          cycle=cycle_id)
        return result('HELD_EVIDENCE', 'No matching terminal publication is verified.', cycle=cycle_id)
