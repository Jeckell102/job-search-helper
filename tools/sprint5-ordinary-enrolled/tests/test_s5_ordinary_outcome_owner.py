from contextlib import closing
import sqlite3

import pytest

from job_search_helper import ordinary_verification_outcome_owner as ownership
from job_search_helper import ordinary_verification_pending as pending
from job_search_helper import scrape_outcome_producer as producer
from job_search_helper.company_events import source_revision
from job_search_helper.engine import State
from job_search_helper.inbox import InventoryInbox
from job_search_helper.repository import RepositoryError
from job_search_helper.sqlite_repository import SQLiteRepository


WORKBOOK = 'fixture-workbook'
COMPANY = {'Company ID': 'COMP-4510', 'Company': 'Example', 'Company Status': 'Active',
           'ATS / Source': 'Rippling', 'Official Careers URL': 'https://example.test/careers'}
SCOPE = {'cycle_id': 'CYC-2F654B5B98D8', 'request_id': 'ordinary-fixture',
         'company_id': COMPANY['Company ID'], 'source_revision': source_revision(COMPANY)}
DISPATCH = 'a' * 64


def facts(**changes):
    return {**SCOPE, 'source_current': True, 'company_status': 'Active',
            'storage_status': 'confirmed', 'inventory_status': 'partial',
            'capability': 'unknown', 'failure': {'category': 'unknown'}, **changes}


@pytest.fixture
def paths(tmp_path):
    state, jobs, inbox = (tmp_path / name for name in ('state.db', 'jobs.db', 'inbox.db'))
    with (
        closing(State(state)), closing(InventoryInbox(inbox, WORKBOOK)),
        closing(SQLiteRepository(jobs, WORKBOOK, initialize=True)) as repository,
    ):
        repository.set_meta('ready', 'yes')
        repository.import_rows('Companies', [(2, COMPANY)])
    return state, jobs, inbox


def open_stores(paths):
    return pending.open_verification_stores(*paths, WORKBOOK, writable_jobs=True)


def owner(stores):
    return {**SCOPE, 'store_binding_sha256': pending.store_binding(stores)}


def test_jobs_reservation_survives_crash_and_missing_state(paths):
    with open_stores(paths) as stores:
        reservation = ownership.reserve_outcome_owner(stores, owner(stores), DISPATCH)
        assert reservation['state'] == 'RESERVED'
        expected = dict(SCOPE, dispatch_sha256=DISPATCH, state_path=str(paths[0]),
                        state_device=paths[0].stat().st_dev, state_inode=paths[0].stat().st_ino)
        assert reservation['owner'] == expected
        assert stores.state.cycle(SCOPE['cycle_id']) is None
        assert not stores.jobs.db.in_transaction
    paths[0].unlink()
    with closing(SQLiteRepository(paths[1], WORKBOOK)) as repository:
        with pytest.raises(RepositoryError, match='exact verification finisher'):
            repository.record_scrape_outcome(facts())
        with pytest.raises(RepositoryError, match='exact verification finisher'):
            repository.record_scrape_outcome(facts(request_id='drift', source_revision='b' * 64))
        assert repository.scrape_outcomes() == []


def test_exact_retry_reuses_reservation_and_refuses_replacement(paths):
    with open_stores(paths) as stores:
        first = ownership.reserve_outcome_owner(stores, owner(stores), DISPATCH)
    with open_stores(paths) as stores:
        assert ownership.reserve_outcome_owner(stores, owner(stores), DISPATCH) == first
        for candidate, dispatch in (({**owner(stores), 'request_id': 'second-request'}, DISPATCH),
                                    (owner(stores), 'b' * 64)):
            with pytest.raises(RepositoryError, match='another dispatch or State'):
                ownership.reserve_outcome_owner(stores, candidate, dispatch)
    paths[0].rename(paths[0].with_suffix('.original'))
    with closing(State(paths[0])):
        pass
    with open_stores(paths) as stores:
        with pytest.raises(RepositoryError, match='another dispatch or State'):
            ownership.reserve_outcome_owner(stores, owner(stores), DISPATCH)
        assert stores.jobs.db.execute(
            'SELECT dispatch_sha256,state_inode FROM main.ordinary_verification_outcome_owners',
        ).fetchall() == [(DISPATCH, first['owner']['state_inode'])]


def test_cycleless_conflict_holds_while_independent_outcomes_stay_available(paths):
    with open_stores(paths) as stores:
        ownership.reserve_outcome_owner(stores, owner(stores), DISPATCH)
        with pytest.raises(RepositoryError, match='exact verification finisher'):
            stores.jobs.record_scrape_outcome(facts(cycle_id=None))
        for other in (facts(cycle_id='CYC-DIFFERENT'), facts(company_id='COMP-OTHER'),
                      facts(cycle_id=None, request_id='unrelated-legacy')):
            assert stores.jobs.record_scrape_outcome(other)['recorded']
        assert len(stores.jobs.scrape_outcomes()) == 3


