import importlib
import json
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest


ENV_NAME = 'WRAPPER_AMPHENOL_OPERATOR_RECIPE_ENROLLMENT'
OWNER = {'request_id': 'operator-fresh-request', 'request_sha256': 'a' * 64,
         'source_revision': 'b' * 64}
PREDECESSOR = {'predecessor_outcome_id': 'OUT-' + 'c' * 24,
               'predecessor_repair_key': 'd' * 64,
               'predecessor_task_id': 'WRAP-' + 'e' * 10,
               'predecessor_task_state_sha256': 'f' * 64,
               'failure_fingerprint': '1' * 64}
FRESH_OUTCOME = 'OUT-' + '2' * 24


@pytest.fixture
def host():
    with patch.object(Path, 'read_text', return_value='fixture-token'):
        return importlib.import_module('host_server')


def enrollment(host, fields):
    return host.recipe_enrollment_from_process_environment({ENV_NAME: json.dumps(fields)})


def test_successor_requires_all_pins_and_cannot_authorize_a_release(host):
    assert host.recipe_enrollment_from_process_environment({}) is None
    assert enrollment(host, OWNER).predecessor_outcome_id == ''
    enrolled = enrollment(host, {**OWNER, **PREDECESSOR})
    assert enrolled.predecessor_outcome_id == PREDECESSOR['predecessor_outcome_id']
    assert enrolled.retry_approval is None and not enrolled.activate_approved_release
    for key in PREDECESSOR:
        incomplete = {**OWNER, **PREDECESSOR}
        del incomplete[key]
        with pytest.raises(ValueError, match='Invalid exact operator'):
            enrollment(host, incomplete)
    with pytest.raises(ValueError, match='Invalid exact operator'):
        host.recipe_enrollment_from_process_environment({ENV_NAME: json.dumps({**OWNER, **PREDECESSOR})[:-1]
            + ',"request_id":"replacement"}'})
    with pytest.raises(ValueError, match='cannot authorize retry or release'):
        host.recipe_enrollment_from_process_environment({ENV_NAME: json.dumps({**OWNER, **PREDECESSOR}),
            'WRAPPER_AMPHENOL_ACTIVATE_APPROVED_RELEASE': '1'})


def test_exact_successor_reservation_precedes_existing_pilot_launch(host, monkeypatch, tmp_path):
    steps = []
    coordinator = SimpleNamespace(stop=threading.Event(), store=SimpleNamespace(
        reserve_operator_repair_successor=lambda **pins: steps.append(('reserve', pins))))
    monkeypatch.setattr(host.OperatorAmphenolRecipeEnrollment, '_canonical_recipe_workspace',
                        lambda self: tmp_path)
    monkeypatch.setattr(host.AmphenolRecipeEnrollment, '_launch',
                        lambda self, root, runtime, outcome: steps.append(('launch', outcome)) or {'state': 'fixture'})
    enrolled = enrollment(host, {**OWNER, **PREDECESSOR})
    assert enrolled._launch(tmp_path, coordinator, FRESH_OUTCOME) == {'state': 'fixture'}
    assert steps == [('reserve', {**PREDECESSOR, 'source_revision': OWNER['source_revision'],
                                  'company_id': 'COMP-0490', 'outcome_id': FRESH_OUTCOME}),
                     ('launch', FRESH_OUTCOME)]
    steps.clear()
    enrollment(host, OWNER)._launch(tmp_path, coordinator, FRESH_OUTCOME)
    assert steps == [('launch', FRESH_OUTCOME)]


def test_drifted_source_and_stopped_controls_do_not_reserve_or_launch(host, monkeypatch, tmp_path):
    def unexpected(*args, **kwargs):
        pytest.fail('Reserved or launched repair after a preflight hold')

    coordinator = SimpleNamespace(stop=threading.Event(), store=SimpleNamespace(
        reserve_operator_repair_successor=unexpected))
    monkeypatch.setattr(host.AmphenolRecipeEnrollment, '_launch', unexpected)
    monkeypatch.setattr(host.OperatorAmphenolRecipeEnrollment, '_canonical_recipe_workspace', lambda self: None)
    enrolled = enrollment(host, {**OWNER, **PREDECESSOR})
    assert enrolled._launch(tmp_path, coordinator, FRESH_OUTCOME) == {'state': 'HELD_RECIPE_CONTROLS'}
    coordinator.stop.set()
    monkeypatch.setattr(host.OperatorAmphenolRecipeEnrollment, '_canonical_recipe_workspace', unexpected)
    assert enrolled._launch(tmp_path, coordinator, FRESH_OUTCOME) == {'state': 'HELD_RECIPE_CONTROLS'}
