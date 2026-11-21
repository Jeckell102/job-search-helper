"""Check the enrolled review boundary with disposable local and workbook data."""

import json
import sqlite3
from types import SimpleNamespace

import pytest

from job_search_helper import ats, cli, ordinary_verification_pending as pending
from job_search_helper.pipeline_probe import inspect, inspect_ordinary_review
from job_search_helper.repository import RepositoryError
from job_search_helper.scrape_first_pass import Blocked, Controller
from job_search_helper.sheet_profile import COMPACT_SCHEMAS

from test_exact_cycle_recovery import RecordingRemote
from test_ordinary_verification_pending import COMPANY, COMPANY_ID, CYCLE_ID, attempt
from test_s5_ordinary_publication_continuation import WORKBOOK, measured_scope
from test_s5_ordinary_worker_handoff import local_worker, mismatch


def controller_for(cycle_probe, proof_probe, stage='PUBLISHING'):
    controller = Controller.__new__(Controller)
    controller.state = {'cycle_id': CYCLE_ID, 'stage': stage, 'before_cycles': []}
    controller.scraper_admission_fd = None
    controller.env = {}
    controller.save = lambda **changes: controller.state.update(changes)
    controller.announce = lambda message: None

    def probe(*args):
        if not args:
            return cycle_probe
        assert args == ('ordinary-review-proof', CYCLE_ID)
        try:
            return proof_probe(CYCLE_ID)
        except (RepositoryError, ValueError) as exc:
            raise Blocked(str(exc)) from exc

    controller.probe = probe
    return controller


def finished_cycle_probe(**extra):
    return {'cycles': [{'id': CYCLE_ID, 'status': 'Complete'}], 'scraper_busy': False, **extra}


def publish(launch, monkeypatch, *, typed):
    def fetch(*args):
        return mismatch() if typed else ats.Inventory(
            'complete', jobs=[], ats='Rippling', source_url=COMPANY['Official Careers URL'],
        )

    remote = RecordingRemote([COMPANY], schemas=COMPACT_SCHEMAS)
    remote.spreadsheet_id = WORKBOOK
    monkeypatch.setattr(ats, 'fetch_inventory', fetch)
    monkeypatch.setattr(cli, 'get_remote_repository', lambda **kwargs: remote)
    assert launch(resume=True, resume_cycle_id=CYCLE_ID, capture_ordinary_verification=True,
                  fetch_workers=1, browser_fallback=False) == 0
    named = dict(sync_only=True, sync_cycle_id=CYCLE_ID, sync_company_ids=[COMPANY_ID])
    assert launch(**named, publish_ordinary_verification=True) == 0
    assert len(remote.commits) == 1
    return named


def test_unenrolled_keeps_the_regular_publication_path(measured_scope):
    controller = controller_for(finished_cycle_probe(), inspect_ordinary_review)
    calls = []
    healthy = {'configured_backend': 'sqlite', 'ready': True, 'pending_cells': 0, 'pending_rows': 0}

    def helper(*args):
        calls.append(args)
        return healthy

    controller.helper = helper
    controller.publish_gate()
    assert calls == [('storage', 'status')]
    assert controller.state['scrape_publication'] == healthy
    assert controller.state['stage'] == 'REVIEWING'


def test_jobs_only_cut_holds_before_workbook_or_review(measured_scope, monkeypatch):
    launch, _, _, _ = measured_scope

    def interrupt(*args, **kwargs):
        raise RuntimeError('cut before State')

    monkeypatch.setattr(pending, 'arm', interrupt)
    with pytest.raises(RuntimeError, match='cut before State'):
        launch(resume=True, resume_cycle_id=CYCLE_ID, capture_ordinary_verification=True,
               fetch_workers=1, browser_fallback=False)
    with pytest.raises(ValueError, match='incomplete or inconsistent'):
        inspect_ordinary_review(CYCLE_ID)


def test_pending_publication_cannot_report_finished_or_try_global_sync(measured_scope, monkeypatch):
    launch, _, _, _ = measured_scope
    publish(launch, monkeypatch, typed=True)
    controller = controller_for(finished_cycle_probe(), inspect_ordinary_review, 'SCRAPING')
    controller.command = controller.helper = lambda *args, **kwargs: pytest.fail('unexpected side effect')
    with pytest.raises(Blocked, match='still needs its exact verification result'):
        controller.scrape()
    assert controller.state['stage'] == 'SCRAPING'
    controller.state['stage'] = 'PUBLISHING'
    with pytest.raises(Blocked, match='still needs its exact verification result'):
        controller.publish_gate()
    assert controller.state['stage'] == 'PUBLISHING'


