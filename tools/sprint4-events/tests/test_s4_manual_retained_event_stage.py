"""Fixture-only manual retained staging; no signer or lifecycle factories."""
import json
from pathlib import Path
import socket

import pytest

from job_search_helper.cli import PROJECT_ROOT, WriterLockBusy, scraper_lock_name, writer_lock
from job_search_helper.company_events import (
    BRIDGE_CONSUMER, MANUAL_RETAINED_HOLD, MANUAL_RETAINED_SCHEMA, CompanyEventBridge, _json_digest,
)
from job_search_helper.company_intake_dispatcher import CompanyIntakeDispatcher
from job_search_helper.engine import Engine, State
from job_search_helper.repository import SCHEMAS
from job_search_helper.retained_work_exception import _request_provenance
from job_search_helper.scan_request import _read_request, requested_scan, verify_queued_event_for_normal_resume
from job_search_helper.sqlite_repository import SQLiteRepository


def company(company_id):
    return {'Company': company_id, 'Company ID': company_id, 'Company Status': 'Active',
            'Official Careers URL': 'https://example.test/jobs/' + company_id,
            'ATS / Source': 'Greenhouse'}


@pytest.fixture
def stores(tmp_path, monkeypatch):
    assert PROJECT_ROOT == Path(__file__).resolve().parents[1]
    def unexpected_connection(*args, **kwargs):
        pytest.fail('fixture attempted a network connection')
    monkeypatch.setattr(socket.socket, 'connect', unexpected_connection)
    monkeypatch.setattr(socket.socket, 'connect_ex', unexpected_connection)
    state = State(tmp_path / 'state.db')
    repo = SQLiteRepository(tmp_path / 'jobs.sqlite3', 'fixture-book', initialize=True)
    repo.set_meta('ready', 'yes')
    for tab in SCHEMAS:
        repo.import_rows(tab, [])
    repo.import_rows('Companies', enumerate([company('HISTORICAL'), company('TARGET')], 2))
    blocker = {'id': 'CYC-HISTORICAL', 'all': False, 'status': 'In Progress',
               'started_at': '2026-11-20T12:00:00+00:00',
               'companies': {'HISTORICAL': {'stage': 'queued'}}}
    Engine(repo, state)._sync_cycle(blocker)
    event = repo.mutate_company_with_event({
        'tab': 'Companies', 'identity': {'Company ID': 'TARGET'},
        'values': {'Official Careers URL': 'https://example.test/jobs/changed'},
    })['company_event']
    bridge = CompanyEventBridge(repo, tmp_path)
    try:
        yield repo, state, bridge, event, blocker
    finally:
        state.close()
        repo.close()


def scope(event, blocker):
    return {'company_id': event['company_id'], 'source_revision': event['source_revision'],
            'blocking_cycle_id': blocker['id']}


def receipt_path(bridge, event):
    return bridge.evidence_directory / 'receipts' / (event['event_id'] + '.json')


def forbidden_dispatch(*args, **kwargs):
    pytest.fail('automatic staging attempted child dispatch')


