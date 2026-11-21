"""One immutable receipt derivation shared by exact-cycle boundaries."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from pathlib import Path

from .publication_receipts import record_fingerprints


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _digest(value):
    return hashlib.sha256(_canonical(value).encode('utf-8')).hexdigest()



ORDINARY_EVENT_PLAN_BINDING = 'ordinary_company_event'
ORDINARY_EVENT_AUTHORITY = 'ordinary-company-event-exact-v2'
REPAIR_RETRY_PLAN_BINDING = 'repair_retry_receipt_binding'


@dataclass(frozen=True)
class _OrdinaryEventPlanContext:
    """Detached observation from the read-only durable verifier."""

    _observation: str
    spreadsheet_id: str
    state_directory: Path


def load_ordinary_event_plan_context(reader, state, runtime, *, cycle_id, request_sha256):
    """Bind an existing read-only admission/archive and frozen observation."""
    from .ordinary_company_event_fetch import load_ordinary_event_observation

    record = load_ordinary_event_observation(
        reader, state, runtime, cycle_id=cycle_id, request_sha256=request_sha256,
    )
    return _OrdinaryEventPlanContext(
        _canonical(record), reader.spreadsheet_id, Path(state.path).resolve().parent,
    )


def _ordinary_observation(context):
    if not isinstance(context, _OrdinaryEventPlanContext):
        raise ValueError('Ordinary Company-event publication requires a verified plan context.')
    return json.loads(context._observation)


def ordinary_event_plan_payload(context):
    """Project the exact frozen observation to the existing Inbox payload."""
    inventory = _ordinary_observation(context)['inventory']
    if (inventory['status'] not in {'complete', 'partial'} or not inventory['jobs']
            or inventory.get('verified_zero') is not None):
        raise ValueError('Ordinary Company-event exact planning requires a nonempty plannable inventory.')
    if inventory['status'] == 'complete' and (
            inventory['browser_pending_urls'] or inventory['browser_discovery_incomplete']):
        raise ValueError('Ordinary Company-event complete inventory has unresolved browser work.')
    return {
        **{key: value for key, value in inventory.items()
           if key not in {'status', 'outcome_failure', 'verified_zero'}},
        'inventory_status': inventory['status'],
    }


def has_ordinary_event_scope(cycle, request_id=None):
    """Recognize either event provenance channel, including inconsistent input."""
    return cycle.get('company_event') is not None or any(
        isinstance(value, str) and value.startswith('company-event:')
        for value in (cycle.get('start_request_id'), request_id)
    )


def ordinary_event_observation_binding(cycle, company_id, context):
    """Re-derive the exact publication authority from the admitted scope."""
    from .runner import _canonical_runtime_binding

    record = _ordinary_observation(context)
    admitted = record['binding']
    request = admitted['request']
    event = request['company_event']
    companies = cycle.get('companies')
    if (cycle.get('id') != admitted['cycle_id'] or cycle.get('all') is not False
            or not isinstance(companies, dict) or set(companies) != {company_id}
            or company_id != admitted['company_id'] or request['company_ids'] != [company_id]
            or cycle.get('start_request_id') != request['request_id']
            or cycle.get('request_fingerprint') != admitted['request_fingerprint']
            or cycle.get('company_event') != event
            or any(cycle.get(key) is not None for key in (
                'operator_request', 'repair_retry', 'temporary_retry', 'selected_retry_reservation_sha256',
                'retained_work_exception', 'recovery_pause',
            ))):
        raise ValueError('Ordinary Company-event plan context disagrees with the admitted cycle.')
    item = companies[company_id]
    runtime = _canonical_runtime_binding(cycle.get('runtime_binding'))
    if (not isinstance(item, dict) or item.get('company') != admitted['company_name']
            or item.get('outcome_source_fact') != admitted['source_fact']
            or item.get('outcome_source_revision') != event['source_revision']
            or runtime != admitted['runtime']):
        raise ValueError('Ordinary Company-event plan context disagrees with the admitted source or runtime.')
    return {
        'authority': ORDINARY_EVENT_AUTHORITY, 'cycle_id': cycle['id'],
        'request_id': request['request_id'], 'request_sha256': admitted['request_sha256'],
        'request_fingerprint': admitted['request_fingerprint'],
        'company_event_id': event['event_id'], 'company_id': company_id,
        'source_revision': event['source_revision'],
        'bridge_receipt_sha256': admitted['bridge_receipt_sha256'],
        'observation_sha256': record['sha256'], 'provider_inventory_sha256': record['inventory_sha256'],
        'workbook_id_sha256': _digest(context.spreadsheet_id),
        'release_id': runtime.get('release_id', 'NO_RELEASE'),
        'release_binding_sha256': _digest(runtime),
    }


def ordinary_event_receipt_binding(cycle, company_id, payload, context):
    if _canonical(payload) != _canonical(ordinary_event_plan_payload(context)):
        raise ValueError('Ordinary Company-event Inbox payload disagrees with the frozen observation.')
    return ordinary_event_observation_binding(cycle, company_id, context)


def _ordinary_event_receipt(cycle, company_id, payload, plan, timestamp, request_id, context):
    from .exact_cycle_planner import _exact_plan_digest, _require_ordinary_event_source_unchanged
    from .sheet_profile import COMPACT_PROFILE

    binding = ordinary_event_receipt_binding(cycle, company_id, payload, context)
    operations = plan.get('remote_projection')
    version = plan.get('record_fingerprint_version', 1)
    if (plan.get('exact_plan_version') != 2 or plan.get('publication_profile') != COMPACT_PROFILE
            or plan.get('cycle_id') != cycle['id'] or plan.get('company_id') != company_id
            or plan.get('requested_url') != payload['requested_url']
            or plan.get('inventory_payload_digest') != _digest(payload)
            or plan.get(ORDINARY_EVENT_PLAN_BINDING) != binding
            or plan.get('plan_digest') != _exact_plan_digest(plan)
            or not isinstance(operations, list) or not operations
            or plan.get('remote_projection_digest') != _digest(operations)
            or version not in {1, 2} or 'selected_retry_receipt_binding' in plan
            or REPAIR_RETRY_PLAN_BINDING in plan
            or 'retained_membership_only' in plan
            or (request_id is not None and request_id != binding['request_id'])):
        raise ValueError('Ordinary Company-event receipt binding disagrees with the sealed exact plan.')
    _require_ordinary_event_source_unchanged(plan, company_id)
    records = record_fingerprints(operations, include_guard_only=version == 2)
    if plan.get('remote_records') != records or plan.get('remote_records_digest') != _digest(records):
        raise ValueError('Ordinary Company-event receipt disagrees with frozen record fingerprints.')
    request = _ordinary_observation(context)['binding']['request']
    return {
        'binding': binding,
        'records': records,
        'schedule': {'boundary': 'idle', 'enqueued_at': request['enqueued_at']},
        'timestamp': timestamp,
    }


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


def has_repair_retry_scope(cycle, request_id=None):
    """Recognize repair provenance even when a retry checkpoint is malformed."""
    return cycle.get('repair_retry') is not None or any(
        isinstance(value, str) and value.startswith('company-retry:')
        for value in (cycle.get('start_request_id'), request_id)
    )


def repair_retry_receipt_binding(cycle, company_id):
    """Bind one released Company retry to its actual request and activation."""
    from .repair_retry import release_binding_sha256, validate_retry_request
    from .runner import _canonical_runtime_binding

    companies = cycle.get('companies')
    if (cycle.get('all') is not False or not isinstance(companies, dict) or set(companies) != {company_id}
            or any(cycle.get(key) is not None for key in (
                'company_event', 'operator_request', 'temporary_retry', 'selected_retry_reservation_sha256',
                'retained_work_exception', 'recovery_pause',
            ))):
        raise ValueError('Repair retry publication requires its sole Company and no alternate lineage.')
    item = companies[company_id]
    if not isinstance(item, dict):
        raise ValueError('Repair retry publication has no frozen Company.')
    source = item.get('outcome_source_revision')
    request_id = cycle.get('start_request_id')
    retry = validate_retry_request({
        'repair_retry': cycle.get('repair_retry'), 'request_id': request_id, 'source_revision': source,
    }, [company_id])
    fact = item.get('outcome_source_fact')
    if (retry != cycle['repair_retry'] or not isinstance(fact, dict) or fact.get('company_id') != company_id
            or fact.get('eligible') is not True or _digest(fact) != source):
        raise ValueError('Repair retry publication disagrees with the frozen Company source.')
    release = retry['release']
    try:
        runtime = _canonical_runtime_binding(cycle.get('runtime_binding'))
    except RuntimeError as exc:
        raise ValueError('Repair retry publication has no exact admitted release runtime.') from exc
    if runtime != {'state': 'COMPLETE', **{key: value for key, value in release.items() if key != 'schema'}}:
        raise ValueError('Repair retry publication runtime disagrees with its activated release.')
    return {
        'request_id': request_id,
        'company_id': company_id,
        'source_revision': source,
        'release_id': release['release_id'],
        'release_binding_sha256': release_binding_sha256(release),
    }


def require_current_repair_retry(cycle, company_id, repository, state_directory):
    """Recheck the existing release and current Company authorities."""
    from .company_events import current_company_source_revision
    from .integration_release import assert_active_release_binding

    binding = repair_retry_receipt_binding(cycle, company_id)
    assert_active_release_binding(state_directory, cycle['repair_retry']['release'])
    if current_company_source_revision(repository, company_id) != binding['source_revision']:
        raise ValueError('Repair retry publication Company source is no longer current.')
    return binding


def require_unambiguous_repair_retry_receipt(inbox, cycle_id, receipt):
    """Hold existing legacy or conflicting retry receipts before any insert."""
    from .publication_receipts import _receipt_id

    binding = receipt['binding']
    expected_id = _receipt_id(binding)
    remote_state = inbox.exact_remote_state(cycle_id, binding['company_id'])
    if remote_state is not None and remote_state['receipt_id'] != expected_id:
        raise ValueError('Repair retry frozen remote intent has a different receipt.')
    with inbox.lock:
        existing = inbox.connection.execute(
            "SELECT receipt_id FROM main.publication_receipts "
            "WHERE json_extract(binding,'$.company_id')=? "
            "AND json_extract(binding,'$.request_id') IN (?,?)",
            (binding['company_id'], binding['request_id'], cycle_id),
        ).fetchall()
    if any(receipt_id != expected_id for receipt_id, in existing):
        raise ValueError('Repair retry has a conflicting legacy publication receipt.')
    same_records = inbox.find_receipt(binding['company_id'], receipt['records'])
    if same_records is not None and same_records['binding'] != binding:
        raise ValueError('Repair retry frozen records have a different publication receipt.')


def repair_retry_has_confirmed_publication(inbox, local, cycle, company_id):
    """Prove the same receipt was confirmed in Sheets and acknowledged in Jobs."""
    from . import publication_receipts
    from .repair_retry import retry_request
    from .scan_request import request_fingerprint

    binding = repair_retry_receipt_binding(cycle, company_id)
    cycle_id = cycle['id']
    retry = cycle['repair_retry']
    request = retry_request(retry, enqueued_at=retry['activated_at'])
    if cycle.get('request_fingerprint') != request_fingerprint(request, [company_id]):
        raise ValueError('Repair retry publication has no exact admitted request fingerprint.')
    if cycle.get('status') != 'Complete':
        return False
    with inbox.lock:
        if (inbox.get(cycle_id, company_id) is not None
                or inbox.plan(cycle_id, company_id) is not None
                or inbox.exact_remote_state(cycle_id, company_id) is not None):
            return False
        receipt = inbox.receipt({'binding': binding})
        if (receipt is None or receipt['binding'] != binding
                or receipt['state'] != publication_receipts.SYNC_CONFIRMED
                or receipt['schedule'] != {'boundary': 'idle', 'enqueued_at': retry['activated_at']}
                or not receipt['records'] or not receipt['acknowledgement_id']):
            return False
        require_unambiguous_repair_retry_receipt(inbox, cycle_id, receipt)
        applications = local.db.execute(
            'SELECT application.plan_digest, application.apply_id '
            'FROM exact_local_applications AS application '
            'JOIN exact_local_acknowledgements AS ack ON ack.apply_id=application.apply_id '
            'WHERE application.cycle=? AND application.company=? AND ack.receipt_id=? '
            'AND ack.acknowledgement_id=?',
            (cycle_id, company_id, receipt['receipt_id'], receipt['acknowledgement_id']),
        ).fetchall()
        if len(applications) != 1:
            return False
        plan_digest, apply_id = applications[0]
        inbox._require_exact_local_acknowledgement(
            local, cycle_id, company_id, plan_digest, receipt['receipt_id'],
            receipt['acknowledgement_id'], expected_apply_id=apply_id,
        )
    return True


def _sealed_repair_retry_binding(cycle, company_id, payload, plan, request_id):
    from .exact_cycle_planner import _exact_plan_digest, _require_ordinary_event_source_unchanged
    from .sheet_profile import COMPACT_PROFILE

    binding = repair_retry_receipt_binding(cycle, company_id)
    if (plan.get('exact_plan_version') != 2 or plan.get('publication_profile') != COMPACT_PROFILE
            or plan.get('cycle_id') != cycle['id'] or plan.get('company_id') != company_id
            or plan.get('requested_url') != payload.get('requested_url')
            or plan.get('inventory_payload_digest') != _digest(payload)
            or plan.get(REPAIR_RETRY_PLAN_BINDING) != binding
            or plan.get('plan_digest') != _exact_plan_digest(plan)
            or any(key in plan for key in (ORDINARY_EVENT_PLAN_BINDING, 'selected_retry_receipt_binding',
                                          'retained_membership_only', 'selected_legacy_control_before_prefix_recovery'))
            or (request_id is not None and request_id != binding['request_id'])):
        raise ValueError('Repair retry publication requires its exact compact-v2 frozen binding.')
    _require_ordinary_event_source_unchanged(plan, company_id)
    return binding


def derive_receipt(cycle, company_id, payload, plan, timestamp, *, request_id=None,
                   ordinary_event_context=None):
    """Return the sole full binding/schedule contract for frozen plans.

    ``timestamp`` records local receipt creation only.  It must never change
    the immutable schedule, so interrupted plans with incomplete date fields
    remain recoverable under every exact-cycle consumer.
    """
    if (has_ordinary_event_scope(cycle, request_id) or ORDINARY_EVENT_PLAN_BINDING in plan
            or ordinary_event_context is not None):
        if has_repair_retry_scope(cycle, request_id) or REPAIR_RETRY_PLAN_BINDING in plan:
            raise ValueError('Repair retry publication cannot reuse an ordinary Company-event binding.')
        return _ordinary_event_receipt(
            cycle, company_id, payload, plan, timestamp, request_id, ordinary_event_context,
        )
    repair_binding = (
        _sealed_repair_retry_binding(cycle, company_id, payload, plan, request_id)
        if has_repair_retry_scope(cycle, request_id) or REPAIR_RETRY_PLAN_BINDING in plan else None
    )
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
    if repair_binding is not None:
        if (plan.get('remote_projection_digest') != _digest(operations)
                or plan.get('remote_records') != records or plan.get('remote_records_digest') != _digest(records)):
            raise ValueError('Repair retry publication disagrees with its frozen record fingerprints.')
        return {
            'binding': repair_binding,
            'records': records,
            'schedule': {'boundary': 'idle', 'enqueued_at': cycle['repair_retry']['activated_at']},
            'timestamp': timestamp,
        }
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
