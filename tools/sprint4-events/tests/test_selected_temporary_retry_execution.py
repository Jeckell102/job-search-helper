"""One synthetic provider invocation for an exact ordinary selected successor."""
from contextlib import closing
import json
import os
from unittest.mock import Mock, patch

import pytest

from job_search_helper import ats, selected_temporary_retry_execution as execution
from job_search_helper.cli import writer_lock
from job_search_helper.engine import Engine, State
from job_search_helper.inbox import InventoryInbox
from job_search_helper.temporary_retry import SelectedTemporaryRetrySink, _selected_sha
from test_retained_operator_run import BOARD
from test_selected_temporary_retry_admission import admit, scheduled, view  # noqa: F401, shared fixture
from test_temporary_retry import close_fixture_blocker, selected  # noqa: F401, nested fixture


@pytest.fixture
def admitted(scheduled, monkeypatch):
    fixture, outcome, sink = scheduled
    close_fixture_blocker(fixture)
    result = admit(fixture, sink, snapshot=view(fixture, outcome))
    assert result['state'] == 'ADMITTED_LOCAL_CYCLE'

    def forbidden(*args, **kwargs):
        raise AssertionError('Selected fixture execution entered the ordinary engine.')

    monkeypatch.setattr(Engine, 'start_cycle', forbidden)
    monkeypatch.setattr('job_search_helper.local_pipeline.LocalPipeline.run', forbidden)
    return fixture, outcome, sink, result['cycle_id']


def freeze(fixture, sink, cycle_id, provider, *, runtime=None):
    with (writer_lock(fixture.root / 'scraper.lock'), writer_lock(fixture.root / 'writer.lock'),
          closing(State(str(fixture.state_path), readonly=True)) as state):
        return execution.freeze_selected_temporary_retry_locked(
            sink, state, runtime or fixture.runtime, cycle_id=cycle_id, fetcher=provider)


def journal(fixture, cycle_id):
    return fixture.root / 'selected-retry-inventory' / (cycle_id + '.json')


def snapshot(fixture):
    with closing(fixture.local()) as local, closing(State(str(fixture.state_path), readonly=True)) as state:
        return (state.cycles(), {tab: local.read(tab) for tab in local.schemas},
                fixture.inbox_path.read_bytes(), fixture.service.get_calls.copy(), fixture.service.batches.copy())


def inventory(*, status='complete', failure=None, board=BOARD):
    return ats.Inventory(status, jobs=[{'posting_id': 'fixture-job', 'title': 'Fixture job'}],
                         source_url=board, ats='Jobvite', outcome_failure=failure)


@pytest.mark.parametrize('status', ['complete', 'partial'])
def test_exact_frozen_inventory_replays_without_ordinary_writes(admitted, status):
    fixture, outcome, sink, cycle_id = admitted
    failure = ats.outcome_failure('temporary_transport', 'retryable_http_status') if status == 'partial' else None
    provider = Mock(return_value=inventory(status=status, failure=failure))
    before = snapshot(fixture)
    first = freeze(fixture, sink, cycle_id, provider)
    assert first == {'state': 'INVENTORY_FROZEN', 'cycle_id': cycle_id,
                     'company_id': outcome['identity']['company_id'], 'outcome_id': outcome['outcome_id'],
                     'inventory_sha256': first['inventory_sha256'], 'inventory_status': status,
                     'job_count': 1, 'recovered': False}
    provider.assert_called_once_with('Jobvite', BOARD, outcome['identity']['company_id'], 'Samtec')
    frozen = journal(fixture, cycle_id)
    original = frozen.read_bytes()
    evidence = json.loads(original)
    assert evidence['inventory']['outcome_failure'] == failure
    assert evidence['inventory']['jobs'] == [{'posting_id': 'fixture-job', 'title': 'Fixture job'}]
    assert evidence['binding']['runtime'] == fixture.runtime
    assert evidence['binding']['request']['temporary_retry']['outcome_id'] == outcome['outcome_id']
    assert evidence['binding']['original_outcome']['outcome_sha256'] == _selected_sha(outcome)
    assert freeze(fixture, sink, cycle_id, provider) == {**first, 'recovered': True}
    provider.assert_called_once()
    assert frozen.read_bytes() == original
    assert snapshot(fixture) == before
    assert not fixture.queue_path.exists()


