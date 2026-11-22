import copy
import json
import shlex
import sqlite3

import pytest

import embraer_pilot_arming as armer
import successor_environment as environment
import native_withdraw_current as entry


def task():
    return {'id': entry.TASK, 'status': 'PAUSED', 'stop_requested': True,
            'mode': 'develop', 'phase': 'implement', 'workflow_version': 2,
            'time_budget_policy': 'one_hour_from_first_assignment_including_pauses',
            'activated_at': 1234.0, 'sessions': 2,
            'calls': 5, 'tokens': 7000, 'max_sessions': 8}


def test_exact_stopped_successor_withdrawal_and_lost_response_replay(tmp_path):
    selected = {'request_id': entry.REQUEST, 'request_sha256': entry.REQUEST_SHA,
                'source_revision': 'a'*64, 'shared_boards_sha256': 'b'*64,
                'ats_sha256': 'c'*64, 'baseline_sha256': 'd'*64, 'successor': {
                    'outcome_id':entry.OUTCOME,'predecessor_outcome_id':'OUT-'+'1'*24,
                    'predecessor_repair_key':'e'*64,'predecessor_task_id':'WRAP-'+'1'*10,
                    'predecessor_task_state_sha256':'f'*64,'failure_fingerprint':'0'*64}}
    owned = {environment.ENROLLMENT: json.dumps(selected, sort_keys=True, separators=(',', ':'))}
    path = armer._owner_path(tmp_path, entry.REQUEST)
    armer._write_new_private(path, {'schema': armer._SCHEMA, 'enrollment': selected,
                                   'outcome_id': entry.OUTCOME})
    original = task()
    proof = {'task': original, 'request_id': entry.REQUEST, 'outcome_id': entry.OUTCOME,
             'unresolved_inferences': 0, 'sender_receipt_sha256': entry.PAIRED_RECEIPT,
             'receiver_receipt_sha256': entry.PAIRED_RECEIPT}
    before = copy.deepcopy(proof)
    # This exact authentic state is unsupported by the unchanged original gate.
    assert not armer._can_disarm_task(original)
    state = {'manager': {**owned, 'UNRELATED': 'preserved'}, 'process': owned.copy(),
             'pid': 20, 'crash': True, 'writes': []}

    def system(operation, *values):
        if operation == 'show-environment':
            return '\n'.join(f'{key}={shlex.quote(value)}' for key, value in state['manager'].items())
        state['writes'].append((operation, *values))
        if operation == 'unset-environment':
            assert values == (environment.ENROLLMENT,)
            state['manager'].pop(environment.ENROLLMENT)
        elif operation == 'restart':
            assert values == (environment.WRAPPER,)
            state['pid'] += 1
            state['process'] = {}
            if state['crash']:
                state['crash'] = False
                raise TimeoutError('fixture response lost after actual restart')
        else:
            pytest.fail(operation)

    def terminal_proof(**kwargs):
        assert kwargs == {'enrollment': selected, 'outcome_id': entry.OUTCOME}
        return proof

    def quiet():
        assert proof == before

    def run():
        return entry.withdraw_stopped(armer, environment, root=tmp_path,
            terminal_proof=terminal_proof, system=system,
            inspect_wrapper=lambda: (state['pid'], state['process']),
            check_quiescent=quiet)

    original_owner = path.read_bytes()
    for key in ('sender_receipt_sha256', 'receiver_receipt_sha256'):
        with pytest.raises(ValueError, match='settled successor'):
            entry.withdraw_stopped(armer,environment,root=tmp_path,
                terminal_proof=lambda **kwargs:{**proof,key:'f'*64},system=system,
                inspect_wrapper=lambda:(state['pid'],state['process']),check_quiescent=quiet)
    assert path.read_bytes()==original_owner and state['writes']==[]
    with pytest.raises(TimeoutError):
        run()
    saved = path.read_bytes()
    result = run()
    assert result['state'] == 'EMBRAER_PILOT_WITHDRAWN'
    assert result['task_id'] == entry.TASK
    assert run() == result and path.read_bytes() == saved
    assert state['writes'] == [('unset-environment', environment.ENROLLMENT),
                               ('restart', environment.WRAPPER)]
    assert state['manager'] == {'UNRELATED': 'preserved'} and state['process'] == {}
    assert proof == before and not armer._can_disarm_task(original)
    assert json.loads(saved)['disarm_receipts'] == {
        'sender_receipt_sha256': entry.PAIRED_RECEIPT,
        'receiver_receipt_sha256': entry.PAIRED_RECEIPT}



def test_real_stopped_state_and_empty_slot_required():
    value=task();entry.require_stopped(value)
    for change in ({'id':'WRAP-other'},{'status':'PAUSED_BLOCKED'},{'stop_requested':False},{'phase':'inspect'}):
        with pytest.raises(ValueError):entry.require_stopped({**value,**change})
    import importlib.util
    spec=importlib.util.spec_from_file_location('current_controls_fixture',entry.ENTRY)
    runtime=importlib.util.module_from_spec(spec);spec.loader.exec_module(runtime)
    db=sqlite3.connect(':memory:')
    db.executescript('CREATE TABLE settings(key TEXT,value TEXT); CREATE TABLE tasks(state TEXT); CREATE TABLE inference_receipts(status TEXT); CREATE TABLE receipts(result TEXT);')
    for key,value in {'queue_enabled':False,'campaign_enabled':False,'autopilot_enabled':False,'pilot_task':None}.items():
        db.execute('INSERT INTO settings VALUES (?,?)',(key,json.dumps(value)))
    db.execute('INSERT INTO tasks VALUES (?)',(json.dumps(task()),));runtime.controls(db)
    db.execute("UPDATE settings SET value=? WHERE key='pilot_task'",(json.dumps(entry.TASK),))
    with pytest.raises(ValueError):runtime.controls(db)
    db.close()
