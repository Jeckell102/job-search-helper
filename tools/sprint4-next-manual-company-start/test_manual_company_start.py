from contextlib import closing
import fcntl
import importlib.util
import os
from pathlib import Path
import sys

import pytest

from job_search_helper import ats, cli, scrape_first_pass
from job_search_helper.company_events import CompanyEventBridge, _json_digest, read_verified_queued_event
from job_search_helper.engine import State
from job_search_helper.inbox import InventoryInbox
from job_search_helper.repository import GoogleRepository
from job_search_helper.sheet_profile import COMPACT_PROFILE, COMPACT_SCHEMAS
from job_search_helper.sqlite_repository import SQLiteRepository
from sheets_fixture import RangeSheets


ROOT = Path(__file__).parent
RUNTIME = {'state': 'NO_RELEASE', 'source_manifest_sha256': 'a' * 64,
           'config_sha256': 'b' * 64, 'dependency_manifest_sha256': 'c' * 64}


def load_module(monkeypatch, name, path):
    specification = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(specification)
    monkeypatch.setitem(sys.modules, name, module)
    specification.loader.exec_module(module)
    return module


@pytest.fixture
def manual(tmp_path, monkeypatch):
    bootstrap = load_module(monkeypatch, 'release_admission_bootstrap', ROOT / 'release_admission_bootstrap.py')
    package = ROOT / 'src' / 'job_search_helper'
    load_module(monkeypatch, 'job_search_helper.manual_company_start', package / 'manual_company_start.py')
    runner = load_module(monkeypatch, 'job_search_helper.manual_candidate_runner', package / 'runner.py')
    root = tmp_path / '.state'
    root.mkdir()
    database, jobs = root / 'state.db', root / 'jobs.sqlite3'
    workbook = 'private-manual-start-workbook'
    monkeypatch.setenv('SPREADSHEET_ID', workbook)
    monkeypatch.setenv('JOB_STORAGE_BACKEND', 'sqlite')
    monkeypatch.setenv('JOB_DB_FILE', str(jobs))
    monkeypatch.setenv('STATE_DB_FILE', str(database))
    monkeypatch.setattr(runner, 'PROJECT_ROOT', tmp_path)
    monkeypatch.setattr(runner, 'state_path', lambda: database)
    monkeypatch.setattr(runner, '_load_environment', lambda: None)
    monkeypatch.setattr(cli, 'get_repository', lambda **kwargs: SQLiteRepository(jobs, workbook, readonly=True))
    monkeypatch.setattr(cli, 'get_remote_repository', lambda **kwargs: pytest.fail('opened a workbook'))
    monkeypatch.setattr(bootstrap, '_validate_runtime', lambda *args: RUNTIME)
    with closing(State(database)), closing(InventoryInbox(root / 'inventories.sqlite3', workbook)):
        pass
    with closing(SQLiteRepository(jobs, workbook, initialize=True)) as repository:
        repository.set_meta('ready', 'yes')
        repository.set_meta('sheets_profile', COMPACT_PROFILE)

        def launch():
            returned = []

            def worker(_exe, _argv, environment):
                original = int(environment['JSH_SCRAPER_ADMISSION_FD'])
                duplicated = os.dup(original)
                try:
                    monkeypatch.setenv('JSH_SCRAPER_ADMISSION_FD', str(duplicated))
                    returned.append(runner.main(['start']))
                finally:
                    if os.environ.get('JSH_SCRAPER_ADMISSION_FD') == str(duplicated):
                        os.close(duplicated)
                        monkeypatch.delenv('JSH_SCRAPER_ADMISSION_FD')

            monkeypatch.setattr(bootstrap.os, 'execve', worker)
            bootstrap.admit_and_exec(tmp_path, ['start'])
            [result] = returned
            return result

        yield root, repository, launch


def add_company(repository, number):
    company = 'COMP-MANUAL-' + str(number)
    result = repository.import_companies_with_events([(number + 2, {'Company': company, 'Company ID': company,
        'Company Status': 'Active', 'Official Careers URL': 'https://boards.greenhouse.io/manual-fixture',
        'ATS / Source': 'Greenhouse'})], origin='manual-start-fixture')
    [event] = result['company_events']
    return event


