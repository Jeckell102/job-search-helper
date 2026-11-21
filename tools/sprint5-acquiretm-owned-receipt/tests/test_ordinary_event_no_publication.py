"""Exact ordinary dispositions that never use a Sheets writer."""
from contextlib import closing, contextmanager, nullcontext
from dataclasses import replace
import json
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from job_search_helper import ats, cli, runner
from job_search_helper.acquiretm import SOURCE
from job_search_helper.company_events import CompanyEventBridge, _json_digest
from job_search_helper.engine import State
from job_search_helper.inbox import InventoryInbox
from job_search_helper.ordinary_event_settlement import ordinary_event_outcome_settled
from job_search_helper.scrape_outcome_delivery import OutcomeDelivery, SCHEMA
from job_search_helper.sheet_profile import COMPACT_PROFILE, COMPACT_SCHEMAS
from job_search_helper.sqlite_repository import SQLiteRepository
from job_search_helper.temporary_retry import _selected_sha
from test_acquiretm import UpdatePanelPage
from test_ordinary_company_event_fetch import (
    COMPANY, OBSERVED, RUNTIME, create_ordinary_cycle, observe, ordinary_cycle, workbook_reader,
)
from test_ordinary_company_event_publication import _publish


def _fetch_result(kind):
    if kind == 'blocked':
        return ats.Inventory('blocked', source_url=OBSERVED, ats='Lever', outcome_failure=ats.outcome_failure(
            'access_denied', 'public_access_denied',
        ))
    return ats.Inventory('failed', source_url=OBSERVED, ats='Lever', outcome_failure=ats.outcome_failure(
        'temporary_transport', 'retryable_http_status',
    ))


