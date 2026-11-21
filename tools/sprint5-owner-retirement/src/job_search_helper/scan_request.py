"""Explicit one-time fresh scan requests; old checkpoints are never deleted."""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import sqlite3


COMPANY_ONLY_MODE = "company-only"
# A request made while the intake boundary is clear is created synchronously by
# ``start``.  When another cycle owns the single-writer boundary, the request
# remains durable and must be admitted within this target after that cycle has
# completed and the operator invokes ``start`` again.  These are deliberately
# separate measurements: a paused cycle must not be disguised as an idle one.
COMPANY_ONLY_IDLE_START_TARGET_SECONDS = 60
COMPANY_ONLY_BUSY_START_TARGET_SECONDS = 60
_TERMINAL_CYCLE_STATES = {"Complete", "Complete with exceptions"}


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
        from .company_events import has_pending_eligible_company_event
        if (getattr(engine.repo, "is_local", False) is True
                and has_pending_eligible_company_event(engine.repo)
                and _unfinished_cycle_ids(engine, state)):
            raise ValueError("Company event is held in the outbox behind unfinished work; resume only the exact prior cycle.")
        return None
    request, company_ids = _read_request(path)
    queued_event = None
    if request.get("company_event") is not None:
        from .company_events import read_verified_queued_event
        _, verified = read_verified_queued_event(engine.repo, path.parent)
        if verified != request:
            raise ValueError("Queued Company-event request changed during admission.")
        queued_event = verified
    request = dict(request, request_fingerprint=request_fingerprint(request, company_ids))
    mode = request['mode']
    if request.get('repair_retry') is not None:
        # This happens before cycle creation, checkpointing, or renaming the
        # request.  A release change therefore leaves the exact request and
        # any prior inventory/cursor available for an explicit later recovery.
        from .integration_release import assert_active_release_binding
        assert_active_release_binding(database.parent, request['repair_retry']['release'])
    local_cycles, mirror_cycles = _cycle_views(engine.repo, state) if mode == COMPANY_ONLY_MODE else ([], [])
    measurement_request = _request_with_event_observation(
        request, engine.repo, path.parent, (local_cycles, mirror_cycles),
    )
    found = [cycle for cycle in state.cycles() if cycle.get('start_request_id') == request['request_id']]
    if len(found) > 1:
        raise ValueError('Duplicate fresh-scan request IDs require reconciliation.')
    if found:
        from .retained_cycle_retirement_control import assert_cycle_not_retired
        assert_cycle_not_retired(state, found[0]['id'])
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
            measurement_request, cycle, local_cycles, mirror_cycles=mirror_cycles,
        )
        state.save_cycle(cycle)
        engine._sync_cycle(cycle)
        if queued_event is not None:
            from .company_events import CompanyEventBridge
            CompanyEventBridge(engine.repo, path.parent).archive_ordinary_admission(queued_event, cycle, state)
    path.replace(path.with_name('last-scan-request.json'))
    if mode == COMPANY_ONLY_MODE:
        print(f'Company-only scan: {cycle_id}. Only {len(company_ids)} declared company ID(s) are queued.', flush=True)
    else:
        print(f'Fresh full scan: {cycle_id}. Previous scan checkpoints are retained; requested slow companies are queued last.', flush=True)
    return cycle_id


def _request_with_event_observation(request, repository, root, cycles):
    event = request.get("company_event")
    if (event is None or "company_event_timing" in request
            or getattr(repository, "is_local", False) is not True):
        return request
    from .company_events import CompanyEventBridge, read_verified_queued_event
    try:
        # Legacy timing can be derived at admission without changing the
        # request, receipt, or existing request fingerprint.
        _, verified = read_verified_queued_event(repository, root)
        if verified == {key: value for key, value in request.items() if key != "request_fingerprint"}:
            measured = dict(request, company_event_timing=CompanyEventBridge(repository, root).observed_timing(event, cycles))
            _company_event_timing(measured)
            return measured
    except (OSError, ValueError, RuntimeError, sqlite3.Error):
        # Legacy requests keep their existing admission rules. Missing
        # timing provenance cannot certify either start target.
        pass
    return request


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
        sources = ('company_event', 'repair_retry', 'operator_request', 'temporary_retry')
        if sum(request.get(source) is not None for source in sources) > 1:
            raise ValueError('Invalid company-only next-scan.json; request provenance is mutually exclusive.')
        _company_event(request, company_ids)
        if request.get('repair_retry') is not None:
            from .repair_retry import validate_retry_request
            validate_retry_request(request, company_ids)
        _operator_request(request, company_ids)
        if request.get('temporary_retry') is not None:
            from .temporary_retry import is_temporary_retry_request
            if not is_temporary_retry_request(request):
                raise ValueError('Invalid company-only next-scan.json; temporary retry does not bind this scope.')
    else:
        raise ValueError('Invalid next-scan.json; refusing to alter scan selection.')
    _company_event_timing(request)
    return request, company_ids


