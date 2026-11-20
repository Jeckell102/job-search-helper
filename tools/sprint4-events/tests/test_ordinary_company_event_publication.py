"""Composed exact publication, cleanup and replay for an ordinary Company event."""
from contextlib import closing
from unittest.mock import Mock, patch

import pytest

from job_search_helper import ats
from job_search_helper.cli import writer_lock
from job_search_helper.engine import Engine, State
from job_search_helper.inbox import InventoryInbox
from job_search_helper.ordinary_company_event_publication import publish_ordinary_event_locked
from job_search_helper.ordinary_event_publication_archive import archive_before_cleanup
from job_search_helper.sqlite_repository import SQLiteRepository
from test_ordinary_company_event_fetch import OBSERVED, RUNTIME, observe, ordinary_cycle, workbook_reader
from test_retained_operator_run import DESCRIPTION


def _prepare(fixture):
    workbook = workbook_reader()
    original = {
        'title': 'Implementation Manager', 'posting_id': 'ordinary-42', 'location': 'Remote, United States',
        'url': 'https://jobs.eu.lever.co/acme/ordinary-42', 'description': DESCRIPTION, 'ats': 'Lever',
    }
    provider = Mock(return_value=ats.Inventory('complete', [original], source_url=OBSERVED, ats='Lever'))
    assert observe(fixture, provider, workbook)['state'] == 'INVENTORY_FROZEN'
    return workbook, provider


def _publish(fixture, workbook):
    root, cycle_id, digest = fixture
    with (writer_lock(root / 'scraper.lock'), writer_lock(root / 'writer.lock'),
          closing(SQLiteRepository(root / 'jobs.sqlite3', 'sheet')) as local,
          closing(State(str(root / 'state.db'))) as state,
          closing(InventoryInbox(root / 'inventories.sqlite3', 'sheet')) as inbox):
        engine = Engine(local, state, inbox=inbox, runtime_binding=RUNTIME, error_log_path=root / 'errors.jsonl')
        return publish_ordinary_event_locked(engine, workbook, cycle_id=cycle_id, request_sha256=digest)


def test_ordinary_event_recovers_lost_sheets_response_and_archives_exact_result(ordinary_cycle):
    root, cycle_id, digest = ordinary_cycle
    workbook, provider = _prepare(ordinary_cycle)
    sheets = workbook.return_value.service
    sheets.lose_response = True
    holding = _publish(ordinary_cycle, workbook)
    assert holding['held'] == [{'company_id': 'COMP-1', 'reason': 'uncertain_write'}], holding
    first_batches = list(sheets.batches)
    assert first_batches
    report = _publish(ordinary_cycle, workbook)
    assert report['state'] == 'SYNC_CONFIRMED', report
    assert report['binding']['request_sha256'] == digest
    assert report['binding']['authority'] == 'ordinary-company-event-exact-v2'
    assert report['final_stage'] == 'complete'
    assert report['cycle_id'] == cycle_id
    assert sheets.batches == first_batches
    reopened_workbook = Mock(side_effect=AssertionError('archived replay opened the workbook'))
    assert _publish(ordinary_cycle, reopened_workbook) == report
    reopened_workbook.assert_not_called()
    provider.assert_called_once()
    with (closing(InventoryInbox(root / 'inventories.sqlite3', 'sheet')) as inbox,
          closing(SQLiteRepository(root / 'jobs.sqlite3', 'sheet', readonly=True)) as local):
        assert inbox.get(cycle_id, 'COMP-1') is None
        assert inbox.plan(cycle_id, 'COMP-1') is None
        assert len(local.read('Job History')) == 1
        assert len(local.read('Job Evidence')) == 1


def test_ordinary_event_archive_and_inbox_cleanup_roll_back_together(ordinary_cycle):
    root, cycle_id, _digest = ordinary_cycle
    workbook, provider = _prepare(ordinary_cycle)

    def crash(*args, **kwargs):
        archive_before_cleanup(*args, **kwargs)
        raise RuntimeError('interrupted after archive insertion')

    with patch('job_search_helper.ordinary_event_publication_archive.archive_before_cleanup', side_effect=crash):
        holding = _publish(ordinary_cycle, workbook)
    assert holding['state'] == 'PUBLICATION_HELD', holding
    assert holding['held'] == [{'company_id': 'COMP-1', 'reason': 'RuntimeError'}]
    first_batches = list(workbook.return_value.service.batches)
    with closing(InventoryInbox(root / 'inventories.sqlite3', 'sheet')) as inbox:
        assert inbox.plan(cycle_id, 'COMP-1') is not None
        assert not inbox.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='ordinary_event_publication_archive'").fetchone()
    assert _publish(ordinary_cycle, workbook)['state'] == 'SYNC_CONFIRMED'
    assert workbook.return_value.service.batches == first_batches
    provider.assert_called_once()


def test_archive_requires_the_same_jobs_acknowledgement_on_replay(ordinary_cycle):
    root, _cycle_id, _digest = ordinary_cycle
    workbook, _provider = _prepare(ordinary_cycle)
    result = _publish(ordinary_cycle, workbook)
    assert result['state'] == 'SYNC_CONFIRMED', result
    with closing(SQLiteRepository(root / 'jobs.sqlite3', 'sheet')) as local, local.transaction():
        local.db.execute('UPDATE exact_local_acknowledgements SET selected_fields_digest=? WHERE apply_id=?',
                         ('0' * 64, result['apply_id']))
    not_opened = Mock()
    with pytest.raises(ValueError, match='lacks the exact Jobs acknowledgement'):
        _publish(ordinary_cycle, not_opened)
    not_opened.assert_not_called()


def test_event_receipt_cannot_enter_legacy_reconciliation_before_remote_intent(ordinary_cycle):
    from job_search_helper import publication_receipts

    root, cycle_id, _digest = ordinary_cycle
    workbook, provider = _prepare(ordinary_cycle)
    with patch.object(InventoryInbox, 'freeze_exact_remote_plan', side_effect=ValueError('stop before intent')):
        report = _publish(ordinary_cycle, workbook)
    assert report['held'] == [{'company_id': 'COMP-1', 'reason': 'stop before intent'}], report
    with closing(InventoryInbox(root / 'inventories.sqlite3', 'sheet')) as inbox:
        plan = inbox.plan(cycle_id, 'COMP-1')[0]
        assert inbox.exact_remote_state(cycle_id, 'COMP-1') is None
        binding = plan['ordinary_company_event']
        stripped = {key: binding[key] for key in (
            'request_id', 'company_id', 'source_revision', 'release_id', 'release_binding_sha256',
        )}
        receipt = {'binding': stripped, 'records': plan['remote_records']}
        inbox.mark_receipt_pending(receipt, timestamp='pending')
        with pytest.raises(ValueError, match='trusted Sheets confirmation'):
            inbox.reconcile_receipt(receipt, plan['remote_records'], 'forged-ack', timestamp='invalid')
        with pytest.raises(ValueError, match='trusted Sheets confirmation'):
            publication_receipts.reconcile_sync(
                inbox.connection, stripped, plan['remote_records'], 'forged-ack', timestamp='invalid',
            )
        with pytest.raises(ValueError, match='exact publication plan'):
            inbox.discard_preflight_rejected_receipt(receipt, cursor=0)
        assert inbox.receipt(receipt)['state'] == publication_receipts.SYNC_PENDING
    assert workbook.return_value.service.batches == []
    assert _publish(ordinary_cycle, workbook)['state'] == 'SYNC_CONFIRMED'
    provider.assert_called_once()
