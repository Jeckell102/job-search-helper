import json
import tempfile
import time
import sys

sys.path.insert(0, '/home/chris/.codex/.chatgpt-projects/g-p-6ab70f626df48191a04039506182677f/work/wrapper-workflow-20261118/host')
from coordinator_store import Store
import coordinator as coordinator_module
from pathlib import Path


def spec(objective, company='COMP-0001'):
    return dict(
        objective=objective,
        tests=['tests/test_a.py'],
        mode='develop',
        max_sessions=10,
        authorization_version=1,
        evidence_requirements={'version': 1, 'required_files': ['tests/test_a.py', 'src/a.py'], 'source_targets': []},
        workflow_version=2,
        integration={'company_id': company, 'company': 'Example', 'configured_url': 'https://example.com/jobs',
                     'tests': ['tests/test_a.py'], 'source_targets': ['src/a.py']},
    )


with tempfile.TemporaryDirectory() as tmp:
    store = Store(tmp)
    first = store.enqueue_batch('digest-one', [spec('First bounded assignment')], held=True)[0][0]
    store.update(first, stop_requested=True, reason='Pause requested.')
    activated = store.activate_next_untouched()
    print(json.dumps({
        'paused_task_selected': activated['id'] == first,
        'stop_requested_before': True,
        'stop_requested_after': activated['stop_requested'],
        'selected_status': activated['status'],
    }, sort_keys=True))

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp) / 'repo'
    (root / 'src').mkdir(parents=True)
    (root / 'tests').mkdir()
    (root / 'docs').mkdir()
    (root / 'src/a.py').write_text('value = 1\n')
    (root / 'tests/test_a.py').write_text('def test_a(): assert True\n')
    coordinator_module.code.ROOT = root
    co = coordinator_module.Coordinator(Path(tmp) / 'tasks')
    result = co.command({'action': 'batch', 'items': [{
        'objective': 'Develop COMP-0001 Correct Company at https://correct.example/jobs. Inspect src/a.py. Run tests/test_a.py.',
        'mode': 'develop',
        'integration': {
            'company_id': 'COMP-9999', 'company': 'Different Company',
            'configured_url': 'https://different.example/jobs',
            'tests': ['tests/test_a.py'], 'source_targets': ['src/a.py'],
        },
    }]})
    state = co.store.get(result['ids'][0])
    print(json.dumps({
        'contradictory_identity_accepted': True,
        'objective': state['objective'],
        'structured_identity': state['integration'],
    }, sort_keys=True))

with tempfile.TemporaryDirectory() as tmp:
    store = Store(tmp)
    a = store.enqueue_batch('digest-one', [spec('First bounded assignment')], held=True)[0][0]
    b = store.enqueue_batch('digest-two', [spec('Changed bounded assignment')], held=True)[0][0]
    print(json.dumps({
        'duplicate_company_tasks': [a, b],
        'company_ids': [store.get(a)['integration']['company_id'], store.get(b)['integration']['company_id']],
        'task_count': len(store.all()),
    }, sort_keys=True))

with tempfile.TemporaryDirectory() as tmp:
    store = Store(tmp)
    direct = store.create(
        'Unrelated direct task', ['tests/test_a.py'], 'review',
        authorization_version=1, workflow_version=2,
    )
    campaign = store.enqueue_batch('campaign', [spec('Campaign assignment')], held=True)[0][0]
    store.configure_autopilot(True)
    selected = store.activate_next_untouched()
    claimed = store.claim_queued()
    print(json.dumps({
        'campaign_selection_while_direct_queued': selected,
        'claimed_task': claimed['id'],
        'claimed_unrelated_direct_task': claimed['id'] == direct['id'],
        'campaign_task_remained': store.get(campaign)['status'],
    }, sort_keys=True))
