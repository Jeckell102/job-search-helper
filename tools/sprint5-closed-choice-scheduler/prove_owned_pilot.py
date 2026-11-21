"""Drive the isolated pilot with the archived owned outcome and a simulated Jetson."""
from contextlib import closing
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory, mkdtemp
from types import SimpleNamespace
from unittest.mock import patch
import json
import shutil
import sqlite3
import subprocess
import sys


STAGE = Path(__file__).resolve().parent
OWNER = Path('/tmp/jsh-s5-owned-readback-proof.ddhsnqyo')
ORIGINAL = Path('/tmp/jsh-s5-amphenol-owned-replay/single-owned-choice-run')
MODEL_PROOF = 'dc7235dbeb02bca5cecd94c0b2e652cdbfad1a6bd9a7a26fe731cf5cdb46409e'
SOURCE_PIN = '895ec36e443eea5a1c49c622d99b505d5ed49d5ff6c22d37e71eb5a610bb3c9d'


def offline(event, _args):
    if event in {'socket.connect', 'socket.getaddrinfo'}:
        raise RuntimeError('Pilot composition rehearsal is offline')


def main():
    sys.addaudithook(offline)
    native = Path('/home/chris/job-search-helper_old')
    tools = STAGE / 'dev/wrapper-coder/tools'
    sys.path[:0] = [str(tools), str(STAGE / 'src')]
    import coding_tools as code
    from acquiretm_membership_recipe import TARGET_PATH
    from amphenol_recipe_candidate import save_candidate
    from amphenol_recipe_choice_input import read_owned_choice_input
    from coordinator import AMPHENOL_RECIPE_WORK_ORDER, Coordinator

    root = Path(mkdtemp(prefix='jsh-s5-owned-pilot-composition.'))
    print(root, file=sys.stderr, flush=True)
    application = root / 'owned'
    application.mkdir(mode=0o700)
    for name in ('company-event-bridge', 'ordinary-event-inventory'):
        shutil.copytree(OWNER / name, application / name)
    tasks = root / 'tasks'
    tasks.mkdir(mode=0o700)
    for before, after in (
        *((OWNER / name, application / name) for name in ('jobs.sqlite3', 'state.db', 'inventories.sqlite3')),
        (OWNER / 'coordinator/tasks.sqlite3', tasks / 'tasks.sqlite3'),
    ):
        with (closing(sqlite3.connect(before.as_uri() + '?mode=ro', uri=True)) as reader,
              closing(sqlite3.connect(after)) as target):
            reader.backup(target)

    shutil.copytree(ORIGINAL / 'queue-base', root / 'queue-base')
    code.BASE, code.ROOT, code.VENV = root, root / 'repo', native / '.venv'
    archive = (ORIGINAL / 'choice-receipt.json').read_bytes()
    assert sha256(archive).hexdigest() == MODEL_PROOF
    recorded = json.loads(archive)
    assert recorded['status'] == 'CHOICE_ACCEPTED' and recorded['calls'] == 1
    binding = recorded['owned_binding']
    calls = []

    def simulated_model(messages, schemas, limit):
        calls.append(1)
        assert len(calls) == 1 and (messages, schemas) == (selected['messages'], selected['tools'])
        assert 256 <= limit <= 1000
        return {
            'message': {'role': 'assistant', 'tool_calls': [{'type': 'function', 'function': {
                'name': 'worker_checkpoint', 'arguments': {
                    'summary': 'W1', 'next_action': 'listing_membership_change', 'outcome': 'phase_done',
                },
            }}]},
            'usage': {'prompt_eval_count': 500, 'eval_count': 60, 'done_reason': 'stop'},
        }

    def owned_reader(state):
        return read_owned_choice_input(
            application, SimpleNamespace(path=tasks / 'tasks.sqlite3'),
            outcome_id=binding['outcome_id'], expected_task_id=state['id'], enabled=True)

    def approved_profile(held):
        if held['outcome_id'] != binding['outcome_id']:
            return None
        return {
            'source_revision': binding['source_revision'], 'mode': 'review', 'max_sessions': 1,
            'objective': 'Review the recorded AcquireTM pagination failure in '
                         'src/job_search_helper/acquiretm.py and tests/test_acquiretm.py.',
            'integration': {
                'company_id': binding['company_id'], 'company': 'Amphenol Aerospace',
                'configured_url': binding['board'], 'ats': 'AcquireTM',
                'source_targets': [TARGET_PATH], 'tests': ['tests/test_acquiretm.py'],
                'work_order': AMPHENOL_RECIPE_WORK_ORDER,
            },
        }

    def cut(*_args):
        raise OSError('fixture interruption before saving candidate')

    def build(state, prepared, receipt):
        return save_candidate(tasks / state['id'], code.root(), prepared, receipt)

    def offline_baseline(paths):
        # This disposable namespace cannot access the user systemd bus.
        # Keep the real Landlock/seccomp command inside the normal test worker.
        assert paths == 'tests/test_acquiretm.py'
        with TemporaryDirectory(prefix='baseline-', dir=root) as output:
            command = ['/usr/bin/python3', '-I', str(tools / 'coding_sandbox.py'),
                       str(code.root()), str(code.VENV), output, paths]
            result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=90)
        return {'exit_code': result.returncode, 'timed_out': False,
                'output': result.stdout + result.stderr}

    common = {
        'budget': lambda *_: SimpleNamespace(available_generation_tokens=1200, prompt_tokens=500),
        'company_revision_resolver': lambda company_id: (
            binding['source_revision'] if company_id == binding['company_id'] else None),
        'repair_profile_selector': approved_profile,
        'owned_recipe_reader': owned_reader,
    }
    first = Coordinator(tasks, model=simulated_model, owned_recipe_builder=cut, **common)
    selected = read_owned_choice_input(application, first.store, outcome_id=binding['outcome_id'], enabled=True)
    assert selected['binding'] == binding
    [held] = first.store.held_repair_intake()
    assert not first.store.queue_enabled() and not first.store.campaign_enabled()
    scheduler = first._acquire_scheduler()
    try:
        source_token = code.WORKSPACE.set(root / 'queue-base')
        try:
            task = first.command({'action': 'prepare-held-repair', 'repair_key': held['repair_key']})['id']
        finally:
            code.WORKSPACE.reset(source_token)
        assert first.command({'action': 'pilot-start', 'id': task})['ok']
        assert first.store.claim_pilot(task)
        with patch.object(code, 'run_tests', offline_baseline):
            first.step(task)
        assert first.store.get(task)['baseline_passed'] is True
        assert first.store.claim_pilot(task)
        try:
            first.step(task)
        except OSError as exc:
            assert str(exc) == 'fixture interruption before saving candidate', exc
        else:
            raise AssertionError('The fixture did not reach its intended interruption')
        [choice] = first.store.inference_receipts(task)
        assert choice['status'] == 'COMPLETED' and choice['accepted_recipe_choice']['summary'] == 'W1'
        assert not (tasks / task / 'recipe-candidate').exists()
    finally:
        first._release_scheduler(scheduler)

    def refuse_inference(*_args):
        raise AssertionError('Restart replayed the completed choice')

    restarted = Coordinator(tasks, model=refuse_inference, owned_recipe_builder=build, **common)
    scheduler = restarted._acquire_scheduler()
    try:
        restarted.store.recover()
        assert restarted.store.claim_pilot(task)
        restarted.step(task)
        saved = restarted.store.get(task)
        assert saved['status'] == 'REVIEW_COMPLETE_LIVE_NOT_VALIDATED'
        assert saved['calls'] == len(calls) == 1
        assert restarted.store.inference_receipts(task) == [choice]
        assert not restarted.store.queue_enabled() and not restarted.store.campaign_enabled()
        candidate = tasks / task / 'recipe-candidate'
        assert sha256((candidate / TARGET_PATH).read_bytes()).hexdigest() == SOURCE_PIN
        written = json.loads((candidate / 'build-receipt.json').read_text())
        assert written['request_id'] == choice['request_id']
        assert written['witness_sha256'] == binding['witness_sha256']
    finally:
        restarted._release_scheduler(scheduler)
    print(json.dumps({
        'disposition': 'DISPOSABLE_OWNED_PILOT_RESTART_AND_CANDIDATE_PASS',
        'outcome_id': binding['outcome_id'], 'task_id': task, 'source_sha256': SOURCE_PIN,
        'simulated_model_calls': len(calls), 'real_model_calls': 0,
        'receipt_preserved': True, 'baseline_passed': True, 'release_installed': False,
    }, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
