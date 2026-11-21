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
def measured_scope(local_worker, monkeypatch, tmp_path, request):
    import release_admission_bootstrap

    initial, _, _ = local_worker
    directory = tmp_path / 'named-ordinary'
    directory.mkdir(mode=0o700)
    state, jobs, inbox = [directory / name for name in ('state.db', 'jobs.sqlite3', 'inventories.sqlite3')]
    for key, value in {'JOB_STORAGE_BACKEND': 'sqlite', 'STATE_DB_FILE': state,
                       'JOB_DB_FILE': jobs, 'SPREADSHEET_ID': WORKBOOK}.items():
        monkeypatch.setenv(key, str(value))
    capture_root = None
    if getattr(request, 'param', False):
        capture_root = tmp_path / 'private-capture'
        capture_root.mkdir(mode=0o700)
        monkeypatch.setenv('JOB_SEARCH_ORDINARY_CAPTURE_ROOT', str(capture_root))
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
        if capture_root is not None and kwargs.get('capture_ordinary_verification'):
            descriptor = release_admission_bootstrap._ordinary_capture_root_descriptor(
                runner.PROJECT_ROOT, state, ['start', '--capture-ordinary-verification'])
            monkeypatch.setenv('JSH_ORDINARY_RAW_CAPTURE_FD', str(descriptor))
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
        facts = {
            'cycle_id': CYCLE_ID, 'request_id': owner['request_id'],
            'company_id': COMPANY_ID, 'source_revision': owner['source_revision'],
            'source_current': True, 'company_status': 'Active',
            'inventory_status': 'partial', 'storage_status': 'confirmed',
            'failure': {'category': 'unknown'},
        }
        with pytest.raises(RepositoryError, match='require their exact verification finisher'):
            stores.jobs.record_scrape_outcome(facts)
        with stores.jobs.transaction():
            with pytest.raises(RepositoryError, match='require their exact verification finisher'):
                stores.jobs._record_scrape_outcome_in_transaction(facts)
        # Seed an already committed result to exercise recovery after the future
        # owned finisher commits Jobs and before it checkpoints State.
        fixture = SQLiteRepository(jobs.with_name('historical-fixture.sqlite3'), WORKBOOK, initialize=True)
        try:
            created = fixture.record_scrape_outcome(facts)
            outcome_row = fixture.db.execute(
                'SELECT outcome_id,request_id,company_id,source_revision,outcome,action,payload,recorded_at '
                'FROM scrape_outcomes').fetchone()
            with stores.jobs.transaction():
                stores.jobs.db.execute('INSERT INTO scrape_outcomes VALUES (?,?,?,?,?,?,?,?)', outcome_row)
        finally:
            fixture.close()
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


@pytest.mark.parametrize('measured_scope,cut_after_capture', [(True, False), (True, True)],
                         indirect=['measured_scope'])
def test_exact_direct_response_private_capture_and_restart(
    measured_scope, monkeypatch, tmp_path, cut_after_capture,
):
    from contextlib import contextmanager
    import socket

    from job_search_helper import shared_boards
    from job_search_helper.company_sources import REPAIRS
    from job_search_helper.ordinary_raw_capture import open_custody
    from job_search_helper.ordinary_verification_publisher import read_captured_ordinary_response
    from test_ordinary_verification_pending import CONFIGURED
    from test_s5_typed_rippling_mismatch import html, page_state

    launch, state, jobs, inbox = measured_scope
    response_body = html(page_state('different-tenant', total=1))
    remote = RecordingRemote([COMPANY], schemas=COMPACT_SCHEMAS)
    remote.spreadsheet_id = WORKBOOK
    direct_requests = []

    def forbidden(*args, **kwargs):
        pytest.fail('the controlled capture must not use a network socket')

    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket, 'getaddrinfo', forbidden)
    monkeypatch.delenv('SSL_CERT_FILE', raising=False)
    monkeypatch.delenv('SSL_CERT_DIR', raising=False)
    monkeypatch.setitem(REPAIRS, COMPANY_ID, {
        'company': COMPANY['Company'], 'expected_url': COMPANY['Official Careers URL'],
        'ats': 'Rippling', 'url': CONFIGURED, 'evidence': 'synthetic fixture',
    })

    class RawResponse:
        status = 200
        headers = {}
        url = CONFIGURED

        def read(self, limit):
            return response_body[:limit]

    class Opener:
        @contextmanager
        def open(self, request, *, timeout):
            assert request.get_method() == 'GET' and request.full_url == CONFIGURED
            direct_requests.append(request.full_url)
            yield RawResponse()

    def build_opener(*handlers):
        assert any(isinstance(handler, shared_boards.ProxyHandler) and handler.proxies == {}
                   for handler in handlers)
        return Opener()

    monkeypatch.setattr(shared_boards, 'build_opener', build_opener)
    monkeypatch.setattr(cli, 'get_remote_repository', lambda **kwargs: remote)
    capture = dict(resume=True, resume_cycle_id=CYCLE_ID, capture_ordinary_verification=True,
                   fetch_workers=1, browser_fallback=False)
    if cut_after_capture:
        from job_search_helper.ordinary_raw_capture import CaptureError
        from job_search_helper.ordinary_verification_worker import OrdinaryVerificationHandoff

        def cut(*args, **kwargs):
            raise RuntimeError('fixture cut after private capture and before paired State')

        with monkeypatch.context() as interrupted:
            interrupted.setattr(OrdinaryVerificationHandoff, 'save', cut)
            with pytest.raises(RuntimeError, match='fixture cut after private capture'):
                launch(**capture)
        with pytest.raises(CaptureError, match='capture_dispatch_already_reserved'):
            launch(**capture)
        with pending.open_verification_stores(state, jobs, inbox, WORKBOOK) as stores:
            assert stores.inbox.get(CYCLE_ID, COMPANY_ID) is None
            assert pending.read_marker(stores.state.cycle(CYCLE_ID), COMPANY_ID)['state'] == 'ARMED'
        assert direct_requests == [CONFIGURED] and remote.commits == []
        return
    assert launch(**capture) == launch(**capture) == 0
    assert direct_requests == [CONFIGURED]

    root = tmp_path / 'private-capture'
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with open_custody(root, descriptor) as custody:
            with pending.open_verification_stores(state, jobs, inbox, WORKBOOK) as stores:
                stored = read_captured_ordinary_response(stores, CYCLE_ID, COMPANY_ID, custody)
                assert stored.body == response_body
                assert b'__NEXT_DATA__' not in stores.inbox.connection.execute(
                    'SELECT payload FROM inventories WHERE cycle=? AND company=?',
                    (CYCLE_ID, COMPANY_ID)).fetchone()[0].encode()
            assert launch(sync_only=True, sync_cycle_id=CYCLE_ID, sync_company_ids=[COMPANY_ID],
                          publish_ordinary_verification=True) == 0
            with pending.open_verification_stores(state, jobs, inbox, WORKBOOK) as stores:
                assert stores.inbox.get(CYCLE_ID, COMPANY_ID) is None
                assert read_captured_ordinary_response(stores, CYCLE_ID, COMPANY_ID, custody) == stored
    finally:
        os.close(descriptor)
    assert direct_requests == [CONFIGURED] and len(remote.commits) == 1


