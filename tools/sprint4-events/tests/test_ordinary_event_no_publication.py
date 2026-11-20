"""Exact ordinary dispositions that never use a Sheets writer."""
from contextlib import closing
from unittest.mock import Mock, patch

import pytest

from job_search_helper import ats
from job_search_helper.engine import State
from job_search_helper.inbox import InventoryInbox
from job_search_helper.scrape_outcome_delivery import OutcomeDelivery, SCHEMA
from job_search_helper.sqlite_repository import SQLiteRepository
from job_search_helper.temporary_retry import _selected_sha
from test_ordinary_company_event_fetch import (
    COMPANY, OBSERVED, create_ordinary_cycle, observe, ordinary_cycle, workbook_reader,
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
