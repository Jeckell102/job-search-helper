import json
import pytest

from embraer_successor_admission import EmbraerOperatorEnrollment, EmbraerSuccessorAuthorization


AUTH = EmbraerSuccessorAuthorization('OUT-' + '6' * 24, 'OUT-' + '1' * 24, '2' * 64,
                                     'WRAP-' + '3' * 10, '4' * 64, '5' * 64)


class Store:
    def __init__(self): self.items, self.calls = [], []
    def _operator_successor_repair_key(self, key): return 'successor-' + key
    def held_repair_intake(self): return self.items
    def reserve_operator_repair_successor(self, **kwargs):
        self.calls.append(kwargs)
        self.items.append({'repair_key': 'successor-' + kwargs['predecessor_repair_key'],
                           'outcome_id': kwargs['outcome_id'], 'status': 'HELD_FOR_REPAIR_TRIAGE'})
        return {'repair_key': self.items[-1]['repair_key'], 'owner_status': 'HELD_FOR_REPAIR_TRIAGE'}


def test_enrollment_successor_uses_promoted_pair_without_a_second_reservation():
    class Enrollment(EmbraerOperatorEnrollment):
        def _paired(self, store, source, *, exact_repair_key=None):
            assert exact_repair_key == 'successor-' + AUTH.predecessor_repair_key
            return (({'repair_key': exact_repair_key, 'outcome_id': source['record']['outcome_id'],
                      'status': 'PROMOTED_PAUSED'}, {'id': 'WRAP-' + '7' * 10})
                    if store.items else None)

    enrollment = Enrollment('request-123', '7' * 64, '8' * 64, '9' * 64, 'a' * 64, 'b' * 64,
                            successor=AUTH)
    store = Store()
    source = {'acknowledged': True,
              'record': {'outcome_id': AUTH.outcome_id, 'failure_fingerprint': AUTH.failure_fingerprint}}
    first, hold = enrollment._successor_pair(store, source)
    assert hold is None and first[0]['status'] == 'PROMOTED_PAUSED'
    second, hold = enrollment._successor_pair(store, source)
    assert hold is None and second == first
    assert len(store.calls) == 1


def test_optional_successor_owner_is_strict_and_default_absence_is_unchanged():
    base = {'request_id': 'operator-embraer-20261122-02', 'source_revision': '7' * 64,
            'request_sha256': '8' * 64, 'shared_boards_sha256': '9' * 64,
            'ats_sha256': 'a' * 64, 'baseline_sha256': 'b' * 64}
    assert EmbraerOperatorEnrollment.from_process_environment({'WRAPPER_EMBRAER_OPERATOR_PILOT_ENROLLMENT': json.dumps(base)}).successor is None
    value = {**base, 'successor': AUTH.__dict__}
    parsed = EmbraerOperatorEnrollment.from_process_environment({'WRAPPER_EMBRAER_OPERATOR_PILOT_ENROLLMENT': json.dumps(value)})
    assert parsed.successor == AUTH
    duplicate_outer = json.dumps(base)[:-1] + ',"request_id":"other"}'
    with pytest.raises(ValueError):
        EmbraerOperatorEnrollment.from_process_environment({'WRAPPER_EMBRAER_OPERATOR_PILOT_ENROLLMENT': duplicate_outer})
    duplicate_nested = json.dumps(value).replace('"outcome_id":', '"outcome_id":"OUT-' + '0' * 24 + '","outcome_id":', 1)
    with pytest.raises(ValueError):
        EmbraerOperatorEnrollment.from_process_environment({'WRAPPER_EMBRAER_OPERATOR_PILOT_ENROLLMENT': duplicate_nested})