@pytest.mark.parametrize('case', ['owned', 'untyped', 'foreign', 'nonempty', 'malformed'])
def test_named_amphenol_pagination_settlement_is_exact_and_never_publishes(tmp_path, monkeypatch, capsys, case):
    state_path, jobs = tmp_path / 'state.db', tmp_path / 'jobs.sqlite3'
    monkeypatch.setenv('SPREADSHEET_ID', 'sheet')
    cid = 'COMP-0491' if case == 'foreign' else 'COMP-0490'
    company = {'Company ID': cid, 'Company': 'Amphenol Aerospace', 'Company Status': 'Active',
               'ATS / Source': 'AcquireTM', 'Official Careers URL': SOURCE}
    with (closing(State(str(state_path))), closing(InventoryInbox(tmp_path / 'inventories.sqlite3', 'sheet')),
          closing(SQLiteRepository(jobs, 'sheet', initialize=True)) as repo):
        repo.set_meta('ready', 'yes')
        repo.set_meta('sheets_profile', COMPACT_PROFILE)
        repo.ensure_columns('Opportunities', ['Opportunity ID'])
        repo.import_rows('Companies', [(2, {**company, 'Official Careers URL': SOURCE.replace('home.aspx', 'old.aspx')})])
        event = repo.mutate_company_with_event({
            'tab': 'Companies', 'identity': {'Company ID': cid}, 'values': {'Official Careers URL': SOURCE},
        })['company_event']
        CompanyEventBridge(repo, tmp_path).process_pending()
    request = json.loads((tmp_path / 'next-scan.json').read_bytes())
    digest = _json_digest(request)

    page = UpdatePanelPage('same_page' if case == 'untyped' else 'delayed')
    details = Mock(side_effect=AssertionError('Pre-detail failure must not open a detail'))
    browser = SimpleNamespace(new_context=lambda: SimpleNamespace(new_page=lambda: page, request=details),
                              close=lambda: None)
    playwright = SimpleNamespace(chromium=SimpleNamespace(launch=lambda **kwargs: browser))
    monkeypatch.setitem(sys.modules, 'playwright.sync_api',
                        SimpleNamespace(sync_playwright=lambda: nullcontext(playwright)))
    monkeypatch.setattr('job_search_helper.acquiretm.time.monotonic_ns', lambda: page.clock_ns)
    fetch = ats.fetch_inventory

    def fetch_fixture(provider, url, _cid, name):
        result = fetch(provider, url, 'COMP-0490', name)
        if case == 'nonempty':
            return replace(result, jobs=[{'posting_id': 'fixture'}])
        if case == 'malformed':
            return replace(result, outcome_failure={**result.outcome_failure, 'evidence': {}})
        return result

    provider = Mock(side_effect=fetch_fixture)
    monkeypatch.setattr(ats, 'fetch_inventory', provider)
    workbook = workbook_reader(company, SOURCE)

    def remote(*, write, interactive, schemas, evidence_archives):
        assert not write and not interactive and schemas == COMPACT_SCHEMAS and not evidence_archives
        return workbook()

    monkeypatch.setattr(cli, 'get_remote_repository', remote)

    @contextmanager
    def admission():
        with cli.writer_lock(tmp_path / 'scraper.lock'):
            yield state_path, jobs, RUNTIME

    monkeypatch.setattr(runner, '_retained_operator_admission', admission)

    def command(action, cycle_id=None):
        argv = ['ordinary-company-event', action, '--request-sha256', digest]
        if cycle_id is not None:
            argv.extend(['--cycle-id', cycle_id])
        status = runner.scrape_main(argv)
        captured = capsys.readouterr()
        record = next((line.removeprefix('Ordinary Company event: ') for line in captured.out.splitlines()
                       if line.startswith('Ordinary Company event: ')), None)
        return status, json.loads(record) if record else None

    status, admitted = command('admit-fetch')
    if case == 'malformed':
        assert (status, admitted) == (1, None)
        with closing(SQLiteRepository(jobs, 'sheet', readonly=True)) as repo:
            assert not repo.scrape_outcomes()
        provider.assert_called_once_with('AcquireTM', SOURCE, cid, 'Amphenol Aerospace')
        workbook.assert_called_once()
        return
    assert status == 0 and admitted['state'] == 'INVENTORY_FROZEN'
    cycle_id = admitted['cycle_id']
    if case != 'owned':
        assert command('publish', cycle_id) == (1, {'state': 'HELD_NO_PUBLICATION_SCOPE',
                                                    'cycle_id': cycle_id, 'request_sha256': digest})
        if case == 'nonempty':
            writer = Mock(side_effect=AssertionError('Typed local-only evidence cannot open a Sheets writer'))
            assert _publish((tmp_path, cycle_id, digest), writer)['state'] == 'HELD_NO_PUBLISHABLE_EVENT_INVENTORY'
            writer.assert_not_called()
        with closing(SQLiteRepository(jobs, 'sheet', readonly=True)) as repo:
            assert not repo.scrape_outcomes()
        workbook.assert_called_once()
        provider.assert_called_once_with('AcquireTM', SOURCE, cid, 'Amphenol Aerospace')
        return

    with patch.object(State, 'save_cycle', side_effect=RuntimeError('cut before State')):
        assert command('publish', cycle_id) == (1, None)
    sink = Mock()
    sink.ingest_immutable.side_effect = lambda record: {
        'schema': SCHEMA, 'consumer': 'repair-coordinator', 'outcome_id': record['outcome_id'],
        'record_sha256': _selected_sha(record), 'disposition': 'ACCEPTED',
        'sink_receipt_id': 'fixture-sink:pagination', 'sink_status': 'HELD_FOR_REPAIR_TRIAGE',
    }
    with closing(SQLiteRepository(jobs, 'sheet')) as repo:
        [outcome] = repo.scrape_outcomes()
        assert not ordinary_event_outcome_settled(repo, outcome)
        assert OutcomeDelivery(repo, sink).drain(outcome_id=outcome['outcome_id']) == [
            {'outcome_id': outcome['outcome_id'], 'disposition': 'HELD_ORDINARY_EVENT_SETTLEMENT'},
        ]
    sink.ingest_immutable.assert_not_called()

    status, result = command('publish', cycle_id)
    assert status == 0 and result['state'] == 'FETCH_REPAIR_QUALIFIED'
    outcome = result['outcome']
    assert outcome['identity']['request_id'] == request['request_id']
    assert outcome['identity']['source_revision'] == request['source_revision']
    assert outcome['identity']['company_event_id'] == event['event_id']
    assert (outcome['outcome'], outcome['action'], outcome['repair_category']) == (
        'QUALIFIED_INTEGRATION_REPAIR', 'upsert_qualified_repair', 'pagination_regression',
    )
    assert command('publish', cycle_id) == (0, result)
    with (closing(SQLiteRepository(jobs, 'sheet', readonly=True)) as repo,
          closing(State(str(state_path), readonly=True)) as state):
        assert repo.scrape_outcomes() == [outcome]
        assert ordinary_event_outcome_settled(repo, outcome)
        assert state.cycle(cycle_id)['companies'][cid]['stage'] == 'partial'
        assert repo.matches('Companies', {'Company ID': cid})[0][1]['Scan State'] == 'Partial'
        assert not repo.read('Job History') and not repo.read('Job Evidence')
    with closing(SQLiteRepository(jobs, 'sheet')) as repo:
        delivery = OutcomeDelivery(repo, sink)
        assert delivery.drain(outcome_id=outcome['outcome_id'])[0]['disposition'] == 'ACCEPTED'
        assert delivery.drain(outcome_id=outcome['outcome_id']) == []
    sink.ingest_immutable.assert_called_once_with(outcome)
    assert workbook.call_count == 2 and not workbook.return_value.service.batches
    provider.assert_called_once_with('AcquireTM', SOURCE, cid, 'Amphenol Aerospace')
    details.get.assert_not_called()