def _company_event(request, company_ids):
    """Validate optional M2 provenance before it becomes cycle metadata."""
    event = request.get('company_event')
    if event is None:
        return None
    if not isinstance(event, dict):
        raise ValueError('Invalid company-only next-scan.json; company event must be an object.')
    required = ('schema', 'event_id', 'company_id', 'source_revision')
    if any(not isinstance(event.get(key), str) or not event[key].strip() for key in required):
        raise ValueError('Invalid company-only next-scan.json; company event identity is incomplete.')
    if not isinstance(event.get('revision'), int) or event['revision'] < 1:
        raise ValueError('Invalid company-only next-scan.json; company event revision is invalid.')
    if (event['schema'] != 'company-event-scan-request-v1'
            or len(company_ids) != 1
            or event['company_id'] != company_ids[0]
            or event['source_revision'] != request['source_revision']):
        raise ValueError('Invalid company-only next-scan.json; company event does not bind this scope.')
    return event


def _operator_request(request, company_ids):
    """Validate the explicit one-company operator provenance used by M1."""
    value = request.get('operator_request')
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError('Invalid company-only next-scan.json; operator request must be an object.')
    required = ('schema', 'request_id', 'company_id', 'source_revision')
    if (set(value) != set(required)
            or any(not isinstance(value.get(key), str) or not value[key].strip() for key in required)
            or value['schema'] != 'operator-company-scan-request-v1'
            or len(company_ids) != 1
            or value['request_id'] != request['request_id']
            or value['company_id'] != company_ids[0]
            or value['source_revision'] != request['source_revision']):
        raise ValueError('Invalid company-only next-scan.json; operator request does not bind this scope.')
    return value


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
    # Preserve fingerprints for pre-M2 manual requests with no provenance.
    # When provenance is supplied it is immutable: request IDs cannot silently
    # substitute another Company event during recovery.
    if request.get('company_event') is not None:
        canonical['company_event'] = request['company_event']
    if 'company_event_timing' in request:
        canonical['company_event_timing'] = request['company_event_timing']
    if request.get('repair_retry') is not None:
        canonical['repair_retry'] = request['repair_retry']
    if request.get('operator_request') is not None:
        canonical['operator_request'] = request['operator_request']
    if request.get('temporary_retry') is not None:
        canonical['temporary_retry'] = request['temporary_retry']
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
    timing = _company_event_timing(request)
    enqueued = _enqueued_at(request)
    observed_event = _timestamp(timing['observed_at'], 'Company event observation') if timing else enqueued
    blocking = sorted(_unfinished_cycle_ids(engine, state, include_remote=include_remote))
    age_seconds = max(0, int((observed.astimezone(timezone.utc) - observed_event).total_seconds()))
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
        **({'company_event_observed_at': timing['observed_at']} if timing else {}),
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


def company_only_intake_start_measurement(request, cycle, cycles, *, mirror_cycles=()):
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
    timing = _company_event_timing(request)
    if timing is not None:
        return _measure_company_event(timing, started, cycles, mirror_cycles)
    if request.get("company_event") is not None:
        return {"condition": "unverified", "started_at": started.isoformat(), "target_met": None}
    completed = []
    for prior in [*cycles, *mirror_cycles]:
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


def _cycle_views(repository, state, *, include_remote=True):
    local = state.cycles() if state is not None else []
    remote = []
    if include_remote:
        if hasattr(repository, 'read_columns'):
            remote = [row for _, row in repository.read_columns(
                'Scan Cycles', ['Cycle ID', 'Cycle Status', 'Started At', 'Completed At', 'Notes'])]
        else:
            remote = repository.read('Scan Cycles')
    if state is not None:
        from .retained_cycle_retirement_control import verified_retired_cycle_ids
        retired = verified_retired_cycle_ids(state)
        if (not isinstance(retired, (set, frozenset))
                or any(not isinstance(value, str) or not value or value != value.strip()
                       for value in retired)):
            raise ValueError('Verified cycle retirement IDs are invalid.')
        if retired:
            # The retired row may carry the supersession of older cycles.
            # Removing it must not reactivate those already superseded IDs.
            # This is an admission view only: no stored status, completion
            # timestamp, original scope, or mirrored record is rewritten.
            excluded = retired | superseded_cycle_ids(local + remote)
            local = [row for row in local if row.get('id') not in excluded]
            remote = [row for row in remote if row.get('Cycle ID') not in excluded]
    return local, remote


