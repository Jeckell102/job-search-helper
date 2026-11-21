"""Only a typed public partial may advance the exact selected operator request."""

from contextlib import closing, contextmanager, nullcontext
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from job_search_helper import ats, cli, runner
from job_search_helper.acquiretm import SOURCE
from job_search_helper.cli import writer_lock
from job_search_helper.engine import State
from job_search_helper.inbox import InventoryInbox
from job_search_helper.operator_amphenol_fetch import observe_operator_amphenol_partial
from job_search_helper.operator_company_request import _digest, queue_operator_company_request
from job_search_helper.sheet_profile import COMPACT_PROFILE
from job_search_helper.sqlite_repository import SQLiteRepository
from test_acquiretm import UpdatePanelPage
from test_ordinary_company_event_fetch import RUNTIME, workbook_reader


@pytest.mark.parametrize('partial', [True, False])
def test_selected_observation_preserves_request_before_admission(tmp_path, monkeypatch, capsys, partial):
    state_path, jobs = tmp_path / 'state.db', tmp_path / 'jobs.sqlite3'
    company = {'Company ID': 'COMP-0490', 'Company': 'Amphenol Aerospace', 'Company Status': 'Active',
               'ATS / Source': 'AcquireTM', 'Official Careers URL': SOURCE}
    with (closing(State(str(state_path))), closing(InventoryInbox(tmp_path / 'inventories.sqlite3', 'sheet')),
          closing(SQLiteRepository(jobs, 'sheet', initialize=True)) as repo):
        repo.set_meta('ready', 'yes')
        repo.set_meta('sheets_profile', COMPACT_PROFILE)
        repo.ensure_columns('Opportunities', ['Opportunity ID'])
        repo.import_rows('Companies', [(2, company)])
        queue_operator_company_request(repo, tmp_path, 'COMP-0490', 'operator-amphenol-fixture')
    request_path = tmp_path / 'next-scan.json'
    saved_request = request_path.read_bytes()
    digest = _digest(json.loads(saved_request))

    page = UpdatePanelPage('delayed')
    details = Mock(side_effect=AssertionError('Typed partial must not fetch the detail pages'))
    browser = SimpleNamespace(new_context=lambda: SimpleNamespace(new_page=lambda: page, request=details),
                              close=lambda: None)
    playwright = SimpleNamespace(chromium=SimpleNamespace(launch=lambda **kwargs: browser))
    monkeypatch.setitem(sys.modules, 'playwright.sync_api',
                        SimpleNamespace(sync_playwright=lambda: nullcontext(playwright)))
    monkeypatch.setattr('job_search_helper.acquiretm.time.monotonic_ns', lambda: page.clock_ns)
    complete = ats.Inventory('complete', source_url=SOURCE, ats='AcquireTM')
    provider = Mock(side_effect=ats.fetch_inventory) if partial else Mock(return_value=complete)
    remote = workbook_reader(company, SOURCE)

    def observe(fetcher, remote_reader):
        with (writer_lock(tmp_path / 'scraper.lock'), writer_lock(tmp_path / 'writer.lock'),
              closing(SQLiteRepository(jobs, 'sheet', readonly=True)) as reader,
              closing(State(str(state_path), readonly=True)) as state):
            result = observe_operator_amphenol_partial(reader, state, RUNTIME, request_sha256=digest,
                                                       fetcher=fetcher, remote_reader=remote_reader)
            assert state.cycles() == []
            assert reader.scrape_outcomes(company_id='COMP-0490') == []
            assert request_path.read_bytes() == saved_request
            return result

    result = observe(provider, remote)
    assert result['state'] == ('QUALIFIED_PARTIAL_FROZEN' if partial else 'HELD_NO_QUALIFIED_PARTIAL')
    provider.assert_called_once_with('AcquireTM', SOURCE, 'COMP-0490', 'Amphenol Aerospace')
    assert observe(Mock(side_effect=AssertionError('rerun fetched')), Mock(side_effect=AssertionError('rerun read'))) == result
    if not partial:
        return

    @contextmanager
    def admission():
        with writer_lock(tmp_path / 'scraper.lock'):
            yield state_path, jobs, RUNTIME

    monkeypatch.setenv('SPREADSHEET_ID', 'sheet')
    monkeypatch.setattr(runner, '_retained_operator_admission', admission)
    monkeypatch.setattr(ats, 'fetch_inventory', Mock(side_effect=AssertionError('scoped replay fetched')))
    monkeypatch.setattr(cli, 'get_remote_repository', Mock(side_effect=AssertionError('scoped replay opened Sheets')))
    command = ['operator-amphenol-partial', '--request-sha256', digest]
    replace = Path.replace
    save_cycle = State.save_cycle

    def cut_acknowledgement(path, destination):
        if path == request_path:
            raise OSError('cut before queue acknowledgement')
        return replace(path, destination)

    with monkeypatch.context() as interrupted:
        interrupted.setattr(Path, 'replace', cut_acknowledgement)
        assert runner.scrape_main(command) == 1
        assert 'cut before queue acknowledgement' in capsys.readouterr().err
    assert request_path.read_bytes() == saved_request
    with closing(SQLiteRepository(jobs, 'sheet', readonly=True)) as repo:
        assert repo.scrape_outcomes(company_id='COMP-0490') == []

    def cut_terminal(state, cycle):
        if 'operator_amphenol_observation_sha256' in cycle:
            raise RuntimeError('cut before State save')
        return save_cycle(state, cycle)

    with monkeypatch.context() as interrupted:
        interrupted.setattr(State, 'save_cycle', cut_terminal)
        assert runner.scrape_main(command) == 1
        assert 'cut before State save' in capsys.readouterr().err
    assert not request_path.exists()

    with closing(SQLiteRepository(jobs, 'sheet', readonly=True)) as repo:
        assert repo.scrape_outcomes(company_id='COMP-0490') == []

    def settled_from_command():
        assert runner.scrape_main(command) == 0
        return json.loads(capsys.readouterr().out.removeprefix('Operator Amphenol partial: '))

    settled = settled_from_command()
    assert settled_from_command() == settled
    with (closing(SQLiteRepository(jobs, 'sheet', readonly=True)) as repo,
          closing(State(str(state_path), readonly=True)) as state):
        assert settled['state'] == 'FETCH_REPAIR_QUALIFIED'
        assert settled['outcome']['identity']['request_id'] == 'operator-amphenol-fixture'
        assert 'company_event_id' not in settled['outcome']['identity']
        assert state.cycle(settled['cycle_id'])['companies']['COMP-0490']['stage'] == 'partial'
        assert repo.scrape_outcomes(company_id='COMP-0490') == [settled['outcome']]
        assert repo.db.execute('SELECT count(*) FROM company_event_outbox').fetchone() == (0,)

    with closing(SQLiteRepository(jobs, 'sheet')) as repo:
        repo.db.execute('UPDATE scrape_outcomes SET recorded_at=?', ('different timestamp',))
    assert runner.scrape_main(command) == 1
    assert 'conflicting outcome' in capsys.readouterr().err
    with closing(SQLiteRepository(jobs, 'sheet', readonly=True)) as repo:
        assert repo.db.execute('SELECT recorded_at FROM scrape_outcomes').fetchall() == [('different timestamp',)]
