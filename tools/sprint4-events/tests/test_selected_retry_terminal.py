"""No-publication settlement and restart proof for the signed retry path."""
from contextlib import closing
from unittest.mock import Mock, patch

import pytest

from job_search_helper import ats
from job_search_helper.cli import writer_lock
from job_search_helper.engine import Engine, State
from job_search_helper.inbox import InventoryInbox
from job_search_helper.retained_operator_command import _retry_workbook_guard
from job_search_helper.retained_work_runner import assert_normal_lifecycle_not_held
from job_search_helper.selected_temporary_retry_publication import publish_frozen_selected_retry_locked
from test_retained_operator_run import BOARD, COMPANY_ID
from test_selected_temporary_retry_admission import scheduled
from test_selected_temporary_retry_execution import admitted, freeze, journal
from test_temporary_retry import selected


def _terminal(scenario):
    code = {
        'failed': ('temporary_transport', 'retryable_http_status'),
        'blocked': ('access_denied', 'public_access_denied'),
    }.get(scenario)
    return ats.Inventory(
        'complete' if scenario in {'zero', 'empty'} else scenario,
        source_url=BOARD, ats='Jobvite', browser_fallback_allowed=False,
        outcome_failure=ats.outcome_failure(*code) if code else None,
        verified_zero='samtec_jobvite_explicit_zero' if scenario == 'zero' else None,
    )


def _publish(fixture, sink, cycle_id, reader, writer):
    with (writer_lock(fixture.root / 'scraper.lock'), writer_lock(fixture.root / 'writer.lock'),
          closing(fixture.local(write=True)) as repository, closing(State(str(fixture.state_path))) as state,
          closing(InventoryInbox(fixture.inbox_path, sink.reader.spreadsheet_id)) as inbox):
        engine = Engine(repository, state, inbox=inbox, runtime_binding=fixture.runtime)
        return publish_frozen_selected_retry_locked(
            sink, engine, writer, cycle_id=cycle_id,
            workbook_guard=lambda company: _retry_workbook_guard(sink, reader, company),
        )


@pytest.mark.parametrize(('scenario', 'disposition', 'stage', 'scan_state'), [
    ('failed', 'HELD_TEMPORARY_RETRY_CAP', 'failed', 'Failed'),
    ('blocked', 'HELD_ACCESS_DENIED', 'blocked', 'Blocked / Manual Review'),
    ('zero', 'VERIFIED_ZERO', 'complete', 'Complete'),
])
def test_exact_terminal_retry_has_one_outcome_and_no_publication(admitted, scenario, disposition, stage, scan_state):
    fixture, parent, sink, cycle_id = admitted
    provider = Mock(return_value=_terminal(scenario))
    assert freeze(fixture, sink, cycle_id, provider)['state'] == 'INVENTORY_FROZEN'
    before = journal(fixture, cycle_id).read_bytes()
    reader, writer = Mock(side_effect=fixture.remote), Mock()
    batches = list(fixture.service.batches)
    with closing(fixture.local()) as local:
        jobs = local.read('Job History')
        dirty = local.db.execute('SELECT * FROM dirty ORDER BY tab,row_id,header').fetchall()
    result = _publish(fixture, sink, cycle_id, reader, writer)
    assert result['state'] == disposition
    assert _publish(fixture, sink, cycle_id, reader, writer) == result
    reader.assert_called_once()
    writer.assert_not_called()
    provider.assert_called_once()
    assert batches == fixture.service.batches
    assert journal(fixture, cycle_id).read_bytes() == before
    with closing(fixture.local()) as local, closing(State(str(fixture.state_path), readonly=True)) as state:
        cycle = state.cycle(cycle_id)
        assert cycle['companies'][COMPANY_ID]['stage'] == stage
        assert cycle['selected_retry_terminal_sha256'] == result['receipt_sha256']
        assert local.read('Job History') == jobs
        assert local.db.execute('SELECT * FROM dirty ORDER BY tab,row_id,header').fetchall() == dirty
        company = local.matches('Companies', {'Company ID': COMPANY_ID})[0][1]
        assert not company['Active Cycle ID']
        assert company['Scan State'] == scan_state
        assert local.db.execute('SELECT COUNT(*) FROM selected_retry_terminal_receipts').fetchone() == (1,)
        assert local.db.execute('SELECT COUNT(*) FROM scrape_outcomes WHERE request_id=?',
                                ('temporary-retry:' + parent['outcome_id'],)).fetchone() == (1,)
    assert_normal_lifecycle_not_held(fixture.root, fixture.jobs_path)


