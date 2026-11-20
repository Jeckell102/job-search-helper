"""Durable runtime receipts for already verified ordinary-cycle mapping facts.

Callers own the ordinary scraper admission and Jobs writer boundary. Open
the two handles with open_runtime_mapping_stores while those holds are in
force. This module stores facts already produced by an authorized verifier.
Public operations need idle handles and SQLite's statement-status table.
"""
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import re
import sqlite3
import stat

from .company_events import canonical_company_fact
from .source_configuration_snapshot import (
    _canonical_bytes,
    _digest,
    _duplicate_free_json,
    _resolve_authoritative_installed_source_configuration,
    mapping_fact_by_id,
    mapping_fact_id,
    qualification_for_snapshot,
    read_source_configuration_mapping_facts,
    validate_installed_source_configuration,
    validate_mapping_divergence_fact,
    validate_source_configuration_defect,
    validate_source_configuration_qualification_evidence,
)


_TABLE = 'runtime_source_mapping_facts'
_SCHEMA = 'runtime-source-mapping-fact-v1'
_FOREIGN_PROVENANCE = ('company_event', 'operator_request', 'repair_retry', 'temporary_retry',
                       'recovery_pause', 'selected_retry_reservation_sha256')
_GROUP_FIELDS = ('source_configuration_mapping_fact', 'source_configuration_defect',
                 'source_configuration_qualification_evidence')


def _physical_identity(path):
    if path.resolve(strict=True) != path:
        raise ValueError('Runtime mapping fact requires canonical durable database paths.')
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError('Runtime mapping fact database is not an ordinary single-link file.')
    return info.st_dev, info.st_ino


def _fd_identities():
    # Linux SQLite does not expose its main file descriptor through sqlite3.
    # Identify the new descriptor while opening the specific managed handle.
    descriptors = {}
    try:
        entries = list(Path('/proc/self/fd').iterdir())
    except OSError as exc:
        raise ValueError('Runtime mapping fact cannot inspect opened file descriptors.') from exc
    for entry in entries:
        try:
            fd = int(entry.name)
            info = os.fstat(fd)
        except (OSError, ValueError):
            continue
        if stat.S_ISREG(info.st_mode):
            descriptors[fd] = (info.st_dev, info.st_ino)
    return descriptors


@dataclass(frozen=True)
class _OpenedStore:
    path: Path
    connection: object
    descriptor: int
    identity: tuple[int, int]


def _open_store(stack, path, factory, connection_name):
    identity = _physical_identity(path)
    before = _fd_identities()
    store = factory(path)
    stack.callback(store.close)
    connection = getattr(store, connection_name)
    connection.execute('SELECT 1 FROM main.sqlite_master LIMIT 1').fetchone()
    candidates = [fd for fd, current in _fd_identities().items()
                  if current == identity and before.get(fd) != current]
    if len(candidates) != 1:
        raise ValueError('Runtime mapping fact cannot prove the opened database identity.')
    store._runtime_mapping_open = _OpenedStore(path, connection, candidates[0], identity)
    _store_identity(store, connection)
    return store


@contextmanager
def open_runtime_mapping_stores(state_path, jobs_path, workbook_id, *, writable_state=False):
    """Open and pin State and read-only Jobs within the caller's owned leases.

    Leave both handles in autocommit with all cursors exhausted or closed
    before invoking public custody operations.
    """
    from .engine import State
    from .sqlite_repository import SQLiteRepository

    state_path, jobs_path = Path(state_path).absolute(), Path(jobs_path).absolute()
    if state_path.parent != jobs_path.parent or state_path == jobs_path:
        raise ValueError('Runtime mapping fact requires co-located, distinct State and Jobs.')
    with ExitStack() as stack:
        state = _open_store(stack, state_path, lambda path: State(path, readonly=not writable_state), 'connection')
        jobs = _open_store(stack, jobs_path, lambda path: SQLiteRepository(path, workbook_id, readonly=True), 'db')
        yield state, jobs


