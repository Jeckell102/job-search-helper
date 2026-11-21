"""One bounded recipe-choice experiment using the existing coordinator receipts."""
from dataclasses import replace
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
import sys
import time

root = Path(__file__).resolve().parent
native = Path('/home/chris/job-search-helper_old/dev/wrapper-coder')
staged_witness = Path('/tmp/jsh-s5-amphenol-typed-live/result.json')
guided_database = Path('/tmp/jsh-s5-amphenol-guided.dev/tasks/tasks.sqlite3')
previous_choice = Path('/tmp/jsh-s5-amphenol-recipe-choice/tasks/tasks.sqlite3')
witness_sha256 = 'd10331c3e89b63ef00a8a26af7ac4c69f66beb95167e3b2005b4d9e101cd0602'

sys.path.insert(0, str(native / 'tools'))
import coding_tools as code
import coordinator as existing
from coordinator_baseline import files


def sha(path):
    return sha256(path.read_bytes()).hexdigest()


def read_only(database):
    return sqlite3.connect(f'{database.as_uri()}?mode=ro', uri=True, timeout=5)


def assert_other_schedulers_idle():
    for database in (native / 'tasks/tasks.sqlite3', guided_database, previous_choice):
        with read_only(database) as db:
            settings = {key: json.loads(value) for key, value in db.execute(
                "SELECT key,value FROM settings WHERE key IN ('queue_enabled','campaign_enabled','autopilot_enabled')")}
            if settings.get('queue_enabled', True) or settings.get('campaign_enabled') or settings.get('autopilot_enabled'):
                raise RuntimeError('Other scheduling controls are active')
            if db.execute("SELECT 1 FROM tasks WHERE json_extract(state,'$.status') IN ('QUEUED','RUNNING','PAUSING') LIMIT 1").fetchone():
                raise RuntimeError('Another task is active')
            if db.execute("SELECT 1 FROM inference_receipts WHERE status IN ('DISPATCHING','UNCERTAIN') LIMIT 1").fetchone():
                raise RuntimeError('Other inference must be settled first')


def bounded_budget(messages, offered):
    measured = existing.estimate(messages, offered)
    return replace(measured, available_generation_tokens=min(1000, measured.available_generation_tokens))


def infer(messages, offered, limit):
    assert_other_schedulers_idle()
    if ([schema['function']['name'] for schema in offered] != ['worker_checkpoint']
            or not 256 <= limit <= 1000):
        raise RuntimeError('Model choice must use only the closed checkpoint schema')
    return existing.infer(messages, offered, limit)


class RecipeChoice(existing.Coordinator):
    def messages(self, state, protocol):
        if state['mode'] != 'review' or state['phase'] != 'inspect':
            raise RuntimeError('Recipe selection is a read-only inspection decision')
        system = ('Choose one strategy as a strictly bounded evidence decision. '
                  'Respond using worker_checkpoint, one call. Never propose source code. '
                  'Use evidence ID W1 in summary. Put the exact chosen strategy ID in next_action, '
                  'with phase_done in outcome. If observations are insufficient, use hold '
                  'in next_action and blocked in outcome. Use only the values in the tool schema.')
        options = {
            'listing_membership_change': 'Wait for fresh posting identifiers on the verified board after the same page click, then run the existing scope, completeness and full-detail checks.',
            'fixed_delay': 'Use the example observed elapsed time as a fixed sleeping interval on every page, with no listing state as readiness evidence.',
            'hold': 'Current observations cannot support one bounded repair.'
        }
        return [{'role': 'system', 'content': system}, {'role': 'user', 'content': json.dumps({
            'task': 'Select how to recognize a completed pagination transition without weakening any existing validation.',
            'candidates': options,
            'W1': witness['failure']['evidence'],
            'scope': 'Amphenol Aerospace COMP-0490 on its verified AcquireTM employer board',
        }, sort_keys=True)}]


if len(sys.argv) != 3:
    sys.exit('Pass the independently approved recipe file and its exact SHA-256')
