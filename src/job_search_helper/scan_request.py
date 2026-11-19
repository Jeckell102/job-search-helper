"""Explicit one-time fresh scan requests; old checkpoints are never deleted."""
from datetime import datetime, timezone
import hashlib
import json


COMPANY_ONLY_MODE = "company-only"
# A request made while the intake boundary is clear is created synchronously by
# ``start``.  When another cycle owns the single-writer boundary, the request
# remains durable and must be admitted within this target after that cycle has
# completed and the operator invokes ``start`` again.  These are deliberately
# separate measurements: a paused cycle must not be disguised as an idle one.
COMPANY_ONLY_IDLE_START_TARGET_SECONDS = 60
COMPANY_ONLY_BUSY_START_TARGET_SECONDS = 60


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
    measurement_cycles = list(state.cycles())
    if mode == COMPANY_ONLY_MODE:
        if hasattr(engine.repo, 'read_columns'):
            measurement_cycles.extend(row for _, row in engine.repo.read_columns(
                'Scan Cycles', ['Cycle ID', 'Cycle Status', 'Started At', 'Completed At', 'Notes']))
        else:
            measurement_cycles.extend(engine.repo.read('Scan Cycles'))
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
    if mode == COMPANY_ONLY_MODE:
        cycle = state.cycle(cycle_id)
        if cycle is None:
            raise ValueError('Company-only cycle checkpoint is missing; refusing to consume the request.')
        cycle['intake_start_measurement'] = company_only_intake_start_measurement(
            request, cycle, measurement_cycles,
        )
        state.save_cycle(cycle)
        engine._sync_cycle(cycle)
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


def company_only_queue_status(engine, state, database, *, observed_at=None, include_remote=True):
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
    blocking = sorted(_unfinished_cycle_ids(engine, state, include_remote=include_remote))
    age_seconds = max(0, int((observed.astimezone(timezone.utc) - enqueued).total_seconds()))
    recovery = (
        'Company-only request is waiting for safe boundary behind unfinished cycle(s): '
        + ', '.join(blocking)
        + '. Keep next-scan.json unchanged; do not delete locks or supersede the cycle. '
          'Resume the blocking cycle with ./job-search-scraper start --resume. '
          'There is no automatic cancel path for an existing cycle.'
        if blocking else
        'Company-only request is ready for the next normal ./job-search-scraper start. '
        'Keep next-scan.json unchanged until that command acknowledges it.'
    )
    return {
        'state': 'WAITING_SAFE_BOUNDARY' if blocking else 'READY_FOR_START',
        'request_id': request['request_id'],
        'company_ids': list(company_ids),
        'enqueued_at': request['enqueued_at'],
        'queue_age_seconds': age_seconds,
        'blocking_cycle_ids': blocking,
        'recovery': recovery,
        'intake_start_targets': {
            'idle_seconds': COMPANY_ONLY_IDLE_START_TARGET_SECONDS,
            'busy_seconds_after_safe_boundary': COMPANY_ONLY_BUSY_START_TARGET_SECONDS,
            'busy_boundary': ('the last blocking cycle reaches Complete or Complete with exceptions; '
                              'the next normal start command admits the durable request'),
        },
    }


def company_only_intake_start_measurement(request, cycle, cycles):
    """Measure a company-only request without consulting a wall clock.

    The caller supplies the immutable enqueue timestamp, the durable cycle
    checkpoint, and a captured cycle list.  Keeping this pure makes both the
    idle and busy target evidence deterministic and prevents a status read
    from changing a request or a cycle.
    """
    if request.get('mode') != COMPANY_ONLY_MODE:
        raise ValueError('Intake measurement requires a company-only request.')
    enqueued = _enqueued_at(request)
    started = _timestamp(cycle.get('started_at'), 'cycle started_at')
    completed = []
    for prior in cycles:
        completed_at = prior.get('completed_at') or prior.get('Completed At')
        if not completed_at:
            continue
        completed_time = _timestamp(completed_at, 'cycle completed_at')
        if enqueued <= completed_time <= started:
            completed.append((completed_time, str(prior.get('id') or prior.get('Cycle ID') or '')))
    if completed:
        boundary_at, boundary_cycle_id = max(completed)
        elapsed = max(0, int((started - boundary_at).total_seconds()))
        return {
            'condition': 'busy', 'target_seconds': COMPANY_ONLY_BUSY_START_TARGET_SECONDS,
            'target_anchor': 'safe_boundary_completed_at', 'safe_boundary_cycle_id': boundary_cycle_id,
            'safe_boundary_at': boundary_at.isoformat(), 'started_at': started.isoformat(),
            'intake_to_start_seconds': elapsed, 'target_met': elapsed <= COMPANY_ONLY_BUSY_START_TARGET_SECONDS,
        }
    elapsed = max(0, int((started - enqueued).total_seconds()))
    return {
        'condition': 'idle', 'target_seconds': COMPANY_ONLY_IDLE_START_TARGET_SECONDS,
        'target_anchor': 'enqueued_at', 'enqueued_at': enqueued.isoformat(), 'started_at': started.isoformat(),
        'intake_to_start_seconds': elapsed, 'target_met': elapsed <= COMPANY_ONLY_IDLE_START_TARGET_SECONDS,
    }


def _timestamp(value, label):
    if not isinstance(value, str) or not value:
        raise ValueError(f'{label} must be an ISO-8601 timestamp.')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ValueError(f'{label} must be an ISO-8601 timestamp.') from exc
    if parsed.tzinfo is None:
        raise ValueError(f'{label} must include a timezone.')
    return parsed.astimezone(timezone.utc)


def _unfinished_cycle_ids(engine, state, *, include_remote=True):
    """Return non-superseded local and workbook cycles that still own work."""
    local = state.cycles()
    if not include_remote:
        remote = []
    elif hasattr(engine.repo, 'read_columns'):
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