@pytest.mark.parametrize('fault', ['provider', 'wrong-board', 'before-freeze', 'after-freeze'])
def test_fault_replay_is_bounded(admitted, monkeypatch, fault):
    fixture, _outcome, sink, cycle_id = admitted
    provider = Mock(return_value=inventory(board='https://jobs.jobvite.com/unrelated/search'
                                           if fault == 'wrong-board' else BOARD),
                    side_effect=OSError('fixture provider interrupted') if fault == 'provider' else None)
    write = execution._write_record

    def interrupt(path, record, *, initial):
        if initial or fault == 'after-freeze':
            write(path, record, initial=initial)
        if not initial:
            raise OSError('fixture freeze acknowledgement interrupted')

    before = snapshot(fixture)
    if fault in ('before-freeze', 'after-freeze'):
        with monkeypatch.context() as patch:
            patch.setattr(execution, '_write_record', interrupt)
            with pytest.raises(OSError, match='fixture freeze'):
                freeze(fixture, sink, cycle_id, provider)
    else:
        with pytest.raises(ValueError if fault == 'wrong-board' else OSError):
            freeze(fixture, sink, cycle_id, provider)
    saved = journal(fixture, cycle_id)
    original = saved.read_bytes()
    replay = freeze(fixture, sink, cycle_id, provider)
    assert replay['state'] == ('INVENTORY_FROZEN' if fault == 'after-freeze' else 'HELD_FETCH_UNCERTAIN')
    assert saved.read_bytes() == original
    assert snapshot(fixture) == before
    provider.assert_called_once()


def test_process_exit_inside_provider_preserves_one_durable_claim(admitted):
    fixture, _outcome, sink, cycle_id = admitted
    child = os.fork()
    if child == 0:
        try:
            with closing(fixture.local()) as reader:
                child_sink = SelectedTemporaryRetrySink(
                    reader, fixture.root, outcome_id=sink.outcome_id, request_sha256=sink.request_sha256,
                    reservation_digest=sink.reservation_digest, clock=sink.clock)
                freeze(fixture, child_sink, cycle_id, staticmethod(lambda *_args: os._exit(73)))
        finally:
            os._exit(74)
    _, status = os.waitpid(child, 0)
    assert os.waitstatus_to_exitcode(status) == 73
    saved = journal(fixture, cycle_id)
    original = saved.read_bytes()
    assert json.loads(original)['state'] == 'CLAIMED'
    provider = Mock(return_value=inventory())
    assert freeze(fixture, sink, cycle_id, provider)['state'] == 'HELD_FETCH_UNCERTAIN'
    assert saved.read_bytes() == original
    provider.assert_not_called()


