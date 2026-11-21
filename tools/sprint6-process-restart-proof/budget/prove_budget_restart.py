"""Exercise the actual owned-pilot budget and controls across two processes."""
from pathlib import Path
from tempfile import mkdtemp
from types import SimpleNamespace
from unittest.mock import Mock, patch
import json
import os
import subprocess
import sys

TOOLS = Path('/tmp/jsh-s5-enrolled-retry-receipt.20261121/dev/wrapper-coder/tools')
sys.path.insert(0, str(TOOLS))


def reject_network(event, _args):
    if event.startswith(('socket.connect', 'socket.getaddrinfo', 'socket.gethostbyname', 'socket.bind', 'socket.sendto')):
        raise AssertionError('The budget fixture cannot use network transport')


sys.addaudithook(reject_network)
import coordinator
from test_coordinator import response
from test_outcome_intake import facts


def owned(co, index):
    company = f'COMP-{index:04d}'
    revision = f'fixture-revision-{index}'
    intake = {'action': 'ingest-scrape-outcome', 'facts': facts(
        company_id=company, source_revision=revision, request_id=f'company-event:CEV-fixture-{index}')}
    held = co.command(intake)
    assert held['recorded'] and held['status'] == 'HELD_FOR_REPAIR_TRIAGE', held
    proposal = {'action': 'promote-repair', 'repair_key': held['repair_key'],
                'source_revision': revision, 'mode': 'review', 'max_sessions': 1,
                'objective': 'Inspect src/a.py and run tests/test_a.py.',
                'integration': {'company_id': company, 'company': f'Fixture Company {index}',
                                'configured_url': f'https://job-boards.greenhouse.io/fixture{index}',
                                'ats': 'Greenhouse', 'tests': ['tests/test_a.py'],
                                'source_targets': ['src/a.py']}}
    task = co.command(proposal)['id']
    assert co.store.get(task)['status'] == 'PAUSED'
    return task, intake, held, proposal


def counters(state):
    return [state[name] for name in ('sessions', 'calls', 'tokens')]


def phase(co, work, name, model):
    if name == 'exhaust':
        co.command({'action': 'queue-pause'})
        task, intake, held, proposal = owned(co, 489)
        co.command({'action': 'pilot-start', 'id': task})

        def reply(*_args):
            control = coordinator.INFERENCE_CONTROL.get()
            stored = co.store.inference_receipt(control['request_id'])
            assert stored['status'] == 'DISPATCHING' and stored['control_binding'] == control
            return response('worker_checkpoint', {'summary': 'Initial review saved.',
                'next_action': 'Continue the approved review.', 'outcome': 'continue'})

        model.side_effect = reply
        for _ in range(10):
            assert co.store.claim_pilot(task), co.store.get(task)['status']
            co.step(task)
            if co.store.get(task)['status'] == 'PAUSED_BUDGET':
                break
        state = co.store.get(task)
        visible = co.command({'action': 'status', 'id': task})
        assert state['status'] == 'PAUSED_BUDGET' and 'PAUSED_BUDGET' in visible['text'], visible['text']
        assert counters(state) == [1, 1, 560] and state['max_sessions'] == 1
        [receipt] = co.store.inference_receipts(task)
        assert receipt['status'] == 'COMPLETED'
        model.assert_called_once()
        assert not co.store.claim_pilot(task)
        (work / 'exhausted.json').write_text(json.dumps({'pid': os.getpid(), 'state': state,
            'intake': intake, 'held': held, 'proposal': proposal, 'receipt': receipt,
            'actions': co.store.receipts(task)}, sort_keys=True))
        return

    saved = json.loads((work / 'exhausted.json').read_bytes())
    first = saved['state']['id']
    assert os.getpid() != saved['pid']
    co.store.recover()

    def assert_held():
        visible = co.command({'action': 'status', 'id': first})
        assert 'PAUSED_BUDGET' in visible['text'] and 'progress saved' in visible['text'], visible['text']
        assert co.store.get(first) == saved['state']
        assert co.store.inference_receipts(first) == [saved['receipt']]
        assert co.store.receipts(first) == saved['actions']
        assert not co.store.claim_pilot(first)

    assert_held()
    duplicate = co.command(saved['intake'])
    assert duplicate['recorded'] is False
    assert all(duplicate[k] == saved['held'][k] for k in ('repair_key', 'outcome_id'))
    assert co.command(saved['proposal'])['id'] == first
    assert len(co.store.all()) == 1
    try:
        co.command({'action': 'resume', 'id': first})
    except ValueError as exc:
        assert 'Task budget exhausted' in str(exc), str(exc)
    else:
        raise AssertionError('ordinary resume reset an exhausted budget')
    assert_held()
    co.command({'action': 'pilot-stop'})
    second, _, second_held, _ = owned(co, 490)
    assert second != first and second_held['repair_key'] != saved['held']['repair_key']
    assert second_held['outcome_id'] != saved['held']['outcome_id']
    assert co.store.pilot_task() is None
    co.command({'action': 'pilot-start', 'id': second})
    assert co.store.pilot_task() == second and co.store.claim_pilot(second)
    second_state = co.store.get(second)
    assert second_state['repair_provenance']['company_id'] == 'COMP-0490'
    assert second_state['repair_provenance']['source_revision'] == 'fixture-revision-490'
    assert second_state['status'] == 'RUNNING' and counters(second_state) == [0, 0, 0]
    assert second_state['max_sessions'] == 1 and co.store.inference_receipts(second) == []
    assert not co.store.queue_enabled() and not co.store.campaign_enabled()
    assert_held()
    assert len(co.store.all()) == 2
    model.assert_not_called()
    (work / 'RESULT.json').write_text(json.dumps({'result': 'PASS',
        'exhaust_pid': saved['pid'], 'reopen_pid': os.getpid(), 'first_status': 'PAUSED_BUDGET',
        'first_counters': counters(saved['state']), 'duplicate_absorbed': True,
        'resume_refused': True, 'unchanged_first_state_and_receipts': True,
        'second_status': second_state['status'], 'second_counters': counters(second_state),
        'reopen_model_calls': model.call_count, 'global_queue_open': False, 'campaign_open': False},
        indent=2, sort_keys=True) + '\n')


