"""Run the settled #03 continuation on a disposable database and workspace."""

import json
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch


HERE = Path(__file__).resolve().parent
PROJECT = Path('/home/chris/job-search-helper_old')
SAVED_BASELINE = HERE / 'saved-baseline'
VENV = PROJECT / '.venv'
sys.path[:0] = [str(HERE / 'tools'), str(SAVED_BASELINE / 'src')]

import coding_tools as code
from coordinator import Coordinator
from coordinator_baseline import binding, files
from coordinator_store import Store, task_state_digest
from embraer_operator_pilot import ENV, TARGET, EmbraerOperatorEnrollment


PARENT = 'WRAP-250158dc79'


def saved_fixture():
    return json.loads((HERE / 'PRIVATE_SAVED_FIXTURE.json').read_text())


def clone_baseline(parent, destination):
    exact = parent['assignment_baseline']
    for name, expected in exact['manifest'].items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        data = (SAVED_BASELINE / name).read_bytes()
        if sha256(data).hexdigest() != expected:
            raise ValueError('The saved frozen baseline no longer matches')
        target.write_bytes(data)
    if binding(files(destination)) != exact:
        raise ValueError('Disposable frozen baseline copy no longer matches')


def seed(root, saved):
    store = Store(root / 'tasks')
    with store.connect() as db:
        for table, rows in saved['rows'].items():
            if table == 'settings':
                db.executemany('INSERT OR REPLACE INTO settings VALUES (?,?)', rows)
            else:
                placeholders = ','.join('?' for _ in rows[0])
                db.executemany(f'INSERT INTO {table} VALUES ({placeholders})', rows)
    parent = store.get(PARENT)
    clone_baseline(parent, root / 'pilot-bases' / ('embraer-' + parent['assignment_baseline']['digest']))
    sender = saved['sender']
    [receiver] = saved['rows']['scrape_outcome_delivery_receipts']
    assert sender['acknowledged'] and saved['enrollment']['request_id'] == 'operator-embraer-20261122-03'
    assert sender['record']['identity']['request_id'] == saved['enrollment']['request_id']
    assert Store._validate_delivery_receipt(
        receiver[2:7], consumer=receiver[0], canonical=sender['record'],
        record_sha256=sender['digest']) == json.loads(sender['row'][6])
    expiry = min(int(time.time()) + 600, int(parent['activated_at']) + 3600)
    now = min(int(time.time()), expiry - 60)
    approval = {
        'schema': 'embraer-03-continuation-v1',
        'parent_task_id': PARENT,
        'parent_task_state_sha256': task_state_digest(parent),
        'repair_key': parent['held_repair_key'],
        'outcome_id': sender['record']['outcome_id'],
        'record_sha256': sender['digest'],
        'receipt_sha256': receiver[5],
        'failure_fingerprint': sender['record']['failure_fingerprint'],
        'source_revision': sender['record']['identity']['source_revision'],
        'baseline_sha256': parent['assignment_baseline']['digest'],
        'issued_at': now - 1,
        'expires_at': expiry,
    }
    (root / 'approval.json').write_text(json.dumps(approval))
    return now


def test_in_process(paths):
    sandbox = HERE / 'tools/coding_sandbox.py'
    with tempfile.TemporaryDirectory(prefix='offline-test-', dir=HERE) as scratch:
        command = ['/usr/bin/python3', '-I', str(sandbox), str(code.root()), str(VENV), scratch, *paths.split()]
        result = subprocess.run(command, capture_output=True, text=True, timeout=95)
    return {'exit_code': result.returncode, 'output': result.stdout + result.stderr,
            'timed_out': False, 'command': command}


def simulate_edit(messages, schemas, output_tokens):
    """Simulate one structurally valid response. Never use this as release evidence."""
    if len(schemas) != 1 or schemas[0]['function']['name'] != 'code_edit':
        raise AssertionError('The continuation can offer only its guarded edit')
    if output_tokens < 256:
        raise AssertionError('The measured compact turn must leave useful output room')
    source = (code.root() / TARGET).read_bytes()
    old = "                    raise _embraer_heading_failure()\n                raise FetchError('partial','Breezy visible detail identity or description missing.')"
    new = "                    pass  # Valid Embraer job banner beside the employer brand.\n                else:\n                    raise FetchError('partial','Breezy visible detail identity or description missing.')"
    if source.decode().count(old) != 1 or not any(old.splitlines()[0].strip() in m['content'] for m in messages):
        raise AssertionError('The offered packet must show the exact repair boundary')
    from coordinator import estimate
    count = estimate(messages, schemas).prompt_tokens
    assert count + output_tokens <= 1941
    return {'message': {'role': 'assistant', 'content': '', 'tool_calls': [{'type': 'function', 'function': {
        'name': 'code_edit', 'arguments': {'path': TARGET, 'sha256': sha256(source).hexdigest(),
                                          'old': old, 'new': new}}}]},
        'usage': {'prompt_eval_count': count, 'eval_count': 140, 'done_reason': 'tool_calls'}}