@pytest.mark.parametrize('when', ['before', 'during', 'after'])
def test_newer_revision_with_same_hash_holds_without_refetch(admitted, when):
    fixture, outcome, sink, cycle_id = admitted
    cid = outcome['identity']['company_id']

    def drift():
        with closing(fixture.local(write=True)) as writer:
            for url in ('https://jobs.jobvite.com/another/search', BOARD):
                writer.mutate_company_with_event({'tab': 'Companies', 'identity': {'Company ID': cid},
                                                  'values': {'Official Careers URL': url}})

    def fetch(*_args):
        if when == 'during':
            drift()
        return inventory()

    provider = Mock(side_effect=fetch)
    if when == 'before':
        drift()
    first = freeze(fixture, sink, cycle_id, provider)
    if when == 'after':
        assert first['state'] == 'INVENTORY_FROZEN'
        drift()
    else:
        assert first['state'] == 'HELD_SOURCE_CHANGED'
    record = journal(fixture, cycle_id)
    original = record.read_bytes() if record.exists() else None
    held = freeze(fixture, sink, cycle_id, provider)
    assert held['state'] == 'HELD_SOURCE_CHANGED'
    if when == 'before':
        provider.assert_not_called()
        assert not record.exists()
    else:
        provider.assert_called_once()
        assert json.loads(original)['inventory_sha256'] == held['inventory_sha256']
        assert record.read_bytes() == original
    with closing(State(str(fixture.state_path), readonly=True)) as state:
        item = state.cycle(cycle_id)['companies'][cid]
        assert item['outcome_source_revision'] == outcome['identity']['source_revision']
        assert item['stage'] == 'queued'


def test_exact_cycle_claim_runtime_and_generic_work_gates(admitted):
    fixture, outcome, sink, cycle_id = admitted
    provider = Mock(return_value=inventory())
    cid = outcome['identity']['company_id']
    queue = fixture.queue_path
    queue.write_text('{"unrelated":true}')
    assert freeze(fixture, sink, cycle_id, provider)['state'] == 'HELD_REQUEST_SLOT'
    queue.unlink()
    with pytest.raises(ValueError, match='runtime differs'):
        freeze(fixture, sink, cycle_id, provider, runtime={**fixture.runtime, 'config_sha256': 'e' * 64})
    with pytest.raises(ValueError, match='exact saved cycle'):
        freeze(fixture, sink, fixture.manifest['cycle_id'], provider)
    with closing(State(str(fixture.state_path))) as state:
        historical = state.cycle(fixture.manifest['cycle_id'])
        state.save_cycle({**historical, 'status': 'In Progress'})
    assert freeze(fixture, sink, cycle_id, provider)['blocking_cycle_ids'] == [historical['id']]
    close_fixture_blocker(fixture)
    with closing(InventoryInbox(fixture.inbox_path, sink.reader.spreadsheet_id)) as inbox:
        with inbox.connection:
            inbox.connection.execute('INSERT INTO inventories (cycle,company,payload) VALUES (?,?,?)',
                                     (cycle_id, cid, '{"generic":true}'))
    assert freeze(fixture, sink, cycle_id, provider)['state'] == 'HELD_ORDINARY_WORK_PRESENT'
    provider.assert_not_called()
    assert not journal(fixture, cycle_id).exists()


def test_changed_saved_source_never_gets_refreshed(admitted):
    fixture, outcome, sink, cycle_id = admitted
    cid = outcome['identity']['company_id']
    with closing(State(str(fixture.state_path))) as state:
        cycle = state.cycle(cycle_id)
        cycle['companies'][cid]['outcome_source_revision'] = 'e' * 64
        state.save_cycle(cycle)
    provider = Mock(return_value=inventory())
    with pytest.raises(ValueError, match='saved source'):
        freeze(fixture, sink, cycle_id, provider)
    provider.assert_not_called()
    assert not journal(fixture, cycle_id).exists()


def test_provider_entry_requires_a_callable(admitted):
    fixture, _outcome, sink, cycle_id = admitted
    with (writer_lock(fixture.root / 'scraper.lock'), writer_lock(fixture.root / 'writer.lock'),
          closing(State(str(fixture.state_path), readonly=True)) as state):
        with pytest.raises(ValueError, match='exact sink and a provider'):
            execution.freeze_selected_temporary_retry_locked(
                sink, state, fixture.runtime, cycle_id=cycle_id, fetcher=None)
        result = execution.freeze_selected_temporary_retry_locked(
            sink, state, fixture.runtime, cycle_id=cycle_id,
            fetcher=Mock(return_value=inventory()))
    assert result['state'] == 'INVENTORY_FROZEN'
