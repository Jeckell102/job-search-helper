"""One durable provider observation for an admitted ordinary Company event."""
from contextlib import closing
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import sqlite3
import stat

from .ats import Inventory
from .company_events import canonical_company_fact, read_verified_ordinary_event_admission
from .company_sources import repair_source
from .engine import Engine, State
from .exact_cycle_sync import _unique_company
from .integration_release import assert_release_settled
from .retained_operator_journal import provider_inventory_digest
from .retained_work_runner import _inventory_snapshot, assert_normal_lifecycle_not_held
from .repository import GoogleRepository, _equivalent, _url
from .runner import _canonical_runtime_binding
from .scan_request import _cycle_views, _unfinished_from_views
from .scoped_provider_observation import provider_identity, read_observation, write_observation
from .sheet_profile import COMPACT_PROFILE, COMPACT_SCHEMAS
from .sqlite_repository import SQLiteRepository
from .temporary_retry import _selected_sha, _sync_directory


DIRECTORY = 'ordinary-event-inventory'


def assert_no_active_ordinary_event_observation(state_directory, *, permitted_cycle_id=None):
    """Keep legacy runners away from a claimed or frozen event cycle."""
    root = Path(state_directory).resolve()
    directory = root / DIRECTORY
    try:
        attrs = directory.lstat()
    except FileNotFoundError:
        return
    if not stat.S_ISDIR(attrs.st_mode) or stat.S_IMODE(attrs.st_mode) != 0o700 or attrs.st_uid != os.geteuid():
        raise ValueError('Ordinary event observation directory is unsafe.')
    records = sorted(record.stem for record in directory.glob('*.json'))
    if not records:
        return
    state_path = root / 'state.db'
    if state_path.is_symlink() or not state_path.is_file():
        raise ValueError('Ordinary event observation is missing its canonical State.')
    with closing(State(str(state_path), readonly=True)) as state:
        for cycle_id in records:
            if not re.fullmatch(r'CYC-[0-9A-F]{12}', cycle_id):
                raise ValueError('Ordinary event observation has an invalid cycle identity.')
            cycle = state.cycle(cycle_id)
            if (not cycle or not cycle.get('company_event') or
                    (cycle_id != permitted_cycle_id and
                     (cycle.get('status') not in {'Complete', 'Complete with exceptions'}
                      or not isinstance(cycle.get('ordinary_event_settlement_sha256'), str)
                      or not re.fullmatch(r'[0-9a-f]{64}', cycle['ordinary_event_settlement_sha256'])))):
                raise ValueError('Ordinary Company event owns the cycle; use its exact observation path.')


def _admission(reader, state, runtime, cycle_id, request_sha256):
    if not isinstance(reader, SQLiteRepository) or not reader.readonly or not isinstance(state, State) or not state.readonly:
        raise ValueError('Ordinary event observation requires canonical read-only State and Jobs.')
    path = Path(state.path)
    root = path.resolve().parent
    if (not isinstance(cycle_id, str) or not re.fullmatch(r'CYC-[0-9A-F]{12}', cycle_id)
            or not isinstance(request_sha256, str) or not re.fullmatch(r'[0-9a-f]{64}', request_sha256)
            or reader.path != root / 'jobs.sqlite3' or reader.path.is_symlink()
            or path != root / 'state.db' or path.is_symlink()
            or reader.get_meta('sheets_profile') != COMPACT_PROFILE):
        raise ValueError('Ordinary event observation dependencies or exact identity changed.')
    cycle = state.cycle(cycle_id)
    if not cycle:
        raise ValueError('Ordinary event observation has no admitted cycle.')
    runtime = _canonical_runtime_binding(runtime)
    Engine.validate_cycle_runtime_binding(cycle, runtime)
    admission = read_verified_ordinary_event_admission(reader, state, cycle_id)
    if admission['request_sha256'] != request_sha256:
        raise ValueError('Ordinary event observation requires the exact admitted request digest.')
    event = admission['request']['company_event']
    cid = event['company_id']
    item = cycle['companies'][cid]
    raw = admission['request']
    binding = {
        'schema': 'ordinary-company-event-inventory-v1', 'cycle_id': cycle_id, 'company_id': cid,
        'request': raw, 'request_sha256': request_sha256, 'request_fingerprint': cycle['request_fingerprint'],
        'bridge_receipt_sha256': _selected_sha(admission['receipt']), 'runtime': runtime,
        'company_name': item['company'], 'source_fact': admission['source_fact'],
    }
    return root, cycle, admission, binding