@pytest.mark.parametrize('typed', [False, True])
def test_published_finisher_records_one_complete_outcome_or_holds_typed_mismatch(
    measured_scope, monkeypatch, typed,
):
    from job_search_helper.ordinary_verification_finisher import finish_published_ordinary

    launch, state, jobs, inbox = measured_scope
    def fetch(*args):
        return mismatch() if typed else ats.Inventory(
            'complete', jobs=[], ats='Rippling', source_url=COMPANY['Official Careers URL'],
            reason='fixture official inventory complete',
        )
    monkeypatch.setattr(ats, 'fetch_inventory', fetch)
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
        runtime = stores.state.cycle(CYCLE_ID)['runtime_binding']
        result = finish_published_ordinary(stores, runtime, CYCLE_ID, COMPANY_ID)
        repeated = finish_published_ordinary(stores, runtime, CYCLE_ID, COMPANY_ID)
        if typed:
            assert result == repeated == {'state': 'VERIFICATION_PENDING'}
            assert stores.jobs.scrape_outcomes() == []
        else:
            assert result['state'] == 'OUTCOME_STORED'
            assert repeated['state'] == 'ALREADY_STORED'
            assert result['terminal'] == repeated['terminal']
            rows = stores.jobs.scrape_outcomes()
            assert len(rows) == 1 and rows[0]['outcome'] == 'COMPLETE'
        assert len(remote.commits) == 1


def test_owned_finish_rechecks_pause_after_publication_and_does_not_open_sheets(measured_scope, monkeypatch, capsys):
    launch, state, jobs, inbox = measured_scope
    monkeypatch.setattr(ats, 'fetch_inventory', lambda *args: mismatch())
    remote = RecordingRemote([COMPANY], schemas=COMPACT_SCHEMAS)
    remote.spreadsheet_id = WORKBOOK
    monkeypatch.setattr(cli, 'get_remote_repository', lambda **kwargs: remote)
    assert launch(resume=True, resume_cycle_id=CYCLE_ID, capture_ordinary_verification=True,
                  fetch_workers=1, browser_fallback=False) == 0
    named = dict(sync_only=True, sync_cycle_id=CYCLE_ID, sync_company_ids=[COMPANY_ID])
    assert launch(**named, publish_ordinary_verification=True) == 0
    with pending.open_verification_stores(state, jobs, inbox, WORKBOOK) as original:
        cycle = original.state.cycle(CYCLE_ID)
        cycle['companies'][COMPANY_ID]['inventory_status'] = 'complete'
        original.state.save_cycle(cycle)
    monkeypatch.setattr(cli, 'get_remote_repository',
                        lambda **kwargs: pytest.fail('outcome finish contacted Sheets'))
    assert launch(**named, finish_ordinary_verification=True) == 1
    assert '"disposition": "VERIFICATION_PENDING"' in capsys.readouterr().out

    writer = SQLiteRepository(jobs, WORKBOOK)
    try:
        writer.import_rows('Companies', [(2, {**COMPANY, 'Company Status': 'Paused'})])
    finally:
        writer.close()
    assert launch(**named, finish_ordinary_verification=True) == 0
    assert '"disposition": "OUTCOME_STORED"' in capsys.readouterr().out
    assert launch(**named, finish_ordinary_verification=True) == 0
    assert '"disposition": "ALREADY_STORED"' in capsys.readouterr().out
    with pending.open_verification_stores(state, jobs, inbox, WORKBOOK) as stores:
        rows = stores.jobs.scrape_outcomes()
        assert len(rows) == 1 and rows[0]['outcome'] == 'STALE_OR_PAUSED'
        assert stores.state.cycle(CYCLE_ID)['companies'][COMPANY_ID]['ordinary_verification_terminal']['outcome_id'] == rows[0]['outcome_id']