def test_exact_terminal_admits_review_and_detects_changed_outcome(measured_scope, monkeypatch):
    launch, state, jobs, inbox = measured_scope
    named = publish(launch, monkeypatch, typed=False)
    assert launch(**named, finish_ordinary_verification=True) == 0
    # The fixture retains its outer scraper lock after the child returns.
    # Use the actual durable cycle status with an idle controller.
    cycle_probe = {**inspect(), 'scraper_busy': False}
    assert cycle_probe['cycles'][-1]['status'] == 'In Progress'
    controller = controller_for(cycle_probe, inspect_ordinary_review, 'SCRAPING')
    controller.command = lambda *args, **kwargs: pytest.fail('unexpected repeat scrape')
    controller.scrape()
    assert controller.state['stage'] == 'PUBLISHING'

    controller.helper = lambda *args, **kwargs: pytest.fail('unexpected global sync or status')
    controller.args = SimpleNamespace(command='review', resume=False, cycle=CYCLE_ID)
    controller.project = state.parent
    calls = []
    controller.preflight = lambda: pytest.fail('unexpected generic publication preflight')
    controller.ai_preflight = lambda: calls.append('ai-check')
    controller.review = lambda: calls.append('review')
    assert controller.run() == 0
    assert calls == ['ai-check', 'review']
    assert controller.state['stage'] == 'REVIEWING'
    terminal = controller.state['scrape_publication']['terminal']
    assert terminal == inspect_ordinary_review(CYCLE_ID)['terminal']

    with pending.open_verification_stores(state, jobs, inbox, WORKBOOK, writable_jobs=True) as stores:
        with stores.jobs.transaction():
            stores.jobs.db.execute('DELETE FROM scrape_outcomes WHERE outcome_id=?', (terminal['outcome_id'],))
    with pytest.raises(RepositoryError, match='terminal evidence changed'):
        inspect_ordinary_review(CYCLE_ID)


def test_terminal_review_uses_readonly_connections(measured_scope, monkeypatch):
    launch, state, _, inbox = measured_scope
    named = publish(launch, monkeypatch, typed=False)
    assert launch(**named, finish_ordinary_verification=True) == 0
    state.chmod(0o640)
    inbox.chmod(0o640)
    opened = []
    original_connect = sqlite3.connect

    def connect_readonly(database, *args, **kwargs):
        assert kwargs.get('uri') is True and str(database).endswith('?mode=ro')
        opened.append(str(database))
        return original_connect(database, *args, **kwargs)

    monkeypatch.setattr(sqlite3, 'connect', connect_readonly)
    assert inspect_ordinary_review(CYCLE_ID)['state'] == 'TERMINAL'
    assert any(str(inbox) in uri for uri in opened)
    assert state.stat().st_mode & 0o777 == inbox.stat().st_mode & 0o777 == 0o640


def test_review_resume_rechecks_after_ai_checks(tmp_path):
    terminal = {'schema': 'ordinary-verification-terminal-v1', 'outcome_id': 'fixture-outcome'}
    proofs = iter([
        {'cycle_id': CYCLE_ID, 'state': 'TERMINAL', 'terminal': terminal},
        {'cycle_id': CYCLE_ID, 'state': 'UNENROLLED'},
    ])
    controller = controller_for(finished_cycle_probe(state_dir=str(tmp_path)), lambda cycle_id: next(proofs))
    root = tmp_path / 'scrape-first-pass'
    root.mkdir()
    workflow = root / 'workflow.json'
    workflow.write_text(json.dumps({
        'cycle_id': CYCLE_ID, 'stage': 'REVIEWING',
        'scrape_publication': {'mode': 'exact-ordinary-verification', 'terminal': terminal},
    }))
    (root / 'latest.json').write_text(json.dumps({'workflow': str(workflow)}))
    controller.args = SimpleNamespace(command='run', resume=True)
    calls = []
    controller.ai_preflight = lambda: calls.append('preflight')
    controller.review = lambda: pytest.fail('review began with missing proof')
    with pytest.raises(Blocked, match='changed during AI checks'):
        controller.run()
    assert calls == ['preflight']
    assert controller.state['status'] == 'PAUSED_NOT_COMPLETE'
