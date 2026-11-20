"""Disposable exact retry publication and acknowledgement proofs."""
from contextlib import closing
from unittest.mock import Mock

import pytest

from job_search_helper.cli import writer_lock
from job_search_helper.engine import Engine, State
from job_search_helper.exact_cycle_planner import _digest
from job_search_helper.inbox import InventoryInbox
from job_search_helper.selected_temporary_retry_publication import publish_selected_temporary_retry_locked
from test_selected_temporary_retry_admission import admit, scheduled, view
from test_temporary_retry import close_fixture_blocker, selected


def _prepare(scheduled):
    fixture, outcome, sink = scheduled
    close_fixture_blocker(fixture)
    snapshot = view(fixture, outcome)
    snapshot['cycles'] = None
    cycle = admit(fixture, sink, snapshot=snapshot)
    assert cycle['state'] == 'ADMITTED_LOCAL_CYCLE'
    fixture.service.before_write = lambda: fixture.assert_held('scraper.lock', 'writer.lock')
    cid = cycle['company_id']
    payload = {
        'inventory_status': 'complete', 'jobs': fixture.fetch.return_value.jobs,
        'requested_url': snapshot['company']['Official Careers URL'],
        'ats': snapshot['company']['ATS / Source'], 'fetched_at': fixture.now.isoformat(),
    }
    with closing(InventoryInbox(fixture.root / 'inventories.sqlite3', sink.reader.spreadsheet_id)) as inbox:
        inbox.save(cycle['cycle_id'], cid, payload)
    return fixture, outcome, sink, cycle, payload


def _publish(fixture, sink, cycle, remote_factory, inventory_digest):
    with (writer_lock(fixture.root / 'scraper.lock'), writer_lock(fixture.root / 'writer.lock'),
          closing(fixture.local(write=True)) as writer, closing(State(str(fixture.state_path))) as state,
          closing(InventoryInbox(fixture.root / 'inventories.sqlite3', sink.reader.spreadsheet_id)) as inbox):
        engine = Engine(writer, state, inbox=inbox, runtime_binding=fixture.runtime,
                        error_log_path=fixture.root / 'errors.jsonl')
        return publish_selected_temporary_retry_locked(
            sink, engine, remote_factory, cycle_id=cycle['cycle_id'], inventory_sha256=inventory_digest)


def test_retry_success_binds_one_source_runtime_and_recovers_exact_receipt(scheduled):
    fixture, outcome, sink, cycle, payload = _prepare(scheduled)
    factory = Mock(side_effect=fixture.remote)
    with pytest.raises(ValueError, match='inventory_changed'):
        _publish(fixture, sink, cycle, factory, '0' * 64)
    factory.assert_not_called()

    result = _publish(fixture, sink, cycle, factory, _digest(payload))
    assert result['state'] == 'SYNC_CONFIRMED', result
    assert result['binding'] == {
        'request_id': 'temporary-retry:' + outcome['outcome_id'],
        'company_id': cycle['company_id'], 'source_revision': outcome['identity']['source_revision'],
        'release_id': 'NO_RELEASE', 'release_binding_sha256': _digest(fixture.runtime),
    }
    assert result['inventory_sha256'] == _digest(payload)
    assert len(fixture.service.batches) > 0
    factory.reset_mock()
    assert _publish(fixture, sink, cycle, factory, _digest(payload)) == result
    factory.assert_not_called()
    fixture.fetch.assert_called_once()
    with closing(State(str(fixture.state_path), readonly=True)) as state:
        saved = state.cycle(cycle['cycle_id'])
        assert saved['status'] == 'Complete'
        assert saved['companies'][cycle['company_id']]['stage'] == 'complete'


def test_retry_workbook_source_drift_holds_before_exact_local_apply(scheduled):
    fixture, _outcome, sink, cycle, payload = _prepare(scheduled)
    remote = fixture.remote()
    with writer_lock(fixture.root / 'scraper.lock'), writer_lock(fixture.root / 'writer.lock'):
        remote.commit([{'tab': 'Companies', 'identity': {'Company ID': cycle['company_id']},
                        'values': {'Automatic Retry?': 'No'}}])
    batches = list(fixture.service.batches)
    result = _publish(fixture, sink, cycle, fixture.remote, _digest(payload))
    assert result['state'] == 'PUBLICATION_HELD', result
    assert 'workbook_company_changed' in result['held'][0]['reason']
    assert fixture.service.batches == batches
    with closing(fixture.local()) as local:
        assert local.db.execute(
            'SELECT COUNT(*) FROM exact_local_applications WHERE cycle=?', (cycle['cycle_id'],)
        ).fetchone()[0] == 0


def test_retry_lost_sheets_response_reuses_original_intent_and_does_not_redispatch(scheduled):
    fixture, _outcome, sink, cycle, payload = _prepare(scheduled)
    fixture.service.lose_response = True
    held = _publish(fixture, sink, cycle, fixture.remote, _digest(payload))
    assert held['state'] == 'PUBLICATION_HELD', held
    assert held['held'] == [{'company_id': cycle['company_id'], 'reason': 'uncertain_write'}]
    with closing(InventoryInbox(fixture.root / 'inventories.sqlite3', sink.reader.spreadsheet_id)) as inbox:
        first_intent = inbox.exact_remote_state(cycle['cycle_id'], cycle['company_id'])
        assert first_intent['state'] == 'SYNC_PENDING'
        assert first_intent['first_attempt_claimed']
    batches = list(fixture.service.batches)
    assert batches
    receipt = _publish(fixture, sink, cycle, fixture.remote, _digest(payload))
    assert receipt['state'] == 'SYNC_CONFIRMED', receipt
    assert receipt['intent_id'] == first_intent['intent_id']
    assert receipt['receipt_id'] == first_intent['receipt_id']
    assert fixture.service.batches == batches
    fixture.fetch.assert_called_once()
