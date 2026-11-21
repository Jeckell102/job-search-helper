"""Run a real stopped scheduler and a fresh recovery process, with fixture inference."""
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import mkdtemp
import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch


STAGED = Path('/tmp/jsh-s5-enrolled-retry-receipt.20261121/dev/wrapper-coder/tools')


def no_network(event, _args):
    if event.startswith(('socket.connect', 'socket.getaddrinfo', 'socket.gethostbyname', 'socket.bind', 'socket.sendto')):
        raise AssertionError('Offline shutdown fixture cannot connect')


sys.addaudithook(no_network)
sys.path.insert(0, str(STAGED))
import coordinator
from coordinator_supervision import CoordinatorSupervision
import test_coordinator
from test_owned_recipe_scheduler import CHOICE, pilot


def supervisor(co, observed):
    def catch_up():
        observed.set()
        return {'fixture': 'observed'}

    return CoordinatorSupervision(co, catch_up, disk_usage=lambda _: SimpleNamespace(free=900, total=1000),
                                 min_free_bytes=100, min_free_ratio=0.05)


def phase_stop(work):
    persistent = work / 'working'
    persistent.mkdir()
    fixture_fs = SimpleNamespace(TemporaryDirectory=lambda: SimpleNamespace(name=str(persistent), cleanup=lambda: None))
    with patch.object(test_coordinator, 'tempfile', fixture_fs):
        scope = pilot.__wrapped__()
        setup, task_id = next(scope)
    co = setup.co
    entered = threading.Event()
    release_answer = threading.Event()
    supervised = threading.Event()
    calls = []
    result = {}
    supervisor_owner = supervisor(co, supervised)

    def fixture_model(*_):
        control = coordinator.INFERENCE_CONTROL.get()
        saved = co.store.inference_receipt(control['request_id'])
        assert saved['status'] == 'DISPATCHING' and saved['control_binding'] == control
        calls.append(saved)
        entered.set()
        assert release_answer.wait(8), 'fixture did not signal late result'
        return test_coordinator.response('worker_checkpoint', CHOICE)

    co.model = fixture_model
    co.owned_recipe_builder = Mock(side_effect=AssertionError('late inference attempted to build a candidate'))
    try:
        co.start()
        supervisor_owner.start(interval=3600)
        assert supervised.wait(8) and entered.wait(8), co.health()
        assert co.store.get(task_id)['status'] == 'RUNNING'

        def stop():
            result.update(supervisor_owner.shutdown('Fixture stop during reserved recipe turn', boundary_timeout=8))

        stopper = threading.Thread(target=stop, name='planned-fixture-stop')
        stopper.start()
        assert co.stop.wait(8)
        assert supervisor_owner.planned_shutdown.is_set()
        assert co.store.inference_receipt(calls[0]['request_id']) == calls[0]
        release_answer.set()
        stopper.join(10)
        assert not stopper.is_alive()
        assert result['state'] == 'SHUTDOWN_PAUSED' and result['recovery_required'] is False
        assert not co.thread.is_alive() and not supervisor_owner.thread.is_alive()
        [receipt] = co.store.inference_receipts(task_id)
        paused = co.store.get(task_id)
        assert receipt['status'] == 'RESPONSE_DROPPED' and 'accepted_recipe_choice' not in receipt
        assert receipt['control_binding'] == calls[0]['control_binding']
        assert (paused['status'], paused['sessions'], paused['calls'], paused['tokens']) == ('PAUSED', 1, 1, 560)
        assert len(calls) == 1 and not co.store.queue_enabled() and not co.store.campaign_enabled()
        co.owned_recipe_builder.assert_not_called()
        (work/'stopped.json').write_text(json.dumps({'pid': os.getpid(), 'task': task_id,
            'task_state': paused, 'receipt': receipt, 'supervision': result['state']}, sort_keys=True))
    finally:
        release_answer.set()
        co.stop.set()
        co.wake.set()
        supervisor_owner.stop.set()
        for thread in (getattr(co, 'thread', None), supervisor_owner.thread):
            if thread is not None:
                thread.join(10)
        scope.close()


def phase_restart(work):
    saved = json.loads((work/'stopped.json').read_bytes())
    task = saved['task']
    assert os.getpid() != saved['pid']
    co = coordinator.Coordinator(work/'working/tasks',
         model=Mock(side_effect=AssertionError('restart inferred again')),
         company_revision_resolver=lambda company_id: 'rev-1' if company_id == 'COMP-0490' else None,
         owned_recipe_reader=Mock(side_effect=AssertionError('restart reread active evidence for a paused pilot')),
         owned_recipe_builder=Mock(side_effect=AssertionError('restart attempted a candidate write')))
    restarted = threading.Event()
    supervised = threading.Event()
    supervisor_owner = supervisor(co, supervised)
    claim = co.store.claim_pilot
    readbacks = []

    def observe_claim(task_id):
        selected = claim(task_id)
        readbacks.append(selected)
        restarted.set()
        return selected

    co.store.claim_pilot = observe_claim
    try:
        assert co.store.pilot_task() == task
        co.start()
        supervisor_owner.start(interval=3600)
        assert restarted.wait(8) and supervised.wait(8), co.health()
        assert readbacks and all(selected is None for selected in readbacks)
        assert co.store.get(task) == saved['task_state']
        assert co.store.inference_receipts(task) == [saved['receipt']]
        assert not co.store.queue_enabled() and not co.store.campaign_enabled()
        co.model.assert_not_called()
        co.owned_recipe_reader.assert_not_called()
        co.owned_recipe_builder.assert_not_called()
        (work/'restarted.json').write_text(json.dumps({'pid': os.getpid(),
            'same_task_and_receipt': True, 'status': co.store.get(task)['status'],
            'model_calls': 0, 'candidate_builds': 0}, sort_keys=True))
    finally:
        supervisor_owner.shutdown('Fixture restart check complete', boundary_timeout=8)


def main():
    if len(sys.argv) == 3:
        phase = {'stop': phase_stop, 'restart': phase_restart}[sys.argv[1]]
        phase(Path(sys.argv[2]))
        return
    work = Path(mkdtemp(prefix='run-', dir=Path(__file__).parent))
    for name in ('stop', 'restart'):
        subprocess.run([sys.executable, str(Path(__file__).resolve()), name, str(work)], check=True, timeout=25)
    result = {name: json.loads((work/f'{name}.json').read_bytes()) for name in ('stopped', 'restarted')}
    result = {
        'result': 'DISPOSABLE_SUPERVISED_OWNED_CHOICE_STOP_RESTART_PASS',
        'process_ids': [result['stopped']['pid'], result['restarted']['pid']],
        'shutdown': result['stopped']['supervision'],
        'late_receipt': result['stopped']['receipt']['status'],
        'calls_and_tokens': [result['stopped']['task_state']['calls'], result['stopped']['task_state']['tokens']],
        'same_paused_task_and_exact_receipt': result['restarted']['same_task_and_receipt'],
        'restart_model_calls': result['restarted']['model_calls'],
        'restart_candidate_builds': result['restarted']['candidate_builds'],
        'staged_sha256': {name: sha256((STAGED/name).read_bytes()).hexdigest() for name in (
            'coordinator.py','coordinator_supervision.py','coordinator_store.py','coordinator_inference.py',
            'test_coordinator.py','test_owned_recipe_scheduler.py')},
    }
    (work/'RESULT.json').write_text(json.dumps(result, sort_keys=True, indent=2) + '\n')
    print(work)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
