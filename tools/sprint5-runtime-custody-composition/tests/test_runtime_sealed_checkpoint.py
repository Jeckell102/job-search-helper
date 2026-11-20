"""Offline composition of runtime custody, the Engine checkpoint and ordinary outcomes."""
from contextlib import closing, contextmanager
from dataclasses import dataclass
from hashlib import sha256
import errno
import fcntl
import json
import os
from pathlib import Path
import shutil
import socket
from types import SimpleNamespace

import pytest

import release_admission_bootstrap as bootstrap
from job_search_helper import cli, engine as engine_module, runner
from job_search_helper import source_configuration_snapshot as snapshot
from job_search_helper.ats import Inventory, outcome_failure
from job_search_helper.engine import Engine, State
from job_search_helper.inbox import InventoryInbox
from job_search_helper.repository import GoogleRepository
from job_search_helper.run_sync import publish_pending
from job_search_helper.runtime_mapping_facts import (
    open_runtime_mapping_stores, persist_runtime_mapping_fact, read_runtime_mapping_fact,
)
from job_search_helper.scrape_outcome_producer import record_cycle_outcomes
from job_search_helper.sheet_profile import COMPACT_PROFILE, COMPACT_SCHEMAS
from job_search_helper.sheets_sync import SheetsSynchronizer
from job_search_helper.sqlite_repository import SQLiteRepository
from sheets_fixture import RangeSheets


ROOT = Path(__file__).resolve().parents[1]
CID = 'COMP-0066'
CYCLE_ID = 'CYC-A123456789AB'
REQUEST_ID = 's5-runtime-checkpoint-fixture'
WORKBOOK = 'S5_checkpoint_fixture'
COMPANY = {'Company ID': CID, 'Company': 'Forterra', 'Company Status': 'Active',
           'Official Careers URL': 'https://www.forterra.com/careers', 'ATS / Source': 'Rippling'}
QUAL_FIELDS = ('company_id', 'source_revision', 'capability_id', 'capability_digest',
               'mapping_digest', 'configuration_digest')
GROUP = {'source_configuration_mapping_fact', 'source_configuration_defect',
         'source_configuration_qualification_evidence'}