def _unfinished_cycle_ids(engine, state, *, include_remote=True):
    """Return non-superseded local and workbook cycles that still own work."""
    repository = engine.repo if include_remote else None
    return _unfinished_from_views(*_cycle_views(repository, state, include_remote=include_remote))


def _unfinished_from_views(local, remote):
    superseded = superseded_cycle_ids(local + remote)
    local_ids = {
        cycle['id'] for cycle in local
        if cycle.get('id') not in superseded
        and cycle.get('status') not in _TERMINAL_CYCLE_STATES
    }
    remote_ids = {
        cycle['Cycle ID'] for cycle in remote
        if cycle.get('Cycle ID') not in superseded
        and cycle.get('Cycle Status') not in _TERMINAL_CYCLE_STATES | {'', None}
    }
    return local_ids | remote_ids


def _company_event_timing(request):
    if "company_event_timing" not in request:
        return None
    timing = request["company_event_timing"]
    if (request.get("mode") != COMPANY_ONLY_MODE or not isinstance(request.get("company_event"), dict)
            or not isinstance(timing, dict)
            or set(timing) != {"observed_at", "blocking_cycle_ids", "condition"}):
        raise ValueError("Invalid Company-event timing identity.")
    blockers = timing["blocking_cycle_ids"]
    condition = timing["condition"]
    if (not isinstance(blockers, list)
            or any(not isinstance(value, str) or not value for value in blockers)
            or blockers != sorted(set(blockers))
            or condition not in ("idle", "busy", "unverified")
            or (condition == "busy" and not blockers)
            or (condition == "idle" and blockers)):
        raise ValueError("Invalid Company-event timing blockers.")
    if _timestamp(timing["observed_at"], "Company event observation") > _enqueued_at(request):
        raise ValueError("Company-event observation is later than its materialized request.")
    return timing


def _verified_completions(blockers, local, remote):
    completed = []
    for cycle_id in blockers:
        saved = [row for row in local if row.get("id") == cycle_id]
        mirrored = [row for row in remote if row.get("Cycle ID") == cycle_id]
        if len(saved) != 1 or len(mirrored) != 1:
            return []
        saved, mirrored = saved[0], mirrored[0]
        if saved.get("status") not in _TERMINAL_CYCLE_STATES or mirrored.get("Cycle Status") != saved["status"]:
            return []
        try:
            checkpoint = _timestamp(saved.get("completed_at"), "cycle completed_at")
            mirror_checkpoint = _timestamp(mirrored.get("Completed At"), "mirrored cycle completed_at")
        except ValueError:
            return []
        if checkpoint != mirror_checkpoint:
            return []
        completed.append((checkpoint, cycle_id))
    return completed


def company_event_timing(observed_at, deferred_blockers, local, remote):
    """Freeze durable deferral and corroborated cycle-window evidence."""
    observed = _timestamp(observed_at, "Company event observation")
    blockers = set(deferred_blockers)
    ambiguous = set()
    superseded = superseded_cycle_ids(local + remote)
    for saved in local + remote:
        cycle_id = saved.get("id") or saved.get("Cycle ID")
        if not cycle_id or cycle_id in superseded or cycle_id in blockers:
            continue
        try:
            started = _timestamp(saved.get("started_at") or saved.get("Started At"), "cycle started_at")
            completed = _timestamp(saved.get("completed_at") or saved.get("Completed At"), "cycle completed_at")
        except ValueError:
            continue
        if started < observed < completed:
            blockers.add(cycle_id)
        elif observed in (started, completed):
            # The outbox and cycle clocks have second resolution. Equality
            # alone cannot distinguish overlap from the preceding/following idle window.
            ambiguous.add(cycle_id)
    candidates = sorted(blockers | ambiguous)
    completions = _verified_completions(sorted(blockers), local, remote)
    if not candidates:
        condition = "idle"
    elif (ambiguous or not completions
            or any(checkpoint < observed for checkpoint, _ in completions)):
        condition = "unverified"
    else:
        condition = "busy"
    return {
        "observed_at": observed_at,
        "blocking_cycle_ids": candidates,
        "condition": condition,
    }