@pytest.mark.parametrize(('provider_status', 'result', 'outcome_class', 'scan'), [
    ('blocked', 'FETCH_BLOCKED', 'BLOCKED', 'Blocked / Manual Review'),
    ('failed', 'FETCH_TEMPORARY', 'TEMPORARY', 'Failed'),
])
def test_definitive_provider_failure_settles_without_workbook_write(
        ordinary_cycle, provider_status, result, outcome_class, scan):
    root, cycle_id, _ = ordinary_cycle
    workbook = workbook_reader()
    provider = Mock(return_value=_fetch_result(provider_status))
    assert observe(ordinary_cycle, provider, workbook)['state'] == 'INVENTORY_FROZEN'
    writer = Mock()
    finished = _publish(ordinary_cycle, writer, remote_reader=workbook)
    assert finished['state'] == result
    assert finished['outcome']['outcome'] == outcome_class
    assert 'receipt_id' not in finished
    assert _publish(ordinary_cycle, writer) == finished
    assert workbook.call_count == 2
    writer.assert_not_called()
    provider.assert_called_once()
    assert workbook.return_value.service.batches == []
    with (closing(SQLiteRepository(root / 'jobs.sqlite3', 'sheet', readonly=True)) as repo,
          closing(State(str(root / 'state.db'), readonly=True)) as state):
        row = repo.matches('Companies', {'Company ID': 'COMP-1'})[0][1]
        assert row['Scan State'] == scan
        assert state.cycle(cycle_id)['status'] == 'Complete with exceptions'
        assert not repo.read('Job History')
        assert not repo.read('Job Evidence')


def test_verified_zero_and_state_recovery_do_not_publish_or_resend(tmp_path):
    greenhouse = {**COMPANY, 'ATS / Source': 'Greenhouse',
                  'Official Careers URL': 'https://job-boards.greenhouse.io/previous'}
    board = 'https://job-boards.greenhouse.io/fixture'
    fixture = create_ordinary_cycle(tmp_path, greenhouse, board)
    reader = workbook_reader(greenhouse, board)
    provider = Mock(return_value=ats.Inventory(
        'complete', source_url='https://boards-api.greenhouse.io/v1/boards/fixture/jobs',
        ats='Greenhouse', verified_zero='greenhouse_explicit_total_zero',
    ))
    assert observe(fixture, provider, reader)['state'] == 'INVENTORY_FROZEN'
    writer = Mock()
    with patch.object(State, 'save_cycle', side_effect=RuntimeError('cut before State')):
        with pytest.raises(RuntimeError, match='cut before State'):
            _publish(fixture, writer, remote_reader=reader)
    report = _publish(fixture, writer)
    assert report['state'] == 'VERIFIED_ZERO'
    assert report['outcome']['outcome'] == 'COMPLETE'
    assert _publish(fixture, writer) == report
    assert reader.call_count == 2
    assert reader.return_value.service.batches == []
    writer.assert_not_called()
    provider.assert_called_once()
    sink = Mock()
    sink.ingest_immutable.side_effect = lambda record: {
        'schema': SCHEMA, 'consumer': 'repair-coordinator', 'outcome_id': record['outcome_id'],
        'record_sha256': _selected_sha(record), 'disposition': 'ACCEPTED',
        'sink_receipt_id': 'fixture-sink:zero', 'sink_status': 'OBSERVED_HELD',
    }
    with closing(SQLiteRepository(tmp_path / 'jobs.sqlite3', 'sheet')) as repo:
        assert OutcomeDelivery(repo, sink).drain(outcome_id=report['outcome']['outcome_id'])[0]['disposition'] == 'ACCEPTED'
    sink.ingest_immutable.assert_called_once_with(report['outcome'])


def test_unverified_empty_inventory_stays_unsettled(ordinary_cycle):
    reader = workbook_reader()
    provider = Mock(return_value=ats.Inventory('complete', source_url=OBSERVED, ats='Lever'))
    assert observe(ordinary_cycle, provider, reader)['state'] == 'INVENTORY_FROZEN'
    writer = Mock()
    assert _publish(ordinary_cycle, writer)['state'] == 'HELD_NO_PUBLISHABLE_EVENT_INVENTORY'
    writer.assert_not_called()
    reader.assert_called_once()


