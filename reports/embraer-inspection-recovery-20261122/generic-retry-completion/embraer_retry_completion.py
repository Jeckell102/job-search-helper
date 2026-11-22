"""Receipt-only closeout adapter for one independently qualified Embraer retry."""

from amphenol_retry_completion import _delivery_pair, _same_completion


HELD = 'HELD_EMBRAER_EXACT_RETRY_TERMINAL'
COMPANY_ID = 'COMP-0634'


def deliver_embraer_qualified_retry(enrollment, coordinator, *, approval, completion_reader, drain_selected):
    """Record only a verified generic qualified-retry completion.

    ``completion_reader`` owns all read-only application checks already shared
    by the generic release path: settled release/approval, retry intent and
    binding, current State, saved inventory, and confirmed publication.  This
    adapter binds that proof back to the original Embraer receipt and uses the
    existing receipt-v1 drain only for the selected terminal outcome.
    """
    try:
        value = completion_reader()
        if not isinstance(value, dict):
            return {'state': HELD}
        binding, record, origin, origin_sender_row, sender_row = (value.get(key) for key in (
            'binding', 'record', 'origin', 'origin_sender_row', 'sender_row'))
        if (not isinstance(getattr(approval, 'release_id', None), str)
                or not isinstance(getattr(approval, 'receipt_sha256', None), str)):
            return {'state': HELD}
        expected = {
            'request_id': 'company-retry:' + binding['attempt_id'],
            'attempt_id': binding['attempt_id'], 'company_id': COMPANY_ID,
            'failed_request_id': enrollment.request_id, 'source_revision': enrollment.source_revision,
            'release_version': binding['release']['release_id'],
            'release_binding_sha256': value['release_binding_sha256'],
        }
        if (not enrollment.qualified(origin[0])
                or binding['company_id'] != COMPANY_ID
                or binding['failed_request_id'] != enrollment.request_id
                or binding['source_revision'] != enrollment.source_revision
                or binding['release']['release_id'] != approval.release_id
                or value.get('approval_receipt_sha256') != approval.receipt_sha256
                or record.get('outcome') != 'COMPLETE'
                or any(record.get('identity', {}).get(key) != item for key, item in expected.items())):
            return {'state': HELD}
        if _delivery_pair(coordinator.store, origin, origin_sender_row) is None:
            return {'state': HELD}
        lifecycle = coordinator.store.retry_lifecycle(binding['attempt_id'])
        if lifecycle is not None and not _same_completion(lifecycle, record, expected):
            return {'state': HELD}
        readback = value.get('readback')
        if not readback or readback[0] != record or readback[2] is not False:
            return {'state': HELD}
        if readback[3] is not True:
            result = drain_selected(record['outcome_id'])
            if result != {'outcome_id': record['outcome_id'], 'disposition': 'ACCEPTED'}:
                return {'state': HELD}
            value = completion_reader()
            if (value.get('binding') != binding or value.get('record') != record
                    or value.get('approval_receipt_sha256') != approval.receipt_sha256):
                return {'state': HELD}
            readback, sender_row = value.get('readback'), value.get('sender_row')
            if not readback or readback[0] != record or readback[2] is not False:
                return {'state': HELD}
        paired = _delivery_pair(coordinator.store, readback, sender_row)
        if (paired is None or paired.get('sink_status') != 'VALIDATED_COMPLETE'
                or not _same_completion(coordinator.store.retry_lifecycle(binding['attempt_id']), record, expected)):
            return {'state': HELD}
        return {'state': 'EMBRAER_RETRY_CONFIRMED', 'attempt_id': binding['attempt_id'],
                'outcome_id': record['outcome_id']}
    except (AttributeError, KeyError, TypeError, ValueError):
        return {'state': HELD}