recipe = Path(sys.argv[1]).resolve(strict=True)
recipe_sha256 = sys.argv[2]
assert str(recipe).startswith('/tmp/') and sha(recipe) == recipe_sha256
assert sha(staged_witness) == witness_sha256
witness = json.loads(staged_witness.read_text())
assert witness['same_board'] is True and witness['state'] == 'partial'
assert witness['failure']['evidence_code'] == 'acquiretm_updatepanel_premature_read'
assert_other_schedulers_idle()
if (root / 'tasks').exists():
    sys.exit('Existing durable selection task present. Its request must not be repeated.')
os.umask(0o077)
source = native / 'queue-base'
private_source = root / 'queue-base'
manifest = files(source)
for name in manifest:
    target = private_source / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((source / name).read_bytes())
assert files(source) == files(private_source) == manifest
(root / 'bridge-token').symlink_to(native / 'bridge-token')
code.BASE = root
code.ROOT = root / 'repo'
existing.MAX_CALLS = 1
existing.CHECKPOINT_SCHEMA = code.spec('worker_checkpoint',
    'Record the evidence ID and one bounded next-action strategy. These are exact identifiers.', {
        'summary': {'type': 'string', 'enum': ['W1']},
        'next_action': {'type': 'string', 'enum': ['listing_membership_change', 'fixed_delay', 'hold']},
        'outcome': {'type': 'string', 'enum': ['phase_done', 'blocked']},
    }, ['summary', 'next_action', 'outcome'])
coordinator = RecipeChoice(root / 'tasks', model=infer, budget=bounded_budget)
coordinator.store.configure_queue(False)
reply = coordinator.command({'action': 'batch', 'campaign_id': 's5-amphenol-recipe-enum-choice-20261121', 'items': [{
    'objective': 'Choose a bounded pagination strategy for the observed board. Run tests/test_acquiretm.py.',
    'mode': 'review', 'max_sessions': 1,
    'integration': {'company_id': 'COMP-0490', 'company': 'Amphenol Aerospace',
                    'configured_url': witness['source'], 'ats': 'AcquireTM',
                    'tests': ['tests/test_acquiretm.py'],
                    'source_targets': ['src/job_search_helper/acquiretm.py']},
}]})
assert reply['ok'] and not reply['reused'] and len(reply['ids']) == 1
selected = reply['ids'][0]
(root / 'task-id').write_text(selected + '\n')
print('Single reviewed recipe choice task', selected, flush=True)
coordinator.command({'action': 'pilot-start', 'id': selected})
coordinator.start()
try:
    while True:
        state = coordinator.store.get(selected)
        if state['status'] not in ('QUEUED', 'RUNNING', 'PAUSING'):
            break
        if not coordinator.thread.is_alive():
            raise RuntimeError(coordinator.health()['text'])
        time.sleep(1)
finally:
    coordinator.stop.set()
    coordinator.wake.set()
    coordinator.thread.join(timeout=15)
    if not coordinator.store.unresolved_inferences():
        (root / 'bridge-token').unlink()

inference = coordinator.store.inference_receipts(selected)
checkpoint = state.get('checkpoint')
valid = (state['status'] == 'REVIEW_COMPLETE_LIVE_NOT_VALIDATED' and len(inference) == 1
         and inference[0]['status'] == 'COMPLETED' and sha(recipe) == recipe_sha256
         and checkpoint == {'summary': 'W1', 'next_action': 'listing_membership_change', 'outcome': 'phase_done'})
result = {'task_id': selected, 'status': 'CHOICE_ACCEPTED' if valid else 'HELD_NO_VALID_CHOICE',
          'task_state': state['status'], 'calls': state['calls'], 'recipe_sha256': recipe_sha256,
          'witness_sha256': witness_sha256,
          'model_request_id': inference[0]['request_id'] if len(inference) == 1 else None,
          'model_response_sha256': inference[0]['response_digest'] if len(inference) == 1 else None,
          'selection': {'strategy': 'listing_membership_change', 'evidence': 'W1'} if valid else None}
(root / 'choice-receipt.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
print(json.dumps(result, indent=2), flush=True)
raise SystemExit(0 if valid else 2)
