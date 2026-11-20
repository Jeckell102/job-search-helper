"""Freeze one selected ordinary successor outside the normal inbox."""
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import stat

from .ats import Inventory
from .company_events import canonical_company_fact, source_revision
from .company_sources import repair_source
from .engine import State
from .integration_release import assert_release_settled
from .repository import _url
from .retained_event_outcome import retained_outcome_source_is_current
from .retained_operator_journal import RetainedOperatorJournal, _inventory_digest
from .retained_work_runner import _inventory_snapshot, assert_normal_lifecycle_not_held
from .runner import _canonical_runtime_binding
from .scan_request import _cycle_views, _timestamp, _unfinished_from_views, cycle_metadata
from .selected_temporary_retry_admission import _bound_request, _require_saved_retry_identity, _saved_admission
from .sqlite_repository import SQLiteRepository
from .temporary_retry import SelectedTemporaryRetrySink, _sync_directory
from .scoped_provider_observation import (
    provider_identity, read_observation as _read_record, write_observation as _write_record,
)


def freeze_selected_temporary_retry_locked(sink, state, runtime_binding, *, cycle_id, fetcher,
                                           workbook_guard=None):
    """Fetch once within the caller's continuously held scraper and writer locks."""
    if not isinstance(sink, SelectedTemporaryRetrySink) or not callable(fetcher):
        raise ValueError('Selected retry execution requires the exact sink and a provider.')
    root, reader = sink.root, sink.reader
    state_path, jobs_path = root / 'state.db', root / 'jobs.sqlite3'
    if (not isinstance(state, State) or not state.readonly or Path(state.path).resolve() != state_path
            or not isinstance(reader, SQLiteRepository) or not reader.readonly or reader.path != jobs_path
            or state_path.is_symlink() or jobs_path.is_symlink()):
        raise ValueError('Selected retry execution requires the canonical read-only SQLite views.')
    assert_release_settled(root)
    if os.path.lexists(root / 'next-scan.json'):
        return {'state': 'HELD_REQUEST_SLOT'}
    outcome, ledger, key = sink._selected()
    dispatch = sink._read(ledger, key)
    if dispatch is None or dispatch['state'] != 'CLAIMED':
        return {'state': 'HELD_DISPATCH_UNCLAIMED'}
    local, mirror = _cycle_views(reader, state)
    runtime = _canonical_runtime_binding(runtime_binding)
    archive = RetainedOperatorJournal(root).read_archived_event(sink.request_sha256, sink.reservation_digest)
    if archive is None or archive['binding']['runtime'] != runtime:
        raise ValueError('Selected retry execution runtime differs from the signed reservation.')
    signed_binding = archive['binding']
    request = _bound_request(outcome, dispatch['scheduled_at'])
    request_id = request['request_id']
    saved_cycles = [row for row in local if row.get('start_request_id') == request_id]
    saved_mirrors = [row for row in mirror if cycle_metadata(row).get('start_request_id') == request_id]
    if len(saved_cycles) > 1 or len(saved_mirrors) > 1:
        raise ValueError('Selected retry execution has conflicting saved cycle identities.')
    if saved_cycles and saved_cycles[0].get('id') != cycle_id:
        raise ValueError('Selected retry execution requires the exact saved cycle.')
    assert_normal_lifecycle_not_held(root, jobs_path, selected_retry_cycle_id=cycle_id)
    blockers = sorted(_unfinished_from_views(local, mirror) - ({cycle_id} if saved_cycles else set()))
    if blockers:
        return {'state': 'HELD_UNFINISHED_CYCLE', 'blocking_cycle_ids': blockers}
    if not saved_cycles:
        return {'state': 'HELD_CLAIM_WITHOUT_STATE', 'request_id': request_id}
    cycle = saved_cycles[0]
    admission = _saved_admission(reader, cycle, saved_mirrors, request, runtime,
                                 reservation=sink.reservation_digest, recovered=True)
    if admission['state'] != 'ADMITTED_LOCAL_CYCLE':
        return admission
    cid = admission['company_id']
    if sum(row.get('Cycle ID') == cycle_id for row in mirror) != 1:
        raise ValueError('Selected retry cycle has conflicting mirror identity.')
    binding = _fetch_binding(sink, cycle, request, runtime, key)
    directory = root / 'selected-retry-inventory'
    path = directory / (cycle_id + '.json')
    saved = _read_record(path, binding)
    evidence = {'cycle_id': cycle_id, 'company_id': cid, 'outcome_id': outcome['outcome_id']}
    if saved is not None and saved['state'] == 'CLAIMED':
        return {'state': 'HELD_FETCH_UNCERTAIN', **evidence}
    if saved is not None:
        _sync_directory(directory)  # A crash may have followed rename before directory fsync.
        inventory = saved['inventory']
        evidence.update(inventory_sha256=saved['inventory_sha256'], inventory_status=inventory['status'],
                        job_count=len(inventory['jobs']))
    if _has_ordinary_work(reader, root / 'inventories.sqlite3', cycle_id):
        return {'state': 'HELD_ORDINARY_WORK_PRESENT', **evidence}

    def current_company():
        (match,) = reader.matches('Companies', {'Company ID': cid})
        row = match[1]
        item = cycle['companies'][cid]
        valid = (retained_outcome_source_is_current(reader, outcome['identity'])
                 and item.get('outcome_source_revision') == source_revision(row)
                 and item.get('outcome_source_fact') == canonical_company_fact(row)
                 and str(row.get('Company Status') or '').strip().casefold() == 'active'
                 and row.get('Active Cycle ID') == cycle_id
                 and row.get('Scan State') != 'Blocked / Manual Review'
                 and str(row.get('Automatic Retry?') or '').strip().casefold() != 'no'
                 and not any(str(row.get(field) or '').strip() for field in ('Claimed By', 'Claim Token')))
        return row if valid else None

    company = current_company()
    if company is None:
        return {'state': 'HELD_SOURCE_CHANGED', **evidence}
    if saved is not None:
        _require_frozen_provider(saved, cycle)
        return {'state': 'INVENTORY_FROZEN', **evidence, 'recovered': True}

    name, url = company['Company'], company['Official Careers URL']
    ats = company.get('ATS / Source', '')
    expected_ats, expected_url, _ = repair_source(ats, url, cid, name)
    provider = provider_identity(expected_ats, expected_url)
    if not provider:
        raise ValueError('Selected retry provider source is unverified.')
    if workbook_guard is not None:
        workbook_guard(company)
    claim = {'state': 'CLAIMED', 'binding': binding, 'fetch_started_at': sink._now().isoformat()}
    _write_record(path, claim, initial=True)
    fetched = fetcher(ats, url, cid, name)
    if not isinstance(fetched, Inventory):
        raise ValueError('Selected retry returned an invalid inventory.')
    inventory = _inventory_snapshot(fetched, company, fetched_at=sink._now().isoformat(), event_scope=True)
    if provider_identity(inventory['ats'], inventory['source_url']) != provider:
        raise ValueError('Selected retry inventory belongs to a different source.')
    inventory_sha256 = _inventory_digest(inventory, signed_binding)
    _write_record(path, {**claim, 'state': 'FROZEN', 'inventory': inventory,
                         'inventory_sha256': inventory_sha256}, initial=False)
    evidence.update(inventory_sha256=inventory_sha256, inventory_status=inventory['status'],
                    job_count=len(inventory['jobs']))
    if current_company() is None:
        return {'state': 'HELD_SOURCE_CHANGED', **evidence}
    return {'state': 'INVENTORY_FROZEN', **evidence, 'recovered': False}


