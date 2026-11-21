"""Verify the enrolled host respects a real SQLite disk hold across recovery."""
from contextlib import closing
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory, mkdtemp
from types import SimpleNamespace
from unittest.mock import patch
import json
import os
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
    from amphenol_recipe_choice_input import read_owned_choice_input
    text = Path.read_text

    def fixture_host_token(path, *args, **kwargs):
        if path.name == 'bridge-token':
            return 'offline-fixture-only'
        return text(path, *args, **kwargs)

    with patch.object(Path, 'read_text', fixture_host_token):
        import host_server as host

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
    shutil.copytree(ORIGINAL / 'queue-base', root / 'repo')
    code.BASE, code.ROOT, code.VENV = root, root / 'repo', native / '.venv'
    host.JOB_SEARCH_ROOT = root
    os.environ.update(JOB_STORAGE_BACKEND='sqlite', SPREADSHEET_ID='sheet',
                      STATE_DB_FILE=str(application / 'state.db'),
                      JOB_DB_FILE=str(application / 'jobs.sqlite3'))
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

    def cut(*_args):
        raise OSError('fixture interruption before saving candidate')

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

    enrollment = {key: binding[key] for key in ('company_event_id', 'request_id', 'source_revision')}
    recipe = host.AmphenolRecipeEnrollment.from_process_environment({
        'WRAPPER_AMPHENOL_RECIPE_ENROLLMENT': json.dumps(enrollment),
    })
    first = host.build_coordinator(recipe)
    first.model = simulated_model
    first.budget = lambda *_: SimpleNamespace(available_generation_tokens=1200, prompt_tokens=500)
    first.owned_recipe_builder = cut
    supervision = host.build_supervision(first, recipe=recipe)
    selected = read_owned_choice_input(application, first.store, outcome_id=binding['outcome_id'], enabled=True)
    assert selected['binding'] == binding
    assert not first.store.all()
    assert not first.store.queue_enabled() and not first.store.campaign_enabled()
    scheduler = first._acquire_scheduler()
    try:
        started = supervision.catch_up()
        assert started['state'] == 'RECIPE_PILOT_QUEUED' and started['outcome_id'] == binding['outcome_id'], started
        task = started['task_id']
        disk = SimpleNamespace(free=1, total=10 * 1024**3)
        supervision.disk_usage = lambda _: disk
        assert supervision.tick()['state'] == 'DISK_PRESSURE_HOLD'
        held_coordinator = host.build_coordinator(recipe)
        assert held_coordinator.store.pilot_task() is None
        assert held_coordinator.store.claim_pilot(task) is None
        assert held_coordinator.store.get(task)['status'] == 'PAUSED'
        assert not held_coordinator.store.inference_receipts(task) and not calls

        disk.free = 9 * 1024**3
        recovered_supervision = host.build_supervision(held_coordinator, recipe=recipe)
        recovered_supervision.disk_usage = lambda _: disk
        result = recovered_supervision.tick()
        assert result['state'] == 'ACTIVE'
        assert result['catch_up'] == {'state': 'HELD_RECIPE_OWNER'}
        assert [state['id'] for state in held_coordinator.store.all()] == [task]
        assert held_coordinator.store.pilot_task() is None and not calls
        assert not held_coordinator.store.queue_enabled() and not held_coordinator.store.campaign_enabled()

        # Explicit approval to resume this single task exists only in the fixture.
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

    restarted = host.build_coordinator(recipe)
    restarted.model = refuse_inference
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
        assert supervision.catch_up() != started
        assert len(restarted.store.all()) == 1
    finally:
        restarted._release_scheduler(scheduler)
    print(json.dumps({
        'disposition': 'DISPOSABLE_ENROLLED_DISK_HOLD_AND_RESTART_PASS',
        'outcome_id': binding['outcome_id'], 'task_id': task, 'source_sha256': SOURCE_PIN,
        'simulated_model_calls': len(calls), 'real_model_calls': 0,
        'receipt_preserved': True, 'baseline_passed': True, 'release_installed': False,
        'activated_during_disk_hold': False, 'auto_restarted_after_disk_recovery': False,
    }, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