def _company(reader, cycle, admission, binding):
    cid = binding['company_id']
    rows = reader.matches('Companies', {'Company ID': cid})
    if len(rows) != 1 or not admission['source_current']:
        return None
    row = rows[0][1]
    if (row.get('Active Cycle ID') != cycle['id'] or row.get('Scan State') != 'Queued'
            or row.get('Company') != binding['company_name']
            or str(row.get('Company Status') or '').strip().casefold() != 'active'
            or any(str(row.get(key) or '').strip() for key in ('Claimed By', 'Claim Token'))
            or canonical_company_fact(row) != binding['source_fact']):
        return None
    return row


def _scope_has_storage(reader, root, cycle_id):
    path = root / 'inventories.sqlite3'
    if path.is_symlink() or not path.is_file() or not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError('Ordinary event observation requires the canonical inventory store.')
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as inbox:
        if inbox.execute('SELECT id FROM destination').fetchall() != [(reader.spreadsheet_id,)]:
            raise ValueError('Ordinary event observation workbook does not match the inventory store.')
        for table in ('inventories', 'sync_plans', 'exact_sync_chunks', 'exact_plan_local_state',
                      'exact_remote_plans', 'exact_legacy_plan_migrations', 'exact_selected_legacy_recoveries'):
            if inbox.execute(f'SELECT 1 FROM {table} WHERE cycle=? LIMIT 1', (cycle_id,)).fetchone():
                return True
    return reader.db.execute(
        'SELECT 1 FROM exact_local_applications WHERE cycle=? LIMIT 1', (cycle_id,),
    ).fetchone() is not None


def load_ordinary_event_observation(reader, state, runtime, *, cycle_id, request_sha256):
    """Read the exact frozen evidence again before publishing any job rows."""
    root, _cycle, _facts, binding = _admission(reader, state, runtime, cycle_id, request_sha256)
    record = read_observation(root / DIRECTORY / (cycle_id + '.json'), binding)
    if record is None or record['state'] != 'FROZEN':
        raise ValueError('Ordinary event has no verified frozen provider observation.')
    _require_frozen_provider(record['inventory'], binding)
    return record


def _require_frozen_provider(inventory, binding):
    fact = binding['source_fact']
    requested = inventory['requested_url']
    ats, board, _ = repair_source(fact['ats_source'], requested, binding['company_id'], binding['company_name'])
    provider = provider_identity(ats, board)
    if (_url(requested) != fact['official_careers_url']
            or not provider or provider_identity(inventory['ats'], inventory['source_url']) != provider):
        raise ValueError('Ordinary event frozen observation belongs to a different source.')


def _verify_workbook(reader, remote_reader, company):
    remote = remote_reader()
    if (not isinstance(remote, GoogleRepository) or remote.spreadsheet_id != reader.spreadsheet_id
            or remote.schemas != COMPACT_SCHEMAS):
        raise ValueError('Ordinary event observation requires the exact compact workbook.')
    remote.validate_schema()
    fields = ['Company ID', 'Company Status', 'Official Careers URL', 'ATS / Source']
    observed = _unique_company(remote, company['Company ID'], fields)
    if any(not _equivalent(field, observed.get(field, ''), company.get(field, '')) for field in fields):
        raise ValueError('Ordinary event workbook Company source changed.')


