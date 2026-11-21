"""Exercise the exact host catch-up path using the synthetic owned event fixture."""
from contextlib import closing
from dataclasses import asdict, replace
import importlib
import json
from pathlib import Path
from shutil import copyfile
from unittest.mock import Mock, patch

import pytest

import coding_tools
from job_search_helper.engine import State
from job_search_helper.company_events import read_verified_ordinary_event_admission
from job_search_helper.scrape_outcome_delivery import CONSUMER, OutcomeDelivery
from job_search_helper.sqlite_repository import SQLiteRepository
import test_ordinary_event_no_publication as ordinary


@pytest.fixture
def host():
    with patch.object(Path, 'read_text', return_value='disposable-token'):
        return importlib.import_module('host_server')


@pytest.fixture
def enrolled(host, tmp_path, monkeypatch, capsys):
    root = tmp_path / 'application'
    root.mkdir()
    monkeypatch.setattr(host, 'JOB_SEARCH_ROOT', tmp_path)
    monkeypatch.setenv('JOB_STORAGE_BACKEND', 'sqlite')
    monkeypatch.setenv('SPREADSHEET_ID', 'sheet')
    monkeypatch.setenv('STATE_DB_FILE', str(root / 'state.db'))
    monkeypatch.setenv('JOB_DB_FILE', str(root / 'jobs.sqlite3'))

    class BeforeSenderAcknowledgement(Exception):
        pass

    class StopBeforeAcknowledgement(OutcomeDelivery):
        def drain(self, **scope):
            [record] = self.repository.scrape_outcomes()
            if ordinary.ordinary_event_outcome_settled(self.repository, record):
                raise BeforeSenderAcknowledgement
            return super().drain(**scope)

    with monkeypatch.context() as fixture_patch:
        fixture_patch.setattr(ordinary, 'OutcomeDelivery', StopBeforeAcknowledgement)
        with pytest.raises(BeforeSenderAcknowledgement):
            ordinary.test_named_amphenol_pagination_settlement_is_exact_and_never_publishes(
                root, fixture_patch, capsys, 'owned')

    with (closing(State(str(root / 'state.db'), readonly=True)) as state,
          closing(SQLiteRepository(root / 'jobs.sqlite3', 'sheet')) as jobs):
        [selected] = jobs.pending_scrape_outcomes(CONSUMER)
        admitted = read_verified_ordinary_event_admission(jobs, state, selected['identity']['cycle_id'])
        request = admitted['request']
        other = jobs.record_scrape_outcome({
            'request_id': 'OTHER-1', 'company_id': 'COMP-0001', 'source_revision': 'rev-1',
            'cycle_id': 'CYC-OTHER', 'provider': 'greenhouse', 'adapter_version': 'v1',
            'source_current': True, 'company_status': 'Active', 'storage_status': 'confirmed',
            'inventory_status': 'partial', 'capability': 'unknown', 'failure': {'category': 'unknown'},
        })['outcome']
    scope = {'company_event_id': request['company_event']['event_id'],
             'request_id': request['request_id'], 'source_revision': request['source_revision']}
    recipe = host.AmphenolRecipeEnrollment.from_process_environment({
        'WRAPPER_AMPHENOL_RECIPE_ENROLLMENT': json.dumps(scope),
    })
    assert asdict(recipe) == scope

    source = tmp_path / 'assignment-source'
    project = Path(__file__).resolve().parents[3]
    for name in ('src/job_search_helper/acquiretm.py', 'tests/test_acquiretm.py'):
        target = source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        copyfile(project / name, target)
    (source / 'docs').mkdir()
    (source / 'docs/wrapper-development-test-protocol.md').write_text('# Test protocol\nRun the exact test.')
    monkeypatch.setattr(coding_tools, 'BASE', tmp_path)
    monkeypatch.setattr(coding_tools, 'ROOT', source)
    monkeypatch.setattr(coding_tools, 'git', lambda *_: '')
    coordinator = host.build_coordinator(recipe)
    coordinator.model = Mock(side_effect=AssertionError('The host trigger must never invoke inference'))
    coordinator.command({'action': 'queue-pause'})
    supervision = host.build_supervision(coordinator, recipe=recipe)
    return recipe, coordinator, supervision, root, selected, other


def test_environment_is_default_off_and_malformed_enrollment_is_held(host):
    parser = host.AmphenolRecipeEnrollment.from_process_environment
    assert parser({}) is None
    assert host.drain_scrape_outcomes()['state'] == 'HELD_EXACT_OPERATOR_SCOPE_REQUIRED'
    for malformed in ('', '{}', '[]', '{"outcome_id":"OUT-selected-later"}'):
        with pytest.raises(ValueError, match='exact Amphenol recipe process enrollment'):
            parser({'WRAPPER_AMPHENOL_RECIPE_ENROLLMENT': malformed})