def test_local_only_disposition_cannot_override_a_claimed_publication_chunk(ordinary_cycle):
    root, cycle_id, _request = ordinary_cycle
    reader = workbook_reader()
    provider = Mock(return_value=_fetch_result('failed'))
    assert observe(ordinary_cycle, provider, reader)['state'] == 'INVENTORY_FROZEN'
    with closing(InventoryInbox(root / 'inventories.sqlite3', 'sheet')) as inbox, inbox.connection:
        inbox.connection.execute(
            'INSERT INTO exact_sync_chunks VALUES (?,?,?,?,?,?)',
            (cycle_id, 'COMP-1', 0, 1, 'a' * 64, 'CLAIMED'),
        )
    writer = Mock()
    with pytest.raises(ValueError, match='local-only settlement conflicts with publication evidence'):
        _publish(ordinary_cycle, writer, remote_reader=reader)
    writer.assert_not_called()
    reader.assert_called_once()
    with (closing(SQLiteRepository(root / 'jobs.sqlite3', 'sheet', readonly=True)) as repo,
          closing(State(str(root / 'state.db'), readonly=True)) as state):
        assert state.cycle(cycle_id)['status'] == 'In Progress'
        assert not repo.scrape_outcomes()


@pytest.mark.parametrize('table', [
    'exact_legacy_plan_migration_archive', 'exact_legacy_delivery_evidence_archive',
    'exact_selected_legacy_recovery_archive',
])
def test_historical_exact_archive_blocks_local_only_settlement(ordinary_cycle, table):
    root, cycle_id, _request = ordinary_cycle
    reader = workbook_reader()
    observe(ordinary_cycle, Mock(return_value=_fetch_result('failed')), reader)
    with closing(InventoryInbox(root / 'inventories.sqlite3', 'sheet')) as inbox, inbox.connection:
        inbox.connection.execute(f'INSERT INTO {table} VALUES (?,?,?,?)',
                                 (cycle_id, 'COMP-1', '{}', '2026-11-20T12:00:00Z'))
    writer = Mock()
    with pytest.raises(ValueError, match='local-only settlement conflicts with publication evidence'):
        _publish(ordinary_cycle, writer, remote_reader=reader)
    writer.assert_not_called()
    reader.assert_called_once()
    with (closing(SQLiteRepository(root / 'jobs.sqlite3', 'sheet', readonly=True)) as repo,
          closing(State(str(root / 'state.db'), readonly=True)) as state):
        assert state.cycle(cycle_id)['status'] == 'In Progress'
        assert repo.matches('Scan Cycles', {'Cycle ID': cycle_id})[0][1]['Cycle Status'] == 'In Progress'
        assert not repo.scrape_outcomes()


@pytest.mark.parametrize('phase', ['before settlement', 'before delivery'])
def test_receipt_alias_naming_exact_cycle_blocks_local_only_result(ordinary_cycle, phase):
    root, cycle_id, _request = ordinary_cycle
    reader = workbook_reader()
    provider = Mock(return_value=_fetch_result('blocked'))
    observe(ordinary_cycle, provider, reader)
    writer = Mock()
    result = _publish(ordinary_cycle, writer, remote_reader=reader) if phase == 'before delivery' else None
    with closing(State(str(root / 'state.db'), readonly=True)) as state:
        revision = state.cycle(cycle_id)['company_event']['source_revision']
    receipt = {
        'binding': {'request_id': 'legacy-alias', 'cycle_id': cycle_id, 'company_id': 'COMP-1',
                    'source_revision': revision, 'release_id': 'legacy'},
        'records': {'Job History|fixture': 'prior-record'},
        'schedule': {'boundary': 'idle', 'enqueued_at': '2026-11-20T12:00:00Z'},
        'timestamp': '2026-11-20T12:00:00Z',
    }
    with closing(InventoryInbox(root / 'inventories.sqlite3', 'sheet')) as inbox:
        inbox.ensure_receipt(receipt)
        inbox.mark_receipt_pending(receipt, timestamp=receipt['timestamp'])
        assert inbox.reconcile_receipt(receipt, receipt['records'], 'prior-ack', timestamp=receipt['timestamp'])
    if result:
        sink = Mock()
        outcome_id = result['outcome']['outcome_id']
        with closing(SQLiteRepository(root / 'jobs.sqlite3', 'sheet')) as repo:
            assert OutcomeDelivery(repo, sink).drain(outcome_id=outcome_id) == [
                {'outcome_id': outcome_id, 'disposition': 'HELD_ORDINARY_EVENT_SETTLEMENT'},
            ]
        sink.ingest_immutable.assert_not_called()
    else:
        with pytest.raises(ValueError, match='local-only settlement conflicts with publication evidence'):
            _publish(ordinary_cycle, writer, remote_reader=reader)
        reader.assert_called_once()
    writer.assert_not_called()
    provider.assert_called_once()
