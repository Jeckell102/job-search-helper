from types import SimpleNamespace

import coordinator
import pytest


def _state(**changes):
    value = {
        'workflow_version': 2, 'mode': 'develop', 'phase': 'inspect',
        'integration': {'work_order': 'breezy-embraer-brand-heading-v1'},
        'workflow': {'stall_turns': coordinator.workflow.MAX_STALL_TURNS},
    }
    value.update(changes)
    return value


def test_exact_stalled_embraer_offer_requires_fresh_complete_evidence(monkeypatch, tmp_path):
    observed = []
    monkeypatch.setattr(coordinator.workflow, 'plan', lambda *args: observed.append(args) or {'next': None})
    monkeypatch.setattr(coordinator, 'phase_evidence', lambda *args: (True, ''))
    assert coordinator.embraer_inspection_checkpoint_offer(_state(), [], {'x': 'y'}, tmp_path)
    assert len(observed) == 1


def test_offer_excludes_other_phase_work_order_stall_and_stale_evidence(monkeypatch, tmp_path):
    monkeypatch.setattr(coordinator.workflow, 'plan', lambda *args: {'next': None})
    monkeypatch.setattr(coordinator, 'phase_evidence', lambda *args: (True, ''))
    assert not coordinator.embraer_inspection_checkpoint_offer(_state(phase='implement'), [], {}, tmp_path)
    assert not coordinator.embraer_inspection_checkpoint_offer(
        _state(integration={'work_order': 'other'}), [], {}, tmp_path)
    assert not coordinator.embraer_inspection_checkpoint_offer(
        _state(workflow={'stall_turns': coordinator.workflow.MAX_STALL_TURNS - 1}), [], {}, tmp_path)
    monkeypatch.setattr(coordinator, 'phase_evidence', lambda *args: (False, 'stale evidence'))
    assert not coordinator.embraer_inspection_checkpoint_offer(_state(), [], {}, tmp_path)


def test_offer_rejects_a_refreshed_plan_with_real_remaining_work(monkeypatch, tmp_path):
    monkeypatch.setattr(coordinator.workflow, 'plan', lambda *args: {'next': {'name': 'code_read'}})
    monkeypatch.setattr(coordinator, 'phase_evidence', lambda *args: (True, ''))
    assert not coordinator.embraer_inspection_checkpoint_offer(_state(), [], {}, tmp_path)


@pytest.mark.parametrize('model_result', ['phase_done', 'continue', 'plain_text'])
def test_checkpoint_only_session_advances_or_holds_after_one_call(monkeypatch, model_result):
    state = _state(
        id='WRAP-0000000001', inference_session_id='session', calls=5, tokens=99, sessions=2,
        no_progress=2, evidence_requirements={'version': 1, 'required_files': ['src/x.py']},
        checkpoint={}, manifest={'docs/backlog/COMP-0634.md': 'n' * 64}, result_control_generation=0,
        workflow={'stall_turns': coordinator.workflow.MAX_STALL_TURNS, 'focus_receipt_id': 243},
    )
    dispatched, published, prompt_states = [], [], []
    receipts = [{'id': 242, 'phase': 'inspect', 'name': 'code_read',
                 'arguments': {'path': 'docs/backlog/COMP-0634.md', 'start_line': 1},
                 'result': {'ok': True, 'result': {'sha256': 'n' * 64,
                                                    'text': '1: Verified factual note\n'}}}]

    class Store:
        def get(self, task_id):
            assert task_id == state['id']
            return state

        def control_generation(self):
            return 7

        def publish_result(self, task_id, current, **changes):
            assert task_id == state['id']
            published.append(changes)
            return {**state, **changes}

    instance = coordinator.Coordinator.__new__(coordinator.Coordinator)
    instance.store = Store()
    instance.paused = lambda task_id: False
    instance.check_deadline = lambda task_id: state
    instance.evidence_receipts = lambda task_id: receipts
    def messages(active, protocol):
        prompt_states.append(active)
        return [{'role': 'system', 'content': 'fresh-guided-history'}]
    instance.messages = messages
    instance.budget = lambda history, schemas: SimpleNamespace(available_generation_tokens=4000, prompt_tokens=10)

    def dispatch(current, session_id, history, offered, output, prompt, generation):
        dispatched.append((list(history), offered))
        checkpoint = {'summary': 'Evidence supports the named repair.',
                      'next_action': 'Implement the bounded fix.', 'outcome': model_result}
        message = {'tool_calls': [{'function': {'name': 'worker_checkpoint', 'arguments': checkpoint}}]}
        if model_result == 'plain_text':
            message = {'content': 'I will read the file again.'}
        return {'usage': {}, 'message': message}, {'tools_allowed': True}

    instance._dispatch_session_inference = dispatch
    monkeypatch.setattr(coordinator, 'manifest', lambda: {'src/x.py': 'current', 'docs/backlog/COMP-0634.md': 'n' * 64})
    monkeypatch.setattr(coordinator.code, 'root', lambda: '/fixture')
    monkeypatch.setattr(coordinator.workflow, 'plan', lambda *args: {'next': None})
    monkeypatch.setattr(coordinator.workflow, 'progress_key', lambda *args: 'unchanged')
    monkeypatch.setattr(coordinator, 'phase_evidence', lambda *args: (True, ''))

    instance._session_body(state, {'text': 'protocol'})
    assert len(dispatched) == 1
    history, offered = dispatched[0]
    assert [schema['function']['name'] for schema in offered] == ['worker_checkpoint']
    assert any('refreshed work plan has no next tool' in message['content'] for message in history)
    assert not any('session closing is not a blocker' in message['content'] for message in history)
    assert 'focus_receipt_id' not in prompt_states[-1]['workflow']
    assert state['workflow']['focus_receipt_id'] == 243
    final = published[-1]
    if model_result == 'phase_done':
        assert final['phase'] == 'implement' and final['status'] == 'QUEUED'
    else:
        assert final['phase'] == 'inspect' and final['status'] == 'PAUSED_BLOCKED'
        assert final['checkpoint']['outcome'] == 'blocked'
    assert all(not ({'calls', 'tokens', 'sessions'} & set(change)) for change in published)