def _store_identity(store, connection):
    opened = getattr(store, '_runtime_mapping_open', None)
    if not isinstance(opened, _OpenedStore) or opened.connection is not connection:
        raise ValueError('Runtime mapping fact requires its managed opened database handle.')
    candidate = Path(store.path).absolute()
    databases = connection.execute('PRAGMA database_list').fetchall()
    if any(schema not in {'main', 'temp'} for _, schema, _ in databases):
        raise ValueError('Runtime mapping fact does not accept attached databases.')
    named = [name for _, schema, name in databases if schema == 'main']
    try:
        descriptor = os.fstat(opened.descriptor)
        current = _physical_identity(candidate)
        descriptor_path = os.readlink(f'/proc/self/fd/{opened.descriptor}')
    except OSError as exc:
        raise ValueError('Runtime mapping fact opened database identity changed.') from exc
    if (candidate != opened.path or named != [str(candidate)] or descriptor_path != str(candidate)
            or (descriptor.st_dev, descriptor.st_ino) != opened.identity or current != opened.identity):
        raise ValueError('Runtime mapping fact opened database identity changed.')
    return candidate, list(current)


def _verified_store_identities(state, repository):
    state_path, state_identity = _store_identity(state, state.connection)
    jobs_path, jobs_identity = _store_identity(repository, repository.db)
    if state_path.parent != jobs_path.parent or state_identity == jobs_identity:
        raise ValueError('Runtime mapping fact requires co-located, distinct State and Jobs.')
    if repository.db.execute(
        'SELECT value FROM main.meta WHERE key=?', ('spreadsheet_id',),
    ).fetchall() != [(repository.spreadsheet_id,)]:
        raise ValueError('Runtime mapping fact Jobs workbook identity changed.')
    return state_identity, jobs_identity


def _require_idle_stores(state, repository):
    from .engine import State
    from .sqlite_repository import SQLiteRepository

    if not isinstance(state, State) or not isinstance(repository, SQLiteRepository) or state.path == ':memory:':
        raise ValueError('Runtime mapping fact requires durable State and local Jobs.')
    for connection in (state.connection, repository.db):
        if connection.in_transaction:
            raise ValueError('Runtime mapping fact requires idle State and Jobs connections.')
        # An unfinished SELECT can pin a WAL read snapshot while sqlite3
        # reports autocommit. The probe itself is the only allowed busy VM.
        try:
            busy = connection.execute('SELECT count(*) FROM main.sqlite_stmt WHERE busy').fetchone()
        except sqlite3.Error as exc:
            raise ValueError('Runtime mapping fact cannot verify idle SQLite connections.') from exc
        if busy != (1,):
            raise ValueError('Runtime mapping fact requires idle State and Jobs connections.')


