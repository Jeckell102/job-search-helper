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


def _publish(fixture, workbook, *, remote_reader=None):
    root, cycle_id, digest = fixture
    with (writer_lock(root / 'scraper.lock'), writer_lock(root / 'writer.lock'),
          closing(SQLiteRepository(root / 'jobs.sqlite3', 'sheet')) as local,
          closing(State(str(root / 'state.db'))) as state,
          closing(InventoryInbox(root / 'inventories.sqlite3', 'sheet')) as inbox):
        engine = Engine(local, state, inbox=inbox, runtime_binding=RUNTIME, error_log_path=root / 'errors.jsonl')
        return publish_ordinary_event_locked(
            engine, workbook, cycle_id=cycle_id, request_sha256=digest, remote_reader=remote_reader,
        )


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
    from job_search_helper.scrape_outcome_delivery import OutcomeDelivery

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
    sink = Mock()
    with closing(SQLiteRepository(root / 'jobs.sqlite3', 'sheet')) as local:
        outcome_id = result['outcome']['outcome_id']
        assert OutcomeDelivery(local, sink).drain(outcome_id=outcome_id) == [
            {'outcome_id': outcome_id, 'disposition': 'HELD_ORDINARY_EVENT_SETTLEMENT'},
        ]
    sink.ingest_immutable.assert_not_called()


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
        shorter = {key: value for key, value in stripped.items() if key != 'release_binding_sha256'}
        alias = {**receipt, 'binding': shorter, 'schedule': inbox.receipt(receipt)['schedule'],
                 'timestamp': 'irrelevant'}
        with pytest.raises(ValueError, match='exact publication plan'):
            inbox.ensure_receipt(alias)
        with pytest.raises(ValueError, match='trusted Sheets confirmation'):
            inbox.reconcile_receipt(alias, plan['remote_records'], 'forged-ack', timestamp='invalid')
        assert inbox.connection.execute('SELECT COUNT(*) FROM publication_receipts').fetchone() == (1,)

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


def test_settlement_finishes_state_after_jobs_commit_without_fetch_or_workbook(ordinary_cycle):
    from job_search_helper.retained_work_runner import assert_normal_lifecycle_not_held
    from job_search_helper.scrape_outcome_delivery import OutcomeDelivery, SCHEMA
    from job_search_helper.temporary_retry import _selected_sha

    root, cycle_id, digest = ordinary_cycle
    workbook, provider = _prepare(ordinary_cycle)
    original = State.save_cycle

    def interrupted(state, cycle):
        if cycle.get('ordinary_event_settlement_sha256'):
            raise RuntimeError('interrupted before terminal State')
        return original(state, cycle)

    with patch.object(State, 'save_cycle', interrupted):
        with pytest.raises(RuntimeError, match='interrupted before terminal State'):
            _publish(ordinary_cycle, workbook)
    with pytest.raises(ValueError, match='Ordinary Company event owns the cycle'):
        assert_normal_lifecycle_not_held(root, root / 'jobs.sqlite3')
    with closing(SQLiteRepository(root / 'jobs.sqlite3', 'sheet', readonly=True)) as local:
        mirror = local.matches('Scan Cycles', {'Cycle ID': cycle_id})[0][1]
        assert mirror['Cycle Status'] == 'Complete'
        before = local.db.execute('SELECT outcome_id,recorded_at FROM scrape_outcomes').fetchall()
        assert len(before) == 1
    sink = Mock()
    sink.ingest_immutable.side_effect = lambda record: {
        'schema': SCHEMA, 'consumer': 'repair-coordinator', 'outcome_id': record['outcome_id'],
        'record_sha256': _selected_sha(record), 'disposition': 'ACCEPTED',
        'sink_receipt_id': 'fixture-sink:ordinary', 'sink_status': 'OBSERVED_HELD',
    }
    with closing(SQLiteRepository(root / 'jobs.sqlite3', 'sheet')) as local:
        assert OutcomeDelivery(local, sink).drain(outcome_id=before[0][0]) == [
            {'outcome_id': before[0][0], 'disposition': 'HELD_ORDINARY_EVENT_SETTLEMENT'},
        ]
    sink.ingest_immutable.assert_not_called()
    unopened = Mock()
    replay = _publish(ordinary_cycle, unopened)
    assert replay['state'] == 'SYNC_CONFIRMED'
    assert replay['binding']['request_sha256'] == digest
    assert replay['outcome']['outcome'] == 'COMPLETE'
    assert replay['outcome']['outcome_id'] == before[0][0]
    assert _publish(ordinary_cycle, unopened) == replay
    with closing(State(str(root / 'state.db'), readonly=True)) as state:
        cycle = state.cycle(cycle_id)
        assert cycle['status'] == 'Complete'
        assert cycle['completed_at'] == before[0][1]
        assert cycle['ordinary_event_settlement_sha256'] == replay['settlement_sha256']
    assert_normal_lifecycle_not_held(root, root / 'jobs.sqlite3')
    with closing(SQLiteRepository(root / 'jobs.sqlite3', 'sheet')) as local:
        delivery = OutcomeDelivery(local, sink)
        assert delivery.drain(outcome_id=before[0][0]) == [
            {'outcome_id': before[0][0], 'disposition': 'ACCEPTED'},
        ]
        assert delivery.drain(outcome_id=before[0][0]) == []
    sink.ingest_immutable.assert_called_once_with(replay['outcome'])
    provider.assert_called_once()
    unopened.assert_not_called()


