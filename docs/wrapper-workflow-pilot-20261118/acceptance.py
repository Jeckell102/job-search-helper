"""One bounded real host/Jetson acceptance; saves receipts only on MuleLab."""
import json
from pathlib import Path
import sys
import time
sys.path.insert(0, '/home/chris/job-search-helper_old/dev/wrapper-coder/tools')
import coordinator as c
import coordinator_workflow as w
from coordinator_workspace import workspace

base = c.code.BASE/'runs'/time.strftime('workflow-acceptance-%Y%m%d-%H%M%S')
co = c.Coordinator(base/'tasks')
task = co.command({'action': 'batch', 'items': [{'objective': 'Review the existing Scythe Robotics COMP-0506 offline test contract in src/job_search_helper/scythe_robotics.py. Run tests/test_scythe_robotics.py. This is coordinator acceptance; live source validation is a separate assignment.', 'mode': 'review', 'max_sessions': 2}]})['ids'][0]
print(json.dumps({'acceptance': str(base), 'task': task}), flush=True)
co.step(task)
state = co.store.get(task)
if not state.get('baseline_passed'):
    raise RuntimeError('Real isolated baseline failed: ' + str(co.store.receipts(task)[-1]['result']))
for _ in range(40):
    state = co.store.get(task)
    with workspace(co.store, state):
        plan = w.plan(state, co.store.receipts(task), c.manifest(), c.code.root())
    if not plan['next']:
        break
    co.step(task)
    if co.store.get(task)['status'] != 'QUEUED':
        raise RuntimeError(co.store.get(task)['reason'])
else:
    raise RuntimeError('Preparation did not finish within acceptance bound.')
print(json.dumps({'baseline': 'passed', 'automatic_receipts': len(co.store.receipts(task)), 'calls_before_inference': co.store.get(task)['calls']}), flush=True)
co.step(task)  # One bounded model session with exact installed tokenizer.
if co.store.get(task)['phase'] == 'verify':
    co.step(task)
state = co.store.get(task)
result = {k: state[k] for k in ('id', 'status', 'phase', 'calls', 'tokens', 'sessions', 'reason')}
(base/'acceptance-result.json').write_text(json.dumps(result, indent=2))
print(json.dumps(result), flush=True)
