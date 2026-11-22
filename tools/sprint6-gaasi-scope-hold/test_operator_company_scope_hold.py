"""One fixture for normal admission, the real hold, and ordered progression."""

from contextlib import closing
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

import release_admission_bootstrap as bootstrap
from job_search_helper import ats, cli, operator_company_scope_hold as hold, runner, scrape_first_pass
from job_search_helper.engine import State
from job_search_helper.inbox import InventoryInbox
from job_search_helper.operator_company_request import _digest, queue_operator_company_request
from job_search_helper.sheet_profile import COMPACT_PROFILE
from job_search_helper.sqlite_repository import SQLiteRepository


PROJECT = Path(__file__).resolve().parent
WORKBOOK = 'scope-hold-fixture'
GA = {'Company ID': hold.COMPANY, 'Company': 'General Atomics Aeronautical Systems',
      'Company Status': 'Active', 'ATS / Source': hold.PARENT[0], 'Official Careers URL': hold.PARENT[1]}
FORTERRA = {'Company ID': 'COMP-0066', 'Company': 'Forterra', 'Company Status': 'Active',
            'ATS / Source': 'Rippling', 'Official Careers URL': 'https://www.forterra.com/careers'}
JOB = {'Job Key': 'comp-9999:manual:preserve', 'Company': 'Unrelated fixture',
       'Job Title': 'Preserved role', 'Official Job URL': 'https://example.test/preserve',
       'Requisition ID': 'preserve', 'Job Status': 'Open and verified', 'Salary / Range': 'Estimated $120000-$150000'}