def test_terminal_retry_state_crash_recovers_durable_receipt(admitted):
    fixture, _parent, sink, cycle_id = admitted
    provider = Mock(return_value=_terminal('failed'))
    freeze(fixture, sink, cycle_id, provider)
    reader, writer = Mock(side_effect=fixture.remote), Mock()
    with patch.object(State, 'save_cycle', side_effect=RuntimeError('interrupted before State commit')):
        with pytest.raises(RuntimeError, match='interrupted before State'):
            _publish(fixture, sink, cycle_id, reader, writer)
    with pytest.raises(ValueError, match='Selected retry owns this cycle'):
        assert_normal_lifecycle_not_held(fixture.root, fixture.jobs_path)
    result = _publish(fixture, sink, cycle_id, reader, writer)
    assert result['state'] == 'HELD_TEMPORARY_RETRY_CAP'
    assert _publish(fixture, sink, cycle_id, reader, writer) == result
    provider.assert_called_once()
    reader.assert_called_once()
    writer.assert_not_called()


def test_ambiguous_empty_does_not_clear_the_cycle(admitted):
    fixture, _parent, sink, cycle_id = admitted
    freeze(fixture, sink, cycle_id, Mock(return_value=_terminal('empty')))
    reader, writer = Mock(), Mock()
    assert _publish(fixture, sink, cycle_id, reader, writer)['state'] == 'HELD_NO_PUBLISHABLE_RETRY_INVENTORY'
    reader.assert_not_called()
    writer.assert_not_called()
    with pytest.raises(ValueError, match='Selected retry owns this cycle'):
        assert_normal_lifecycle_not_held(fixture.root, fixture.jobs_path)


def test_interrupted_jobs_transaction_keeps_cycle_queued_and_can_retry(admitted):
    fixture, _parent, sink, cycle_id = admitted
    provider = Mock(return_value=_terminal('failed'))
    freeze(fixture, sink, cycle_id, provider)
    reader, writer = Mock(side_effect=fixture.remote), Mock()
    from job_search_helper.sqlite_repository import SQLiteRepository
    commit = SQLiteRepository._commit_in_transaction

    def interrupt(repository, operations):
        commit(repository, operations)
        raise RuntimeError('interrupted after local controls changed')

    with patch.object(SQLiteRepository, '_commit_in_transaction', interrupt):
        with pytest.raises(RuntimeError, match='after local controls changed'):
            _publish(fixture, sink, cycle_id, reader, writer)
    with closing(fixture.local()) as local:
        company = local.matches('Companies', {'Company ID': COMPANY_ID})[0][1]
        assert (company['Active Cycle ID'], company['Scan State']) == (cycle_id, 'Queued')
        assert local.db.execute('SELECT COUNT(*) FROM scrape_outcomes').fetchone() == (1,)
        assert not local.db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='selected_retry_terminal_receipts'").fetchone()
    assert _publish(fixture, sink, cycle_id, reader, writer)['state'] == 'HELD_TEMPORARY_RETRY_CAP'
    assert reader.call_count == 2
    provider.assert_called_once()
    writer.assert_not_called()


def test_replay_after_state_commit_ignores_later_company_owner(admitted):
    fixture, _parent, sink, cycle_id = admitted
    freeze(fixture, sink, cycle_id, Mock(return_value=_terminal('failed')))
    reader, writer = Mock(side_effect=fixture.remote), Mock()
    save = State.save_cycle

    def interrupt(state, cycle):
        save(state, cycle)
        raise RuntimeError('interrupted after State commit')

    with patch.object(State, 'save_cycle', interrupt):
        with pytest.raises(RuntimeError, match='after State commit'):
            _publish(fixture, sink, cycle_id, reader, writer)
    owner = {'Active Cycle ID': 'CYC-LATER', 'Scan State': 'Queued'}
    with closing(fixture.local(write=True)) as local:
        local.commit([{'tab': 'Companies', 'identity': {'Company ID': COMPANY_ID}, 'values': owner}])
    assert _publish(fixture, sink, cycle_id, reader, writer)['state'] == 'HELD_TEMPORARY_RETRY_CAP'
    reader.assert_called_once()
    writer.assert_not_called()
    with closing(fixture.local()) as local:
        company = local.matches('Companies', {'Company ID': COMPANY_ID})[0][1]
        assert all(company[key] == value for key, value in owner.items())


