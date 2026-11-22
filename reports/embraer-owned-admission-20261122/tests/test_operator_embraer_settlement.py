"""Exercise the one-company operator request through a typed normal fetch."""

from contextlib import closing
import json
import shutil
import sqlite3
import subprocess
import sys
from unittest.mock import Mock

from job_search_helper import ats
from job_search_helper.cli import PROJECT_ROOT, writer_lock
from job_search_helper.engine import State
from job_search_helper.inbox import InventoryInbox
from job_search_helper.integration_release import source_tree_digest
from job_search_helper.operator_company_request import _digest, queue_operator_company_request
from job_search_helper.operator_embraer_settlement import execute_operator_embraer, read_operator_embraer_source
from job_search_helper.operator_partial_scope import EMBRAER
from job_search_helper.repository import GoogleRepository
from job_search_helper.sheet_profile import COMPACT_PROFILE, COMPACT_SCHEMAS
from job_search_helper.sqlite_repository import SQLiteRepository
from sheets_fixture import RangeSheets
from test_embraer_typed_defect import Transport, _body, _entry


def test_operator_embraer_settlement_keeps_publication_held_and_reopens_owner(tmp_path, monkeypatch):
    state_path, jobs = tmp_path / 'state.db', tmp_path / 'jobs.sqlite3'
    inbox_path = tmp_path / 'inventories.sqlite3'
    company = {
        'Company ID': EMBRAER.company_id, 'Company': EMBRAER.company_name, 'Company Status': 'Active',
        'Official Careers URL': EMBRAER.careers_url, 'ATS / Source': EMBRAER.provider,
    }
    unrelated = {**company, 'Company ID': 'COMP-0666', 'Company': 'Other'}
    monkeypatch.setenv('SPREADSHEET_ID', 'sheet')
    with (closing(State(str(state_path))), closing(InventoryInbox(inbox_path, 'sheet')),
          closing(SQLiteRepository(jobs, 'sheet', initialize=True)) as repository):
        repository.set_meta('ready', 'yes')
        repository.set_meta('sheets_profile', COMPACT_PROFILE)
        repository.ensure_columns('Opportunities', ['Opportunity ID'])
        repository.import_rows('Companies', [(2, company), (3, unrelated)])
        queue_operator_company_request(repository, tmp_path, EMBRAER.company_id, 'operator-embraer-fixture')
        other_before = repository.matches('Companies', {'Company ID': unrelated['Company ID']})
    queued = tmp_path / 'next-scan.json'
    digest = _digest(json.loads(queued.read_text()))
    runtime = {
        'state': 'NO_RELEASE', 'source_manifest_sha256': source_tree_digest(PROJECT_ROOT),
        'config_sha256': 'b' * 64, 'dependency_manifest_sha256': 'c' * 64,
    }

    good, bad = _entry('111111111111', 'Good role'), _entry('222222222222', 'Affected role')
    transport = Transport(json.dumps([good, bad]).encode(), {
        good['url']: _body(good['url'], good['name']),
        bad['url']: _body(bad['url'], bad['name'], brand=True),
    })
    employer_page = Mock()
    employer_page.get.return_value = ats.HTTPResponse(
        200, f'<a href="{EMBRAER.board_url}">US open positions</a>'.encode(),
    )

    def fetch(provider, url, company_id, company_name):
        return ats.fetch_inventory(provider, url, company_id, company_name, transport,
                                   discovery_transport=employer_page)

    sheets = RangeSheets({'Companies': [company]}, schemas=COMPACT_SCHEMAS)
    remote_reader = Mock(return_value=GoogleRepository(sheets, 'sheet', schemas=COMPACT_SCHEMAS,
                                                      min_request_interval=0))

    def settle(fetcher, remote):
        with writer_lock(tmp_path / 'scraper.lock'):
            return execute_operator_embraer((state_path, jobs, runtime), request_sha256=digest,
                                            fetcher=fetcher, remote_reader=remote)

    settled = settle(fetch, remote_reader)
    remote_reader.assert_called_once()
    assert transport.listing_reads == 2
    assert settled['state'] == 'FETCH_REPAIR_QUALIFIED'
    assert not queued.exists()
    assert sheets.request_bytes == 0

    outcome = settled['outcome']
    assert outcome['repair_category'] == 'full_description_regression'
    assert outcome['identity']['request_id'] == 'operator-embraer-fixture'
    no_replay = Mock(side_effect=AssertionError('settled request must not repeat work'))
    assert settle(no_replay, no_replay) == settled

    with (closing(SQLiteRepository(jobs, 'sheet', readonly=True)) as repository,
          closing(InventoryInbox(inbox_path, 'sheet', readonly=True)) as inbox,
          closing(State(str(state_path), readonly=True)) as state):
        proof = read_operator_embraer_source(repository, outcome, digest)
        assert proof['evidence_code'] == EMBRAER.failure_code
        assert proof['settlement_sha256'] == settled['settlement_sha256']
        assert set(proof['source_files']) == {'src/job_search_helper/shared_boards.py', 'src/job_search_helper/ats.py'}
        assert read_operator_embraer_source(repository, outcome, 'a' * 64) is None
        assert state.cycle(settled['cycle_id'])['companies'][EMBRAER.company_id]['stage'] == 'partial'
        assert repository.scrape_outcomes(company_id=EMBRAER.company_id) == [outcome]
        assert repository.matches('Companies', {'Company ID': unrelated['Company ID']}) == other_before
        assert inbox.connection.execute('SELECT count(*) FROM inventories').fetchone() == (0,)
        assert inbox.connection.execute('SELECT count(*) FROM publication_receipts').fetchone() == (0,)


    monkeypatch.syspath_prepend(str(PROJECT_ROOT / 'dev/wrapper-coder/tools'))
    monkeypatch.setenv('JOB_STORAGE_BACKEND', 'sqlite')
    monkeypatch.setenv('STATE_DB_FILE', str(state_path))
    monkeypatch.setenv('JOB_DB_FILE', str(jobs))
    import coding_tools
    from coordinator import Coordinator
    from coordinator_baseline import binding, files
    from embraer_operator_pilot import EmbraerOperatorEnrollment

    wrapper_base = tmp_path / 'wrapper'
    monkeypatch.setattr(coding_tools, 'BASE', wrapper_base)
    monkeypatch.setattr(coding_tools, 'ROOT', wrapper_base / 'repo')
    assignment = files(PROJECT_ROOT)
    baseline_digest = binding(assignment)['digest']
    baseline = wrapper_base / 'pilot-bases' / ('embraer-' + baseline_digest)
    for name in assignment:
        target = baseline / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PROJECT_ROOT / name, target)
    source_files = proof['source_files']
    enrollment = EmbraerOperatorEnrollment(
        outcome['identity']['request_id'], proof['source_revision'], digest,
        source_files['src/job_search_helper/shared_boards.py'], source_files['src/job_search_helper/ats.py'],
        baseline_digest,
    )
    coordinator = Coordinator(
        tmp_path / 'receiver', model=no_replay, repair_profile_selector=enrollment.profile,
        company_revision_resolver=lambda cid: proof['source_revision'] if cid == EMBRAER.company_id else None,
    )
    coordinator.store.set_queue_enabled(False)
    result = enrollment.catch_up(coordinator)
    assert result['state'] == 'EMBRAER_PILOT_QUEUED', result
    assert coordinator.store.pilot_task() == result['task_id']
    task = coordinator.store.get(result['task_id'])
    assert task['status'] == 'QUEUED' and task['mode'] == 'develop' and task['isolated_workspace']
    assert task['repair_provenance']['outcome_id'] == outcome['outcome_id']
    assert enrollment.catch_up(coordinator)['state'] == 'EMBRAER_PILOT_ALREADY_PREPARED'
    assert len(coordinator.store.all()) == 1
    assert not coordinator.store.queue_enabled()
    assert not coordinator.store.campaign_enabled()
    assert not coordinator.store.autopilot_enabled()
    no_replay.assert_not_called()



