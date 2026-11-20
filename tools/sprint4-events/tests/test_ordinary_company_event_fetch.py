"""Normal idle Company events freeze one exact observation without ordinary sync."""
from contextlib import closing
from unittest.mock import Mock

import pytest

from job_search_helper import ats
from job_search_helper.cli import writer_lock
from job_search_helper.company_events import CompanyEventBridge, read_verified_ordinary_event_admission
from job_search_helper.engine import Engine, State
from job_search_helper.inbox import InventoryInbox
from job_search_helper.ordinary_company_event_fetch import (
    DIRECTORY, freeze_ordinary_event_locked, load_ordinary_event_observation,
)
from job_search_helper.retained_work_runner import assert_normal_lifecycle_not_held
from job_search_helper.scan_request import requested_scan
from job_search_helper.repository import GoogleRepository
from job_search_helper.sheet_profile import COMPACT_PROFILE, COMPACT_SCHEMAS
from job_search_helper.sqlite_repository import SQLiteRepository
from sheets_fixture import RangeSheets


RUNTIME = {
    'state': 'NO_RELEASE', 'source_manifest_sha256': 'a' * 64,
    'config_sha256': 'b' * 64, 'dependency_manifest_sha256': 'c' * 64,
}
BOARD = 'https://jobs.eu.lever.co/acme?location=Berlin'
OBSERVED = 'https://api.eu.lever.co/v0/postings/acme?location=Berlin'
COMPANY = {'Company ID': 'COMP-1', 'Company': 'Fixture', 'Company Status': 'Active',
           'ATS / Source': 'Lever', 'Official Careers URL': 'https://jobs.eu.lever.co/acme'}


@pytest.fixture
def ordinary_cycle(tmp_path):
    jobs, state_path = tmp_path / 'jobs.sqlite3', tmp_path / 'state.db'
    with (closing(SQLiteRepository(jobs, 'sheet', initialize=True)) as local,
          closing(State(str(state_path))) as state,
          closing(InventoryInbox(tmp_path / 'inventories.sqlite3', 'sheet'))):
        with local.transaction():
            local.set_meta('ready', 'yes')
            local.set_meta('sheets_profile', COMPACT_PROFILE)
        local.import_rows('Companies', [(2, COMPANY), (3, {**COMPANY, 'Company ID': 'COMP-2', 'Company': 'Other'})])
        event = local.mutate_company_with_event({
            'tab': 'Companies', 'identity': {'Company ID': 'COMP-1'},
            'values': {'Official Careers URL': BOARD},
        })['company_event']
        CompanyEventBridge(local, tmp_path).process_pending()
        with writer_lock(tmp_path / 'scraper.lock'), writer_lock(tmp_path / 'writer.lock'):
            cycle_id = requested_scan(Engine(local, state, runtime_binding=RUNTIME), state, state_path)
        admission = read_verified_ordinary_event_admission(local, state, cycle_id)
        assert admission['request']['company_event']['event_id'] == event['event_id']
    (tmp_path / 'last-scan-request.json').write_text('{}')
    return tmp_path, cycle_id, admission['request_sha256']


def observe(fixture, provider, workbook, *, request_sha256=None):
    root, cycle, digest = fixture
    with (writer_lock(root / 'scraper.lock'), writer_lock(root / 'writer.lock'),
          closing(SQLiteRepository(root / 'jobs.sqlite3', 'sheet', readonly=True)) as local,
          closing(State(str(root / 'state.db'), readonly=True)) as state):
        return freeze_ordinary_event_locked(local, state, RUNTIME, cycle_id=cycle,
                                            request_sha256=request_sha256 or digest,
                                            fetcher=provider, remote_reader=workbook)


def workbook_reader():
    sheets = RangeSheets({'Companies': [{**COMPANY, 'Official Careers URL': BOARD}]}, schemas=COMPACT_SCHEMAS)
    return Mock(return_value=GoogleRepository(sheets, 'sheet', schemas=COMPACT_SCHEMAS, min_request_interval=0))


