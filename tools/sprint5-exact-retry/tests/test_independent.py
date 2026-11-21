import json
import sqlite3

import pytest

from job_search_helper.engine import State
from job_search_helper.exact_cycle_receipt import repair_retry_receipt_binding
from job_search_helper.repair_retry import retry_request
from test_repair_retry_admission_replay import admit, retry


def consume(retry):
    bridge, binding, engine, state = retry
    assert bridge.deliver(binding)['state'] == 'REQUEST_WRITTEN'
    cycle_id = admit(bridge, engine, state)
    assert not bridge.request_path.exists()
    return bridge, binding, engine, state, state.cycle(cycle_id)


@pytest.mark.parametrize('defect', ['missing_runtime', 'foreign_runtime', 'retained_owner'])
def test_unowned_checkpoint_cannot_certify_admission(retry, defect):
    bridge, binding, _, state, saved = consume(retry)
    if defect == 'missing_runtime':
        saved.pop('runtime_binding')
    elif defect == 'foreign_runtime':
        saved['runtime_binding']['source_manifest_sha256'] = 'f' * 64
    else:
        saved['retained_work_exception'] = {'state': 'different_owner'}
    state.save_cycle(saved)
    with pytest.raises(ValueError):
        repair_retry_receipt_binding(saved, binding['company_id'])
    with pytest.raises(RuntimeError, match='admission evidence'):
        bridge.deliver(binding)
    assert not bridge.request_path.exists()
    assert state.cycles() == [saved]


def test_partial_intake_checkpoint_cannot_certify_admission(retry):
    bridge, binding, _, state, saved = consume(retry)
    prior = saved['intake_start_measurement']
    saved['intake_start_measurement'] = {'condition': prior['condition'], 'started_at': prior['started_at']}
    state.save_cycle(saved)
    with pytest.raises(RuntimeError, match='admission evidence'):
        bridge.deliver(binding)
    assert not bridge.request_path.exists()


@pytest.mark.parametrize('condition', ['complete', 'superseded', 'foreign_queue'])
def test_existing_scope_keeps_one_attempt_and_foreign_queue(retry, condition):
    bridge, binding, engine, state, saved = consume(retry)
    if condition == 'complete':
        saved['companies'][binding['company_id']]['stage'] = 'complete'
        engine._sync_cycle(saved)
        assert state.cycle(saved['id'])['status'] == 'Complete'
    elif condition == 'superseded':
        successor = engine.start_cycle(new_scan_request={
            'mode': 'fresh-full-scan', 'request_id': 'unrelated-fixture-successor',
        })
        assert saved['id'] in state.cycle(successor)['supersedes']
    else:
        foreign = {'schema': 'foreign-queue-fixture', 'request_id': 'different'}
        bridge.request_path.write_text(json.dumps(foreign))
        original = bridge.request_path.read_bytes()
        assert bridge.deliver(binding)['state'] == 'WAITING_SAFE_REQUEST_BOUNDARY'
        assert bridge.request_path.read_bytes() == original
        bridge.request_path.unlink()
    durable_before = state.cycles()
    assert bridge.deliver(binding)['state'] == 'REQUEST_ALREADY_ADMITTED'
    assert not bridge.request_path.exists() and state.cycles() == durable_before


def test_wrong_schema_holds_and_readonly_connection_is_closed(retry, monkeypatch, tmp_path):
    bridge, binding, _, state, saved = consume(retry)
    old_state = bridge.database
    shadow = tmp_path / 'wrong-schema.db'
    with sqlite3.connect(shadow) as connection:
        connection.execute('CREATE TABLE other (n TEXT)')
    bridge.database = shadow
    before = shadow.read_bytes()
    with pytest.raises(RuntimeError, match='admission evidence'):
        bridge.deliver(binding)
    assert not bridge.request_path.exists() and shadow.read_bytes() == before

    recorded = []
    initial = State.__init__

    def remember(instance, *args, **kwargs):
        assert kwargs.get('readonly') is True
        initial(instance, *args, **kwargs)
        recorded.append(instance.connection)
        with pytest.raises(sqlite3.OperationalError, match='readonly'):
            instance.connection.execute('DELETE FROM cycles')

    monkeypatch.setattr(State, '__init__', remember)
    bridge.database = old_state
    assert bridge.deliver(binding)['state'] == 'REQUEST_ALREADY_ADMITTED'
    assert len(recorded) == 1
    with pytest.raises(sqlite3.ProgrammingError, match='closed'):
        recorded[0].execute('SELECT 1')
    assert state.cycles() == [saved]