@dataclass
class Fixture:
    project: Path
    runtime: dict
    fact: dict
    monkeypatch: pytest.MonkeyPatch
    fetches: list
    workbook: GoogleRepository

    @property
    def state(self):
        return self.project / '.state/state.db'

    @property
    def jobs(self):
        return self.state.with_name('jobs.sqlite3')

    @property
    def fact_id(self):
        return snapshot.mapping_fact_id(self.fact)

    @contextmanager
    def inherited_admission(self, *, locked=True):
        lease = self.state.with_name('scraper.lock')
        descriptor = os.open(lease, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            if locked:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            os.set_inheritable(descriptor, True)
            with self.monkeypatch.context() as env:
                env.setenv('JSH_SCRAPER_ADMISSION_FD', str(descriptor))
                env.setenv('JSH_SCRAPER_ADMISSION_PATH', str(lease))
                env.setenv('JSH_SCRAPER_RUNTIME_BINDING', json.dumps(self.runtime))
                yield
        finally:
            try:
                os.close(descriptor)
            except OSError as exc:
                if exc.errno != errno.EBADF:
                    raise

    @contextmanager
    def locked(self):
        with (self.inherited_admission(),
              runner._scraper_admission(self.state, require_inherited=True) as measured,
              cli.writer_lock(self.state.with_name('writer.lock'))):
            assert measured == self.runtime
            yield

    def persist(self):
        with (self.locked(), open_runtime_mapping_stores(self.state, self.jobs, WORKBOOK, writable_state=True)
              as (state, jobs)):
            assert persist_runtime_mapping_fact(state, jobs, self.runtime, cycle_id=CYCLE_ID,
                                                company_id=CID, fact=self.fact) == self.fact_id

    def seal(self, *, cycle=CYCLE_ID, company=CID, fact_id=None):
        with self.inherited_admission():
            return Engine._accept_runtime_source_configuration_defect_evidence(
                cycle, company, self.fact_id if fact_id is None else fact_id,
            )

    def cycle(self):
        with closing(State(self.state, readonly=True)) as reader:
            return reader.cycle(CYCLE_ID)

    def assert_unsealed(self):
        assert GROUP.isdisjoint(self.cycle()['companies'][CID])

    def record_outcome(self):
        with self.locked(), closing(SQLiteRepository(self.jobs, WORKBOOK)) as owner:
            sync = publish_pending(SheetsSynchronizer(owner, self.workbook), max_batches=25)
            assert sync['pending_cells'] == 0 and sync['stop_reason'] == 'drained'
            cycle = self.cycle()
            [(_, mirror)] = owner.matches('Scan Cycles', {'Cycle ID': CYCLE_ID})
            assert mirror['Cycle Status'] == cycle['status']
            [company] = self.workbook.read('Companies')
            assert company['Official Careers URL'] == COMPANY['Official Careers URL']
            assert owner.read('Job History') == []
            first, = record_cycle_outcomes(owner, cycle, owner.read('Companies'), storage_confirmed=True)
            second, = record_cycle_outcomes(owner, cycle, owner.read('Companies'), storage_confirmed=True)
            assert second['outcome'] == first['outcome'] and second['recorded'] is False
            [saved] = owner.scrape_outcomes()
            assert saved['outcome_id'] == first['outcome_id']
            return first


@pytest.fixture
def make_fixture(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('A network or live authorization factory was attempted')

    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket.socket, 'connect_ex', forbidden)
    monkeypatch.setattr(socket, 'getaddrinfo', forbidden)
    monkeypatch.setattr(cli, 'authorize', forbidden)
    monkeypatch.setattr(cli, 'get_remote_repository', forbidden)
    for name in ('JSH_SCRAPER_ADMISSION_FD', 'JSH_SCRAPER_ADMISSION_PATH', 'JSH_SCRAPER_RUNTIME_BINDING'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(engine_module, 'uuid', SimpleNamespace(uuid4=lambda: SimpleNamespace(hex=CYCLE_ID[4:])))

    def build(*, packaged=False, observed=True, typed=None):
        project = tmp_path / 'fixture-project'
        package = project / 'src/job_search_helper'
        shutil.copytree(ROOT / 'src/job_search_helper', package, ignore=shutil.ignore_patterns('__pycache__'))
        state_root = project / '.state'
        state_root.mkdir()
        (project / 'requirements.txt').write_text('# Isolated fixture dependency policy\n')
        for name in ('title-blacklist.txt', 'title-review-list.txt'):
            shutil.copy2(ROOT / name, project / name)
        monkeypatch.setattr(snapshot, '_root', lambda: project)
        monkeypatch.setattr(cli, 'PROJECT_ROOT', project)
        monkeypatch.setattr(runner, 'PROJECT_ROOT', project)
        monkeypatch.setenv('JOB_STORAGE_BACKEND', 'sqlite')
        monkeypatch.setenv('SPREADSHEET_ID', WORKBOOK)
        monkeypatch.delenv('STATE_DB_FILE', raising=False)
        monkeypatch.delenv('JOB_DB_FILE', raising=False)
        with closing(SQLiteRepository(state_root / 'jobs.sqlite3', WORKBOOK, initialize=True)) as owner:
            owner.set_meta('ready', 'yes')
            owner.set_meta('sheets_profile', COMPACT_PROFILE)
            owner.import_rows('Companies', [(2, COMPANY)])
            frozen = snapshot.resolve_installed_source_configuration(owner, CID)
        fields = {key: frozen[key] for key in QUAL_FIELDS}
        evidence_code = 'rippling_verified_mapping_divergence'
        qualification = {**fields, 'category': 'same_provider_source_mapping', 'evidence_code': evidence_code}
        (project / snapshot.QUALIFICATION_PATH).write_bytes(snapshot._canonical_bytes({
            'schema': 'source-configuration-qualification-v1', 'qualifications': [qualification],
        }))
        fact = {'schema': 'rippling-mapping-divergence-fact-v1', 'cycle_id': CYCLE_ID, **fields,
                **{key: sha256(key.encode()).hexdigest() for key in (
                    'authority_extraction_digest', 'candidate_inventory_digest', 'regression_inventory_digest')},
                'evidence_code': evidence_code}
        if packaged:
            (project / snapshot.MAPPING_FACTS_PATH).write_bytes(snapshot._canonical_bytes({
                'schema': 'source-configuration-mapping-facts-v1',
                'facts': [{'fact_id': snapshot.mapping_fact_id(fact), 'fact': fact}],
            }))
        service = RangeSheets({'Companies': [COMPANY]}, schemas=COMPACT_SCHEMAS)
        workbook = GoogleRepository(service, WORKBOOK, schemas=COMPACT_SCHEMAS, min_request_interval=0)
        fixture = Fixture(project, bootstrap._validate_runtime(project, state_root), fact, monkeypatch, [], workbook)

        def fetch(ats, url, cid, name):
            fixture.fetches.append((ats, url, cid, name))
            return Inventory('blocked', reason='Unclassified fixture observation', source_url=url,
                             ats='Rippling', outcome_failure=typed)

        with (fixture.locked(), closing(State(fixture.state)) as state,
              closing(SQLiteRepository(fixture.jobs, WORKBOOK)) as owner,
              closing(InventoryInbox(state_root / 'inventories.sqlite3', WORKBOOK)) as inbox):
            engine = Engine(owner, state, fetcher=fetch, inbox=inbox, runtime_binding=fixture.runtime,
                            error_log_path=None)
            assert engine.start_cycle([CID], new_scan_request={
                'request_id': REQUEST_ID, 'request_fingerprint': 'a' * 64,
            }) == CYCLE_ID
            if observed:
                engine.resume_local(CYCLE_ID, fetch_workers=1, assignment_window=1)
                assert fixture.fetches == [('Rippling', COMPANY['Official Careers URL'], CID, 'Forterra')]
                assert state.cycle(CYCLE_ID)['companies'][CID]['stage'] == 'blocked'
            assert owner.scrape_outcomes() == []
        fixture.assert_unsealed()
        return fixture

    return build


def test_owned_fact_through_sealed_checkpoint_and_normal_immutable_writer(make_fixture, monkeypatch):
    fixture = make_fixture()
    fixture.persist()
    fingerprint = bootstrap.source_tree_digest(fixture.project)
    jobs_before = fixture.jobs.read_bytes()
    saved = State.save_cycle
    checkpoint_writes = []

    def require_active_holds(state, checkpoint):
        for name in ('scraper.lock', 'writer.lock'):
            with pytest.raises(cli.WriterLockBusy):
                with cli.writer_lock(fixture.state.with_name(name)):
                    pytest.fail(f'{name} was open to a competing writer')
        checkpoint_writes.append(checkpoint)
        return saved(state, checkpoint)

    with monkeypatch.context() as scoped:
        scoped.setattr(State, 'save_cycle', require_active_holds)
        assert fixture.seal() == fixture.fact_id
        assert fixture.seal() == fixture.fact_id
    assert len(checkpoint_writes) == 1
    item = fixture.cycle()['companies'][CID]
    assert set(item) & GROUP == GROUP and item['source_configuration_mapping_fact'] == fixture.fact
    assert bootstrap.source_tree_digest(fixture.project) == fingerprint
    assert fixture.jobs.read_bytes() == jobs_before
    assert len(fixture.fetches) == 1
    with closing(SQLiteRepository(fixture.jobs, WORKBOOK, readonly=True)) as reader:
        assert reader.scrape_outcomes() == []
    receipt = fixture.record_outcome()
    published = receipt['outcome']
    assert receipt['recorded'] is True
    assert published['outcome'] == 'QUALIFIED_INTEGRATION_REPAIR'
    assert published['repair_category'] == 'same_provider_source_mapping'
    assert published['identity']['cycle_id'] == CYCLE_ID
    assert published['identity']['request_id'] == REQUEST_ID
    assert published['identity']['company_id'] == CID
    for field in ('capability_id', 'capability_digest', 'mapping_digest', 'configuration_digest'):
        assert published[field] == fixture.fact[field]


def test_checkpoint_fault_keeps_owned_fact_and_allows_exact_retry(make_fixture, monkeypatch):
    fixture = make_fixture()
    fixture.persist()

    def fail(*args):
        raise RuntimeError('fixture checkpoint interruption')

    with monkeypatch.context() as scoped:
        scoped.setattr(State, 'save_cycle', fail)
        with pytest.raises(RuntimeError, match='fixture checkpoint interruption'):
            fixture.seal()
    fixture.assert_unsealed()
    with fixture.locked(), open_runtime_mapping_stores(fixture.state, fixture.jobs, WORKBOOK) as (state, jobs):
        assert read_runtime_mapping_fact(state, jobs, fixture.runtime, cycle_id=CYCLE_ID,
                                         company_id=CID)['fact_id'] == fixture.fact_id
    assert fixture.seal() == fixture.fact_id
    assert GROUP <= set(fixture.cycle()['companies'][CID])


def test_missing_runtime_receipt_cannot_use_package_and_legacy_path_still_works(make_fixture):
    fixture = make_fixture(packaged=True)
    with pytest.raises(ValueError, match='not durably owned'):
        fixture.seal()
    fixture.assert_unsealed()
    assert snapshot.mapping_fact_by_id(CYCLE_ID, CID, fixture.fact_id) == fixture.fact
    with (fixture.locked(), closing(State(fixture.state)) as state,
          closing(SQLiteRepository(fixture.jobs, WORKBOOK)) as owner):
        Engine(owner, state)._accept_source_configuration_defect_evidence(CYCLE_ID, CID, fixture.fact_id)
    assert GROUP <= set(fixture.cycle()['companies'][CID])
    assert fixture.record_outcome()['outcome']['outcome'] == 'QUALIFIED_INTEGRATION_REPAIR'


@pytest.mark.parametrize(('args', 'reason'), [
    ({'fact_id': '0' * 64}, 'not durably owned'),
    ({'company': 'COMP-0178'}, 'exact saved Company membership'),
    ({'cycle': 'CYC-A00000000000'}, 'exact ordinary cycle'),
])
def test_foreign_or_wrong_identity_cannot_seal(make_fixture, args, reason):
    fixture = make_fixture()
    fixture.persist()
    with pytest.raises(ValueError, match=reason):
        fixture.seal(**args)
    fixture.assert_unsealed()


@pytest.mark.parametrize(('drift', 'reason'), [
    ('company', 'Company source has changed'),
    ('runtime', 'Saved cycle runtime differs'),
    ('source', 'no longer matches installed state'),
    ('provenance', 'exact ordinary cycle'),
])
def test_stale_or_foreign_owner_cannot_seal(make_fixture, drift, reason):
    fixture = make_fixture()
    fixture.persist()
    if drift == 'company':
        with fixture.locked(), closing(SQLiteRepository(fixture.jobs, WORKBOOK)) as owner:
            owner.commit([{'tab': 'Companies', 'identity': {'Company ID': CID},
                           'values': {'Official Careers URL': 'https://www.forterra.com/changed'}}])
    elif drift == 'source':
        (fixture.project / 'requirements.txt').write_text('# Changed fixture dependency policy\n')
    else:
        with fixture.locked(), closing(State(fixture.state)) as state:
            cycle = state.cycle(CYCLE_ID)
            if drift == 'runtime':
                cycle['runtime_binding']['config_sha256'] = 'e' * 64
            else:
                cycle['operator_request'] = 'fixture-foreign-owner'
            state.save_cycle(cycle)
    with pytest.raises((RuntimeError, ValueError), match=reason):
        fixture.seal()
    fixture.assert_unsealed()


def test_missing_unlocked_and_busy_leases_refuse_sealing(make_fixture):
    fixture = make_fixture()
    fixture.persist()
    with pytest.raises(RuntimeError, match='pre-import scraper lease'):
        Engine._accept_runtime_source_configuration_defect_evidence(CYCLE_ID, CID, fixture.fact_id)
    with fixture.inherited_admission(locked=False), pytest.raises(RuntimeError, match='is not locked'):
        Engine._accept_runtime_source_configuration_defect_evidence(CYCLE_ID, CID, fixture.fact_id)
    with cli.writer_lock(fixture.state.with_name('writer.lock')):
        with pytest.raises(cli.WriterLockBusy):
            fixture.seal()
    fixture.assert_unsealed()
    assert fixture.seal() == fixture.fact_id


@pytest.mark.parametrize('typed', [False, True])
def test_requires_ordinary_incomplete_unclassified_observation(make_fixture, typed):
    fixture = make_fixture(
        observed=typed, typed=outcome_failure('access_denied', 'public_access_denied') if typed else None,
    )
    fixture.persist()
    with pytest.raises(ValueError, match='requires an incomplete ordinary observation'):
        fixture.seal()
    fixture.assert_unsealed()


def test_existing_unknown_outcome_stays_immutable_when_evidence_arrives_late(make_fixture):
    fixture = make_fixture()
    first = fixture.record_outcome()
    assert first['outcome']['outcome'] == 'UNKNOWN_CAPABILITY_HOLD' and first['recorded'] is True
    fixture.persist()
    assert fixture.seal() == fixture.fact_id
    later = fixture.record_outcome()
    assert later['outcome'] == first['outcome'] and later['recorded'] is False