def test_manual_stage_is_exact_idempotent_and_excluded_from_automatic_routes(stores, monkeypatch):
    repo, state, bridge, event, blocker = stores
    assert bridge.process_pending()[0]['state'] == 'WAITING_FOR_UNFINISHED_CYCLE'
    assert repo.pending_company_events(BRIDGE_CONSUMER) == [event]
    assert not bridge.request_path.exists()
    before = state.cycle(blocker['id'])
    result = bridge.stage_manual_retained_event(event['event_id'], **scope(event, blocker))
    raw = bridge.request_path.read_bytes()
    receipt_raw = receipt_path(bridge, event).read_bytes()
    request, companies = _read_request(bridge.request_path)
    receipt = json.loads(receipt_raw)
    assert companies == ['TARGET']
    assert request['manual_retained'] == {'schema': MANUAL_RETAINED_SCHEMA, 'blocking_cycle_id': blocker['id']}
    assert request['company_event_timing']['condition'] == 'unverified'
    assert result['request_sha256'] == receipt['request_sha256'] == _json_digest(request)
    assert result['receipt_sha256'] == _json_digest(receipt)
    assert _request_provenance(request, receipt) == ('TARGET', event['event_id'])
    assert repo.pending_company_events(BRIDGE_CONSUMER) == []
    assert bridge.stage_manual_retained_event(event['event_id'], **scope(event, blocker)) == result
    assert bridge.request_path.read_bytes() == raw
    assert receipt_path(bridge, event).read_bytes() == receipt_raw
    dispatcher = CompanyIntakeDispatcher(repo, bridge.root, child_runner=forbidden_dispatch,
                                         retained_child_runner=forbidden_dispatch)
    assert dispatcher.run_once()['state'] == 'DISABLED'
    monkeypatch.setattr(dispatcher, 'enabled', lambda: True)
    monkeypatch.setattr(dispatcher, 'retained_enabled', lambda: True)
    assert dispatcher.run_once()['state'] == MANUAL_RETAINED_HOLD
    assert dispatcher.status()['ownership'] == {}
    assert bridge.process_pending() == [{'state': MANUAL_RETAINED_HOLD}]
    database = Path(state.path)
    with writer_lock(bridge.root / scraper_lock_name()):
        readonly = SQLiteRepository(repo.path, repo.spreadsheet_id, readonly=True)
        try:
            verifier = CompanyEventBridge(readonly, bridge.root)
            assert verifier.verify_manual_retained_event(event['event_id'], **scope(event, blocker)) == result
            assert readonly.db.total_changes == 0
        finally:
            readonly.close()
        with pytest.raises(ValueError, match='outside ordinary admission'):
            verify_queued_event_for_normal_resume(repo, state, database, cycle_id=blocker['id'])
        with pytest.raises(ValueError, match='outside ordinary admission'):
            requested_scan(Engine(repo, state), state, database)
    assert state.cycle(blocker['id']) == before
    assert bridge.request_path.read_bytes() == raw

    # Even if the historical checkpoint changes later, the marker never
    # degrades to an ordinary request eligible for an apparently idle start.
    blocker['companies']['HISTORICAL']['stage'] = 'complete'
    Engine(repo, state)._sync_cycle(blocker)
    assert dispatcher.run_once()['state'] == MANUAL_RETAINED_HOLD
    with pytest.raises(ValueError, match='outside ordinary admission'):
        requested_scan(Engine(repo, state), state, database)
    with pytest.raises(ValueError, match='one exact local and mirrored unfinished blocker'):
        bridge.verify_manual_retained_event(event['event_id'], **scope(event, blocker))


@pytest.mark.parametrize('cut', ['before_ack', 'before_receipt'])
def test_exact_stage_recovers_between_request_ack_and_receipt(stores, monkeypatch, cut):
    repo, _, bridge, event, blocker = stores

    def interruption(*args, **kwargs):
        raise RuntimeError('simulated local interruption')

    owner, method = ((repo, 'acknowledge_company_event') if cut == 'before_ack'
                     else (bridge, '_write_receipt'))
    with monkeypatch.context() as patch:
        patch.setattr(owner, method, interruption)
        with pytest.raises(RuntimeError, match='local interruption'):
            bridge.stage_manual_retained_event(event['event_id'], **scope(event, blocker))
    raw = bridge.request_path.read_bytes()
    assert not receipt_path(bridge, event).exists()
    assert repo.pending_company_events(BRIDGE_CONSUMER) == ([event] if cut == 'before_ack' else [])
    with pytest.raises(ValueError, match='staging is incomplete'):
        bridge.verify_manual_retained_event(event['event_id'], **scope(event, blocker))
    assert bridge.process_pending() == [{'state': MANUAL_RETAINED_HOLD}]
    proof = bridge.stage_manual_retained_event(event['event_id'], **scope(event, blocker))
    assert bridge.request_path.read_bytes() == raw
    assert proof == bridge.verify_manual_retained_event(event['event_id'], **scope(event, blocker))


def test_busy_lease_and_competing_slot_never_acknowledge(stores):
    repo, _, bridge, event, blocker = stores
    with writer_lock(bridge.root / scraper_lock_name()):
        with pytest.raises(WriterLockBusy):
            bridge.stage_manual_retained_event(event['event_id'], **scope(event, blocker))
    assert not bridge.request_path.exists()
    bridge.request_path.write_bytes(b'{"mode":"fresh-full-scan"}\n')
    raw = bridge.request_path.read_bytes()
    with pytest.raises(ValueError, match='cannot replace'):
        bridge.stage_manual_retained_event(event['event_id'], **scope(event, blocker))
    assert bridge.request_path.read_bytes() == raw
    assert repo.pending_company_events(BRIDGE_CONSUMER) == [event]
    assert not receipt_path(bridge, event).exists()


