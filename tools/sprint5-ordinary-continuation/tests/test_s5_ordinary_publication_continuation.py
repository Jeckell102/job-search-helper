"""Join the named capture and exact publication phases with disposable data."""

import fcntl
import json
import os
import sqlite3

import pytest

from job_search_helper import ats, cli, ordinary_verification_pending as pending, runner
from job_search_helper.ordinary_verification_publisher import verification_input_after_publication
from job_search_helper.repository import RepositoryError, UncertainWriteError
from job_search_helper.sheet_profile import COMPACT_PROFILE, COMPACT_SCHEMAS
from job_search_helper.sqlite_repository import SQLiteRepository

from test_exact_cycle_recovery import RecordingRemote
from test_ordinary_verification_pending import COMPANY, COMPANY_ID, CYCLE_ID, OBSERVATION, attempt
from test_s5_ordinary_worker_handoff import local_worker, mismatch


WORKBOOK = 'fixture-workbook'


@pytest.fixture
def measured_scope(local_worker, monkeypatch, tmp_path):
    import release_admission_bootstrap

    initial, _, _ = local_worker
    directory = tmp_path / 'named-ordinary'
    directory.mkdir(mode=0o700)
    state, jobs, inbox = [directory / name for name in ('state.db', 'jobs.sqlite3', 'inventories.sqlite3')]
    for key, value in {'JOB_STORAGE_BACKEND': 'sqlite', 'STATE_DB_FILE': state,
                       'JOB_DB_FILE': jobs, 'SPREADSHEET_ID': WORKBOOK}.items():
        monkeypatch.setenv(key, str(value))
    runtime = release_admission_bootstrap._validate_runtime(runner.PROJECT_ROOT, directory)
    cycle = initial.state.cycle(CYCLE_ID)
    cycle['runtime_binding'] = runtime
    initial.state.save_cycle(cycle)
    for original, path in ((initial.state.connection, state), (initial.jobs.db, jobs),
                           (initial.inbox.connection, inbox)):
        copy = sqlite3.connect(path)
        try:
            original.backup(copy)
        finally:
            copy.close()
        path.chmod(0o600)
    local = SQLiteRepository(jobs, WORKBOOK)
    try:
        local.ensure_columns('Opportunities', ['Opportunity ID'])
        local.set_meta('sheets_profile', COMPACT_PROFILE)
    finally:
        local.close()
    scraper = directory / 'scraper.lock'
    lock = os.open(scraper, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def launch(**kwargs):
        monkeypatch.setenv('JSH_SCRAPER_ADMISSION_FD', str(os.dup(lock)))
        monkeypatch.setenv('JSH_SCRAPER_ADMISSION_PATH', str(scraper))
        monkeypatch.setenv('JSH_SCRAPER_RUNTIME_BINDING', json.dumps(runtime))
        return runner.run_start(**kwargs)

    try:
        yield launch, state, jobs, inbox
    finally:
        os.close(lock)


def test_measured_capture_exact_publish_and_offline_replay(measured_scope, monkeypatch, capsys):
    launch, state, jobs, inbox = measured_scope
    provider_calls, remote_calls = [], []

    def fetch(*args):
        provider_calls.append(args)
        return mismatch()

    remote = RecordingRemote([COMPANY], schemas=COMPACT_SCHEMAS)
    remote.spreadsheet_id = WORKBOOK

    def remote_factory(**kwargs):
        remote_calls.append(kwargs)
        return remote

    monkeypatch.setattr(ats, 'fetch_inventory', fetch)
    monkeypatch.setattr(cli, 'get_remote_repository', remote_factory)
    assert launch(resume=True, resume_cycle_id=CYCLE_ID, capture_ordinary_verification=True,
                  fetch_workers=1, browser_fallback=False) == 0
    assert len(provider_calls) == 1 and remote_calls == []
    with pending.open_verification_stores(state, jobs, inbox, WORKBOOK) as stores:
        verifier_input = pending.verifier_payload(stores, CYCLE_ID, COMPANY_ID)
        assert verifier_input['observation'] == OBSERVATION
    arguments = dict(sync_only=True, sync_cycle_id=CYCLE_ID, sync_company_ids=[COMPANY_ID],
                     publish_ordinary_verification=True)
    assert launch(**arguments) == 0
    assert len(remote_calls) == len(remote.commits) == 1
    assert '\"disposition\": \"PUBLISHED\"' in capsys.readouterr().out
    assert launch(**arguments) == 0
    assert '\"disposition\": \"ALREADY_PUBLISHED\"' in capsys.readouterr().out
    assert len(provider_calls) == len(remote_calls) == len(remote.commits) == 1

    with pending.open_verification_stores(state, jobs, inbox, WORKBOOK) as stores:
        assert stores.inbox.get(CYCLE_ID, COMPANY_ID) is None
        assert stores.inbox.plan(CYCLE_ID, COMPANY_ID) is None
        assert stores.jobs.scrape_outcomes() == []
        assert verification_input_after_publication(stores, CYCLE_ID, COMPANY_ID) == verifier_input
        assert stores.state.cycle(CYCLE_ID)['companies'][COMPANY_ID]['stage'] == 'partial'


def test_publication_requires_prepared_named_owner_before_remote(measured_scope, monkeypatch):
    launch, state, jobs, inbox = measured_scope

    def forbidden_remote(**kwargs):
        pytest.fail('the remote factory ran before validating the prepared owner')

    monkeypatch.setattr(cli, 'get_remote_repository', forbidden_remote)
    with pytest.raises((ValueError, RepositoryError), match='prepared marker'):
        launch(sync_only=True, sync_cycle_id=CYCLE_ID, sync_company_ids=[COMPANY_ID],
               publish_ordinary_verification=True)
    with pending.open_verification_stores(state, jobs, inbox, WORKBOOK) as stores:
        assert stores.inbox.get(CYCLE_ID, COMPANY_ID) is None
        assert stores.jobs.scrape_outcomes() == []


def test_publisher_recovers_after_response_loss_without_duplicate_write(measured_scope, monkeypatch):
    launch, state, jobs, inbox = measured_scope
    monkeypatch.setattr(ats, 'fetch_inventory', lambda *args: mismatch())

    class UncertainOnFirstCommit(RecordingRemote):
        def commit(self, operations):
            accepted = super().commit(operations)
            if len(self.commits) == 1:
                raise UncertainWriteError('fixture: write succeeded but the response was lost')
            return accepted

    remote = UncertainOnFirstCommit([COMPANY], schemas=COMPACT_SCHEMAS)
    remote.spreadsheet_id = WORKBOOK
    monkeypatch.setattr(cli, 'get_remote_repository', lambda **kwargs: remote)
    assert launch(resume=True, resume_cycle_id=CYCLE_ID, capture_ordinary_verification=True,
                  fetch_workers=1, browser_fallback=False) == 0
    options = dict(sync_only=True, sync_cycle_id=CYCLE_ID, sync_company_ids=[COMPANY_ID],
                   publish_ordinary_verification=True)
    assert launch(**options) == 1
    assert len(remote.commits) == 1
    assert launch(**options) == 0
    assert len(remote.commits) == 1

    writable = SQLiteRepository(jobs, WORKBOOK)
    try:
        writable.import_rows('Companies', [(2, {**COMPANY, 'Claimed By': 'fixture-after-publish'})])
    finally:
        writable.close()
    with pending.open_verification_stores(state, jobs, inbox, WORKBOOK) as stores:
        from job_search_helper.ordinary_verification_publication import read_publication_proof
        assert read_publication_proof(stores, CYCLE_ID, COMPANY_ID) is not None
        with pytest.raises(RepositoryError, match='has a foreign claim'):
            verification_input_after_publication(stores, CYCLE_ID, COMPANY_ID)


def test_terminal_checkpoint_recovers_existing_jobs_write_without_another_write(measured_scope, monkeypatch):
    from job_search_helper.ordinary_verification_terminal import (
        checkpoint_existing_outcome, read_terminal_checkpoint,
    )

    launch, state, jobs, inbox = measured_scope
    monkeypatch.setattr(ats, 'fetch_inventory', lambda *args: mismatch())
    remote = RecordingRemote([COMPANY], schemas=COMPACT_SCHEMAS)
    remote.spreadsheet_id = WORKBOOK
    monkeypatch.setattr(cli, 'get_remote_repository', lambda **kwargs: remote)
    assert launch(resume=True, resume_cycle_id=CYCLE_ID, capture_ordinary_verification=True,
                  fetch_workers=1, browser_fallback=False) == 0
    assert launch(sync_only=True, sync_cycle_id=CYCLE_ID, sync_company_ids=[COMPANY_ID],
                  publish_ordinary_verification=True) == 0
    with cli.writer_lock(state.parent / 'writer.lock'), pending.open_verification_stores(
        state, jobs, inbox, WORKBOOK, writable_jobs=True,
    ) as stores:
        assert read_terminal_checkpoint(stores, CYCLE_ID, COMPANY_ID) is None
        with pytest.raises(RepositoryError, match='outcome is not durable'):
            checkpoint_existing_outcome(stores, CYCLE_ID, COMPANY_ID)
        owner = pending.read_marker(stores.state.cycle(CYCLE_ID), COMPANY_ID)['owner']
        created = stores.jobs.record_scrape_outcome({
            'cycle_id': CYCLE_ID, 'request_id': owner['request_id'],
            'company_id': COMPANY_ID, 'source_revision': owner['source_revision'],
            'source_current': True, 'company_status': 'Active',
            'inventory_status': 'partial', 'storage_status': 'confirmed',
            'failure': {'category': 'unknown'},
        })
        assert read_terminal_checkpoint(stores, CYCLE_ID, COMPANY_ID) is None
        checkpoint = checkpoint_existing_outcome(stores, CYCLE_ID, COMPANY_ID)
        assert checkpoint['outcome_id'] == created['outcome_id']
        assert checkpoint['outcome_payload_sha256'] == pending.digest(created['outcome'])
        assert checkpoint_existing_outcome(stores, CYCLE_ID, COMPANY_ID) == checkpoint
        assert len(stores.jobs.scrape_outcomes()) == len(remote.commits) == 1
        stores.jobs.db.execute('DELETE FROM scrape_outcomes WHERE outcome_id=?', (created['outcome_id'],))
        stores.jobs.db.commit()
        with pytest.raises(RepositoryError, match='terminal evidence changed'):
            read_terminal_checkpoint(stores, CYCLE_ID, COMPANY_ID)
