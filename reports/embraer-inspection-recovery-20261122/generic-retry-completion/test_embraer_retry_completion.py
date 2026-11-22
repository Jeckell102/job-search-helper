from types import SimpleNamespace

import embraer_retry_completion as completion
from embraer_operator_pilot import EmbraerOperatorEnrollment


ENROLLMENT = EmbraerOperatorEnrollment('operator-embraer-20261122-01', 'a' * 64, 'b' * 64,
                                       'c' * 64, 'd' * 64, 'e' * 64)
APPROVAL = SimpleNamespace(release_id='REL-' + '1' * 24, receipt_sha256='2' * 64)


def _value():
    binding = {'attempt_id': 'RTRY-' + '3' * 24, 'company_id': 'COMP-0634',
               'failed_request_id': ENROLLMENT.request_id, 'source_revision': ENROLLMENT.source_revision,
               'release': {'release_id': APPROVAL.release_id}}
    identity = {'request_id': 'company-retry:' + binding['attempt_id'], 'attempt_id': binding['attempt_id'],
                'company_id': 'COMP-0634', 'failed_request_id': ENROLLMENT.request_id,
                'source_revision': ENROLLMENT.source_revision, 'release_version': binding['release']['release_id'],
                'release_binding_sha256': '4' * 64}
    record = {'outcome_id': 'OUT-' + '5' * 24, 'outcome': 'COMPLETE', 'identity': identity}
    origin_record = {'identity': {'company_id': 'COMP-0634', 'request_id': ENROLLMENT.request_id,
        'source_revision': ENROLLMENT.source_revision, 'cycle_id': 'CYC-fixture', 'provider': 'Breezy HR',
        'adapter_version': 'normal-scraper-v1'}, 'outcome': 'QUALIFIED_INTEGRATION_REPAIR',
        'action': 'upsert_qualified_repair', 'repair_category': 'full_description_regression'}
    return {'binding': binding, 'record': record,
            'origin': (origin_record, None, False, True, None), 'origin_sender_row': 'origin-row',
            'sender_row': 'completion-row', 'readback': (record, None, False, True, None), 'release_binding_sha256': '4' * 64,
            'approval_receipt_sha256': APPROVAL.receipt_sha256}


def test_exact_embraer_completion_uses_existing_pair_and_lifecycle(monkeypatch):
    monkeypatch.setattr(completion, '_same_completion', lambda *args: True)
    pairs = []
    monkeypatch.setattr(completion, '_delivery_pair', lambda _store, readback, row:
                        pairs.append((readback, row)) or {'sink_status': 'VALIDATED_COMPLETE'})
    store = SimpleNamespace(retry_lifecycle=lambda attempt: {'state': 'VALIDATED_COMPLETE'})
    result = completion.deliver_embraer_qualified_retry(ENROLLMENT, SimpleNamespace(store=store), approval=APPROVAL,
        completion_reader=_value, drain_selected=lambda _outcome: (_ for _ in ()).throw(AssertionError('no drain')))
    assert result['state'] == 'EMBRAER_RETRY_CONFIRMED'
    assert pairs[0][1] == 'origin-row' and pairs[1][1] == 'completion-row'


def test_wrong_company_or_approval_holds_before_delivery(monkeypatch):
    value = _value()
    value['binding'] = {**value['binding'], 'company_id': 'COMP-0000'}
    monkeypatch.setattr(completion, '_delivery_pair', lambda *args: (_ for _ in ()).throw(AssertionError('no pair')))
    store = SimpleNamespace(retry_lifecycle=lambda attempt: None)
    assert completion.deliver_embraer_qualified_retry(ENROLLMENT, SimpleNamespace(store=store), approval=APPROVAL,
        completion_reader=lambda: value, drain_selected=lambda _outcome: None)['state'] == completion.HELD


def test_stale_terminal_preflight_holds_before_drain(monkeypatch):
    value = _value()
    value['readback'] = (value['record'], None, True, False, None)
    monkeypatch.setattr(completion, '_same_completion', lambda *args: True)
    monkeypatch.setattr(completion, '_delivery_pair', lambda *args: {'sink_status': 'VALIDATED_COMPLETE'})
    store = SimpleNamespace(retry_lifecycle=lambda attempt: {'state': 'VALIDATED_COMPLETE'})
    assert completion.deliver_embraer_qualified_retry(ENROLLMENT, SimpleNamespace(store=store), approval=APPROVAL,
        completion_reader=lambda: value, drain_selected=lambda _outcome: (_ for _ in ()).throw(AssertionError('no drain')))['state'] == completion.HELD