def freeze_ordinary_event_locked(reader, state, runtime, *, cycle_id, request_sha256, fetcher,
                                 remote_reader, clock=None):
    """Claim before fetching, then freeze under the caller's scraper and writer leases."""
    if not callable(fetcher) or not callable(remote_reader):
        raise ValueError('Ordinary event observation requires a provider and read-only workbook guard.')
    now = clock or (lambda: datetime.now(timezone.utc))
    root, cycle, admission, binding = _admission(reader, state, runtime, cycle_id, request_sha256)
    assert_release_settled(root)
    assert_normal_lifecycle_not_held(root, reader.path, ordinary_event_cycle_id=cycle_id)
    local, mirrors = _cycle_views(reader, state)
    if (_unfinished_from_views(local, mirrors) != {cycle_id}
            or cycle.get('status') != 'In Progress'
            or cycle['companies'][binding['company_id']].get('stage') != 'queued'):
        raise ValueError('Ordinary event observation requires the sole queued cycle.')
    cid = binding['company_id']
    path = root / DIRECTORY / (cycle_id + '.json')
    found = read_observation(path, binding)
    result = {'cycle_id': cycle_id, 'company_id': cid, 'request_sha256': request_sha256}
    if found is not None and found['state'] == 'CLAIMED':
        return {'state': 'HELD_FETCH_UNCERTAIN', **result}
    if _scope_has_storage(reader, root, cycle_id):
        return {'state': 'HELD_ORDINARY_WORK_PRESENT', **result}
    company = _company(reader, cycle, admission, binding)
    if company is None:
        return {'state': 'HELD_SOURCE_CHANGED', **result}
    url, ats = company['Official Careers URL'], company['ATS / Source']
    expected_ats, expected_url, _ = repair_source(ats, url, cid, company['Company'])
    expected_provider = provider_identity(expected_ats, expected_url)
    if not expected_provider:
        raise ValueError('Ordinary event provider identity is unverified.')
    if found is None:
        _verify_workbook(reader, remote_reader, company)
        assert_release_settled(root)
        assert_normal_lifecycle_not_held(root, reader.path, ordinary_event_cycle_id=cycle_id)
        _root, current_cycle, current_admission, current_binding = _admission(
            reader, state, runtime, cycle_id, request_sha256,
        )
        if (current_cycle != cycle or current_binding != binding
                or _company(reader, current_cycle, current_admission, current_binding) != company
                or _unfinished_from_views(*_cycle_views(reader, state)) != {cycle_id}
                or _scope_has_storage(reader, root, cycle_id)):
            return {'state': 'HELD_SOURCE_CHANGED', **result}
        claim = {'state': 'CLAIMED', 'binding': binding, 'fetch_started_at': _stamp(now)}
        write_observation(path, claim, initial=True)
        claimed = read_observation(path, binding)
        if claimed != {**claim, 'sha256': _selected_sha(claim)}:
            raise ValueError('Ordinary event observation claim did not persist.')
        fetched = fetcher(ats, url, cid, company['Company'])
        if not isinstance(fetched, Inventory):
            raise ValueError('Ordinary event provider returned invalid inventory.')
        inventory = _inventory_snapshot(fetched, company, fetched_at=_stamp(now), event_scope=True)
        digest = provider_inventory_digest(inventory, event_scope=True)
        if (provider_identity(inventory['ats'], inventory['source_url']) != expected_provider
                or inventory['fetched_at'] < claim['fetch_started_at']):
            raise ValueError('Ordinary event observation returned the wrong provider or time.')
        if read_observation(path, binding) != claimed:
            raise ValueError('Ordinary event observation claim changed while the provider was running.')
        record = {**claim, 'state': 'FROZEN', 'inventory': inventory, 'inventory_sha256': digest}
        write_observation(path, record, initial=False)
        record = read_observation(path, binding)
        _root, current_cycle, current_admission, current_binding = _admission(
            reader, state, runtime, cycle_id, request_sha256,
        )
        if (current_cycle != cycle or current_binding != binding
                or _company(reader, current_cycle, current_admission, current_binding) != company):
            return {'state': 'HELD_SOURCE_CHANGED', **result}
    else:
        _require_frozen_provider(found['inventory'], binding)
        _sync_directory(path.parent)
        record = found
    return {'state': 'INVENTORY_FROZEN', **result, 'inventory_sha256': record['inventory_sha256'],
            'inventory_status': record['inventory']['status'], 'job_count': len(record['inventory']['jobs']),
            'recovered': found is not None}


def _stamp(clock):
    stamp = clock()
    if not isinstance(stamp, datetime) or stamp.utcoffset() is None:
        raise ValueError('Ordinary event observation requires a timezone-aware clock.')
    return stamp.astimezone(timezone.utc).isoformat(timespec='microseconds')