def test_exclusive_slot_publication_cannot_overwrite_a_racing_file(stores, monkeypatch):
    repo, _, bridge, event, blocker = stores
    original = bridge._write_atomic_json
    competitor = b'{"mode":"fresh-full-scan","request_id":"competing"}\n'

    def racing_write(path, payload, *, exclusive=False):
        assert path == bridge.request_path and exclusive
        path.write_bytes(competitor)
        return original(path, payload, exclusive=exclusive)

    monkeypatch.setattr(bridge, '_write_atomic_json', racing_write)
    with pytest.raises(FileExistsError):
        bridge.stage_manual_retained_event(event['event_id'], **scope(event, blocker))
    assert bridge.request_path.read_bytes() == competitor
    assert repo.pending_company_events(BRIDGE_CONSUMER) == [event]
    assert not receipt_path(bridge, event).exists()


def test_changed_source_while_staging_never_becomes_receipt_ready(stores, monkeypatch):
    repo, _, bridge, event, blocker = stores
    original = repo.acknowledge_company_event
    newer = []

    def race(*args, **kwargs):
        newer.append(repo.mutate_company_with_event({
            'tab': 'Companies', 'identity': {'Company ID': 'TARGET'},
            'values': {'Official Careers URL': 'https://example.test/jobs/newest'},
        })['company_event'])
        return original(*args, **kwargs)

    monkeypatch.setattr(repo, 'acknowledge_company_event', race)
    with pytest.raises(ValueError, match='superseded'):
        bridge.stage_manual_retained_event(event['event_id'], **scope(event, blocker))
    raw = bridge.request_path.read_bytes()
    assert not receipt_path(bridge, event).exists()
    assert repo.pending_company_events(BRIDGE_CONSUMER) == newer
    assert bridge.process_pending() == [{'state': MANUAL_RETAINED_HOLD}]
    with pytest.raises(ValueError, match='cannot replace'):
        bridge.stage_manual_retained_event(newer[0]['event_id'], **scope(newer[0], blocker))
    assert bridge.request_path.read_bytes() == raw


def test_wrong_selection_scope_or_existing_owner_cannot_reserve(stores):
    repo, state, bridge, event, blocker = stores
    exact = scope(event, blocker)
    with pytest.raises(ValueError, match='unknown'):
        bridge.stage_manual_retained_event(event['event_id'], **dict(exact, company_id='OTHER'))
    with pytest.raises(ValueError, match='one exact'):
        bridge.stage_manual_retained_event(event['event_id'], **dict(exact, blocking_cycle_id='OTHER'))
    blocker['companies']['TARGET'] = {'stage': 'queued'}
    Engine(repo, state)._sync_cycle(blocker)
    with pytest.raises(ValueError, match='overlaps'):
        bridge.stage_manual_retained_event(event['event_id'], **exact)
    del blocker['companies']['TARGET']
    Engine(repo, state)._sync_cycle(blocker)
    dispatcher = CompanyIntakeDispatcher(repo, bridge.root, child_runner=forbidden_dispatch)
    assert dispatcher._reserve('company-event:' + event['event_id'], '0' * 64) == 'RESERVED'
    with pytest.raises(ValueError, match='dispatcher owner'):
        bridge.stage_manual_retained_event(event['event_id'], **exact)
    assert not bridge.request_path.exists()
    assert repo.pending_company_events(BRIDGE_CONSUMER) == [event]


def test_delivered_event_cannot_be_staged_again_after_slot_is_emptied(stores):
    repo, _, bridge, event, blocker = stores
    bridge.stage_manual_retained_event(event['event_id'], **scope(event, blocker))
    receipt = receipt_path(bridge, event).read_bytes()
    # Model the slot after the separate retained owner has consumed the request.
    bridge.request_path.unlink()
    with pytest.raises(ValueError, match='already delivered'):
        bridge.stage_manual_retained_event(event['event_id'], **scope(event, blocker))
    assert not bridge.request_path.exists()
    assert receipt_path(bridge, event).read_bytes() == receipt
    assert repo.pending_company_events(BRIDGE_CONSUMER) == []


def test_unsettled_other_retained_dispatcher_reservation_holds_manual_slot(stores):
    repo, _, bridge, event, blocker = stores
    dispatcher = CompanyIntakeDispatcher(repo, bridge.root, child_runner=forbidden_dispatch)
    with dispatcher._journal() as journal:
        journal.execute(
            'INSERT INTO request_ownership(request_id,request_digest,route,state) VALUES (?,?,?,?)',
            ('company-event:OTHER', '0' * 64, 'RETAINED', 'RETAINED_RECOVERABLE'),
        )
    with pytest.raises(ValueError, match='dispatcher owner'):
        bridge.stage_manual_retained_event(event['event_id'], **scope(event, blocker))
    assert not bridge.request_path.exists()
    assert repo.pending_company_events(BRIDGE_CONSUMER) == [event]