def snapshot_parent(store, saved):
    with store.connect() as db:
        for table in ('tasks', 'receipts', 'inference_receipts'):
            column = 'id' if table == 'tasks' else 'task'
            order = 'request_id' if table == 'inference_receipts' else 'id'
            rows = db.execute(f'SELECT * FROM {table} WHERE {column}=? ORDER BY {order}', (PARENT,)).fetchall()
            assert rows == [tuple(row) for row in saved['rows'][table]], table
        for table in ('scrape_outcome_intake', 'scrape_outcome_delivery_receipts'):
            assert db.execute(f'SELECT * FROM {table}').fetchall() == [tuple(row) for row in saved['rows'][table]]


def run_phase(root, simulation_time, phase):
    saved = saved_fixture()
    approval = json.loads((root / 'approval.json').read_text())
    enrollment = EmbraerOperatorEnrollment.from_process_environment({ENV: json.dumps(saved['enrollment'])})
    baseline = root / 'pilot-bases' / ('embraer-' + approval['baseline_sha256'])
    coordinator = Coordinator(root / 'tasks', model=simulate_edit,
                              company_revision_resolver=lambda _company: approval['source_revision'])
    generation = coordinator.store.control_generation()

    @contextmanager
    def isolated_owner(_enrollment):
        yield baseline, root / 'fixture-only-jobs.sqlite3', 'fixture-only-destination'

    with (patch.object(code, 'BASE', root), patch.object(code, 'run_tests', test_in_process),
          patch.object(EmbraerOperatorEnrollment, 'owner_scope', isolated_owner),
          patch.object(EmbraerOperatorEnrollment, '_source', return_value=saved['sender']),
          patch('time.time', return_value=simulation_time)):
        enrollment.authorize_continuation(coordinator, approval, expected_control_generation=generation)
        result = enrollment.catch_up(coordinator)
        descriptor = coordinator.store.resolve_embraer_03_continuation(
            approval['repair_key'], outcome_id=approval['outcome_id'], source_revision=approval['source_revision'])
        child = descriptor['task_id']
        assert result.get('task_id') == child and child != PARENT
        first_reservation_count = len(coordinator.store.inference_receipts(child))
        assert first_reservation_count == 0
        if phase == 'restarted':
            for _ in range(4):
                coordinator.step(child)
                if coordinator.store.get(child)['status'] not in ('QUEUED', 'RUNNING'):
                    break
            state = coordinator.store.get(child)
            receipts = coordinator.store.inference_receipts(child)
            assert len(receipts) == 1 and receipts[0]['status'] == 'COMPLETED'
            assert state['status'] == 'AWAITING_LIVE_VALIDATION', state['reason']
            assert state['sessions'] == 8 and state['calls'] == 16 and state['tokens'] <= 120000
            assert not coordinator.store.unresolved_inferences()
            assert enrollment.catch_up(coordinator).get('task_id') == child
            assert len(coordinator.store.inference_receipts(child)) == 1
            assert not (root / 'fixture-only-jobs.sqlite3').exists()
            from embraer_terminal_candidate import derive_embraer_final_diff, read_embraer_terminal_candidate
            diff = derive_embraer_final_diff(state, coordinator.store, pilot_baseline=baseline, expected_task_id=child)
            candidate = read_embraer_terminal_candidate(
                enrollment, coordinator.store, project=baseline, jobs=root / 'fixture-only-jobs.sqlite3',
                destination='fixture-only-destination', current_source_manifest=diff['source_manifest'],
                current_acceptance_source_manifest=diff['acceptance_source_manifest'], final_diff=diff,
                expected_task_id=child)
            assert candidate['jetson_edit']['request_id'] == receipts[0]['request_id']
            evidence = {'prompt_tokens': receipts[0]['reserved_prompt_tokens'],
                        'output_tokens': receipts[0]['reserved_output_tokens'],
                        'status': state['status'], 'reservations': len(receipts),
                        'tokens_after': state['tokens'], 'simulated_edit_verified': True}
        else:
            evidence = {'status': coordinator.store.get(child)['status'], 'reservations': first_reservation_count}
        snapshot_parent(coordinator.store, saved)
        return {'child': child, **evidence}


def main():
    if len(sys.argv) == 4:
        _, root, clock, phase = sys.argv
        print(json.dumps(run_phase(Path(root), float(clock), phase)))
        return
    with tempfile.TemporaryDirectory(prefix='embraer-03-proof-', dir=HERE) as directory:
        root = Path(directory)
        clock = seed(root, saved_fixture())
        reports = [json.loads(subprocess.check_output(
            [sys.executable, '-B', __file__, str(root), str(clock), phase], text=True))
            for phase in ('first', 'restarted')]
        assert reports[0]['child'] == reports[1]['child']
        print(json.dumps({'fixture_only': True, 'parent_inference_receipts_unchanged': 15,
                          'new_scrape_requests': 0, 'new_outcomes': 0, 'processes': reports}, indent=2))


if __name__ == '__main__':
    main()
