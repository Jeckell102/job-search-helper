import fcntl
import json
import sys
import threading
import time
import types
from pathlib import Path
from unittest.mock import patch

HOST = Path('/home/chris/job-search-helper_old/dev/wrapper-coder/tools')
sys.path.insert(0, str(HOST))

import coordinator as c
import test_coordinator as fixture
from test_coordinator_queue import QueueTests


def make_queue_fixture():
    case = QueueTests(methodName='test_autopilot_stop_survives_restart')
    case.setUp()
    return case


def cleanup(case):
    case.doCleanups()


def pilot_autopilot_race():
    case = make_queue_fixture()
    try:
        task = case.batch(1)['ids'][0]
        case.co.command({'action': 'queue-pause'})
        entered = threading.Event()
        release = threading.Event()
        original = case.co.store.set_pilot_task
        errors = []

        def delayed_set(task_id):
            entered.set()
            if not release.wait(2):
                raise RuntimeError('race harness timeout')
            return original(task_id)

        def start_pilot():
            try:
                case.co.command({'action': 'pilot-start', 'id': task})
            except Exception as exc:
                errors.append(f'{type(exc).__name__}: {exc}')

        with patch.object(case.co.store, 'set_pilot_task', side_effect=delayed_set):
            thread = threading.Thread(target=start_pilot)
            thread.start()
            assert entered.wait(2), 'pilot did not reach set_pilot_task'
            autopilot = case.co.command({'action': 'autopilot-start'})
            release.set()
            thread.join(3)
        return {
            'task': task,
            'pilot_thread_errors': errors,
            'autopilot_command': {k: autopilot.get(k) for k in ('ok', 'autopilot', 'enabled', 'pilot')},
            'final': {
                'pilot': case.co.store.pilot_task(),
                'autopilot': case.co.store.autopilot_enabled(),
                'queue': case.co.store.queue_enabled(),
                'task_status': case.co.store.get(task)['status'],
            },
        }
    finally:
        cleanup(case)


def pause_before_model_dispatch():
    case = fixture.CoordinatorTests(methodName='test_completion_claim_without_evidence_cannot_advance')
    case.setUp()
    try:
        task = case.task()
        case.co.step(task)  # baseline
        model_calls = []
        pause_results = []
        paused_once = False

        def budget(messages, schemas):
            nonlocal paused_once
            if not paused_once:
                paused_once = True
                pause_results.append(case.co.command({'action': 'pause', 'id': task})['state']['status'])
            return types.SimpleNamespace(prompt_tokens=500, available_generation_tokens=6000)

        def model(messages, schemas, limit):
            model_calls.append({'limit': limit, 'state_at_dispatch': case.co.store.get(task)['status'],
                                'stop_requested': case.co.store.get(task)['stop_requested']})
            return case.checkpoint('continue')

        case.co.budget = budget
        case.co.model = model
        case.co.step(task)
        return {
            'task': task,
            'pause_result_status': pause_results,
            'model_calls': model_calls,
            'final_status': case.co.store.get(task)['status'],
            'calls_counter': case.co.store.get(task)['calls'],
        }
    finally:
        cleanup(case)


def run_bypasses_scheduler_lock():
    case = fixture.CoordinatorTests(methodName='test_completion_claim_without_evidence_cannot_advance')
    case.setUp()
    holder = case.co
    blocker = threading.Event()
    try:
        task = case.task()
        # Exercise the public start path: it acquires scheduler.lock, but its
        # worker is held inert so a second coordinator can be tested safely.
        original_run = holder.run
        holder.run = lambda: blocker.wait(3)
        holder.start()

        contender = c.Coordinator(holder.store.base, holder.model, holder.budget)
        visited = []

        def step(task_id):
            visited.append(task_id)
            contender.store.update(task_id, status='PAUSED_BLOCKED')
            contender.stop.set()

        contender.step = step
        contender.run()  # direct run() never checks scheduler_lock ownership
        return {
            'task': task,
            'holder_thread_alive': holder.thread.is_alive(),
            'contender_visited': visited,
            'final_status': holder.store.get(task)['status'],
        }
    finally:
        blocker.set()
        holder.stop.set()
        holder.wake.set()
        if getattr(holder, 'thread', None):
            holder.thread.join(2)
        if holder.scheduler_lock:
            try:
                fcntl.flock(holder.scheduler_lock, fcntl.LOCK_UN)
                holder.scheduler_lock.close()
            except OSError:
                pass
        holder.run = original_run
        cleanup(case)


def rejected_pilot_keeps_slot():
    case = make_queue_fixture()
    try:
        task = case.batch(1)['ids'][0]
        case.co.command({'action': 'queue-pause'})
        case.co.store.update(task, tokens=c.MAX_TOKENS)
        errors = {}
        for action in ('pilot-start', 'autopilot-start', 'queue-resume'):
            try:
                case.co.command({'action': action, 'id': task})
            except ValueError as exc:
                errors[action] = str(exc)
        return {'errors': errors, 'pilot_remains_set': case.co.store.pilot_task() == task,
                'task_status': case.co.store.get(task)['status']}
    finally:
        cleanup(case)


if __name__ == '__main__':
    print(json.dumps({
        'pilot_autopilot_race': pilot_autopilot_race(),
        'pause_before_model_dispatch': pause_before_model_dispatch(),
        'run_bypasses_scheduler_lock': run_bypasses_scheduler_lock(),
        'rejected_pilot_keeps_slot': rejected_pilot_keeps_slot(),
    }, indent=2, sort_keys=True))
