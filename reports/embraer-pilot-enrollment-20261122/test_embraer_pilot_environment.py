import json
import shlex

import pytest

from embraer_pilot_arming import reconcile_pilot
from embraer_pilot_environment import ENROLLMENT, WRAPPER


class WrapperFixture:
    def __init__(self):
        self.manager, self.process, self.pid, self.calls = {'OTHER': 'preserved'}, {}, 10, []

    def system(self, operation, *values):
        if operation == 'show-environment':
            return '\n'.join(f'{key}={shlex.quote(value)}' for key, value in self.manager.items())
        self.calls.append((operation, *values))
        if operation == 'set-environment':
            key, value = values[0].split('=', 1)
            self.manager[key] = value
        elif operation == 'unset-environment':
            del self.manager[values[0]]
        elif operation == 'restart':
            assert values == (WRAPPER,)
            self.process = {key: value for key, value in self.manager.items() if key != 'OTHER'}
            self.pid += 1
        else:
            pytest.fail(operation)

    def inspect(self):
        return self.pid, self.process


def _enrollment(request_id, request_sha256):
    return ({'request_id': request_id, 'request_sha256': request_sha256,
             'source_revision': 'a' * 64, 'shared_boards_sha256': 'b' * 64,
             'ats_sha256': 'c' * 64, 'baseline_sha256': 'd' * 64}, 'OUT-' + 'e' * 24)


def test_arm_is_idempotent_and_keeps_unrelated_manager_values(tmp_path):
    fixture = WrapperFixture()
    request_id, request_sha = 'operator-embraer-20261122-01', 'a' * 64
    read = lambda **kwargs: _enrollment(**kwargs)
    first = reconcile_pilot(action='arm', root=tmp_path, request_id=request_id,
                            request_sha256=request_sha, read_enrollment=read,
                            system=fixture.system, inspect_wrapper=fixture.inspect,
                            check_quiescent=lambda: None)
    again = reconcile_pilot(action='arm', root=tmp_path, request_id=request_id,
                            request_sha256=request_sha, read_enrollment=read,
                            system=fixture.system, inspect_wrapper=fixture.inspect,
                            check_quiescent=lambda: None)
    assert first['state'] == again['state'] == 'EMBRAER_PILOT_ENROLLED'
    assert fixture.manager['OTHER'] == 'preserved' and list(fixture.process) == [ENROLLMENT]
    assert [call[0] for call in fixture.calls] == ['set-environment', 'restart']


def test_foreign_scope_and_nonterminal_disarm_hold(tmp_path):
    fixture = WrapperFixture()
    request_id, request_sha = 'operator-embraer-20261122-02', 'a' * 64
    fixture.manager[ENROLLMENT] = 'foreign'
    with pytest.raises(ValueError, match='Another operator'):
        reconcile_pilot(action='arm', root=tmp_path, request_id=request_id, request_sha256=request_sha,
                        read_enrollment=lambda **kwargs: _enrollment(**kwargs), system=fixture.system,
                        inspect_wrapper=fixture.inspect, check_quiescent=lambda: None)
    fixture.manager.pop(ENROLLMENT)
    reconcile_pilot(action='arm', root=tmp_path, request_id=request_id, request_sha256=request_sha,
                    read_enrollment=lambda **kwargs: _enrollment(**kwargs), system=fixture.system,
                    inspect_wrapper=fixture.inspect, check_quiescent=lambda: None)
    with pytest.raises(ValueError, match='terminal'):
        reconcile_pilot(action='disarm', root=tmp_path, request_id=request_id,
                        terminal_proof=lambda **_kwargs: {'unresolved_inferences': 1}, system=fixture.system,
                        inspect_wrapper=fixture.inspect, check_quiescent=lambda: None)


def test_disarm_requires_terminal_and_captures_both_receipts(tmp_path):
    fixture = WrapperFixture()
    request_id, request_sha = 'operator-embraer-20261122-03', 'a' * 64
    reconcile_pilot(action='arm', root=tmp_path, request_id=request_id, request_sha256=request_sha,
                    read_enrollment=lambda **kwargs: _enrollment(**kwargs), system=fixture.system,
                    inspect_wrapper=fixture.inspect, check_quiescent=lambda: None)
    result = reconcile_pilot(action='disarm', root=tmp_path, request_id=request_id,
                             terminal_proof=lambda **kwargs: {
                                 'outcome_id': kwargs['outcome_id'], 'request_id': request_id,
                                 'task': {'status': 'AWAITING_LIVE_VALIDATION'}, 'unresolved_inferences': 0,
                                 'sender_receipt_sha256': '1' * 64, 'receiver_receipt_sha256': '2' * 64},
                             system=fixture.system, inspect_wrapper=fixture.inspect,
                             check_quiescent=lambda: None)
    assert result['state'] == 'EMBRAER_PILOT_WITHDRAWN'
    saved = json.loads(open(result['owner_record']).read())
    assert saved['disarm_receipts'] == {'sender_receipt_sha256': '1' * 64, 'receiver_receipt_sha256': '2' * 64}
    assert fixture.manager == {'OTHER': 'preserved'} and fixture.process == {}


def test_disarm_rejects_generic_in_progress_but_accepts_quiescent_abort(tmp_path):
    fixture = WrapperFixture()
    request_id, request_sha = 'operator-embraer-20261122-04', 'a' * 64
    reconcile_pilot(action='arm', root=tmp_path, request_id=request_id, request_sha256=request_sha,
                    read_enrollment=lambda **kwargs: _enrollment(**kwargs), system=fixture.system,
                    inspect_wrapper=fixture.inspect, check_quiescent=lambda: None)
    base = {'outcome_id': 'OUT-' + 'e' * 24, 'request_id': request_id, 'unresolved_inferences': 0,
            'sender_receipt_sha256': '1' * 64, 'receiver_receipt_sha256': '2' * 64}
    with pytest.raises(ValueError, match='terminal'):
        reconcile_pilot(action='disarm', root=tmp_path, request_id=request_id,
                        terminal_proof=lambda **_kwargs: {**base, 'task': {'status': 'RUNNING'}},
                        system=fixture.system, inspect_wrapper=fixture.inspect, check_quiescent=lambda: None)
    result = reconcile_pilot(action='disarm', root=tmp_path, request_id=request_id,
                             terminal_proof=lambda **_kwargs: {**base, 'task': {
                                 'status': 'PAUSED_BLOCKED', 'stop_requested': True}},
                             system=fixture.system, inspect_wrapper=fixture.inspect, check_quiescent=lambda: None)
    assert result['state'] == 'EMBRAER_PILOT_WITHDRAWN'