def _measure_company_event(timing, started, local, remote):
    observed = _timestamp(timing["observed_at"], "Company event observation")
    blockers = timing["blocking_cycle_ids"]
    base = {"company_event_observed_at": observed.isoformat(), "started_at": started.isoformat()}
    if timing["condition"] == "busy":
        completed = _verified_completions(blockers, local, remote)
        if completed and all(observed <= checkpoint <= started for checkpoint, _ in completed):
            boundary, cycle_id = max(completed)
            elapsed = int((started - boundary).total_seconds())
            return {
                **base, "condition": "busy", "target_seconds": COMPANY_ONLY_BUSY_START_TARGET_SECONDS,
                "target_anchor": "safe_boundary_completed_at", "safe_boundary_cycle_id": cycle_id,
                "safe_boundary_at": boundary.isoformat(), "intake_to_start_seconds": elapsed,
                "target_met": elapsed <= COMPANY_ONLY_BUSY_START_TARGET_SECONDS,
            }
    if timing["condition"] == "idle" and observed <= started:
        elapsed = int((started - observed).total_seconds())
        return {
            **base, "condition": "idle", "target_seconds": COMPANY_ONLY_IDLE_START_TARGET_SECONDS,
            "target_anchor": "company_event_observed_at", "intake_to_start_seconds": elapsed,
            "target_met": elapsed <= COMPANY_ONLY_IDLE_START_TARGET_SECONDS,
        }
    return {**base, "condition": "unverified", "blocking_cycle_ids": blockers, "target_met": None}


def verify_queued_event_for_normal_resume(repository, state, database, *, cycle_id):
    """Return the exact bytes allowed to remain during an explicitly reviewed resume.

    Call under the scraper lease after pinning the existing local cycle and
    enforcing lifecycle, workflow and runtime admission. Never consume or
    bridge this request from the resume path.
    """
    from .company_events import read_verified_queued_event
    payload, request = read_verified_queued_event(repository, database.parent)
    if not isinstance(cycle_id, str) or not cycle_id:
        raise ValueError("Reviewed resume requires an exact blocking cycle ID.")
    local, remote = _cycle_views(repository, state)
    cycle = state.cycle(cycle_id)
    if (_unfinished_from_views(local, remote) != {cycle_id}
            or not isinstance(cycle, dict) or cycle.get("status") not in {"In Progress", "Awaiting Review"}
            or not isinstance(cycle.get("runtime_binding"), dict)
            or not isinstance(cycle.get("companies"), dict) or not cycle["companies"]
            or any(key in cycle for key in ("operator_request", "repair_retry", "temporary_retry", "recovery_pause"))
            or any(key.startswith("retained_") for key in cycle)
            or request["company_ids"][0] in cycle["companies"]
            or request["request_id"] == cycle.get("start_request_id")):
        raise ValueError("Queued Company event is not disjoint from one exact ordinary blocking cycle.")
    mirrors = [row for row in remote if row.get("Cycle ID") == cycle_id]
    if len(mirrors) != 1:
        raise ValueError("Reviewed resume requires one exact blocking cycle mirror.")
    mirror = mirrors[0]
    notes = cycle_metadata(mirror)
    if (mirror.get("Cycle Status") != cycle["status"]
            or notes.get("company_ids") != list(cycle["companies"])
            or notes.get("runtime_binding") != cycle["runtime_binding"]
            or notes.get("start_request_id") != cycle.get("start_request_id")
            or any(key in notes for key in ("operator_request", "repair_retry", "temporary_retry", "recovery_pause"))
            or any(key.startswith("retained_") for key in notes)):
        raise ValueError("Reviewed resume blocking cycle mirror disagrees with its local checkpoint.")

    _exclude_retained_resume(database.parent, request["request_id"], cycle_id)
    return payload


def _exclude_retained_resume(root, request_id, cycle_id):
    # An active signed exception is preserved even before it acquires a
    # dispatcher reservation. This is an exclusion check, not activation.
    checks = (
        ("company-intake-dispatch.sqlite3",
         "SELECT 1 FROM request_ownership WHERE route='RETAINED' "
         "AND (request_id=? OR exception_cycle=?) LIMIT 1", (request_id, cycle_id)),
        ("retained-work-exceptions.sqlite3",
         "SELECT 1 FROM retained_work_exceptions WHERE cycle=? "
         "UNION ALL SELECT 1 FROM retained_work_admissions "
         "WHERE request_id=? OR exception_cycle=? LIMIT 1", (cycle_id, request_id, cycle_id)),
    )
    for filename, query, parameters in checks:
        path = root / filename
        if path.is_symlink():
            raise ValueError("Company intake ownership evidence must be a regular file.")
        if path.exists():
            with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
                if db.execute(query, parameters).fetchone() is not None:
                    raise ValueError("Retained intake ownership excludes ordinary resume.")
