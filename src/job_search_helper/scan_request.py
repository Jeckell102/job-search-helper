"""Explicit one-time fresh scan requests; old checkpoints are never deleted."""
from datetime import datetime, timezone
import hashlib
import json


COMPANY_ONLY_MODE = "company-only"


def cycle_metadata(cycle):
    if 'Notes' not in cycle:
        return cycle
    try:
        value = json.loads(cycle.get('Notes') or '{}')
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError):
        return {}


def superseded_cycle_ids(cycles):
    result = set()
    for cycle in cycles:
        values = cycle_metadata(cycle).get('supersedes', [])
        if isinstance(values, list):
            result.update(value for value in values if isinstance(value, str))
    return result


def requested_scan(engine, state, database):
    """Consume a user-requested fresh scan only after its checkpoint is saved.

    The request ID makes a retry after interruption select the same new cycle.
    A receipt is kept for audit. With no request, the runner creates a fresh scan.
    """
    path = database.parent / 'next-scan.json'
    if not path.exists():
        return None
    request, company_ids = _read_request(path)
    request = dict(request, request_fingerprint=request_fingerprint(request, company_ids))
    mode = request['mode']
    found = [cycle for cycle in state.cycles() if cycle.get('start_request_id') == request['request_id']]
    if len(found) > 1:
        raise ValueError('Duplicate fresh-scan request IDs require reconciliation.')
    if found:
        if found[0].get('request_fingerprint') != request['request_fingerprint']:
            raise ValueError('Request ID reuse has different immutable request content; refusing to reuse a cycle.')
        cycle_id = found[0]['id']
    else:
        # The caller holds the normal scraper/writer lock.  Do not supersede a
        # normal cycle to make room for a one-company request: leave the durable
        # request in place and make the blocking cycle visible to the operator.
        status = company_only_queue_status(engine, state, database) if mode == COMPANY_ONLY_MODE else None
        if status and status['blocking_cycle_ids']:
            raise ValueError(status['recovery'])
        cycle_id = engine.start_cycle(company_ids=company_ids, new_scan_request=request)
    path.replace(path.with_name('last-scan-request.json'))
    if mode == COMPANY_ONLY_MODE:
        print(f'Company-only scan: {cycle_id}. Only {len(company_ids)} declared company ID(s) are queued.', flush=True)
    else:
        print(f'Fresh full scan: {cycle_id}. Previous scan checkpoints are retained; requested slow companies are queued last.', flush=True)
    return cycle_id


def _read_request(path):
    request = json.loads(path.read_text())
    if (not isinstance(request, dict)
            or not isinstance(request.get('request_id'), str) or not request['request_id']
            or not isinstance(request.get('start_last', []), list)
            or not all(isinstance(value, str) for value in request.get('start_last', []))):
        raise ValueError('Invalid next-scan.json; refusing to alter scan selection.')
    mode = request.get('mode')
    if mode == 'fresh-full-scan':
        company_ids = None
    elif mode == COMPANY_ONLY_MODE:
        company_ids = request.get('company_ids')
        if (not isinstance(company_ids, list) or not company_ids
                or not all(isinstance(value, str) and value.strip() for value in company_ids)
                or len(set(company_ids)) != len(company_ids)):
            raise ValueError('Invalid company-only next-scan.json; refusing to widen scan selection.')
        if not isinstance(request.get('source_revision'), str) or not request['source_revision'].strip():
            raise ValueError('Invalid company-only next-scan.json; immutable source_revision is required.')
        _enqueued_at(request)
    else:
        raise ValueError('Invalid next-scan.json; refusing to alter scan selection.')
    return request, company_ids


def _enqueued_at(request):
    """Validate the immutable, creator-supplied enqueue timestamp."""
    value = request.get('enqueued_at')
    if not isinstance(value, str) or not value:
        raise ValueError('Invalid company-only next-scan.json; immutable enqueued_at is required.')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ValueError('Invalid company-only next-scan.json; immutable enqueued_at must be ISO-8601.') from exc
    if parsed.tzinfo is None:
        raise ValueError('Invalid company-only next-scan.json; immutable enqueued_at must include a timezone.')
    return parsed.astimezone(timezone.utc)


def request_fingerprint(request, company_ids):
    """Canonical identity for safe company-only request retry/reuse."""
    if request['mode'] != COMPANY_ONLY_MODE:
        return None
    canonical = {
        'mode': COMPANY_ONLY_MODE,
        'company_ids': sorted(company_ids),
        'source_revision': request['source_revision'],
        'enqueued_at': request['enqueued_at'],
    }
    encoded = json.dumps(canonical, separators=(',', ':'), sort_keys=True).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def company_only_queue_status(engine, state, database, *, observed_at=None):
    """Read a pending company-only request without changing its durable queue entry."""
    path = database.parent / 'next-scan.json'
    if not path.exists():
        return None
    request, company_ids = _read_request(path)
    if request['mode'] != COMPANY_ONLY_MODE:
        return None
    observed = observed_at or datetime.now(timezone.utc)
    if observed.tzinfo is None:
        raise ValueError('observed_at must include a timezone.')
    enqueued = _enqueued_at(request)
    blocking = sorted(_unfinished_cycle_ids(engine, state))
    age_seconds = max(0, int((observed.astimezone(timezone.utc) - enqueued).total_seconds()))
    recovery = (
        'Company-only request is waiting for safe boundary behind unfinished cycle(s): '
        + ', '.join(blocking)
        + '. Keep next-scan.json unchanged; do not delete locks or supersede the cycle. '
          'Resume the blocking cycle with ./job-search-scraper start --resume. '
          'There is no automatic cancel path for an existing cycle.'
    )
    return {
        'request_id': request['request_id'],
        'company_ids': list(company_ids),
        'enqueued_at': request['enqueued_at'],
        'queue_age_seconds': age_seconds,
        'blocking_cycle_ids': blocking,
        'recovery': recovery,
    }


def _unfinished_cycle_ids(engine, state):
    """Return non-superseded local and workbook cycles that still own work."""
    local = state.cycles()
    if hasattr(engine.repo, 'read_columns'):
        remote = [row for _, row in engine.repo.read_columns(
            'Scan Cycles', ['Cycle ID', 'Cycle Status', 'Notes'])]
    else:
        remote = engine.repo.read('Scan Cycles')
    superseded = superseded_cycle_ids(local + remote)
    local_ids = {
        cycle['id'] for cycle in local
        if cycle.get('id') not in superseded
        and cycle.get('status') not in {'Complete', 'Complete with exceptions'}
    }
    remote_ids = {
        cycle['Cycle ID'] for cycle in remote
        if cycle.get('Cycle ID') not in superseded
        and cycle.get('Cycle Status') not in {'Complete', 'Complete with exceptions', '', None}
    }
    return local_ids | remote_ids