def test_catchup_delivers_exact_receipt_then_starts_one_isolated_pilot(enrolled):
    _, coordinator, supervision, root, selected, other = enrolled
    result = supervision.catch_up()
    task_id = result['task_id']
    assert result == {'state': 'RECIPE_PILOT_QUEUED', 'outcome_id': selected['outcome_id'], 'task_id': task_id}
    assert coordinator.store.pilot_task() == task_id
    [task] = coordinator.store.all()
    assert (task['id'], task['status'], task['mode'], task['isolated_workspace'], task['max_sessions']) == (
        task_id, 'QUEUED', 'review', True, 1,
    )
    prepared = coordinator.owned_recipe_reader(task)
    assert prepared['binding']['outcome_id'] == selected['outcome_id']
    with closing(SQLiteRepository(root / 'jobs.sqlite3', 'sheet', readonly=True)) as jobs:
        [delivery_row] = jobs._outcome_delivery_rows(CONSUMER, outcome_id=selected['outcome_id'])
        assert json.loads(delivery_row[6])['sink_receipt_id'] == prepared['binding']['sink_receipt_id']
        assert jobs.pending_scrape_outcomes(CONSUMER) == [other]
    assert not coordinator.store.queue_enabled() and not coordinator.store.campaign_enabled()
    assert supervision.catch_up() == {'state': 'HELD_RECIPE_CONTROLS'}
    coordinator.command({'action': 'pilot-stop'})
    [paused] = coordinator.store.all()
    assert supervision.catch_up() == {'state': 'HELD_RECIPE_OWNER'}
    assert coordinator.store.all() == [paused]
    coordinator.model.assert_not_called()


def test_interruption_after_promotion_never_resumes_paused_task(enrolled):
    _, coordinator, supervision, _, _, _ = enrolled
    dispatch = coordinator.command

    def cut_before_pilot(request):
        if request['action'] == 'pilot-start':
            raise OSError('Fixture interruption before pilot activation')
        return dispatch(request)

    coordinator.command = cut_before_pilot
    assert supervision.catch_up() == {'state': 'HELD_RECIPE_BOUNDARY'}
    [paused] = coordinator.store.all()
    coordinator.command = dispatch
    assert paused['status'] == 'PAUSED'
    assert supervision.catch_up() == {'state': 'HELD_RECIPE_OWNER'}
    assert coordinator.store.all() == [paused] and coordinator.store.pilot_task() is None
    coordinator.model.assert_not_called()


def test_restart_from_acknowledgement_selects_the_same_single_pilot(host, enrolled):
    recipe, coordinator, supervision, root, selected, _ = enrolled
    with patch.object(type(recipe), '_launch', side_effect=OSError('Fixture interruption after acknowledgement')):
        assert supervision.catch_up() == {'state': 'HELD_RECIPE_BOUNDARY'}
    assert not coordinator.store.all()
    restarted = host.build_coordinator(recipe)
    restarted.model = coordinator.model
    with patch('coordinator_receipt_host_bridge.ManualReceiptV1HostBridge.manual_drain',
               side_effect=AssertionError('Durable outcome acknowledgement must not be resent')):
        result = recipe.catch_up(restarted)
    assert (result['state'], result['outcome_id']) == ('RECIPE_PILOT_QUEUED', selected['outcome_id'])
    [task] = restarted.store.all()
    assert task['id'] == result['task_id']
    with closing(SQLiteRepository(root / 'jobs.sqlite3', 'sheet', readonly=True)) as jobs:
        assert jobs.db.execute('SELECT count(*) FROM scrape_outcome_delivery_receipts').fetchone() == (1,)
    restarted.model.assert_not_called()


def test_wrong_request_or_revision_never_hands_off_the_outcome(enrolled):
    recipe, coordinator, _, root, selected, other = enrolled
    new_id = 'CEV-' + '0' * 32
    for foreign in (replace(recipe, company_event_id=new_id, request_id='company-event:' + new_id),
                    replace(recipe, source_revision='0' * 64)):
        assert foreign.catch_up(coordinator) == {'state': 'HELD_EXACT_TERMINAL_OUTCOME'}
    with closing(SQLiteRepository(root / 'jobs.sqlite3', 'sheet', readonly=True)) as jobs:
        assert {row['outcome_id'] for row in jobs.pending_scrape_outcomes(CONSUMER)} == {
            selected['outcome_id'], other['outcome_id'],
        }
    assert not coordinator.store.held_repair_intake() and not coordinator.store.all()
    coordinator.model.assert_not_called()


def test_uncertain_inference_preserves_the_existing_hold(enrolled):
    _, coordinator, supervision, _, _, _ = enrolled
    coordinator.command({'action': 'queue-resume'})
    task = coordinator.command({'action': 'start', 'mode': 'review',
                               'objective': 'Read src/job_search_helper/acquiretm.py and run tests/test_acquiretm.py.'})['id']
    assert coordinator.store.claim_queued(task)
    session = coordinator.store.start_inference_session(task)
    reservation = coordinator.store.reserve_inference(
        task, phase=session['phase'], prompt_digest='fixture-prompt', tools_digest='fixture-tools',
        prompt_tokens=500, output_tokens=500, expected_control_generation=coordinator.store.control_generation(),
        session_id=session['inference_session_id'],
    )
    coordinator.store.finalize_inference(reservation['request_id'], terminal_error='Fixture response unavailable')
    [uncertain] = coordinator.store.inference_receipts(task)
    before = coordinator.store.all()
    assert uncertain['status'] == 'UNCERTAIN'
    assert supervision.catch_up() == {'state': 'HELD_RECIPE_CONTROLS'}
    assert coordinator.store.all() == before and coordinator.store.pilot_task() is None
    assert coordinator.store.inference_receipts(task) == [uncertain]
    coordinator.model.assert_not_called()