@pytest.mark.parametrize('field', ['local_records_digest', 'projection_digest', 'orphan_chunk'])
def test_exact_archived_digest_and_orphan_contradictions_fail_closed(ordinary_cycle, field):
    import json
    from job_search_helper.exact_cycle_planner import _digest
    from job_search_helper.exact_cycle_sync import _remote_intent_id

    root, cycle_id, _request = ordinary_cycle
    workbook, provider = _prepare(ordinary_cycle)
    assert _publish(ordinary_cycle, workbook)['state'] == 'SYNC_CONFIRMED'
    with closing(InventoryInbox(root / 'inventories.sqlite3', 'sheet')) as inbox, inbox.connection:
        if field == 'orphan_chunk':
            inbox.connection.execute(
                'INSERT INTO exact_sync_chunks VALUES (?,?,?,?,?,?)',
                (cycle_id, 'COMP-1', 0, 1, 'a' * 64, 'CLAIMED'),
            )
        else:
            proof = json.loads(inbox.connection.execute(
                'SELECT evidence FROM ordinary_event_publication_archive').fetchone()[0])
            proof[field] = '0' * 64
            if field == 'projection_digest':
                proof['intent_id'] = _remote_intent_id(cycle_id, 'COMP-1', proof['plan_digest'], proof[field])
            inbox.connection.execute(
                'UPDATE ordinary_event_publication_archive SET proof_sha256=?,evidence=?',
                (_digest(proof), json.dumps(proof, ensure_ascii=False, sort_keys=True, separators=(',', ':'))),
            )
    unopened = Mock()
    with pytest.raises(ValueError, match='durable readback proof|conflicts with active Inbox'):
        _publish(ordinary_cycle, unopened)
    unopened.assert_not_called()
    provider.assert_called_once()


def test_one_final_workbook_probe_holds_a_changed_board_before_remote_write(ordinary_cycle):
    from job_search_helper.sheets_sync import SheetsSynchronizer
    from test_ordinary_company_event_fetch import BOARD

    workbook, provider = _prepare(ordinary_cycle)
    remote = workbook.return_value
    original_read = remote.read_columns
    original_publish = SheetsSynchronizer.publish_exact_scope
    final_reads = []
    active = False

    def read(tab, headers):
        if active and tab == 'Companies':
            final_reads.append(list(headers))
            remote.service.set_cell('Companies', 1, 'Official Careers URL', BOARD.replace('Berlin', 'Boston'))
        return original_read(tab, headers)

    def enter(self, *args, **kwargs):
        guard = kwargs['pre_commit_guard']

        def guarded():
            nonlocal active
            active = True
            try:
                guard()
            finally:
                active = False

        return original_publish(self, *args, **{**kwargs, 'pre_commit_guard': guarded})

    remote.read_columns = read
    with patch.object(SheetsSynchronizer, 'publish_exact_scope', enter):
        result = _publish(ordinary_cycle, workbook)
    assert result['state'] == 'PUBLICATION_HELD', result
    assert final_reads == [['Company ID', 'Company Status', 'Official Careers URL', 'ATS / Source']]
    assert not remote.service.batches
    provider.assert_called_once()


def test_outcome_preserves_a_settled_publication_but_suppresses_a_superseded_event(ordinary_cycle):
    from job_search_helper.repository import RepositoryError
    from job_search_helper.scrape_outcome_delivery import OutcomeDelivery
    from test_ordinary_company_event_fetch import BOARD

    root, cycle_id, _request = ordinary_cycle
    workbook, provider = _prepare(ordinary_cycle)
    with patch('job_search_helper.ordinary_company_event_publication.settle_ordinary_event',
               side_effect=RuntimeError('interrupt before the outcome')):
        with pytest.raises(RuntimeError, match='interrupt before the outcome'):
            _publish(ordinary_cycle, workbook)
    with closing(SQLiteRepository(root / 'jobs.sqlite3', 'sheet')) as local:
        events = []
        for url in (BOARD.replace('Berlin', 'Boston'), BOARD):
            events.append(local.mutate_company_with_event({
                'tab': 'Companies', 'identity': {'Company ID': 'COMP-1'},
                'values': {'Official Careers URL': url},
            })['company_event'])
        with pytest.raises(RepositoryError, match='sealed event writer'):
            local.record_scrape_outcome({
                'request_id': 'legacy-alias', 'cycle_id': cycle_id, 'company_id': 'COMP-1',
                'source_revision': events[-1]['source_revision'], 'source_current': True,
                'inventory_status': 'complete',
            })
        assert not local.scrape_outcomes()
    unopened = Mock()
    with patch.object(State, 'save_cycle', side_effect=RuntimeError('cut before stale terminal State')):
        with pytest.raises(RuntimeError, match='cut before stale terminal State'):
            _publish(ordinary_cycle, unopened)
    sink = Mock()
    with closing(SQLiteRepository(root / 'jobs.sqlite3', 'sheet')) as local:
        stored = local.scrape_outcomes()[0]
        assert OutcomeDelivery(local, sink).drain(outcome_id=stored['outcome_id']) == [
            {'outcome_id': stored['outcome_id'], 'disposition': 'HELD_ORDINARY_EVENT_SETTLEMENT'},
        ]
    result = _publish(ordinary_cycle, unopened)
    assert result['state'] == 'SYNC_CONFIRMED'
    outcome = result['outcome']
    assert outcome['outcome'] == 'STALE_OR_PAUSED'
    assert outcome['identity']['source_revision'] == events[-1]['source_revision']
    with closing(SQLiteRepository(root / 'jobs.sqlite3', 'sheet')) as local:
        assert local.scrape_outcomes() == [outcome]
        assert OutcomeDelivery(local, sink).drain(outcome_id=outcome['outcome_id']) == [
            {'outcome_id': outcome['outcome_id'], 'disposition': 'STALE_SUPPRESSED'},
        ]
    assert _publish(ordinary_cycle, unopened) == result
    unopened.assert_not_called()
    sink.ingest_immutable.assert_not_called()
    provider.assert_called_once()
