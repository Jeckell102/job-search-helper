"""One immutable receipt derivation shared by exact-cycle boundaries."""
from __future__ import annotations

import hashlib
import json

from .publication_receipts import record_fingerprints


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _digest(value):
    return hashlib.sha256(_canonical(value).encode('utf-8')).hexdigest()


def derive_receipt(cycle, company_id, payload, plan, timestamp):
    """Return the sole full binding/schedule contract for frozen plans.

    ``timestamp`` records local receipt creation only.  It must never change
    the immutable schedule, so interrupted plans with incomplete date fields
    remain recoverable under every exact-cycle consumer.
    """
    records = record_fingerprints(plan['operations'])
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
            'request_id': str(cycle.get('start_request_id') or cycle['id']),
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