def load_selected_retry_inventory(sink, state, runtime, *, cycle_id):
    """Reopen only the selected frozen fetch, including after local application."""
    outcome, ledger, key = sink._selected()
    claim = sink._read(ledger, key)
    if claim is None or claim['state'] != 'CLAIMED':
        raise ValueError('Selected retry has no durable dispatch claim.')
    archived = RetainedOperatorJournal(sink.root).read_archived_event(sink.request_sha256, sink.reservation_digest)
    if archived is None or archived['binding']['runtime'] != _canonical_runtime_binding(runtime):
        raise ValueError('Selected retry inventory runtime differs from the signed reservation.')
    request = _bound_request(outcome, claim['scheduled_at'])
    cycle = state.cycle(cycle_id)
    binding = _fetch_binding(sink, cycle, request, runtime, key)
    record = _read_record(sink.root / 'selected-retry-inventory' / (cycle_id + '.json'), binding)
    if record is None or record['state'] != 'FROZEN':
        raise ValueError('Selected retry has no verified frozen inventory.')
    _require_frozen_provider(record, cycle)
    return record


def _require_frozen_provider(record, cycle):
    binding = record['binding']
    item = cycle['companies'][binding['company_id']]
    fact = item['outcome_source_fact']
    inventory = record['inventory']
    expected_ats, expected_url, _ = repair_source(
        fact['ats_source'], inventory['requested_url'], binding['company_id'], item['company'],
    )
    provider = provider_identity(expected_ats, expected_url)
    if (_url(inventory['requested_url']) != fact['official_careers_url']
            or not provider or provider_identity(inventory['ats'], inventory['source_url']) != provider):
        raise ValueError('Selected retry frozen provider source differs from admission.')


def _fetch_binding(sink, cycle, request, runtime, key):
    cid = request['company_ids'][0]
    identity = _require_saved_retry_identity(cycle, request, runtime, reservation=sink.reservation_digest)
    return {'cycle_id': cycle['id'], 'company_id': cid, 'request': request,
            'request_fingerprint': identity['request_fingerprint'], 'runtime': runtime, 'original_outcome': key}


def _has_ordinary_work(reader, inbox, cycle_id):
    if not stat.S_ISREG(inbox.lstat().st_mode):
        raise ValueError('Selected retry requires the canonical ordinary inbox.')
    with closing(sqlite3.connect(inbox.as_uri() + '?mode=ro', uri=True)) as db:
        if db.execute('SELECT id FROM destination').fetchall() != [(reader.spreadsheet_id,)]:
            raise ValueError('Selected retry ordinary inbox destination changed.')
        for name in ('inventories', 'sync_plans', 'exact_sync_chunks'):
            if db.execute(f'SELECT 1 FROM {name} WHERE cycle=? LIMIT 1', (cycle_id,)).fetchone():
                return True
    db = reader.db
    present = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                         "AND name='exact_local_applications'").fetchone()
    return bool(present and db.execute('SELECT 1 FROM exact_local_applications WHERE cycle=? LIMIT 1',
                                       (cycle_id,)).fetchone())