@pytest.mark.parametrize('bridged', (False, True))
def test_manual_start_uses_exact_existing_actions_under_inherited_admission(manual, monkeypatch, bridged):
    root, repository, launch = manual
    event = add_company(repository, 1)
    if bridged:
        assert CompanyEventBridge(repository, root).process_pending()[0]['state'] == 'REQUEST_WRITTEN'
    monkeypatch.setattr(scrape_first_pass, 'main', lambda *args: pytest.fail('used broad workflow'))
    calls = []

    def execute(action, admission, *, request_sha256, cycle_id=None):
        assert admission == (root / 'state.db', root / 'jobs.sqlite3', RUNTIME)
        with (root / 'scraper.lock').open('rb') as competing:
            with pytest.raises(BlockingIOError):
                fcntl.flock(competing, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with cli.writer_lock(root / 'writer.lock'):
            _, request = read_verified_queued_event(repository, root)
        assert request['company_event']['event_id'] == event['event_id']
        assert request['company_ids'] == [event['company_id']]
        assert request_sha256 == _json_digest(request)
        calls.append((action, cycle_id))
        return {'state': 'INVENTORY_FROZEN' if action == 'admit-fetch' else 'SYNC_CONFIRMED',
                'cycle_id': 'CYC-123456ABCDEF'}

    monkeypatch.setattr(sys.modules['job_search_helper.manual_company_start'], 'execute_ordinary_event', execute)
    assert launch() == 0
    assert calls == [('admit-fetch', None), ('publish', 'CYC-123456ABCDEF')]


def test_manual_start_holds_two_pending_events_without_creating_a_request(manual, monkeypatch):
    root, repository, launch = manual
    add_company(repository, 1)
    add_company(repository, 2)
    monkeypatch.setattr(scrape_first_pass, 'main', lambda *args: pytest.fail('used broad workflow'))
    monkeypatch.setattr(sys.modules['job_search_helper.manual_company_start'], 'execute_ordinary_event',
                        lambda *args, **kwargs: pytest.fail('executed an ambiguous event'))
    assert launch() == 1
    assert not (root / 'next-scan.json').exists()


def test_manual_start_holds_backend_drift_before_repository_factory(manual, monkeypatch, capsys):
    root, repository, launch = manual
    add_company(repository, 1)
    monkeypatch.setattr(cli, 'storage_backend', lambda: 'sheets')
    monkeypatch.setattr(cli, 'get_repository', lambda **kwargs: pytest.fail('used backend-switching factory'))
    monkeypatch.setattr(scrape_first_pass, 'main', lambda *args: pytest.fail('entered broad scan'))
    assert launch() == 1
    assert 'admitted local SQLite layout' in capsys.readouterr().err
    assert not (root / 'next-scan.json').exists()


def test_bare_start_without_pending_event_preserves_existing_workflow(manual, monkeypatch):
    _, _, launch = manual

    def broad(argv):
        assert argv == ['run', '--scraper-args']
        assert os.environ.get('JSH_SCRAPER_ADMISSION_FD')
        assert 'JSH_RETAINED_OPERATOR_SQLITE_LAYOUT' not in os.environ
        return 17

    monkeypatch.setattr(scrape_first_pass, 'main', broad)
    assert launch() == 17


def test_manual_start_settles_one_verified_zero_through_existing_ordinary_path(manual, monkeypatch, capsys):
    root, repository, launch = manual
    event = add_company(repository, 1)
    sheet = RangeSheets({'Companies': repository.read('Companies')}, schemas=COMPACT_SCHEMAS)
    remote = GoogleRepository(sheet, repository.spreadsheet_id, schemas=COMPACT_SCHEMAS, min_request_interval=0)
    fetches = []

    def provider(ats_name, board, company_id, name):
        fetches.append(company_id)
        assert ats_name == 'Greenhouse' and company_id == event['company_id']
        assert board == 'https://boards.greenhouse.io/manual-fixture'
        return ats.Inventory('complete', source_url='https://boards-api.greenhouse.io/v1/boards/manual-fixture/jobs',
                             ats='Greenhouse', verified_zero='greenhouse_explicit_total_zero')

    def workbook(*, write, **kwargs):
        assert write is False
        return remote

    monkeypatch.setattr(ats, 'fetch_inventory', provider)
    monkeypatch.setattr(cli, 'get_remote_repository', workbook)
    monkeypatch.setattr(scrape_first_pass, 'main', lambda *args: pytest.fail('entered broad scan'))
    assert launch() == 0
    assert 'VERIFIED_ZERO' in capsys.readouterr().out
    assert fetches == [event['company_id']]
    assert sheet.batches == []
    assert not (root / 'next-scan.json').exists()
    [outcome] = repository.scrape_outcomes(company_id=event['company_id'])
    assert outcome['outcome'] == 'COMPLETE' and outcome['action'] == 'save_without_repair'
