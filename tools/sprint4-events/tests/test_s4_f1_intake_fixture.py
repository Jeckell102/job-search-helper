"""Composed Sprint 4 F1 contract with real isolated stores and kernel locks."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import socket
import sqlite3

import pytest

from job_search_helper import company_events as event_module, engine as engine_module, runner, sqlite_repository
from job_search_helper.cli import PROJECT_ROOT, scraper_lock_name, writer_lock
from job_search_helper.company_events import CompanyEventBridge, _json_digest
from job_search_helper.company_intake_dispatcher import CompanyIntakeDispatcher
from job_search_helper.engine import State
from job_search_helper.repository import MemoryRepository, SCHEMAS
from job_search_helper.scan_request import (
    company_event_timing, company_only_intake_start_measurement, verify_queued_event_for_normal_resume,
)
from job_search_helper.sheets_sync import SheetsSynchronizer
from job_search_helper.sqlite_repository import SQLiteRepository


class SheetFixture(MemoryRepository):
    spreadsheet_id = 'fixture-workbook'

    def __init__(self, companies):
        super().__init__({'Companies': companies})
        self.next_snapshot = None
        self.company_reads = 0

    def read(self, tab):
        snapshot = super().read(tab)
        if tab == 'Companies':
            self.company_reads += 1
            if self.next_snapshot is not None:
                next_snapshot, self.next_snapshot = self.next_snapshot, None
                self.replace_companies(next_snapshot)
        return snapshot

    def replace_companies(self, companies):
        self._sheets['Companies'] = MemoryRepository({'Companies': companies})._sheets['Companies']


def company(company_id, *, slug=None):
    return {
        'Company': company_id, 'Company ID': company_id, 'Company Status': 'Active',
        'Official Careers URL': 'https://boards.greenhouse.io/' + (slug or company_id.lower()),
        'ATS / Source': 'Greenhouse',
    }


@pytest.fixture
def stores(tmp_path, monkeypatch):
    assert PROJECT_ROOT == Path(__file__).resolve().parents[1]

    def unexpected_network(*args, **kwargs):
        pytest.fail('network access is outside the isolated F1 fixture')

    monkeypatch.setattr(socket.socket, 'connect', unexpected_network)
    monkeypatch.setattr(socket.socket, 'connect_ex', unexpected_network)
    root = tmp_path / 'state'
    root.mkdir()
    jobs = tmp_path / 'jobs.sqlite3'
    database = root / 'state.db'
    monkeypatch.setenv('JOB_DB_FILE', str(jobs))
    monkeypatch.setenv('JOB_STORAGE_BACKEND', 'sqlite')
    monkeypatch.setattr(runner, '_load_environment', lambda: None)
    monkeypatch.setattr(runner, 'load_title_blacklist', lambda: None)
    monkeypatch.setattr(runner, 'load_title_review_list', lambda: None)
    monkeypatch.setattr(runner, '_refresh_review_queue', lambda *args: None)
    monkeypatch.setattr(runner, 'state_path', lambda: database)

    def get_repository(*, write=False, **kwargs):
        return SQLiteRepository(jobs, SheetFixture.spreadsheet_id, readonly=not write)

    monkeypatch.setattr(runner, 'get_repository', get_repository)
    repo = SQLiteRepository(jobs, SheetFixture.spreadsheet_id, initialize=True)
    for tab in SCHEMAS:
        repo.import_rows(tab, [])
    repo.set_meta('ready', 'yes')
    state = State(database)
    state.close()
    try:
        yield repo, root, database
    finally:
        repo.close()


def closed_cycle_only(engine, cycle_id):
    cycle = engine.state.cycle(cycle_id)
    for member in cycle['companies'].values():
        member['stage'] = 'complete'
    engine._sync_cycle(cycle)
    return {'run_counts': {}}


def event_receipt(bridge, request):
    event_id = request['company_event']['event_id']
    path = bridge.evidence_directory / 'receipts' / (event_id + '.json')
    return json.loads(path.read_bytes())


def test_authoritative_first_read_catchup_to_one_idle_scoped_normal_start(stores, monkeypatch):
    repo, root, database = stores
    historical = company('HISTORICAL')
    addition = company('NEW')
    remote = SheetFixture([historical])
    remote.next_snapshot = [historical, addition]
    synchronizer = SheetsSynchronizer(repo, remote)
    totals = synchronizer.pull()
    assert remote.company_reads == 2
    assert totals['company_event_bootstrap_catchup']['imported'] == 1
    bridge = CompanyEventBridge(repo, root)
    events = repo.pending_company_events(bridge.consumer)
    assert [event['company_id'] for event in events] == ['NEW']
    additional_pull = synchronizer.pull()
    assert repo.pending_company_events(bridge.consumer) == events, additional_pull

    requested = []
    admitted = []

    def child(command):
        assert command == (str(PROJECT_ROOT / 'job-search-scraper'), 'start')
        request = json.loads(bridge.request_path.read_bytes())
        handoff = json.loads((root / 'scrape-first-pass/company-intake-handoff.json').read_bytes())
        assert handoff['request_id'] == request['request_id']
        assert handoff['request_digest'] == _json_digest(request)
        requested.append(request)
        return runner.run_start(fetch_workers=1, browser_fallback=False, defer_sync=True)

    def synthetic_scan(engine, cycle_id, **kwargs):
        admitted.append(engine.state.cycle(cycle_id))
        return closed_cycle_only(engine, cycle_id)

    monkeypatch.setattr(runner, '_run_scan_with_retries', synthetic_scan)
    dispatcher = CompanyIntakeDispatcher(repo, root, child_runner=child)
    assert dispatcher.run_once()['state'] == 'DISABLED'
    dispatcher.set_enabled(True)
    result = dispatcher.run_once()
    assert result['state'] == 'CHILD_LAUNCHED', (result, dispatcher.status())
    assert dispatcher.run_once()['state'] == 'NO_READY_REQUEST'
    assert len(admitted) == len(requested) == 1
    request, cycle, event = requested[0], admitted[0], events[0]
    assert request['request_id'] == 'company-event:' + event['event_id']
    assert request['company_ids'] == list(cycle['companies']) == ['NEW']
    assert cycle['company_event'] == request['company_event']
    assert request['source_revision'] == event['source_revision']
    assert cycle['runtime_binding']['state'] == 'NO_RELEASE'
    assert event_receipt(bridge, request)['request_sha256'] == _json_digest(request)
    assert json.loads((root / 'last-scan-request.json').read_bytes()) == request
    assert cycle['intake_start_measurement']['condition'] == 'idle'
    assert cycle['intake_start_measurement']['target_anchor'] == 'company_event_observed_at'
    assert repo.pending_company_events(bridge.consumer) == []


@pytest.mark.parametrize('finish_current', [True, False])
def test_busy_source_change_under_real_admission(stores, monkeypatch, finish_current):
    repo, root, database = stores
    clock = datetime(2026, 11, 20, 16, tzinfo=timezone.utc)
    monkeypatch.setattr(engine_module, 'now', lambda: clock.isoformat())
    monkeypatch.setattr(sqlite_repository, 'timestamp', lambda: clock.isoformat())
    monkeypatch.setattr(event_module, 'datetime', type('FixtureClock', (), {'now': staticmethod(lambda tz: clock)}))
    active, target = company('CURRENT'), company('NEXT')
    remote = SheetFixture([active, target])
    synchronizer = SheetsSynchronizer(repo, remote)
    synchronizer.pull()
    bridge = CompanyEventBridge(repo, root)
    assert repo.pending_company_events(bridge.consumer) == []
    edit = repo.mutate_company_with_event({
        'tab': 'Companies', 'identity': {'Company ID': 'CURRENT'},
        'values': {'Official Careers URL': 'https://boards.greenhouse.io/current-changed'},
    })['company_event']
    assert edit['company_id'] == 'CURRENT'
    lock = root / scraper_lock_name()
    assert lock.name == 'scraper.lock'
    launched = []
    in_scan = []
    terminal_sync = []
    busy_event = []

    def child(command):
        launched.append(command)
        return runner.run_start(fetch_workers=1, browser_fallback=False, defer_sync=True)

    dispatcher = CompanyIntakeDispatcher(repo, root, child_runner=child)
    dispatcher.set_enabled(True)

    class SynchronousFinalPull:
        totals = {}

        def __enter__(self):
            return self

        exited = False

        def __exit__(self, *args):
            nonlocal clock
            if not self.exited:
                self.exited = True
                clock += timedelta(seconds=1)
                with writer_lock(root / 'writer.lock'):
                    terminal_sync.append(synchronizer.pull())

    monkeypatch.setattr(
        'job_search_helper.run_sync.run_scoped_sync',
        lambda *args, **kwargs: SynchronousFinalPull(),
    )

    def synthetic_scan(engine, cycle_id, **kwargs):
        nonlocal clock
        before = engine.state.cycle(cycle_id)
        in_scan.append(before)
        if len(in_scan) == 1:
            assert list(before['companies']) == ['CURRENT']
            clock += timedelta(seconds=5)
            remote = synchronizer.remote
            updated_target = company('NEXT', slug='next-changed')
            remote.replace_companies([active, updated_target])
            with writer_lock(root / 'writer.lock'):
                synchronizer.pull()
            pending = repo.pending_company_events(bridge.consumer)
            assert [event['company_id'] for event in pending] == ['NEXT']
            busy_event.extend(pending)
            assert not bridge.request_path.exists()
            with pytest.raises(RuntimeError, match='lock|running'):
                with writer_lock(lock):
                    pytest.fail('a competing writer acquired the scraper flock')
            assert dispatcher.run_once()['state'] == 'HELD_BRIDGE_BOUNDARY'
            assert not launched and not bridge.request_path.exists()
            assert repo.pending_company_events(bridge.consumer) == pending
            if not finish_current:
                return {'run_counts': {}}
        clock += timedelta(seconds=5)
        return closed_cycle_only(engine, cycle_id)

    monkeypatch.setattr(runner, '_run_scan_with_retries', synthetic_scan)
    assert runner.run_start(fetch_workers=1, browser_fallback=False) == 0
    assert len(in_scan) == 1 and not launched
    assert len(terminal_sync) == 1
    if not finish_current:
        assert not bridge.request_path.exists()
        assert repo.pending_company_events(bridge.consumer) == busy_event
        deferral = list((bridge.evidence_directory / 'deferred').glob('*.json'))
        assert len(deferral) == 1
        assert json.loads(deferral[0].read_bytes())['blocking_cycle_ids'] == [in_scan[0]['id']]
        assert dispatcher.run_once()['state'] == 'HELD_UNFINISHED_CYCLE'
        with pytest.raises(ValueError, match='held in the outbox behind unfinished work'):
            runner.run_start(fetch_workers=1, browser_fallback=False, defer_sync=True)
        assert len(in_scan) == 1
        assert runner.run_start(resume=True, fetch_workers=1, browser_fallback=False) == 0
        assert in_scan[0]['id'] == in_scan[1]['id']
        assert len(terminal_sync) == 2 and not launched

    request = json.loads(bridge.request_path.read_bytes())
    assert request['company_ids'] == ['NEXT']
    assert request['company_event']['event_id'] == busy_event[0]['event_id']
    assert request['source_revision'] == busy_event[0]['source_revision']
    assert request['company_event_timing'] == {
        'observed_at': '2026-11-20T16:00:05+00:00',
        'blocking_cycle_ids': [in_scan[0]['id']],
        'condition': 'busy',
    }
    assert event_receipt(bridge, request)['request_sha256'] == _json_digest(request)
    assert repo.pending_company_events(bridge.consumer) == []
    clock += timedelta(seconds=4)
    result = dispatcher.run_once()
    assert result['state'] == 'CHILD_LAUNCHED', (result, dispatcher.status())
    assert dispatcher.run_once()['state'] == 'NO_READY_REQUEST'
    assert len(launched) == 1
    assert [list(cycle['companies']) for cycle in in_scan] == (
        [['CURRENT'], ['NEXT']] if finish_current else [['CURRENT'], ['CURRENT'], ['NEXT']]
    )
    assert in_scan[-1]['company_event'] == request['company_event']
    measured = in_scan[-1]['intake_start_measurement']
    assert measured['condition'] == 'busy'
    assert measured['safe_boundary_cycle_id'] == in_scan[0]['id']
    assert measured['target_anchor'] == 'safe_boundary_completed_at'
    assert measured['intake_to_start_seconds'] == 5


def queued_legacy_event(repo, root, monkeypatch):
    bridge = CompanyEventBridge(repo, root)
    repo.import_rows('Companies', enumerate([company('NEXT')], 2))
    changed = repo.mutate_company_with_event({
        'tab': 'Companies', 'identity': {'Company ID': 'NEXT'},
        'values': {'Official Careers URL': 'https://boards.greenhouse.io/next-new'},
    })['company_event']
    original = bridge._request_for

    def without_timing(event, cycles):
        request = original(event, cycles)
        del request['company_event_timing']
        return request

    monkeypatch.setattr(bridge, '_request_for', without_timing)
    assert bridge.process_pending()[0]['state'] == 'REQUEST_WRITTEN'
    return bridge, changed


def test_explicit_reviewed_runner_resume_preserves_queued_legacy_event(stores, monkeypatch):
    repo, root, database = stores
    bridge, event = queued_legacy_event(repo, root, monkeypatch)
    repo.import_rows('Companies', [(3, company('CURRENT'))])
    raw = bridge.request_path.read_bytes()
    state = State(database)
    try:
        with runner._scraper_admission(database) as runtime:
            engine = engine_module.Engine(repo, state, runtime_binding=runtime)
            cycle_id = engine.start_cycle(company_ids=['CURRENT'])
    finally:
        state.close()

    scans = []

    def scan(engine, selected, **options):
        scans.append((selected, list(engine.state.cycle(selected)['companies'])))
        return closed_cycle_only(engine, selected)

    class FinalSync:
        totals = {}

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    monkeypatch.setattr(runner, '_run_scan_with_retries', scan)
    monkeypatch.setattr('job_search_helper.run_sync.run_scoped_sync', lambda *a, **k: FinalSync())
    with pytest.raises(ValueError, match='fresh next-scan.json request is pending'):
        runner.run_start(fetch_workers=1, browser_fallback=False, resume=True)
    with pytest.raises(ValueError, match='exact resume ID'):
        runner.run_start(fetch_workers=1, browser_fallback=False, resume=True, resume_cycle_id='CYC-OTHER')
    assert not scans
    with monkeypatch.context() as scoped:
        scoped.setattr(CompanyEventBridge, 'process_pending',
                       lambda *a, **k: pytest.fail('Exact resume must not bridge the pre-existing event'))
        assert runner.scrape_main([
            'start', '--resume', '--resume-cycle-id', cycle_id, '--fetch-workers', '1', '--no-browser-fallback',
        ]) == 0
    assert scans == [(cycle_id, ['CURRENT'])]
    assert bridge.request_path.read_bytes() == raw

    dispatcher = CompanyIntakeDispatcher(
        repo, root, child_runner=lambda _: runner.run_start(fetch_workers=1, browser_fallback=False, defer_sync=True),
    )
    dispatcher.set_enabled(True)
    assert dispatcher.run_once()['state'] == 'CHILD_LAUNCHED'
    assert scans[-1][1] == ['NEXT']
    assert scans[-1][0] != cycle_id
    assert dispatcher.run_once()['state'] == 'NO_READY_REQUEST'
    request = json.loads((root / 'last-scan-request.json').read_bytes())
    assert request['company_event']['event_id'] == event['event_id']


def save_blocker(state, company_id='CURRENT', **changes):
    cycle = {
        'id': 'CYC-NORMAL', 'status': 'In Progress', 'companies': {company_id: {'stage': 'queued'}},
        'started_at': '2026-11-20T15:00:00+00:00',
        'runtime_binding': {'state': 'NO_RELEASE'},
    }
    cycle.update(changes)
    state.save_cycle(cycle)
    return cycle['id']


def test_read_only_reviewed_resume_preserves_legacy_file_and_rejects_unproven_routes(stores, monkeypatch):
    repo, root, database = stores
    bridge, event = queued_legacy_event(repo, root, monkeypatch)
    raw = bridge.request_path.read_bytes()
    state = State(database)
    try:
        cycle_id = save_blocker(state)
        repo.import_rows('Scan Cycles', [(2, {
            'Cycle ID': cycle_id, 'Cycle Status': 'In Progress',
            'Notes': json.dumps({'company_ids': ['CURRENT'], 'runtime_binding': {'state': 'NO_RELEASE'}}),
        })])
        with writer_lock(root / scraper_lock_name()):
            assert verify_queued_event_for_normal_resume(repo, state, database, cycle_id=cycle_id) == raw
            assert bridge.request_path.read_bytes() == raw
            with pytest.raises(ValueError, match='not disjoint'):
                verify_queued_event_for_normal_resume(repo, state, database, cycle_id='other-cycle')
            save_blocker(state, company_id='NEXT')
            with pytest.raises(ValueError, match='not disjoint'):
                verify_queued_event_for_normal_resume(repo, state, database, cycle_id=cycle_id)
            save_blocker(state, repair_retry={})
            with pytest.raises(ValueError, match='not disjoint'):
                verify_queued_event_for_normal_resume(repo, state, database, cycle_id=cycle_id)
            save_blocker(state, runtime_binding={'state': 'different'})
            with pytest.raises(ValueError, match='mirror disagrees'):
                verify_queued_event_for_normal_resume(repo, state, database, cycle_id=cycle_id)
            save_blocker(state)
            bad = dict(json.loads(raw), operator_request={})
            bridge.request_path.write_text(json.dumps(bad))
            with pytest.raises(ValueError, match='not an ordinary Company-event request'):
                verify_queued_event_for_normal_resume(repo, state, database, cycle_id=cycle_id)
            bridge.request_path.write_bytes(raw)
            receipt = bridge.evidence_directory / 'receipts' / (event['event_id'] + '.json')
            saved = receipt.read_bytes()
            receipt.write_text(json.dumps(dict(json.loads(saved), request_sha256='0' * 64)))
            with pytest.raises(ValueError, match='receipt does not bind'):
                verify_queued_event_for_normal_resume(repo, state, database, cycle_id=cycle_id)
            receipt.write_bytes(saved)
            dispatcher = CompanyIntakeDispatcher(repo, root, child_runner=lambda command: pytest.fail('spawned'))
            request = json.loads(raw)
            with dispatcher._journal() as journal:
                journal.execute(
                    'INSERT INTO request_ownership(request_id,request_digest,route,state,exception_cycle) VALUES (?,?,?,?,?)',
                    (request['request_id'], _json_digest(request), 'RETAINED', 'RETAINED_STARTING', cycle_id),
                )
            with pytest.raises(ValueError, match='Retained intake ownership'):
                verify_queued_event_for_normal_resume(repo, state, database, cycle_id=cycle_id)
            with dispatcher._journal() as journal:
                journal.execute('DELETE FROM request_ownership')
            with sqlite3.connect(root / 'retained-work-exceptions.sqlite3') as controls:
                controls.execute('CREATE TABLE retained_work_exceptions (cycle TEXT)')
                controls.execute('CREATE TABLE retained_work_admissions (request_id TEXT, exception_cycle TEXT)')
                controls.execute('INSERT INTO retained_work_exceptions VALUES (?)', (cycle_id,))
            with pytest.raises(ValueError, match='Retained intake ownership'):
                verify_queued_event_for_normal_resume(repo, state, database, cycle_id=cycle_id)
            with sqlite3.connect(root / 'retained-work-exceptions.sqlite3') as controls:
                controls.execute('DELETE FROM retained_work_exceptions')
            repo.mutate_company_with_event({
                'tab': 'Companies', 'identity': {'Company ID': 'NEXT'},
                'values': {'Official Careers URL': 'https://boards.greenhouse.io/newest'},
            })
            with pytest.raises(ValueError, match='stale or lacks exact acknowledgement'):
                verify_queued_event_for_normal_resume(repo, state, database, cycle_id=cycle_id)
        assert bridge.request_path.read_bytes() == raw
    finally:
        state.close()


def test_historical_unfinished_cycle_remains_held_without_creating_a_request(stores):
    repo, root, database = stores
    repo.import_rows('Companies', enumerate([company('NEXT')], 2))
    event = repo.mutate_company_with_event({
        'tab': 'Companies', 'identity': {'Company ID': 'NEXT'},
        'values': {'Official Careers URL': 'https://boards.greenhouse.io/next-new'},
    })['company_event']
    state = State(database)
    try:
        cycle_id = save_blocker(state, company_id='HISTORICAL', id='CYC-HISTORICAL', runtime_binding=None)
        prior = state.cycle(cycle_id)
        dispatcher = CompanyIntakeDispatcher(repo, root, child_runner=lambda command: pytest.fail('spawned'))
        dispatcher.set_enabled(True)
        assert dispatcher.run_once()['state'] == 'HELD_UNFINISHED_CYCLE'
        bridge = CompanyEventBridge(repo, root)
        assert repo.pending_company_events(bridge.consumer) == [event]
        assert not bridge.request_path.exists()
        assert state.cycle(cycle_id) == prior
    finally:
        state.close()


def test_timing_does_not_claim_boundary_from_equal_or_disagreeing_checkpoints():
    start = '2026-11-20T16:00:00+00:00'
    end = '2026-11-20T16:00:20+00:00'
    cycle = {'id': 'CYC-1', 'status': 'Complete', 'started_at': start, 'completed_at': end}
    mirror = {'Cycle ID': 'CYC-1', 'Cycle Status': 'Complete', 'Started At': start, 'Completed At': end}
    assert company_event_timing(end, [], [cycle], [mirror])['condition'] == 'unverified'
    timing = company_event_timing(end, ['CYC-1'], [cycle], [mirror])
    assert timing['condition'] == 'busy'
    request = {'mode': 'company-only', 'company_event': {}, 'company_event_timing': timing,
               'enqueued_at': '2026-11-20T16:00:22+00:00'}
    measured = company_only_intake_start_measurement(
        request, {'started_at': '2026-11-20T16:00:25+00:00'}, [cycle],
        mirror_cycles=[dict(mirror, **{'Completed At': start})],
    )
    assert measured['condition'] == 'unverified'
    assert measured['target_met'] is None


def test_standalone_bridge_uses_configured_state_before_materializing(stores, monkeypatch):
    repo, root, _ = stores
    configured = root / 'configured-state.db'
    monkeypatch.setenv('STATE_DB_FILE', str(configured))
    repo.import_rows('Companies', enumerate([company('NEXT')], 2))
    event = repo.mutate_company_with_event({
        'tab': 'Companies', 'identity': {'Company ID': 'NEXT'},
        'values': {'Official Careers URL': 'https://boards.greenhouse.io/next-new'},
    })['company_event']
    state = State(configured)
    try:
        save_blocker(state)
        bridge = CompanyEventBridge(repo, root)
        assert bridge.process_pending()[0]['state'] == 'WAITING_FOR_UNFINISHED_CYCLE'
        assert repo.pending_company_events(bridge.consumer) == [event]
        assert not bridge.request_path.exists()
    finally:
        state.close()


def test_legacy_event_admission_reads_observation_and_preserves_exact_receipt(stores, monkeypatch):
    repo, root, _ = stores
    bridge, event = queued_legacy_event(repo, root, monkeypatch)
    raw = bridge.request_path.read_bytes()
    receipt = bridge.evidence_directory / 'receipts' / (event['event_id'] + '.json')
    receipt_bytes = receipt.read_bytes()
    admitted = []

    def synthetic_scan(engine, cycle_id, **kwargs):
        admitted.append(engine.state.cycle(cycle_id))
        return closed_cycle_only(engine, cycle_id)

    monkeypatch.setattr(runner, '_run_scan_with_retries', synthetic_scan)
    assert runner.run_start(fetch_workers=1, browser_fallback=False, defer_sync=True) == 0
    assert (root / 'last-scan-request.json').read_bytes() == raw
    assert receipt.read_bytes() == receipt_bytes
    assert admitted[0]['intake_start_measurement']['target_anchor'] == 'company_event_observed_at'