def _owner(state, repository, runtime_binding, cycle_id, company_id):
    # Import here because Engine imports the installed snapshot during admission.
    from .engine import Engine
    from .runner import _canonical_runtime_binding

    if (not isinstance(cycle_id, str) or not re.fullmatch(r'CYC-[0-9A-F]{12}', cycle_id)
            or not isinstance(company_id, str) or not re.fullmatch(r'COMP-\d{4,}', company_id)):
        raise ValueError('Runtime mapping fact owner identity is malformed.')
    state_identity, jobs_identity = _verified_store_identities(state, repository)
    row = state.connection.execute('SELECT data FROM main.cycles WHERE id=?', (cycle_id,)).fetchone()
    cycle = _duplicate_free_json(row[0].encode('utf-8')) if row and isinstance(row[0], str) else None
    if (not isinstance(cycle, dict) or cycle.get('id') != cycle_id
            or any(cycle.get(key) is not None for key in _FOREIGN_PROVENANCE)
            or not isinstance(cycle.get('companies'), dict)
            or not isinstance(cycle.get('started_at'), str) or not cycle['started_at']):
        raise ValueError('Runtime mapping fact requires its exact ordinary cycle.')
    request_id = cycle.get('start_request_id')
    fingerprint = cycle.get('request_fingerprint')
    if ((request_id is not None and (not isinstance(request_id, str) or not 0 < len(request_id) <= 256))
            or (fingerprint is not None and (not isinstance(fingerprint, str)
                                           or not re.fullmatch(r'[0-9a-f]{64}', fingerprint)))):
        raise ValueError('Runtime mapping fact request identity is malformed.')
    runtime = Engine.validate_cycle_runtime_binding(cycle, _canonical_runtime_binding(runtime_binding))
    item = cycle['companies'].get(company_id)
    if not isinstance(item, dict):
        raise ValueError('Runtime mapping fact requires its exact saved Company membership.')
    snapshot = validate_installed_source_configuration(item.get('installed_source_configuration'))
    frozen = item.get('outcome_source_fact')
    if (snapshot is None or snapshot['company_id'] != company_id or not isinstance(frozen, dict)
            or frozen.get('company_id') != company_id
            or item.get('outcome_source_revision') != snapshot['source_revision']):
        raise ValueError('Runtime mapping fact has no exact frozen source admission.')
    if repository.db.execute(
        "SELECT 1 FROM temp.sqlite_master WHERE name COLLATE NOCASE IN ('records','lookups') LIMIT 1",
    ).fetchone() is not None:
        raise ValueError('Runtime mapping fact Jobs Company authority is shadowed.')
    main_company_tables = repository.db.execute(
        "SELECT name,type FROM main.sqlite_master WHERE name COLLATE NOCASE IN ('records','lookups')",
    ).fetchall()
    if set(main_company_tables) != {('records', 'table'), ('lookups', 'table')}:
        raise ValueError('Runtime mapping fact requires main Jobs Company tables.')
    matches = repository.matches('Companies', {'Company ID': company_id})
    if len(matches) != 1 or canonical_company_fact(matches[0][1]) != frozen:
        raise ValueError('Runtime mapping fact Company source has changed.')
    current = _resolve_authoritative_installed_source_configuration(repository, company_id)
    if current != snapshot:
        raise ValueError('Runtime mapping fact installed source has changed.')
    qualification = qualification_for_snapshot(snapshot)
    if qualification is None:
        raise ValueError('Runtime mapping fact requires an exact held qualification.')
    evidence = {'schema': 'source-configuration-qualification-evidence-v1', **qualification}
    binding = {
        'cycle_id': cycle_id, 'company_id': company_id, 'cycle_started_at': cycle['started_at'],
        'request_id': request_id, 'request_fingerprint': fingerprint,
        'runtime_binding': runtime, 'source_revision': snapshot['source_revision'],
        'configuration_digest': snapshot['configuration_digest'], 'qualification_evidence': evidence,
        'state_identity': state_identity, 'jobs_identity': jobs_identity, 'workbook_id': repository.spreadsheet_id,
    }
    return binding, snapshot, item


def _row(connection, cycle_id, company_id):
    relation = connection.execute(
        'SELECT name, type FROM main.sqlite_master WHERE name=? COLLATE NOCASE', (_TABLE,),
    ).fetchone()
    if relation is None:
        return None
    if relation != (_TABLE, 'table'):
        raise ValueError('Runtime mapping fact storage is not the owned table.')
    rows = connection.execute(
        f'SELECT fact_id, record_sha256, payload FROM main.{_TABLE} WHERE cycle=? AND company=?',
        (cycle_id, company_id),
    ).fetchmany(2)
    if len(rows) > 1:
        raise ValueError('Runtime mapping fact has competing rows for its exact owner.')
    return rows[0] if rows else None


def _verify_group(item, fact, binding, snapshot):
    present = set(_GROUP_FIELDS).intersection(item)
    if present and (
        present != set(_GROUP_FIELDS) or item[_GROUP_FIELDS[0]] != fact
        or validate_source_configuration_defect(item[_GROUP_FIELDS[1]], snapshot=snapshot) is None
        or validate_source_configuration_qualification_evidence(item[_GROUP_FIELDS[2]], snapshot=snapshot)
        != binding['qualification_evidence']
    ):
        raise ValueError('Runtime mapping fact conflicts with the sealed cycle evidence.')


def _read_row(row, binding, snapshot, item):
    if row is None:
        return None
    fact_id, sha, raw = row
    record = _duplicate_free_json(raw.encode('utf-8')) if isinstance(raw, str) else None
    if (not isinstance(record, dict) or set(record) != {'schema', 'binding', 'fact'}
            or record['schema'] != _SCHEMA or record['binding'] != binding
            or _canonical_bytes(record).decode('utf-8') != raw or _digest(record) != sha):
        raise ValueError('Runtime mapping fact record does not match its exact owner.')
    fact = validate_mapping_divergence_fact(record['fact'], cycle_id=binding['cycle_id'], snapshot=snapshot)
    if fact is None or mapping_fact_id(fact) != fact_id:
        raise ValueError('Runtime mapping fact identity or payload has changed.')
    _verify_group(item, fact, binding, snapshot)
    return {'fact_id': fact_id, 'fact': fact}


