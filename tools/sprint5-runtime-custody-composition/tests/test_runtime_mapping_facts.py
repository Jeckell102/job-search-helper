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
from job_search_helper.runtime_mapping_facts import (
    open_runtime_mapping_stores,
    persist_runtime_mapping_fact,
    read_runtime_mapping_fact,
)
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
    state_path, jobs_path = state_dir / 'state.db', state_dir / 'jobs.sqlite3'
    with (closing(State(state_path)) as state,
          closing(SQLiteRepository(jobs_path, WORKBOOK, initialize=True)) as repo):
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
    with open_runtime_mapping_stores(state_path, jobs_path, WORKBOOK, writable_state=True) as (state, repo):
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
    jobs_before = Path(repo.path).read_bytes()
    before = state.cycle(cycle_id)
    fact_id = persist(custody)
    row_before, = state.connection.execute(f'SELECT * FROM {TABLE}').fetchall()
    assert persist(custody) == fact_id == snapshot.mapping_fact_id(fact)
    assert state.connection.execute(f'SELECT * FROM {TABLE}').fetchall() == [row_before]
    assert state.cycle(cycle_id) == before
    assert Path(repo.path).read_bytes() == jobs_before
    assert (installed / snapshot.MAPPING_FACTS_PATH).read_bytes() == packaged_before
    assert source_tree_digest(installed) == runtime['source_manifest_sha256']
    with open_runtime_mapping_stores(state.path, repo.path, WORKBOOK) as (readonly_state, reader):
        assert snapshot.mapping_fact_by_id(cycle_id, CID, fact_id) is None
        assert snapshot.mapping_fact_by_id(cycle_id, CID, fact_id, state=readonly_state, repository=reader,
                                           runtime_binding=runtime) == fact
        assert snapshot.mapping_fact_by_id(cycle_id, CID, 'a' * 64, state=readonly_state, repository=reader,
                                           runtime_binding=runtime) is None
        with pytest.raises(ValueError, match='writable State'):
            persist_runtime_mapping_fact(readonly_state, reader, runtime, cycle_id=cycle_id, company_id=CID, fact=fact)


def test_managed_scope_can_reopen_while_runner_handles_are_open(custody):
    state, repo, runtime, fact, _ = custody
    cycle_id = fact['cycle_id']
    with (closing(State(state.path)) as runner_state,
          closing(SQLiteRepository(repo.path, WORKBOOK)) as runner_jobs,
          open_runtime_mapping_stores(state.path, repo.path, WORKBOOK, writable_state=True) as (scope, jobs)):
        assert runner_state.cycle(cycle_id)['id'] == cycle_id
        assert len(runner_jobs.matches('Companies', {'Company ID': CID})) == 1
        assert persist_runtime_mapping_fact(scope, jobs, runtime, cycle_id=cycle_id, company_id=CID,
                                            fact=fact) == snapshot.mapping_fact_id(fact)
    assert read(custody)['fact'] == fact


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


def test_contextual_packaged_fallback_checks_exact_current_mapping_without_writes(custody):
    state, repo, runtime, fact, installed = custody
    cycle_id = fact['cycle_id']
    stale = {**fact, 'mapping_digest': '1' * 64}
    paths = Path(state.path), Path(repo.path)
    before = tuple(path.read_bytes() for path in paths)
    with open_runtime_mapping_stores(*paths, WORKBOOK) as (reader, jobs):
        save_package_fact(installed, stale)
        stale_id = snapshot.mapping_fact_id(stale)
        assert snapshot.mapping_fact_by_id(cycle_id, CID, stale_id) == stale
        assert snapshot.mapping_fact_by_id(cycle_id, CID, stale_id, state=reader, repository=jobs,
                                           runtime_binding=runtime) is None
        save_package_fact(installed, fact)
        fact_id = snapshot.mapping_fact_id(fact)
        assert snapshot.mapping_fact_by_id(cycle_id, CID, fact_id, state=reader, repository=jobs,
                                           runtime_binding=runtime) == fact
    assert state.connection.execute('SELECT name FROM main.sqlite_master WHERE name=?', (TABLE,)).fetchone() is None
    assert tuple(path.read_bytes() for path in paths) == before