def test_terminal_retry_workbook_drift_and_generic_writer_alias_are_held(admitted):
    from job_search_helper.repository import RepositoryError

    fixture, parent, sink, cycle_id = admitted
    freeze(fixture, sink, cycle_id, Mock(return_value=_terminal('failed')))
    fields = {
        'company_id': COMPANY_ID, 'cycle_id': cycle_id,
        'source_revision': parent['identity']['source_revision'],
        'source_current': True, 'inventory_status': 'failed', 'failure': {'category': 'temporary_transport'},
    }
    with closing(fixture.local(write=True)) as local:
        for identity in (
            {'request_id': 'an-unrelated-request'},
            {'request_id': 'temporary-retry:' + parent['outcome_id']},
            {'request_id': 'temporary-retry:' + parent['outcome_id'],
             'temporary_retry_outcome_id': parent['outcome_id'], 'cycle_id': 'CYC-OTHER'},
        ):
            with pytest.raises(RepositoryError, match='sealed terminal writer|temporary retry outcome identity'):
                local.record_scrape_outcome({**fields, **identity})
    remote = fixture.remote()
    fixture.service.before_write = lambda: fixture.assert_held('scraper.lock', 'writer.lock')
    with writer_lock(fixture.root / 'scraper.lock'), writer_lock(fixture.root / 'writer.lock'):
        remote.commit([{'tab': 'Companies', 'identity': {'Company ID': COMPANY_ID},
                        'values': {'Automatic Retry?': 'No'}}])
    batches = list(fixture.service.batches)
    writer = Mock()
    with pytest.raises(ValueError, match='workbook_company_changed'):
        _publish(fixture, sink, cycle_id, fixture.remote, writer)
    assert fixture.service.batches == batches
    writer.assert_not_called()
    with pytest.raises(ValueError, match='Selected retry owns this cycle'):
        assert_normal_lifecycle_not_held(fixture.root, fixture.jobs_path)


def test_terminal_retry_holds_orphan_publication_intent(admitted):
    fixture, _parent, sink, cycle_id = admitted
    freeze(fixture, sink, cycle_id, Mock(return_value=_terminal('failed')))
    with closing(InventoryInbox(fixture.inbox_path, sink.reader.spreadsheet_id)) as inbox, inbox.connection:
        inbox.connection.execute(
            'INSERT INTO exact_remote_plans(cycle,company,local_plan_digest,projection,projection_digest,'
            'receipt_id,intent_id,state,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)',
            (cycle_id, COMPANY_ID, 'local', '[]', 'projection', 'receipt', 'intent',
             'SYNC_PENDING', 'created', 'updated'),
        )
    reader, writer = Mock(), Mock()
    with pytest.raises(ValueError, match='terminal_publication_present'):
        _publish(fixture, sink, cycle_id, reader, writer)
    reader.assert_not_called()
    writer.assert_not_called()


def test_terminal_retry_does_not_accept_source_returned_to_same_url(admitted):
    fixture, parent, sink, cycle_id = admitted
    freeze(fixture, sink, cycle_id, Mock(return_value=_terminal('failed')))
    with closing(fixture.local(write=True)) as local:
        for url in ('https://jobs.jobvite.com/another/search', BOARD):
            local.mutate_company_with_event({
                'tab': 'Companies', 'identity': {'Company ID': COMPANY_ID},
                'values': {'Official Careers URL': url},
            })
        from job_search_helper.company_events import current_company_source_revision
        assert current_company_source_revision(local, COMPANY_ID) == parent['identity']['source_revision']
    reader, writer = Mock(), Mock()
    with pytest.raises(ValueError, match='terminal_source_changed'):
        _publish(fixture, sink, cycle_id, reader, writer)
    reader.assert_not_called()
    writer.assert_not_called()


@pytest.mark.parametrize('mode', ['pending-browser', 'claimed-fetch'])
def test_incomplete_retry_evidence_preserves_selected_hold(admitted, mode):
    fixture, _parent, sink, cycle_id = admitted
    reader, writer = Mock(), Mock()
    if mode == 'claimed-fetch':
        provider = Mock(side_effect=RuntimeError('interrupted provider result'))
        with pytest.raises(RuntimeError, match='interrupted provider result'):
            freeze(fixture, sink, cycle_id, provider)
        with pytest.raises(ValueError, match='no verified frozen inventory'):
            _publish(fixture, sink, cycle_id, reader, writer)
    else:
        pending = _terminal('failed')
        pending.browser_pending_urls = [BOARD + '?page=2']
        provider = Mock(return_value=pending)
        freeze(fixture, sink, cycle_id, provider)
        assert _publish(fixture, sink, cycle_id, reader, writer)['state'] == 'HELD_NO_PUBLISHABLE_RETRY_INVENTORY'
    provider.assert_called_once()
    reader.assert_not_called()
    writer.assert_not_called()
    with pytest.raises(ValueError, match='Selected retry owns this cycle'):
        assert_normal_lifecycle_not_held(fixture.root, fixture.jobs_path)
