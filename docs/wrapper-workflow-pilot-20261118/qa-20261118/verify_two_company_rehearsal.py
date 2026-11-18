"""Bounded host rehearsal: real tools/tests, simulated web/model, private data only."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'wrapper-workflow-20261118/host'))
import coordinator as c


def response(name, args):
    return {'message': {'role': 'assistant', 'content': '', 'tool_calls': [
        {'type': 'function', 'function': {'name': name, 'arguments': args}}]},
        'usage': {'done_reason': 'stop', 'prompt_eval_count': 500, 'eval_count': 60}}


def main():
    packets, visits, tests = [], [], []
    with tempfile.TemporaryDirectory(prefix='wrapper-two-company-qa-') as folder:
        root = Path(folder) / 'baseline'
        for area in ('src', 'tests', 'docs'):
            (root / area).mkdir(parents=True)
        (root / 'src/company.py').write_text('value = 0\n')
        (root / 'tests/test_company.py').write_text(
            'from company import value\ndef test_company():\n    assert value == 1\n')
        (root / 'docs/wrapper-development-test-protocol.md').write_text(
            '# Required wrapper development and test protocol\nRead assigned source and tests. Repair only the assigned source.\n')
        (root / 'pyproject.toml').write_text('[tool.pytest.ini_options]\n')
        tasks = Path(folder) / 'tasks'

        def model(messages, schemas, limit):
            assert len(messages) == 2, 'Conversation history leaked between bounded calls'
            packet = json.loads(messages[1]['content'])
            packets.append(packet)
            identity = packet['integration_identity']
            assert identity['company_id'] in ('COMP-9001', 'COMP-9002')
            other = 'Beta Rehearsal' if identity['company_id'] == 'COMP-9001' else 'Alpha Rehearsal'
            assert other not in messages[1]['content'], 'Cross-company context leakage'
            if identity['company_id'] == 'COMP-9002':
                assert (c.code.root() / 'src/company.py').read_text() == 'value = 0\n'
                return response('worker_checkpoint', {'summary': 'Beta requires operator source clarification.',
                    'next_action': 'Inspect the saved fixture evidence before retry.', 'outcome': 'blocked'})
            if packet['phase'] == 'implement':
                path = c.code.root() / 'src/company.py'
                if path.read_text() == 'value = 0\n':
                    return response('code_edit', {'path': 'src/company.py',
                        'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                        'old': 'value = 0', 'new': 'value = 1'})
            return response('worker_checkpoint', {'summary': 'Alpha fixture source inspected; bounded repair ready.',
                'next_action': 'Run immutable acceptance tests.', 'outcome': 'phase_done'})

        def web(name, args, *unused, **kwargs):
            assert name in ('web_read', 'rendered_web_read'), name
            company = 'Alpha Rehearsal' if 'alpha' in args['url'] else 'Beta Rehearsal'
            return {'ok': True, 'result': {'status': 200, 'url': args['url'],
                'text': company + ' careers. This is a synthetic public listing fixture for offline workflow testing.'}}

        original_test = c.code.run_tests
        def real_test(paths):
            result = original_test(paths)
            tests.append({'workspace': c.code.root().parent.name, 'exit_code': result['exit_code']})
            return result

        with patch.object(c.code, 'ROOT', root), patch.object(c.code, 'BASE', Path(folder)), \
             patch.object(c.code, 'VENV', Path('/home/chris/job-search-helper_old/.venv')), \
             patch.object(c.web, 'execute', side_effect=web), \
             patch.object(c.code, 'run_tests', side_effect=real_test):
            budget = lambda messages, schemas: SimpleNamespace(available_generation_tokens=6000)
            co = c.Coordinator(tasks, model, budget)
            co.command({'action': 'queue-pause'})
            items = []
            for number, name, slug in ((9001, 'Alpha Rehearsal', 'alpha'), (9002, 'Beta Rehearsal', 'beta')):
                items.append({'objective': 'Repair src/company.py and run tests/test_company.py', 'mode': 'develop',
                    'integration': {'company_id': f'COMP-{number}', 'company': name,
                        'configured_url': f'https://example.com/{slug}',
                        'tests': ['tests/test_company.py'], 'source_targets': ['src/company.py']}})
            ids = co.command({'action': 'batch', 'campaign_id': 'offline-two-company', 'items': items})['ids']
            co.command({'action': 'campaign-start', 'campaign_id': 'offline-two-company'})
            paused_once = False
            for step in range(80):
                co.store.activate_next_campaign('offline-two-company')
                task = co.store.claim_campaign('offline-two-company')
                if not task:
                    result = co.command({'action': 'campaign-status'})['campaign_result']
                    if result['state'] in ('DRAINED', 'DRAINED_WITH_EXCEPTIONS'):
                        break
                    raise AssertionError(result)
                if task['id'] == ids[1] and ids[1] not in visits:
                    assert all(task[key] == 0 for key in ('calls', 'tokens', 'sessions'))
                    assert co.store.receipts(ids[1]) == []
                    assert co.store.inference_receipts(ids[1]) == []
                visits.append(task['id'])
                co.step(task['id'])
                state = co.store.get(task['id'])
                if not paused_once and state['calls'] > 0 and state['status'] == 'QUEUED':
                    co.command({'action': 'campaign-stop'})
                    co.paused(task['id'])
                    saved = co.store.get(task['id'])
                    receipts = co.store.receipts(task['id'])
                    co = c.Coordinator(tasks, model, budget)
                    co.store.recover()
                    assert not co.store.campaign_enabled()
                    assert co.store.claim_campaign('offline-two-company') is None
                    for key in ('calls', 'tokens', 'sessions', 'phase'):
                        assert co.store.get(task['id'])[key] == saved[key], key
                    assert co.store.receipts(task['id']) == receipts
                    co.command({'action': 'campaign-start', 'campaign_id': 'offline-two-company'})
                    co.command({'action': 'resume', 'id': task['id']})
                    paused_once = True
            else:
                raise AssertionError('Bounded rehearsal did not finish within 80 steps')
            first, second = [co.store.get(task) for task in ids]
            assert first['status'] == 'AWAITING_LIVE_VALIDATION', first
            assert second['status'] == 'PAUSED_BLOCKED', second
            assert paused_once and len(packets) >= 3
            assert all(task == ids[0] for task in visits[:visits.index(ids[1])])
            assert ids[0] not in visits[visits.index(ids[1]):]
            assert (tasks / ids[0] / 'repo/src/company.py').read_text() == 'value = 1\n'
            assert (tasks / ids[1] / 'repo/src/company.py').read_text() == 'value = 0\n'
            assert (root / 'src/company.py').read_text() == 'value = 0\n'
            assert c.code.WORKSPACE.get() is None
            assert result['state'] == 'DRAINED_WITH_EXCEPTIONS' and result['total'] == 2, result
            assert not co.store.campaign_enabled() and not co.store.queue_enabled()
            assert not co.store.unresolved_inferences()
            for state in (first, second):
                ledger = co.store.inference_receipts(state['id'])
                assert len(ledger) == state['calls']
                assert all(r['task'] == state['id'] and r['status'] == 'COMPLETED' for r in ledger)
            assert co.command({'action': 'campaign-status'})['campaign_result'] == result
            assert any(t['exit_code'] != 0 for t in tests) and any(t['exit_code'] == 0 for t in tests), tests
            report = {'result': 'PASS', 'scope': 'Offline host rehearsal; not live scraper or Jetson validation',
                'model_calls': len(packets), 'steps': len(visits), 'pause_restart_verified': paused_once,
                'real_test_results': tests, 'campaign': result,
                'states': [{k: state[k] for k in ('id', 'status', 'phase', 'calls', 'tokens', 'sessions')}
                           for state in (first, second)]}
            (HERE / 'two-company-rehearsal.json').write_text(json.dumps(report, indent=2) + '\n')
            print('PASS: two companies, real guarded edit and offline tests, isolated context/workspaces, pause/restart, terminal exception accounting.')


if __name__ == '__main__':
    main()
