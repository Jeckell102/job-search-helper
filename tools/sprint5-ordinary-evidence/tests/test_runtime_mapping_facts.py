"""Runtime fact custody fixtures. Digests stand in for already verified bytes."""
from contextlib import closing
import copy
from hashlib import sha256
import json
from pathlib import Path
from shutil import copy2
import socket
import sqlite3

import pytest

from job_search_helper import source_configuration_snapshot as snapshot
from job_search_helper.engine import Engine, State
from job_search_helper.integration_release import source_tree_digest
from job_search_helper.runtime_mapping_facts import persist_runtime_mapping_fact, read_runtime_mapping_fact
from job_search_helper.sqlite_repository import SQLiteRepository


ROOT = Path(__file__).resolve().parents[1]
CID = 'COMP-0066'
WORKBOOK = 'S5_runtime_fact_fixture'
QUAL_FIELDS = ('company_id', 'source_revision', 'capability_id', 'capability_digest',
               'mapping_digest', 'configuration_digest')
TABLE = 'runtime_source_mapping_facts'


@pytest.fixture
def custody(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('mapping-fact persistence attempted network I/O')

    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket, 'getaddrinfo', forbidden)
    installed = tmp_path / 'installed'
    for rel in (*snapshot._PATHS, snapshot.QUALIFICATION_PATH, snapshot.MAPPING_FACTS_PATH):
        path = installed / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        copy2(ROOT / rel, path)
    monkeypatch.setattr(snapshot, '_root', lambda: installed)
    state_dir = tmp_path / 'state'
    with (closing(State(str(state_dir / 'state.db'))) as state,
          closing(SQLiteRepository(state_dir / 'jobs.sqlite3', WORKBOOK, initialize=True)) as repo):
        repo.set_meta('ready', 'yes')
        row = {'Company ID': CID, 'Company': 'Forterra', 'Company Status': 'Active',
               'Official Careers URL': 'https://www.forterra.com/careers', 'ATS / Source': 'Rippling'}
        repo.import_rows('Companies', [(2, row)])
        frozen = snapshot.resolve_installed_source_configuration(repo, CID)
        qualification = {key: frozen[key] for key in QUAL_FIELDS}
        qualification.update(category='same_provider_source_mapping',
                             evidence_code='rippling_verified_mapping_divergence')
        (installed / snapshot.QUALIFICATION_PATH).write_bytes(snapshot._canonical_bytes({
            'schema': 'source-configuration-qualification-v1', 'qualifications': [qualification],
        }))
        runtime = {'state': 'NO_RELEASE', 'source_manifest_sha256': source_tree_digest(installed),
                   'config_sha256': 'c' * 64, 'dependency_manifest_sha256': 'd' * 64}
        engine = Engine(repo, state, runtime_binding=runtime)
        cycle_id = engine.start_cycle([CID], new_scan_request={
            'request_id': 'fixture-ordinary-mapping', 'request_fingerprint': 'f' * 64,
        })
        fact = {'schema': 'rippling-mapping-divergence-fact-v1', 'cycle_id': cycle_id,
                **{key: frozen[key] for key in QUAL_FIELDS},
                **{key: sha256(key.encode()).hexdigest() for key in (
                    'authority_extraction_digest', 'candidate_inventory_digest', 'regression_inventory_digest')},
                'evidence_code': 'rippling_verified_mapping_divergence'}
        yield state, repo, runtime, fact, installed


def persist(custody, replacement=None):
    state, repo, runtime, fact, _ = custody
    return persist_runtime_mapping_fact(state, repo, runtime, cycle_id=fact['cycle_id'], company_id=CID,
                                        fact=fact if replacement is None else replacement)


def read(custody):
    state, repo, runtime, fact, _ = custody
    return read_runtime_mapping_fact(state, repo, runtime, cycle_id=fact['cycle_id'], company_id=CID)


def save_package_fact(installed, fact):
    path = installed / snapshot.MAPPING_FACTS_PATH
    path.write_bytes(snapshot._canonical_bytes({
        'schema': 'source-configuration-mapping-facts-v1',
        'facts': [{'fact_id': snapshot.mapping_fact_id(fact), 'fact': fact}],
    }))


def test_exact_replay_readonly_lookup_and_unchanged_runtime_source(custody):
    state, repo, runtime, fact, installed = custody
    cycle_id = fact['cycle_id']
    assert read(custody) is None
    assert state.connection.execute('SELECT name FROM sqlite_master WHERE name=?', (TABLE,)).fetchone() is None
    packaged_before = (installed / snapshot.MAPPING_FACTS_PATH).read_bytes()
    before = state.cycle(cycle_id)
    fact_id = persist(custody)
    row_before, = state.connection.execute(f'SELECT * FROM {TABLE}').fetchall()
    assert persist(custody) == fact_id == snapshot.mapping_fact_id(fact)
    assert state.connection.execute(f'SELECT * FROM {TABLE}').fetchall() == [row_before]
    assert state.cycle(cycle_id) == before
    assert (installed / snapshot.MAPPING_FACTS_PATH).read_bytes() == packaged_before
    assert source_tree_digest(installed) == runtime['source_manifest_sha256']
    with (closing(State(state.path, readonly=True)) as readonly_state,
          closing(SQLiteRepository(repo.path, WORKBOOK, readonly=True)) as reader):
        assert snapshot.mapping_fact_by_id(cycle_id, CID, fact_id) is None
        assert snapshot.mapping_fact_by_id(cycle_id, CID, fact_id, state=readonly_state, repository=reader,
                                           runtime_binding=runtime) == fact
        assert snapshot.mapping_fact_by_id(cycle_id, CID, 'a' * 64, state=readonly_state, repository=reader,
                                           runtime_binding=runtime) is None
        with pytest.raises(ValueError, match='writable State'):
            persist_runtime_mapping_fact(readonly_state, reader, runtime, cycle_id=cycle_id, company_id=CID, fact=fact)


