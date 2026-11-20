"""One immutable receipt derivation shared by exact-cycle boundaries."""
from __future__ import annotations

import hashlib
import json
import re

from .publication_receipts import record_fingerprints


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _digest(value):
    return hashlib.sha256(_canonical(value).encode('utf-8')).hexdigest()


def selected_retry_receipt_binding(cycle, company_id):
    """Derive an exact receipt identity from the admitted one-company retry."""
    from .runner import _canonical_runtime_binding

    retry = cycle.get('temporary_retry')
    companies = cycle.get('companies')
    if not isinstance(retry, dict) or not isinstance(companies, dict) or set(companies) != {company_id}:
        raise ValueError('Selected publication requires one exact temporary retry Company.')
    outcome_id = retry.get('outcome_id')
    source = retry.get('source_revision')
    request_id = cycle.get('start_request_id')
    if (set(retry) != {'schema', 'outcome_id', 'company_id', 'source_revision', 'retry_index', 'retry_cap'}
            or retry['schema'] != 'temporary-scrape-retry-v1' or retry['company_id'] != company_id
            or type(retry['retry_index']) is not int or retry['retry_index'] != 1
            or type(retry['retry_cap']) is not int or retry['retry_cap'] != 1
            or not isinstance(outcome_id, str) or not re.fullmatch(r'OUT-[0-9a-f]{24}', outcome_id)
            or not isinstance(source, str) or not re.fullmatch(r'[0-9a-f]{64}', source)
            or request_id != 'temporary-retry:' + outcome_id
            or companies[company_id].get('outcome_source_revision') != source):
        raise ValueError('Selected publication retry source or request identity changed.')
    runtime = _canonical_runtime_binding(cycle.get('runtime_binding'))
    return {
        'request_id': request_id,
        'company_id': company_id,
        'source_revision': source,
        'release_id': runtime.get('release_id', 'NO_RELEASE'),
        'release_binding_sha256': _digest(runtime),
    }


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
    binding = {
        'request_id': str(request_id if request_id is not None
                          else cycle.get('start_request_id') or cycle['id']),
        'company_id': str(company_id),
        'source_revision': source_revision,
        'release_id': _digest({'records': records, 'final': plan.get('final', {})}),
    }
    if 'selected_retry_receipt_binding' in plan:
        binding = selected_retry_receipt_binding(cycle, company_id)
        if (plan['selected_retry_receipt_binding'] != binding
                or (request_id is not None and request_id != binding['request_id'])):
            raise ValueError('Selected publication receipt binding disagrees with the frozen plan.')
    return {
        'binding': binding,
        'records': records,
        'schedule': {
            'boundary': 'idle',
            'enqueued_at': str(payload.get('fetched_at') or cycle.get('started_at') or cycle['id']),
        },
        'timestamp': timestamp,
    }