def test_ordinary_event_freezes_once_with_no_legacy_inventory_or_jobs_changes(ordinary_cycle):
    root, cycle_id, request_sha256 = ordinary_cycle
    provider = Mock(return_value=ats.Inventory('complete', jobs=[{'posting_id': 'p'}],
                                               source_url=OBSERVED, ats='Lever'))
    workbook = workbook_reader()
    data = [root / 'inventories.sqlite3', root / 'jobs.sqlite3', root / 'state.db']
    before = {path: path.read_bytes() for path in data}
    result = observe(ordinary_cycle, provider, workbook)
    assert result['state'] == 'INVENTORY_FROZEN'
    assert result['job_count'] == 1
    assert observe(ordinary_cycle, provider, workbook) == {**result, 'recovered': True}
    provider.assert_called_once_with('Lever', BOARD, 'COMP-1', 'Fixture')
    workbook.assert_called_once()
    assert workbook.return_value.service.batches == []
    assert {path: path.read_bytes() for path in data} == before
    assert (root / DIRECTORY / (cycle_id + '.json')).is_file()
    with (closing(SQLiteRepository(root / 'jobs.sqlite3', 'sheet', readonly=True)) as local,
          closing(State(str(root / 'state.db'), readonly=True)) as state):
        frozen = load_ordinary_event_observation(
            local, state, RUNTIME, cycle_id=cycle_id, request_sha256=request_sha256,
        )
        assert frozen['inventory_sha256'] == result['inventory_sha256']
        assert frozen['inventory']['jobs'] == [{'posting_id': 'p'}]
    with pytest.raises(ValueError, match='Ordinary Company event owns the cycle'):
        assert_normal_lifecycle_not_held(root, root / 'jobs.sqlite3')


def test_interrupted_event_uses_the_durable_claim_and_never_calls_again(ordinary_cycle):
    provider = Mock(side_effect=RuntimeError('interrupted provider'))
    workbook = workbook_reader()
    with pytest.raises(RuntimeError, match='interrupted provider'):
        observe(ordinary_cycle, provider, workbook)
    assert observe(ordinary_cycle, provider, workbook)['state'] == 'HELD_FETCH_UNCERTAIN'
    provider.assert_called_once()
    workbook.assert_called_once()


def test_company_event_workbook_guard_drift_and_wrong_digest_stop_before_fetch(ordinary_cycle):
    root, cycle_id, _ = ordinary_cycle
    provider = Mock()
    workbook = workbook_reader()
    with pytest.raises(ValueError, match='exact admitted request digest'):
        observe(ordinary_cycle, provider, workbook, request_sha256='0' * 64)
    workbook.assert_not_called()

    def mutate_during_read():
        with closing(SQLiteRepository(root / 'jobs.sqlite3', 'sheet')) as local:
            for url in ('https://jobs.eu.lever.co/acme?location=Boston', BOARD):
                local.mutate_company_with_event({
                    'tab': 'Companies', 'identity': {'Company ID': 'COMP-1'},
                    'values': {'Official Careers URL': url},
                })
        return workbook()

    assert observe(ordinary_cycle, provider, mutate_during_read)['state'] == 'HELD_SOURCE_CHANGED'
    provider.assert_not_called()
    assert not (root / DIRECTORY / (cycle_id + '.json')).exists()


@pytest.mark.parametrize('returned', [
    'https://api.lever.co/v0/postings/acme?location=Berlin',
    'https://api.eu.lever.co/v0/postings/acme?location=Boston',
    'https://api.eu.lever.co/v0/postings/acme',
])
def test_event_return_cannot_substitute_a_lever_region_or_location(ordinary_cycle, returned):
    workbook = workbook_reader()
    provider = Mock(return_value=ats.Inventory('failed', source_url=returned, ats='Lever',
                    outcome_failure=ats.outcome_failure('temporary_transport', 'retryable_http_status')))
    with pytest.raises(ValueError, match='wrong provider'):
        observe(ordinary_cycle, provider, workbook)
    assert observe(ordinary_cycle, provider, workbook)['state'] == 'HELD_FETCH_UNCERTAIN'
    provider.assert_called_once()
