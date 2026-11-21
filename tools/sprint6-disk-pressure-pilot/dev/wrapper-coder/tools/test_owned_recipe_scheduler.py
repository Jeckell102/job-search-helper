"""Exercise the existing isolated pilot with one saved recipe decision."""
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

import coordinator
from coordinator_store import Store
from coordinator_supervision import CoordinatorSupervision
import test_coordinator as fixture
from test_outcome_intake import facts


CHOICE = {'summary': 'W1', 'next_action': 'listing_membership_change', 'outcome': 'phase_done'}


@pytest.fixture
def pilot():
    setup = fixture.CoordinatorTests()
    setup.setUp()
    try:
        co = setup.co
        co.workflow_version = 2
        co.budget = lambda *_: SimpleNamespace(available_generation_tokens=1200, prompt_tokens=500)
        co.store.company_revision_resolver = lambda company_id: 'rev-1' if company_id == 'COMP-0490' else None
        co.command({'action': 'queue-pause'})
        held = co.store.ingest_scrape_outcome(facts(company_id='COMP-0490', provider='AcquireTM'))
        proposal = {
            'action': 'promote-repair', 'repair_key': held['repair_key'],
            'source_revision': 'rev-1', 'mode': 'review', 'max_sessions': 1,
            'objective': 'Inspect src/a.py and run tests/test_a.py.',
            'integration': {
                'company_id': 'COMP-0490', 'company': 'Amphenol Aerospace',
                'configured_url': 'https://amphenol-aerospace.acquiretm.com/home.aspx',
                'tests': ['tests/test_a.py'], 'source_targets': ['src/a.py'], 'ats': 'AcquireTM',
                'work_order': coordinator.AMPHENOL_RECIPE_WORK_ORDER,
            },
        }
        with patch('coordinator_workspace.batch_source', return_value=setup.root):
            task_id = co.command(proposal)['id']
            co.command({'action': 'pilot-start', 'id': task_id})
        prepared = {
            'binding': {'company_id': 'COMP-0490', 'outcome_id': held['outcome_id'], 'source_revision': 'rev-1'},
            'messages': [{'role': 'system', 'content': 'Choose the reviewed W1 strategy.'}],
            'tools': [coordinator.CHECKPOINT_SCHEMA],
        }
        co.owned_recipe_reader = lambda _state: prepared
        yield setup, task_id
    finally:
        setup.doCleanups()


def claim_step(co, task_id):
    assert co.store.claim_pilot(task_id)
    co.step(task_id)


def test_retry_after_candidate_write_failure_uses_exact_durable_choice(pilot):
    setup, task_id = pilot
    co = setup.co
    co.model = Mock(return_value=fixture.response('worker_checkpoint', CHOICE))
    co.owned_recipe_builder = Mock(side_effect=OSError('Simulated crash before draft write'))

    claim_step(co, task_id)
    with pytest.raises(OSError, match='before draft write'):
        claim_step(co, task_id)
    [receipt] = co.store.inference_receipts(task_id)
    assert receipt['status'] == 'COMPLETED' and receipt['accepted_recipe_choice'] == CHOICE
    co.model.assert_called_once()

    restarted = coordinator.Coordinator(
        co.store.base, model=Mock(side_effect=AssertionError('Inference must not replay')),
        budget=co.budget, company_revision_resolver=co.store.company_revision_resolver,
        owned_recipe_reader=co.owned_recipe_reader, owned_recipe_builder=Mock())
    restarted.store.recover()
    claim_step(restarted, task_id)
    restarted.model.assert_not_called()
    assert restarted.owned_recipe_builder.call_args.args[2] == receipt
    assert restarted.store.get(task_id)['status'] == 'REVIEW_COMPLETE_LIVE_NOT_VALIDATED'
    assert restarted.store.inference_receipts(task_id) == [receipt]
    assert not restarted.store.queue_enabled() and not restarted.store.campaign_enabled()


def test_recipe_with_disabled_hooks_holds_before_inference(pilot):
    setup, task_id = pilot
    co = setup.co
    co.owned_recipe_reader = None
    co.model = Mock(side_effect=AssertionError('Disabled recipe must never invoke inference'))
    claim_step(co, task_id)
    claim_step(co, task_id)
    co.model.assert_not_called()
    assert not co.store.inference_receipts(task_id)
    assert co.store.get(task_id)['status'] == 'PAUSED_BLOCKED'


def test_disk_pressure_stops_enrolled_pilot_and_blocks_reactivation(pilot):
    setup, task_id = pilot
    co = setup.co
    usage = SimpleNamespace(free=10, total=1000)
    catch_up = Mock(return_value={})
    supervision = CoordinatorSupervision(co, catch_up, disk_usage=lambda _: usage,
                                         min_free_bytes=100)
    assert supervision.tick()['state'] == 'DISK_PRESSURE_HOLD'
    catch_up.assert_not_called()

    reopened = Store(co.store.base)
    assert reopened.pilot_task() is None
    assert reopened.get(task_id)['status'] == 'PAUSED'
    assert reopened.claim_pilot(task_id) is None
    with patch.object(coordinator, 'workspace') as workspace:
        for action in ('queue-resume', 'campaign-start', 'pilot-start'):
            with pytest.raises(ValueError, match='Disk pressure'):
                co.command({'action': action, 'id': task_id})
    workspace.assert_not_called()

    usage.free = 900
    assert supervision.tick()['state'] == 'ACTIVE'
    catch_up.assert_called_once()
    assert reopened.pilot_task() is None
    assert not reopened.queue_enabled() and not reopened.campaign_enabled()
    assert reopened.get(task_id)['status'] == 'PAUSED'
    assert co.command({'action': 'pilot-start', 'id': task_id})['ok']


def test_disk_pressure_preserves_in_flight_choice_and_blocks_its_effect(pilot):
    setup, task_id = pilot
    co = setup.co
    claim_step(co, task_id)
    assert co.store.claim_pilot(task_id)
    session = co.store.start_inference_session(task_id, max_calls=1)
    reserved = co.store.reserve_inference(
        task_id, phase='inspect', prompt_digest='a' * 64, tools_digest='b' * 64,
        prompt_tokens=500, output_tokens=1000,
        expected_control_generation=co.store.control_generation(),
        session_id=session['inference_session_id'], max_calls=1)
    before = co.store.get(task_id)
    supervision = CoordinatorSupervision(co, Mock(side_effect=AssertionError('Pressure holds catch-up')),
                                         disk_usage=lambda _: SimpleNamespace(free=10, total=1000),
                                         min_free_bytes=100)
    assert supervision.tick()['state'] == 'DISK_PRESSURE_HOLD'
    assert co.store.inference_receipts(task_id) == [reserved]
    paused = co.store.get(task_id)
    assert paused['status'] == 'PAUSING' and paused['stop_requested']
    assert (paused['calls'], paused['tokens']) == (before['calls'], before['tokens'])
    result = co.store.finalize_inference(reserved['request_id'], fixture.response('worker_checkpoint', CHOICE),
                                         record_owned_recipe_choice=True)
    assert not result['tools_allowed']
    assert result['receipt']['status'] == 'RESPONSE_DROPPED'
    assert 'accepted_recipe_choice' not in result['receipt']