def test_shell_admits_exact_embraer_command_through_bootstrap(tmp_path):
    package = tmp_path / 'src/job_search_helper'
    package.mkdir(parents=True)
    (package / '__init__.py').touch()
    (package / 'runner.py').write_text(
        "import fcntl, json, os, sys\n"
        "assert sys.argv[1:] == ['operator-embraer-partial', '--request-sha256', 'a' * 64]\n"
        "fd = int(os.environ['JSH_SCRAPER_ADMISSION_FD'])\n"
        "path = os.environ['JSH_SCRAPER_ADMISSION_PATH']\n"
        "assert os.path.samestat(os.fstat(fd), os.stat(path))\n"
        "with open(path, 'rb') as competitor:\n"
        "    try:\n"
        "        fcntl.flock(competitor, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
        "    except BlockingIOError:\n"
        "        pass\n"
        "    else:\n"
        "        raise AssertionError('the bootstrap did not hold the scraper lease')\n"
        "layout = json.loads(os.environ['JSH_RETAINED_OPERATOR_SQLITE_LAYOUT'])\n"
        "assert layout['state']['path'].endswith('/state.db')\n"
        "assert layout['jobs']['path'].endswith('/jobs.sqlite3')\n"
    )
    state = tmp_path / '.state'
    state.mkdir()
    for name in ('state.db', 'jobs.sqlite3'):
        with closing(sqlite3.connect(state / name)) as store:
            store.execute('CREATE TABLE fixture (id INTEGER)')
    (tmp_path / '.storage-backend').write_text('sqlite\n')
    for name in ('job-search-scraper', 'release_admission_bootstrap.py', 'pyproject.toml'):
        shutil.copy2(PROJECT_ROOT / name, tmp_path / name)
    result = subprocess.run(
        [str(tmp_path / 'job-search-scraper'), 'operator-embraer-partial', '--request-sha256', 'a' * 64],
        cwd=tmp_path, env={'PYTHON': sys.executable, 'PATH': '/usr/bin:/bin'},
        capture_output=True, text=True, timeout=8,
    )
    assert result.returncode == 0, result.stderr