def test_real_scope_hold_is_local_and_survives_archival_interruption(tmp_path, monkeypatch, capsys):
    database, jobs = tmp_path / 'state.db', tmp_path / 'jobs.sqlite3'
    queue = tmp_path / 'next-scan.json'
    monkeypatch.setenv('JOB_STORAGE_BACKEND', 'sqlite')
    monkeypatch.setenv('STATE_DB_FILE', str(database))
    monkeypatch.setenv('JOB_DB_FILE', str(jobs))
    monkeypatch.setenv('SPREADSHEET_ID', WORKBOOK)
    monkeypatch.setenv('PYTHON', sys.executable)
    checkpoint = {'id': 'CYC-123456ABCDEF', 'status': 'Complete', 'companies': {}}
    with closing(State(str(database))) as state:
        state.save_cycle(checkpoint)
    inbox = tmp_path / 'inventories.sqlite3'
    with closing(InventoryInbox(inbox, WORKBOOK)):
        pass

    def forbidden(*args, **kwargs):
        pytest.fail('Entered broad scan, provider, Google or cycle creation from a scope hold.')

    monkeypatch.setattr(cli, 'get_remote_repository', forbidden)
    monkeypatch.setattr(ats, 'fetch_inventory', forbidden)
    monkeypatch.setattr(scrape_first_pass, 'main', forbidden)
    monkeypatch.setattr(State, 'save_cycle', forbidden)
    monkeypatch.setattr(runner, 'get_repository', forbidden)

    def launch(*arguments):
        result = []

        def exec_worker(_command, _argv, environment):
            descriptor = os.dup(int(environment['JSH_SCRAPER_ADMISSION_FD']))
            environment['JSH_SCRAPER_ADMISSION_FD'] = str(descriptor)
            try:
                result.append(runner.main(arguments))
            finally:
                try:
                    os.close(descriptor)
                except OSError:
                    pass

        with monkeypatch.context() as bootstrap_patch:
            for name in ('JSH_SCRAPER_ADMISSION_FD', 'JSH_SCRAPER_ADMISSION_PATH',
                         'JSH_SCRAPER_RUNTIME_BINDING', 'JSH_RETAINED_OPERATOR_SQLITE_LAYOUT'):
                bootstrap_patch.delenv(name, raising=False)
            bootstrap_patch.setattr(bootstrap.os, 'execve', exec_worker)
            bootstrap.admit_and_exec(PROJECT, arguments)
        return result[0]

    with closing(SQLiteRepository(jobs, WORKBOOK, initialize=True)) as local:
        local.set_meta('ready', 'yes')
        local.set_meta('sheets_profile', COMPACT_PROFILE)
        local.import_rows('Companies', [(2, GA), (3, FORTERRA)])
        local.import_rows('Job History', [(2, JOB)])
        keep_job = local.read_row('Job History', 2)
        request_id = hold.PREFIX + 'gaasi-fixture'
        assert runner.scrape_main(['queue-company', '--company-id', FORTERRA['Company ID'],
                                   '--request-id', ' ' + request_id]) == 1
        assert not queue.exists()
        with monkeypatch.context() as sheets:
            sheets.setenv('JOB_STORAGE_BACKEND', 'sheets')
            assert runner.scrape_main(['queue-company', '--company-id', hold.COMPANY,
                                       '--request-id', request_id]) == 1
        assert not queue.exists()
        assert queue_operator_company_request(local, tmp_path, hold.COMPANY, request_id)['state'] == 'REQUEST_WRITTEN'
        raw = queue.read_bytes()
        digest = _digest(json.loads(raw))

        assert launch('start') == 1
        assert 'requires operator-scope-hold' in capsys.readouterr().err
        with monkeypatch.context() as sheets:
            sheets.setenv('JOB_STORAGE_BACKEND', 'sheets')
            assert launch('start') == 1
            assert 'requires operator-scope-hold' in capsys.readouterr().err
        assert launch('operator-scope-hold', '--request-sha256', '0' * 64) == 1
        assert queue.read_bytes() == raw and not local.scrape_outcomes()

        local.import_rows('Companies', [(2, {**GA, 'Official Careers URL': 'https://example.test/changed'})])
        assert launch('operator-scope-hold', '--request-sha256', digest) == 1
        assert 'Current GA-ASI evidence' in capsys.readouterr().err
        assert queue.read_bytes() == raw and not local.scrape_outcomes()
        local.import_rows('Companies', [(2, GA)])

        def interrupted(*_):
            raise OSError('fixture interrupted after commit')

        with monkeypatch.context() as cut:
            cut.setattr(hold, '_archive', interrupted)
            assert launch('operator-scope-hold', '--request-sha256', digest) == 1
        assert 'interrupted after commit' in capsys.readouterr().err
        [outcome] = local.scrape_outcomes()
        assert outcome['outcome'] == 'BLOCKED' and 'cycle_id' not in outcome['identity']
        assert queue.read_bytes() == raw

        archive = tmp_path / 'operator-company-requests' / 'held' / f'{digest}.json'
        archive.parent.mkdir()
        os.link(queue, archive)
        with monkeypatch.context() as drift:
            drift.setenv('EVIDENCE_ARCHIVES_FILE', str(tmp_path / 'different-evidence.json'))
            assert launch('operator-scope-hold', '--request-sha256', digest) == 1
            assert 'Original runtime ownership' in capsys.readouterr().err
        assert queue.read_bytes() == raw and archive.read_bytes() == raw

        command = [str(PROJECT / 'job-search-scraper'), 'operator-scope-hold', '--request-sha256', digest]
        replay = subprocess.run(command, cwd=PROJECT, text=True, capture_output=True, check=True)
        assert json.loads(replay.stdout)['outcome_id'] == outcome['outcome_id']
        assert not queue.exists() and not (tmp_path / 'last-scan-request.json').exists()
        assert archive.read_bytes() == raw
        assert queue_operator_company_request(local, tmp_path, hold.COMPANY, request_id)['state'] == 'REQUEST_PREVIOUSLY_RESERVED'

        assert queue_operator_company_request(local, tmp_path, FORTERRA['Company ID'], 'fixture-forterra')['state'] == 'REQUEST_WRITTEN'
        next_queue = queue.read_bytes()
        repeated = subprocess.run(command, cwd=PROJECT, text=True, capture_output=True, check=True)
        assert repeated.stdout == replay.stdout and queue.read_bytes() == next_queue
        assert local.scrape_outcomes() == [outcome] and local.read_row('Job History', 2) == keep_job
    with closing(State(str(database), readonly=True)) as state:
        assert state.cycles() == [checkpoint]
