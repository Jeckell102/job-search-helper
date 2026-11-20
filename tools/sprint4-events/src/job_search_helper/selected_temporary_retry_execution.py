"""Freeze one selected ordinary successor outside the normal inbox."""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import stat
import tempfile

from .ats import Inventory, resolve_board
from .company_events import canonical_company_fact, source_revision
from .company_sources import repair_source
from .engine import State
from .integration_release import assert_release_settled
from .retained_event_outcome import retained_outcome_source_is_current
from .retained_operator_journal import RetainedOperatorJournal, _inventory_digest
from .retained_work_exception import _provider_identity
from .retained_work_runner import _inventory_snapshot, assert_normal_lifecycle_not_held
from .runner import _canonical_runtime_binding
from .scan_request import _cycle_views, _timestamp, _unfinished_from_views, cycle_metadata
from .selected_temporary_retry_admission import _bound_request, _require_saved_retry_identity, _saved_admission
from .sqlite_repository import SQLiteRepository
from .temporary_retry import SelectedTemporaryRetrySink, _canonical, _selected_sha, _sync_directory


def _selected_provider_identity(ats, url):
    identity = _provider_identity(ats, url)
    provider = identity.partition(':')[0]
    if provider not in {'greenhouse', 'lever', 'ashby'}:
        return identity
    try:
        adapter, board, _ = resolve_board(ats, url)
    except ValueError:
        return ''
    return provider + ':' + board.casefold() if adapter.casefold() == provider else ''


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
    saved = _read_record(path, binding, signed_binding)
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
        return {'state': 'INVENTORY_FROZEN', **evidence, 'recovered': True}

    name, url = company['Company'], company['Official Careers URL']
    ats = company.get('ATS / Source', '')
    expected_ats, expected_url, _ = repair_source(ats, url, cid, name)
    provider = _selected_provider_identity(expected_ats, expected_url)
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
    if _selected_provider_identity(inventory['ats'], inventory['source_url']) != provider:
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
    record = _read_record(sink.root / 'selected-retry-inventory' / (cycle_id + '.json'), binding, archived['binding'])
    if record is None or record['state'] != 'FROZEN':
        raise ValueError('Selected retry has no verified frozen inventory.')
    return record


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


def _read_record(path, binding, signed_binding):
    try:
        attrs = path.parent.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISDIR(attrs.st_mode) or stat.S_IMODE(attrs.st_mode) != 0o700 or attrs.st_uid != os.geteuid():
        raise ValueError('Selected retry inventory directory is unsafe.')
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    with os.fdopen(fd, 'r', encoding='utf-8') as stream:
        attrs = os.fstat(stream.fileno())
        if (not stat.S_ISREG(attrs.st_mode) or stat.S_IMODE(attrs.st_mode) != 0o600
                or attrs.st_uid != os.geteuid() or attrs.st_nlink != 1):
            raise ValueError('Selected retry inventory record is unsafe.')
        raw = stream.read()
    record = json.loads(raw)
    if not isinstance(record, dict) or _canonical(record) + '\n' != raw:
        raise ValueError('Selected retry inventory record is malformed.')
    expected = {'state', 'binding', 'fetch_started_at', 'sha256'}
    if record.get('state') == 'FROZEN':
        expected.update(('inventory', 'inventory_sha256'))
    if (set(record) != expected or record['binding'] != binding or record['state'] not in ('CLAIMED', 'FROZEN')
            or record['sha256'] != _selected_sha({key: value for key, value in record.items() if key != 'sha256'})):
        raise ValueError('Selected retry inventory record conflicts with its exact admission.')
    _timestamp(record['fetch_started_at'], 'Selected retry fetch claim time')
    if record['state'] == 'FROZEN':
        inventory = record['inventory']
        _timestamp(inventory.get('fetched_at'), 'Selected retry fetch completion time')
        if _inventory_digest(inventory, signed_binding) != record['inventory_sha256']:
            raise ValueError('Selected retry frozen inventory is inconsistent.')
    return record


def _write_record(path, record, *, initial):
    path.parent.mkdir(mode=0o700, exist_ok=True)
    _sync_directory(path.parent.parent)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.retry-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(_canonical({**record, 'sha256': _selected_sha(record)}) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        if initial:
            os.link(temporary, path, follow_symlinks=False)
            os.unlink(temporary)
        else:
            os.replace(temporary, path)
        _sync_directory(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