def _read_owned_runtime_fact(state, repository, runtime_binding, *, cycle_id, company_id):
    binding, snapshot, item = _owner(state, repository, runtime_binding, cycle_id, company_id)
    receipt = _read_row(_row(state.connection, cycle_id, company_id), binding, snapshot, item)
    _verified_store_identities(state, repository)
    return receipt


def read_runtime_mapping_fact(state, repository, runtime_binding, *, cycle_id, company_id):
    """Reopen one exact runtime fact from idle handles without writing."""
    _require_idle_stores(state, repository)
    return _read_owned_runtime_fact(state, repository, runtime_binding, cycle_id=cycle_id, company_id=company_id)


def contextual_mapping_fact_by_id(state, repository, runtime_binding, *, cycle_id, company_id, fact_id):
    _require_idle_stores(state, repository)
    binding, snapshot, item = _owner(state, repository, runtime_binding, cycle_id, company_id)
    runtime = _read_row(_row(state.connection, cycle_id, company_id), binding, snapshot, item)
    if runtime is not None:
        result = runtime['fact'] if runtime['fact_id'] == fact_id else None
    else:
        legacy = mapping_fact_by_id(cycle_id, company_id, fact_id)
        result = validate_mapping_divergence_fact(legacy, cycle_id=cycle_id, snapshot=snapshot)
        if result is not None:
            _verify_group(item, result, binding, snapshot)
    _verified_store_identities(state, repository)
    return result


def persist_runtime_mapping_fact(state, repository, runtime_binding, *, cycle_id, company_id, fact):
    """Record one verifier-supplied fact, or return exactly the prior fact ID."""
    _require_idle_stores(state, repository)
    if state.readonly:
        raise ValueError('Runtime mapping fact requires a dedicated writable State transaction.')
    connection = state.connection
    _verified_store_identities(state, repository)
    with connection:
        connection.execute('BEGIN IMMEDIATE')
        binding, snapshot, item = _owner(state, repository, runtime_binding, cycle_id, company_id)
        checked = validate_mapping_divergence_fact(fact, cycle_id=cycle_id, snapshot=snapshot)
        if checked is None:
            raise ValueError('Runtime mapping fact does not match the exact saved admission.')
        fact_id = mapping_fact_id(checked)
        _verify_group(item, checked, binding, snapshot)
        existing = _read_row(_row(connection, cycle_id, company_id), binding, snapshot, item)
        if existing is not None:
            if existing != {'fact_id': fact_id, 'fact': checked}:
                raise ValueError('Runtime mapping fact is immutable for this cycle and Company.')
            _verified_store_identities(state, repository)
            return fact_id
        legacy = read_source_configuration_mapping_facts()
        if legacy is None or any(entry['fact_id'] != fact_id for entry in legacy
                                 if entry['fact']['cycle_id'] == cycle_id and entry['fact']['company_id'] == company_id):
            raise ValueError('Runtime mapping fact conflicts with packaged mapping evidence.')
        connection.execute(
            f'CREATE TABLE IF NOT EXISTS main.{_TABLE} (cycle TEXT NOT NULL, company TEXT NOT NULL, '
            'fact_id TEXT NOT NULL UNIQUE, record_sha256 TEXT NOT NULL, payload TEXT NOT NULL, '
            'PRIMARY KEY(cycle,company))',
        )
        record = {'schema': _SCHEMA, 'binding': binding, 'fact': checked}
        connection.execute(f'INSERT INTO main.{_TABLE} VALUES (?,?,?,?,?)',
                           (cycle_id, company_id, fact_id, _digest(record), _canonical_bytes(record).decode('utf-8')))
        current = _read_owned_runtime_fact(
            state, repository, runtime_binding, cycle_id=cycle_id, company_id=company_id,
        )
        if current != {'fact_id': fact_id, 'fact': checked}:
            raise ValueError('Runtime mapping fact durable readback changed.')
    return fact_id
