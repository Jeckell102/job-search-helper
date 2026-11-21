from contextlib import closing

import pytest

from job_search_helper import cli, runner, scrape_first_pass
from job_search_helper.company_events import BRIDGE_CONSUMER, CompanyEventBridge, read_verified_queued_event
from job_search_helper.engine import State
from job_search_helper.sqlite_repository import SQLiteRepository


def test_public_start_holds_real_local_company_event_before_and_after_bridge(tmp_path, monkeypatch, capsys):
    database = tmp_path / 'state.db'
    jobs = tmp_path / 'jobs.sqlite3'
    workbook = 'private-fixture-workbook'
    monkeypatch.setattr(runner, '_load_environment', lambda: None)
    monkeypatch.setattr(runner, 'state_path', lambda: database)
    monkeypatch.setattr(cli, 'job_database_path', lambda: jobs)
    monkeypatch.setattr(cli, 'storage_backend', lambda: 'sqlite')
    monkeypatch.setattr(cli, 'get_repository', lambda **kwargs: SQLiteRepository(jobs, workbook, readonly=True))
    monkeypatch.setattr(cli, 'get_remote_repository', lambda **kwargs: pytest.fail('opened workbook'))
    monkeypatch.setattr(scrape_first_pass, 'main', lambda *args: pytest.fail('entered broad scrape pipeline'))

    with closing(State(database)), closing(SQLiteRepository(jobs, workbook, initialize=True)) as repo:
        repo.set_meta('ready', 'yes')
        inserted = repo.import_companies_with_events([(2, {
            'Company': 'Private Fixture', 'Company ID': 'COMP-FIXTURE-NEW', 'Company Status': 'Active',
            'Official Careers URL': 'https://boards.greenhouse.io/private-fixture', 'ATS / Source': 'Greenhouse',
        })], origin='private-application-fixture')
        [event] = inserted['company_events']
        assert inserted['imported'] == 1
        assert event['kind'] == 'company.eligible'
        queue = tmp_path / 'next-scan.json'

        assert runner.main(['start']) == 1
        assert 'waiting for a bridged request' in capsys.readouterr().err
        assert not queue.exists()
        assert repo.pending_latest_company_events(BRIDGE_CONSUMER) == [event]

        [outcome] = CompanyEventBridge(repo, tmp_path).process_pending(limit=1)
        assert outcome['state'] == 'REQUEST_WRITTEN'
        raw, request = read_verified_queued_event(repo, tmp_path)
        assert request['company_ids'] == ['COMP-FIXTURE-NEW']
        assert request['company_event']['event_id'] == event['event_id']
        assert repo.pending_latest_company_events(BRIDGE_CONSUMER) == []

        assert runner.main(['start']) == 1
        assert 'waiting in the queue' in capsys.readouterr().err
        assert queue.read_bytes() == raw
        with closing(State(database, readonly=True)) as state:
            assert list(state.cycles()) == []