def test_contextual_packaged_fallback_checks_existing_sealed_group(custody):
    state, repo, runtime, fact, installed = custody
    cycle_id = fact['cycle_id']
    save_package_fact(installed, fact)
    fact_id = snapshot.mapping_fact_id(fact)
    cycle = state.cycle(cycle_id)
    engine = Engine(repo, state, runtime_binding=runtime)
    engine._accept_source_configuration_defect_evidence_loaded(cycle, cycle['companies'][CID], fact)
    assert snapshot.mapping_fact_by_id(cycle_id, CID, fact_id, state=state, repository=repo,
                                       runtime_binding=runtime) == fact
    del cycle['companies'][CID]['source_configuration_qualification_evidence']
    state.save_cycle(cycle)
    assert snapshot.mapping_fact_by_id(cycle_id, CID, fact_id) == fact
    with pytest.raises(ValueError, match='sealed cycle evidence'):
        snapshot.mapping_fact_by_id(cycle_id, CID, fact_id, state=state, repository=repo,
                                    runtime_binding=runtime)
    assert state.connection.execute('SELECT name FROM main.sqlite_master WHERE name=?', (TABLE,)).fetchone() is None


def test_temp_slot_cannot_hide_or_receive_a_durable_fact(custody):
    state, repo, runtime, fact, installed = custody
    connection = state.connection
    connection.execute(
        f'CREATE TEMP TABLE {TABLE} (cycle, company, fact_id, record_sha256, payload)',
    )
    fact_id = persist(custody)
    other = {**fact, 'candidate_inventory_digest': '1' * 64}
    save_package_fact(installed, other)
    other_id = snapshot.mapping_fact_id(other)
    assert snapshot.mapping_fact_by_id(fact['cycle_id'], CID, other_id, state=state, repository=repo,
                                       runtime_binding=runtime) is None
    with pytest.raises(ValueError, match='immutable'):
        persist(custody, other)
    assert persist(custody) == fact_id
    assert connection.execute(f'SELECT fact_id FROM main.{TABLE}').fetchall() == [(fact_id,)]
    assert connection.execute(f'SELECT fact_id FROM temp.{TABLE}').fetchall() == []
    with open_runtime_mapping_stores(state.path, repo.path, WORKBOOK) as (reader, jobs):
        assert read_runtime_mapping_fact(reader, jobs, runtime, cycle_id=fact['cycle_id'],
                                         company_id=CID) == {'fact_id': fact_id, 'fact': fact}


@pytest.mark.parametrize('target', ['state', 'jobs'])
@pytest.mark.parametrize('already_recorded', [False, True])
def test_replaced_canonical_file_does_not_rebind_its_open_connection(custody, target, already_recorded):
    state, repo, runtime, fact, _ = custody
    fact_id = persist(custody) if already_recorded else None
    path, connection = (Path(state.path), state.connection) if target == 'state' else (Path(repo.path), repo.db)
    replacement = path.with_suffix('.replacement')
    with closing(sqlite3.connect(replacement)) as copy_connection:
        connection.backup(copy_connection)
        with copy_connection:
            copy_connection.execute('PRAGMA journal_mode=DELETE')
            copy_connection.execute('CREATE TABLE fixture_generation (kind)')
            copy_connection.execute('INSERT INTO fixture_generation VALUES (?)', ('replacement',))
    path.rename(path.with_suffix('.original'))
    replacement.rename(path)
    with closing(sqlite3.connect(f'{path.as_uri()}?mode=ro&immutable=1', uri=True)) as fresh:
        assert fresh.execute('SELECT kind FROM main.fixture_generation').fetchall() == [('replacement',)]
    assert connection.execute(
        "SELECT name FROM main.sqlite_master WHERE name='fixture_generation'",
    ).fetchall() == []
    statements = []
    state.connection.set_trace_callback(statements.append)
    with pytest.raises(ValueError, match='opened database identity changed'):
        persist(custody)
    assert not any(statement.startswith('BEGIN') for statement in statements)
    if already_recorded:
        assert state.connection.execute(f'SELECT fact_id FROM main.{TABLE}').fetchall() == [(fact_id,)]
    else:
        assert state.connection.execute('SELECT name FROM main.sqlite_master WHERE name=?', (TABLE,)).fetchone() is None
    with pytest.raises(ValueError, match='opened database identity changed'):
        read(custody)
    if already_recorded:
        connection.close()
        with open_runtime_mapping_stores(state.path, repo.path, WORKBOOK) as (reader, jobs):
            with pytest.raises(ValueError, match='exact owner'):
                read_runtime_mapping_fact(reader, jobs, runtime, cycle_id=fact['cycle_id'], company_id=CID)


def test_rechecks_workbook_from_main_even_when_temp_meta_preserves_original_value(custody):
    state, repo, runtime, fact, _ = custody
    assert persist(custody) == snapshot.mapping_fact_id(fact)
    repo.db.execute('CREATE TEMP TABLE meta AS SELECT * FROM main.meta')
    assert read(custody)['fact'] == fact
    with closing(sqlite3.connect(repo.path)) as other:
        with other:
            other.execute("UPDATE main.meta SET value='different_workbook' WHERE key='spreadsheet_id'")
    assert repo.db.execute("SELECT value FROM temp.meta WHERE key='spreadsheet_id'").fetchone() == (WORKBOOK,)
    with pytest.raises(ValueError, match='Jobs workbook identity changed'):
        read(custody)
    with pytest.raises(ValueError, match='Jobs workbook identity changed'):
        persist(custody)
    assert state.connection.execute(f'SELECT count(*) FROM main.{TABLE}').fetchone() == (1,)


