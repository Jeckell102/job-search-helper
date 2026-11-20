"""Disposable selected retry admission through the actual ordinary Engine."""
from contextlib import closing
from datetime import timedelta
import json
from unittest.mock import patch

import pytest

from job_search_helper.cli import writer_lock
from job_search_helper.engine import Engine, State
from job_search_helper.scan_request import cycle_metadata
from job_search_helper.selected_temporary_retry_admission import admit_selected_temporary_retry_locked
from test_temporary_retry import close_fixture_blocker, selected  # noqa: F401, shared fixture


@pytest.fixture
def scheduled(selected, monkeypatch):
    fixture, outcome, clock, make_sink = selected
    sink = make_sink()
    assert sink.ingest_immutable(outcome)['disposition'] == 'ACCEPTED'
    clock[0] += timedelta(minutes=6)

    def forbidden(*args, **kwargs):
        raise AssertionError('Selected admission entered broad startup, sync, cleanup, or fetch.')

    monkeypatch.setattr('job_search_helper.runner.run_start', forbidden)
    monkeypatch.setattr('job_search_helper.run_sync.run_scoped_sync', forbidden)
    monkeypatch.setattr('job_search_helper.closed_jobs.stage_closed_pending', forbidden)
    monkeypatch.setattr('job_search_helper.cli.get_remote_repository', forbidden)
    monkeypatch.setattr('job_search_helper.ats.fetch_inventory', forbidden)
    return fixture, outcome, sink


def view(fixture, outcome):
    with closing(fixture.local()) as reader:
        company, = reader.matches('Companies', {'Company ID': outcome['identity']['company_id']})
        return {'spreadsheet_id': reader.spreadsheet_id, 'profile': reader.get_meta('sheets_profile'), 'company': company[1],
                'cycles': reader.read('Scan Cycles')}


def admit(fixture, sink, *, snapshot=None, runtime=None):
    with (writer_lock(fixture.root / 'scraper.lock'), writer_lock(fixture.root / 'writer.lock'),
          closing(State(str(fixture.state_path), readonly=True)) as state):
        return admit_selected_temporary_retry_locked(
            sink, state, fixture.runtime if runtime is None else runtime, workbook_snapshot=snapshot)


def successors(fixture):
    with closing(State(str(fixture.state_path), readonly=True)) as state:
        return [cycle for cycle in state.cycles() if cycle.get('temporary_retry')]


def test_real_historical_cycle_is_authoritative_and_workbook_proof_is_required(scheduled):
    fixture, outcome, sink = scheduled
    ready = view(fixture, outcome)
    ready['cycles'] = []
    ledger, = sink.directory.glob('*.json')
    before = ledger.read_bytes()
    blocker = fixture.manifest['cycle_id']
    with patch('job_search_helper.selected_temporary_retry_admission.Engine.start_cycle',
               side_effect=AssertionError('held work must never start')):
        held = admit(fixture, sink, snapshot=ready)
        assert held['state'] == 'HELD_UNFINISHED_CYCLE'
        assert held['blocking_cycle_ids'] == [blocker]
        close_fixture_blocker(fixture, mirror=False)
        assert admit(fixture, sink, snapshot=ready)['blocking_cycle_ids'] == [blocker]
        close_fixture_blocker(fixture)
        assert admit(fixture, sink)['state'] == 'HELD_WORKBOOK_SNAPSHOT_REQUIRED'
        remote_only = {**ready, 'cycles': [{'Cycle ID': 'CYC-REMOTE', 'Cycle Status': 'In Progress'}]}
        assert admit(fixture, sink, snapshot=remote_only)['blocking_cycle_ids'] == ['CYC-REMOTE']
        claimed = {**ready, 'company': {**ready['company'], 'Claim Token': 'another-owner'}}
        assert admit(fixture, sink, snapshot=claimed)['state'] == 'HELD_WORKBOOK_COMPANY'
        previous = {**ready, 'cycles': [{'Cycle ID': 'CYC-REMOTE', 'Cycle Status': 'Complete',
                                        'Notes': json.dumps({'start_request_id': 'temporary-retry:' + outcome['outcome_id']})}]}
        assert admit(fixture, sink, snapshot=previous)['state'] == 'HELD_WORKBOOK_SUCCESSOR_EXISTS'
        with closing(fixture.local(write=True)) as writer:
            writer.commit([{'tab': 'Companies', 'identity': {'Company ID': outcome['identity']['company_id']},
                            'values': {'Scan State': 'Blocked / Manual Review'}}])
        assert admit(fixture, sink, snapshot=ready)['state'] == 'HELD_LOCAL_COMPANY'
    assert ledger.read_bytes() == before
    assert successors(fixture) == []