def test_sealed_public_writer_uses_the_same_guard(paths, monkeypatch):
    # Stub only proof derivation. Use the real State loader, ordinary facts,
    # classifier, write transaction and immutable Jobs outcome storage.
    monkeypatch.setattr(producer, '_sealed_mapping_evidence', lambda *_: {
        'capability': 'sealed', 'failure': {'category': 'same_provider_source_mapping'},
        'capability_id': 'rippling-shared-v1', 'capability_digest': 'a' * 64,
        'mapping_digest': 'b' * 64, 'configuration_digest': 'c' * 64,
    })
    with open_stores(paths) as stores:
        for cycle_id in (SCOPE['cycle_id'], 'CYC-SIBLING'):
            stores.state.save_cycle({
                'id': cycle_id, 'start_request_id': SCOPE['request_id'],
                'companies': {COMPANY['Company ID']: {
                    'stage': 'partial', 'inventory_status': 'partial',
                    'outcome_source_revision': SCOPE['source_revision'],
                }},
            })
        ownership.reserve_outcome_owner(stores, owner(stores), DISPATCH)
        with pytest.raises(RepositoryError, match='exact verification finisher'):
            stores.jobs.record_sealed_source_configuration_outcome(
                SCOPE['cycle_id'], COMPANY['Company ID'], storage_confirmed=True,
            )
        sibling = stores.jobs.record_sealed_source_configuration_outcome(
            'CYC-SIBLING', COMPANY['Company ID'], storage_confirmed=True,
        )
        assert sibling['outcome']['outcome'] == 'QUALIFIED_INTEGRATION_REPAIR'
        assert len(stores.jobs.scrape_outcomes()) == 1


@pytest.mark.parametrize('inventory,expected', [('partial', 'UNKNOWN_CAPABILITY_HOLD'), ('complete', 'COMPLETE')])
def test_exact_prior_outcome_wins_unchanged_without_opt_in(paths, inventory, expected):
    with open_stores(paths) as stores:
        recorded = stores.jobs.record_scrape_outcome(facts(inventory_status=inventory))['outcome']
        raw = stores.jobs.db.execute('SELECT * FROM main.scrape_outcomes').fetchall()
        assert recorded['outcome'] == expected
        assert ownership.reserve_outcome_owner(stores, owner(stores), DISPATCH) == {
            'state': 'EXISTING_OUTCOME', 'outcome': {'outcome_id': recorded['outcome_id'],
                                                    'payload_sha256': pending.digest(recorded), 'outcome': recorded},
        }
        assert stores.jobs.db.execute('SELECT * FROM main.scrape_outcomes').fetchall() == raw
        assert not ownership._has_reservations(stores.jobs.db)


@pytest.mark.parametrize('problem', ['without-cycle', 'competing', 'invalid-index'])
def test_ambiguous_prior_holds_without_reserving(paths, problem):
    with open_stores(paths) as stores:
        first = facts(cycle_id=None) if problem == 'without-cycle' else facts()
        stores.jobs.record_scrape_outcome(first)
        if problem == 'competing':
            stores.jobs.record_scrape_outcome(facts(inventory_status='complete'))
        elif problem == 'invalid-index':
            stores.jobs.db.execute("UPDATE main.scrape_outcomes SET action='untrusted'")
        with pytest.raises(RepositoryError, match='attributed|Multiple immutable|indexed identity'):
            ownership.reserve_outcome_owner(stores, owner(stores), DISPATCH)
        assert not ownership._has_reservations(stores.jobs.db)


def test_reservation_first_holds_jobs_fence_during_prior_read(paths, monkeypatch):
    with open_stores(paths) as stores, closing(SQLiteRepository(paths[1], WORKBOOK)) as contender:
        contender.db.execute('PRAGMA busy_timeout=0')
        read_original = ownership.existing_outcome

        def read_with_contender(repository, expected_owner):
            with pytest.raises(sqlite3.OperationalError, match='locked'):
                contender.record_scrape_outcome(facts())
            return read_original(repository, expected_owner)

        monkeypatch.setattr(ownership, 'existing_outcome', read_with_contender)
        result = ownership.reserve_outcome_owner(stores, owner(stores), DISPATCH)
        assert result['state'] == 'RESERVED'
        with pytest.raises(RepositoryError, match='exact verification finisher'):
            contender.record_scrape_outcome(facts())
        assert contender.scrape_outcomes() == []


def test_first_writer_holds_jobs_fence_and_its_committed_outcome_wins(paths):
    with open_stores(paths) as stores, closing(SQLiteRepository(paths[1], WORKBOOK)) as contender:
        expected_owner = owner(stores)
        stores.jobs.db.execute('PRAGMA busy_timeout=0')
        with contender.transaction():
            recorded = contender._record_scrape_outcome_in_transaction(facts())['outcome']
            with pytest.raises(sqlite3.OperationalError, match='locked'):
                ownership.reserve_outcome_owner(stores, expected_owner, DISPATCH)
        result = ownership.reserve_outcome_owner(stores, expected_owner, DISPATCH)
        assert result['outcome']['outcome'] == recorded
        assert not ownership._has_reservations(stores.jobs.db)


def test_failure_before_jobs_commit_rolls_back_private_reservation(paths, monkeypatch):
    with open_stores(paths) as stores:
        insert = ownership._insert_reservation

        def interrupt(db, binding):
            insert(db, binding)
            raise RuntimeError('cut before Jobs commit')

        with monkeypatch.context() as patch:
            patch.setattr(ownership, '_insert_reservation', interrupt)
            with pytest.raises(RuntimeError, match='before Jobs commit'):
                ownership.reserve_outcome_owner(stores, owner(stores), DISPATCH)
        assert not ownership._has_reservations(stores.jobs.db)
        assert ownership.reserve_outcome_owner(stores, owner(stores), DISPATCH)['state'] == 'RESERVED'