def assert_public_custody_held(custody, reason):
    state, repo, runtime, fact, _ = custody
    with pytest.raises(ValueError, match=reason):
        persist(custody)
    with pytest.raises(ValueError, match=reason):
        read(custody)
    with pytest.raises(ValueError, match=reason):
        snapshot.mapping_fact_by_id(fact['cycle_id'], CID, snapshot.mapping_fact_id(fact),
                                    state=state, repository=repo, runtime_binding=runtime)


@pytest.mark.parametrize('existing', [False, True])
def test_jobs_explicit_read_transaction_cannot_replay_stale_workbook(custody, existing):
    state, repo, _, fact, _ = custody
    if existing:
        assert persist(custody) == snapshot.mapping_fact_id(fact)
    repo.db.execute('BEGIN')
    try:
        key = "SELECT value FROM main.meta WHERE key='spreadsheet_id'"
        assert repo.db.execute(key).fetchone() == (WORKBOOK,)
        with closing(sqlite3.connect(repo.path)) as writer, writer:
            writer.execute("UPDATE main.meta SET value='different_workbook' WHERE key='spreadsheet_id'")
        with closing(sqlite3.connect(repo.path)) as fresh:
            assert fresh.execute(key).fetchone() == ('different_workbook',)
        assert repo.db.execute(key).fetchone() == (WORKBOOK,)
        assert_public_custody_held(custody, 'requires idle State and Jobs')
        assert repo.db.in_transaction
    finally:
        repo.db.rollback()
    assert_public_custody_held(custody, 'Jobs workbook identity changed')
    table = state.connection.execute('SELECT name FROM main.sqlite_master WHERE name=?', (TABLE,)).fetchone()
    assert bool(table) == existing


def test_state_explicit_read_transaction_cannot_replay_removed_cycle(custody):
    state, _, _, fact, _ = custody
    assert persist(custody) == snapshot.mapping_fact_id(fact)
    state.connection.execute('BEGIN')
    try:
        assert state.cycle(fact['cycle_id'])['id'] == fact['cycle_id']
        with closing(sqlite3.connect(state.path)) as writer, writer:
            writer.execute('DELETE FROM main.cycles WHERE id=?', (fact['cycle_id'],))
        with closing(State(state.path, readonly=True)) as fresh:
            assert fresh.cycle(fact['cycle_id']) is None
        assert state.cycle(fact['cycle_id'])['id'] == fact['cycle_id']
        assert_public_custody_held(custody, 'requires idle State and Jobs')
        assert state.connection.in_transaction
    finally:
        state.connection.rollback()
    assert_public_custody_held(custody, 'exact ordinary cycle')


@pytest.mark.parametrize('target', ['state', 'jobs'])
def test_unfinished_select_cannot_pin_old_authority_in_autocommit(custody, target):
    state, repo, _, fact, _ = custody
    assert persist(custody) == snapshot.mapping_fact_id(fact)
    if target == 'state':
        conn, path, relation, column = state.connection, state.path, 'cycles', 'id'
        change = ('DELETE FROM main.cycles WHERE id=?', (fact['cycle_id'],))
        pinned_query = ('SELECT id FROM main.cycles WHERE id=?', (fact['cycle_id'],))
        old_value, fresh_value = (fact['cycle_id'],), None
        fresh_error = 'exact ordinary cycle'
    else:
        conn, path, relation, column = repo.db, repo.path, 'meta', 'key'
        change = ("UPDATE main.meta SET value='different_workbook' WHERE key='spreadsheet_id'", ())
        pinned_query = ("SELECT value FROM main.meta WHERE key='spreadsheet_id'", ())
        old_value, fresh_value = (WORKBOOK,), ('different_workbook',)
        fresh_error = 'Jobs workbook identity changed'
    query = f'SELECT {column} FROM main.{relation} UNION ALL SELECT {column} FROM main.{relation}'
    with closing(conn.execute(query)) as cursor:
        assert cursor.fetchone() is not None and not conn.in_transaction
        with closing(sqlite3.connect(path)) as writer, writer:
            writer.execute(*change)
        with closing(sqlite3.connect(path)) as fresh:
            assert fresh.execute(*pinned_query).fetchone() == fresh_value
        assert conn.execute(*pinned_query).fetchone() == old_value and not conn.in_transaction
        assert_public_custody_held(custody, 'requires idle State and Jobs')
    assert_public_custody_held(custody, fresh_error)