def test_package_compatibility_and_conflicting_authority_does_not_win(custody):
    state, repo, runtime, fact, installed = custody
    cycle_id = fact['cycle_id']
    save_package_fact(installed, fact)
    fact_id = snapshot.mapping_fact_id(fact)
    assert snapshot.mapping_fact_by_id(cycle_id, CID, fact_id) == fact
    assert snapshot.mapping_fact_by_id(cycle_id, CID, fact_id, state=state, repository=repo,
                                       runtime_binding=runtime) == fact
    other = {**fact, 'candidate_inventory_digest': 'a' * 64}
    with pytest.raises(ValueError, match='packaged mapping evidence'):
        persist(custody, other)
    assert read(custody) is None
    assert persist(custody) == fact_id
    save_package_fact(installed, other)
    other_id = snapshot.mapping_fact_id(other)
    assert snapshot.mapping_fact_by_id(cycle_id, CID, other_id) == other
    assert snapshot.mapping_fact_by_id(cycle_id, CID, other_id, state=state, repository=repo,
                                       runtime_binding=runtime) is None


def test_replay_cannot_replace_another_fact_and_rehashed_substitution_is_rejected(custody):
    state, repo, runtime, fact, installed = custody
    fact_id = persist(custody)
    other = {**fact, 'authority_extraction_digest': 'b' * 64}
    with pytest.raises(ValueError, match='immutable'):
        persist(custody, other)
    assert read(custody) == {'fact_id': fact_id, 'fact': fact}
    raw, = state.connection.execute(f'SELECT payload FROM {TABLE}').fetchone()
    forged = json.loads(raw)
    forged['fact'] = other
    with state.connection:
        state.connection.execute(f'UPDATE {TABLE} SET payload=?,record_sha256=?',
                                 (snapshot._canonical_bytes(forged).decode(), snapshot._digest(forged)))
    save_package_fact(installed, fact)
    with pytest.raises(ValueError, match='identity or payload'):
        snapshot.mapping_fact_by_id(fact['cycle_id'], CID, fact_id, state=state, repository=repo,
                                    runtime_binding=runtime)


def test_replaced_relation_does_not_fall_back_to_packaged_fact(custody):
    state, repo, runtime, fact, installed = custody
    fact_id = persist(custody)
    save_package_fact(installed, fact)
    with state.connection:
        state.connection.execute(f'ALTER TABLE {TABLE} RENAME TO foreign_facts')
        state.connection.execute(f'CREATE VIEW {TABLE} AS SELECT * FROM foreign_facts WHERE 0')
    assert snapshot.mapping_fact_by_id(fact['cycle_id'], CID, fact_id) == fact
    with pytest.raises(ValueError, match='not the owned table'):
        snapshot.mapping_fact_by_id(fact['cycle_id'], CID, fact_id, state=state, repository=repo,
                                    runtime_binding=runtime)


@pytest.mark.parametrize(('drift', 'reason'), [
    ('company', 'Company source has changed'),
    ('installed', 'installed source has changed'),
    ('qualification', 'exact held qualification'),
    ('restamped_matrix', 'exact owner'),
    ('runtime', 'runtime differs'),
    ('request', 'exact owner'),
])
def test_source_qualification_and_runtime_drift_hold_without_mutating_fact(custody, drift, reason):
    state, repo, runtime, fact, installed = custody
    persist(custody)
    original = state.connection.execute(f'SELECT * FROM {TABLE}').fetchall()
    if drift == 'company':
        repo.commit([{'tab': 'Companies', 'identity': {'Company ID': CID},
                      'values': {'Official Careers URL': 'https://www.forterra.com/changed'}}])
    elif drift == 'installed':
        path = installed / snapshot._PATHS[0]
        path.write_bytes(path.read_bytes() + b'\n# Fixture-only source drift\n')
    elif drift == 'qualification':
        (installed / snapshot.QUALIFICATION_PATH).write_bytes(snapshot._canonical_bytes({
            'schema': 'source-configuration-qualification-v1', 'qualifications': [],
        }))
    elif drift == 'restamped_matrix':
        path = installed / snapshot.QUALIFICATION_PATH
        matrix = json.loads(path.read_bytes())
        [original_rule] = matrix['qualifications']
        matrix['qualifications'] = sorted([original_rule, {**original_rule, 'company_id': 'COMP-0178'}],
                                          key=snapshot._json)
        path.write_bytes(snapshot._canonical_bytes(matrix))
    else:
        changed = state.cycle(fact['cycle_id'])
        if drift == 'runtime':
            changed['runtime_binding'] = {**runtime, 'config_sha256': 'e' * 64}
        else:
            changed['start_request_id'] = 'new-request-for-same-company'
        state.save_cycle(changed)
    with pytest.raises(ValueError, match=reason):
        read(custody)
    with pytest.raises(ValueError, match=reason):
        persist(custody)
    assert state.connection.execute(f'SELECT * FROM {TABLE}').fetchall() == original


