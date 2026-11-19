"""One immutable receipt derivation shared by exact-cycle boundaries."""
from __future__ import annotations

import hashlib
import json

from .publication_receipts import record_fingerprints


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _digest(value):
    return hashlib.sha256(_canonical(value).encode('utf-8')).hexdigest()


def derive_receipt(cycle, company_id, payload, plan, timestamp, *, request_id=None):
    """Return the sole full binding/schedule contract for frozen plans.

    ``timestamp`` records local receipt creation only.  It must never change
    the immutable schedule, so interrupted plans with incomplete date fields
    remain recoverable under every exact-cycle consumer.
    """
    if request_id is not None and not str(request_id).strip():
        raise ValueError('Exact receipt request ID override is invalid.')
    operations = (plan.get('remote_projection')
                  if plan.get('exact_plan_version') == 2
                  else plan.get('operations'))
    if not isinstance(operations, list) or not operations:
        raise ValueError('Exact receipt requires a frozen remote operation stream.')
    fingerprint_version = plan.get('record_fingerprint_version', 1)
    if fingerprint_version not in {1, 2}:
        raise ValueError('Exact receipt fingerprint version is invalid.')
    records = record_fingerprints(
        operations, include_guard_only=fingerprint_version == 2)
    item = cycle['companies'][company_id]
    request = cycle.get('request', {})
    candidates = (cycle.get('source_revision'),
                  request.get('source_revision') if isinstance(request, dict) else None,
                  item.get('source_revision'), payload.get('source_revision'))
    source_revision = next((str(value).strip() for value in candidates if str(value or '').strip()), None)
    if source_revision is None:
        source_revision = 'frozen-inventory:' + _digest(payload)
    return {
        'binding': {
            'request_id': str(request_id if request_id is not None
                              else cycle.get('start_request_id') or cycle['id']),
            'company_id': str(company_id),
            'source_revision': source_revision,
            'release_id': _digest({'records': records, 'final': plan.get('final', {})}),
        },
        'records': records,
        'schedule': {
            'boundary': 'idle',
            'enqueued_at': str(payload.get('fetched_at') or cycle.get('started_at') or cycle['id']),
        },
        'timestamp': timestamp,
    }