def test_attachment_cannot_substitute_missing_main_company_tables(custody):
    _, repo, _, fact, _ = custody
    fact_id = persist(custody)
    helper = repo.path.with_suffix('.fixture-authority')
    with (closing(sqlite3.connect(repo.path)) as writer,
          closing(sqlite3.connect(helper)) as attachment):
        writer.backup(attachment)
        with writer:
            writer.execute('ALTER TABLE main.records RENAME TO missing_records')
            writer.execute('ALTER TABLE main.lookups RENAME TO missing_lookups')
    repo.db.execute('ATTACH DATABASE ? AS alternative', (str(helper),))
    try:
        assert repo.db.execute(
            "SELECT name FROM main.sqlite_master WHERE name IN ('records','lookups')",
        ).fetchall() == []
        assert len(repo.matches('Companies', {'Company ID': CID})) == 1
        assert_public_custody_held(custody, 'does not accept attached databases')
    finally:
        repo.db.execute('DETACH DATABASE alternative')
    assert_public_custody_held(custody, 'requires main Jobs Company tables')
    with closing(sqlite3.connect(repo.path)) as writer, writer:
        writer.execute('ALTER TABLE main.missing_records RENAME TO records')
        writer.execute('ALTER TABLE main.missing_lookups RENAME TO lookups')
    assert read(custody)['fact_id'] == fact_id
    assert persist(custody) == fact_id


def test_state_attachment_is_held_even_with_normal_main_tables(custody):
    state, _, _, fact, _ = custody
    fact_id = persist(custody)
    state.connection.execute("ATTACH DATABASE ':memory:' AS alternative")
    try:
        assert_public_custody_held(custody, 'does not accept attached databases')
    finally:
        state.connection.execute('DETACH DATABASE alternative')
    assert read(custody)['fact_id'] == fact_id


def test_unavailable_statement_status_holds_all_public_entries(custody):
    _, repo, _, fact, _ = custody
    fact_id = persist(custody)

    def deny_statement_status(action, table, column, database, source):
        if action == sqlite3.SQLITE_READ and table == 'sqlite_stmt':
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    repo.db.set_authorizer(deny_statement_status)
    try:
        assert_public_custody_held(custody, 'cannot verify idle SQLite connections')
    finally:
        repo.db.set_authorizer(None)
    assert persist(custody) == fact_id


def test_temp_company_authority_holds_direct_and_contextual_reads(custody):
    state, repo, runtime, fact, _ = custody
    fact_id = persist(custody)
    repo.db.execute('CREATE TEMP VIEW records AS SELECT * FROM main.records')
    with pytest.raises(ValueError, match='Company authority is shadowed'):
        read(custody)
    with pytest.raises(ValueError, match='Company authority is shadowed'):
        snapshot.mapping_fact_by_id(fact['cycle_id'], CID, fact_id, state=state, repository=repo,
                                    runtime_binding=runtime)
    assert state.connection.execute(f'SELECT fact_id FROM main.{TABLE}').fetchall() == [(fact_id,)]


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
        with closing(SQLiteRepository(repo.path, WORKBOOK)) as writer:
            writer.commit([{'tab': 'Companies', 'identity': {'Company ID': CID},
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
    copied_path = Path(state.path).with_name('copied-state.db')
    with closing(State(copied_path)) as copied:
        state.connection.backup(copied.connection)
    with open_runtime_mapping_stores(copied_path, repo.path, WORKBOOK) as (copied, reader):
        with pytest.raises(ValueError, match='exact owner'):
            read_runtime_mapping_fact(copied, reader, runtime, cycle_id=fact['cycle_id'], company_id=CID)
    with pytest.raises(ValueError, match='complete admitted owner'):
        snapshot.mapping_fact_by_id(fact['cycle_id'], CID, fact_id, state=state)


def test_aliased_state_is_rejected_before_beginning_writer_transaction(custody):
    state, repo, _, _, _ = custody
    alias = Path(state.path).with_name('alias.db')
    alias.symlink_to(state.path)
    with pytest.raises(ValueError, match='canonical durable database paths'):
        with open_runtime_mapping_stores(alias, repo.path, WORKBOOK, writable_state=True):
            pytest.fail('managed open accepted aliased State')


def test_unmanaged_state_is_rejected_before_beginning_writer_transaction(custody):
    state, repo, runtime, fact, _ = custody
    with closing(State(state.path)) as unmanaged:
        statements = []
        unmanaged.connection.set_trace_callback(statements.append)
        with pytest.raises(ValueError, match='managed opened'):
            persist_runtime_mapping_fact(unmanaged, repo, runtime, cycle_id=fact['cycle_id'], company_id=CID, fact=fact)
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