def test_one_pinned_ordinary_cycle_is_saved_without_queue_writer_or_scan(scheduled):
    fixture, outcome, sink = scheduled
    close_fixture_blocker(fixture)
    full = view(fixture, outcome)
    snapshot = {**full, 'cycles': None, 'company': {
        key: full['company'][key] for key in ('Company ID', 'Company Status', 'Official Careers URL')}}
    with closing(fixture.local()) as reader:
        before = {tab: reader.read(tab) for tab in ('Job History', 'Job Evidence', 'Opportunities')}
    result = admit(fixture, sink, snapshot=snapshot)
    assert result['state'] == 'ADMITTED_LOCAL_CYCLE'
    assert result['recovered'] is False
    cycle, = successors(fixture)
    assert cycle['id'] == result['cycle_id']
    assert cycle['runtime_binding'] == fixture.runtime
    assert cycle['request_fingerprint'] == result['request_fingerprint']
    assert cycle['all'] is False and cycle['supersedes'] == []
    assert list(cycle['companies']) == [outcome['identity']['company_id']]
    assert cycle['temporary_retry']['outcome_id'] == outcome['outcome_id']
    assert cycle['temporary_retry']['retry_index'] == cycle['temporary_retry']['retry_cap'] == 1
    with closing(fixture.local()) as reader:
        (row_id, mirror), = reader.matches('Scan Cycles', {'Cycle ID': cycle['id']})
        assert row_id and cycle_metadata(mirror)['runtime_binding'] == fixture.runtime
        assert {tab: reader.read(tab) for tab in before} == before
    assert not fixture.queue_path.exists()
    assert not (fixture.root / 'last-scan-request.json').exists()
    assert admit(fixture, sink) == {**result, 'recovered': True}
    changed = {**fixture.runtime, 'config_sha256': 'a' * 64}
    with pytest.raises(ValueError, match='runtime differs'):
        admit(fixture, sink, snapshot=snapshot, runtime=changed)
    assert successors(fixture) == [cycle]


@pytest.mark.parametrize(('interruption', 'held'), [
    ('before-state', 'HELD_CLAIM_WITHOUT_STATE'),
    ('after-state', 'HELD_ADMISSION_PARTIAL'),
    ('before-membership', 'HELD_ADMISSION_PARTIAL'),
    ('after-all', 'ADMITTED_LOCAL_CYCLE'),
])
def test_interrupted_admission_reconciles_state_without_second_start(scheduled, interruption, held):
    fixture, outcome, sink = scheduled
    close_fixture_blocker(fixture)
    snapshot = view(fixture, outcome)
    original_start = Engine.start_cycle
    original_commit = Engine._commit

    def lose_after_start(engine, *args, **kwargs):
        original_start(engine, *args, **kwargs)
        raise OSError('fixture interruption')

    def lose_before_membership(engine, *operations):
        if any(operation['tab'] == 'Companies' for operation in operations):
            raise OSError('fixture interruption')
        return original_commit(engine, *operations)

    fault = {
        'before-state': patch.object(Engine, 'start_cycle', side_effect=OSError('fixture interruption')),
        'after-state': patch.object(Engine, '_sync_cycle', side_effect=OSError('fixture interruption')),
        'before-membership': patch.object(Engine, '_commit', lose_before_membership),
        'after-all': patch.object(Engine, 'start_cycle', lose_after_start),
    }[interruption]
    with fault, pytest.raises(OSError, match='fixture interruption'):
        admit(fixture, sink, snapshot=snapshot)
    with patch.object(Engine, 'start_cycle', side_effect=AssertionError('a spent claim cannot start')):
        replay = admit(fixture, sink, snapshot=snapshot)
        assert replay['state'] == held
        assert admit(fixture, sink) == replay
    rows = successors(fixture)
    assert len(rows) == (0 if interruption == 'before-state' else 1)
    if rows:
        assert replay['cycle_id'] == rows[0]['id']
    assert not fixture.queue_path.exists()


def test_same_hash_newer_source_event_still_refuses_admission(scheduled):
    fixture, outcome, sink = scheduled
    close_fixture_blocker(fixture)
    snapshot = view(fixture, outcome)
    identity = {'Company ID': outcome['identity']['company_id']}
    with closing(fixture.local(write=True)) as writer:
        for url in ('https://jobs.jobvite.com/another/search', snapshot['company']['Official Careers URL']):
            writer.mutate_company_with_event({'tab': 'Companies', 'identity': identity,
                                              'values': {'Official Careers URL': url}})
    assert admit(fixture, sink, snapshot=snapshot)['state'] == 'HELD_SOURCE_CHANGED'
    assert successors(fixture) == []
