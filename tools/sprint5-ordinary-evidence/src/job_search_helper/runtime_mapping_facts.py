"""Durable runtime receipts for already verified ordinary-cycle mapping facts.

Callers own the ordinary scraper admission and Jobs writer boundary. The
persistence API accepts a fact produced by an authorized verifier. It cannot
establish the truth of the provider evidence digests supplied in that fact.
"""
from pathlib import Path
import re
import stat

from .company_events import canonical_company_fact
from .source_configuration_snapshot import (
    _canonical_bytes,
    _digest,
    _duplicate_free_json,
    _resolve_authoritative_installed_source_configuration,
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


def _store_identity(path, connection):
    candidate = Path(path).absolute()
    opened = [name for _, schema, name in connection.execute('PRAGMA database_list') if schema == 'main']
    if candidate.resolve(strict=True) != candidate or opened != [str(candidate)]:
        raise ValueError('Runtime mapping fact requires canonical durable database paths.')
    info = candidate.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError('Runtime mapping fact database is not an ordinary single-link file.')
    return candidate, [info.st_dev, info.st_ino]


def _owner(state, repository, runtime_binding, cycle_id, company_id):
    # Import here because Engine imports the installed snapshot during admission.
    from .engine import Engine, State
    from .runner import _canonical_runtime_binding
    from .sqlite_repository import SQLiteRepository

    if not isinstance(state, State) or not isinstance(repository, SQLiteRepository) or state.path == ':memory:':
        raise ValueError('Runtime mapping fact requires durable State and local Jobs.')
    if (not isinstance(cycle_id, str) or not re.fullmatch(r'CYC-[0-9A-F]{12}', cycle_id)
            or not isinstance(company_id, str) or not re.fullmatch(r'COMP-\d{4,}', company_id)):
        raise ValueError('Runtime mapping fact owner identity is malformed.')
    state_path, state_identity = _store_identity(state.path, state.connection)
    jobs_path, jobs_identity = _store_identity(repository.path, repository.db)
    if state_path.parent != jobs_path.parent or state_identity == jobs_identity:
        raise ValueError('Runtime mapping fact requires co-located, distinct State and Jobs.')
    cycle = state.cycle(cycle_id)
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
    relation = connection.execute('SELECT type FROM sqlite_master WHERE name=?', (_TABLE,)).fetchone()
    if relation is None:
        return None
    if relation != ('table',):
        raise ValueError('Runtime mapping fact storage is not the owned table.')
    rows = connection.execute(
        f'SELECT fact_id, record_sha256, payload FROM {_TABLE} WHERE cycle=? AND company=?',
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


def read_runtime_mapping_fact(state, repository, runtime_binding, *, cycle_id, company_id):
    """Reopen one exact runtime fact without initializing tables or writing."""
    binding, snapshot, item = _owner(state, repository, runtime_binding, cycle_id, company_id)
    return _read_row(_row(state.connection, cycle_id, company_id), binding, snapshot, item)


def persist_runtime_mapping_fact(state, repository, runtime_binding, *, cycle_id, company_id, fact):
    """Record one verifier-supplied fact, or return exactly the prior fact ID."""
    from .engine import State

    if (not isinstance(state, State) or state.readonly or state.path == ':memory:'
            or state.connection.in_transaction):
        raise ValueError('Runtime mapping fact requires a dedicated writable State transaction.')
    connection = state.connection
    _store_identity(state.path, connection)
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
            return fact_id
        legacy = read_source_configuration_mapping_facts()
        if legacy is None or any(entry['fact_id'] != fact_id for entry in legacy
                                 if entry['fact']['cycle_id'] == cycle_id and entry['fact']['company_id'] == company_id):
            raise ValueError('Runtime mapping fact conflicts with packaged mapping evidence.')
        connection.execute(
            f'CREATE TABLE IF NOT EXISTS {_TABLE} (cycle TEXT NOT NULL, company TEXT NOT NULL, '
            'fact_id TEXT NOT NULL UNIQUE, record_sha256 TEXT NOT NULL, payload TEXT NOT NULL, '
            'PRIMARY KEY(cycle,company))',
        )
        record = {'schema': _SCHEMA, 'binding': binding, 'fact': checked}
        connection.execute(f'INSERT INTO {_TABLE} VALUES (?,?,?,?,?)',
                           (cycle_id, company_id, fact_id, _digest(record), _canonical_bytes(record).decode('utf-8')))
        current = read_runtime_mapping_fact(state, repository, runtime_binding, cycle_id=cycle_id, company_id=company_id)
        if current != {'fact_id': fact_id, 'fact': checked}:
            raise ValueError('Runtime mapping fact durable readback changed.')
    return fact_id