def test_foreign_cycle_company_and_copied_state_do_not_adopt_fact(custody):
    state, repo, runtime, fact, _ = custody
    original_cycle = state.cycle(fact['cycle_id'])
    foreign_cycle = copy.deepcopy(original_cycle)
    foreign_cycle['id'] = 'CYC-A10000000000' if original_cycle['id'] != 'CYC-A10000000000' else 'CYC-B10000000000'
    state.save_cycle(foreign_cycle)
    fact_id = persist(custody)
    with pytest.raises(ValueError, match='saved admission'):
        persist_runtime_mapping_fact(state, repo, runtime, cycle_id=foreign_cycle['id'], company_id=CID, fact=fact)
    with pytest.raises(ValueError, match='saved Company membership'):
        read_runtime_mapping_fact(state, repo, runtime, cycle_id=fact['cycle_id'], company_id='COMP-0178')
    assert snapshot.mapping_fact_by_id(foreign_cycle['id'], CID, fact_id, state=state, repository=repo,
                                       runtime_binding=runtime) is None
    with closing(State(Path(state.path).with_name('copied-state.db'))) as copied:
        state.connection.backup(copied.connection)
        with pytest.raises(ValueError, match='exact owner'):
            read_runtime_mapping_fact(copied, repo, runtime, cycle_id=fact['cycle_id'], company_id=CID)
    with pytest.raises(ValueError, match='complete admitted owner'):
        snapshot.mapping_fact_by_id(fact['cycle_id'], CID, fact_id, state=state)


def test_aliased_state_is_rejected_before_beginning_writer_transaction(custody):
    state, repo, runtime, fact, _ = custody
    alias = Path(state.path).with_name('alias.db')
    alias.symlink_to(state.path)
    with closing(State(alias)) as aliased:
        statements = []
        aliased.connection.set_trace_callback(statements.append)
        with pytest.raises(ValueError, match='canonical durable database paths'):
            persist_runtime_mapping_fact(aliased, repo, runtime, cycle_id=fact['cycle_id'], company_id=CID, fact=fact)
        assert not any(statement.startswith('BEGIN') for statement in statements)


@pytest.mark.parametrize('provenance', ['company_event', 'operator_request', 'repair_retry',
                                       'temporary_retry', 'recovery_pause', 'selected_retry_reservation_sha256'])
def test_foreign_provenance_cannot_create_ordinary_mapping_fact(custody, provenance):
    state, _, _, fact, _ = custody
    cycle = state.cycle(fact['cycle_id'])
    cycle[provenance] = 'fixture-owned-elsewhere'
    state.save_cycle(cycle)
    with pytest.raises(ValueError, match='ordinary cycle'):
        persist(custody)
    assert state.connection.execute('SELECT name FROM sqlite_master WHERE name=?', (TABLE,)).fetchone() is None


def test_sealed_group_must_agree_and_partial_group_blocks_replay(custody):
    state, repo, runtime, fact, _ = custody
    fact_id = persist(custody)
    machine_fact = snapshot.mapping_fact_by_id(fact['cycle_id'], CID, fact_id, state=state, repository=repo,
                                              runtime_binding=runtime)
    cycle = state.cycle(fact['cycle_id'])
    engine = Engine(repo, state, runtime_binding=runtime)
    engine._accept_source_configuration_defect_evidence_loaded(cycle, cycle['companies'][CID], machine_fact)
    assert read(custody) == {'fact_id': fact_id, 'fact': fact}

    del cycle['companies'][CID]['source_configuration_qualification_evidence']
    state.save_cycle(cycle)
    with pytest.raises(ValueError, match='sealed cycle evidence'):
        read(custody)
    with pytest.raises(ValueError, match='sealed cycle evidence'):
        persist(custody)


def test_store_failure_has_no_partial_record(custody):
    state, _, _, fact, _ = custody
    statements = {'denied': False}

    def deny_insert(action, table, trigger, database, source):
        if action == sqlite3.SQLITE_INSERT and table == TABLE:
            statements['denied'] = True
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    state.connection.set_authorizer(deny_insert)
    try:
        with pytest.raises(sqlite3.DatabaseError, match='not authorized'):
            persist(custody)
    finally:
        state.connection.set_authorizer(None)
    assert statements['denied'] and not state.connection.in_transaction
    assert read(custody) is None
    assert state.connection.execute('SELECT name FROM sqlite_master WHERE name=?', (TABLE,)).fetchone() is None
    assert persist(custody) == snapshot.mapping_fact_id(fact)