def child(name, work):
    repo = work / 'repo'
    if name == 'exhaust':
        for folder in ('src', 'tests', 'docs'):
            (repo / folder).mkdir(parents=True)
        (repo / 'src/a.py').write_text('value = 1\n')
        (repo / 'tests/test_a.py').write_text('def test_a(): assert True\n')
        (repo / 'docs/wrapper-development-test-protocol.md').write_text(
            '# Required wrapper development and test protocol\nFollow the tests.\n')
    model = Mock(side_effect=AssertionError('reopened fixture must not invoke inference'))
    resolver = {'COMP-0489': 'fixture-revision-489', 'COMP-0490': 'fixture-revision-490'}.get
    co = coordinator.Coordinator(work / 'tasks', model=model, company_revision_resolver=resolver,
        budget=lambda *_: SimpleNamespace(available_generation_tokens=4000, prompt_tokens=500))
    co.workflow_version = 2
    def public_board(tool, args, _names):
        url = 'https://job-boards.greenhouse.io/fixture489'
        assert name == 'exhaust' and tool == 'web_read' and args == {'url': url}
        return {'ok': True, 'result': {'url': url, 'status': 200, 'content_type': 'text/plain',
            'text': 'Fixture Company 489 Careers. No positions available at this time.'}}

    with patch.object(coordinator.code, 'ROOT', repo), patch('coordinator_workspace.batch_source', return_value=repo), \
         patch.object(coordinator.code, 'git', return_value=''), \
         patch.object(coordinator.web, 'execute', side_effect=public_board), \
         patch.object(coordinator.code, 'run_tests', return_value={'exit_code': 0, 'timed_out': False, 'output': '1 passed'}):
        phase(co, work, name, model)


if __name__ == '__main__':
    if len(sys.argv) == 3:
        child(sys.argv[1], Path(sys.argv[2]))
    else:
        work = Path(mkdtemp(prefix='budget-run-', dir=Path(__file__).parent))
        for name in ('exhaust', 'reopen'):
            subprocess.run([sys.executable, '-B', str(Path(__file__).absolute()), name, str(work)],
                           cwd=work, check=True, timeout=15)
        print(work / 'RESULT.json')
        print((work / 'RESULT.json').read_text(), end='')
