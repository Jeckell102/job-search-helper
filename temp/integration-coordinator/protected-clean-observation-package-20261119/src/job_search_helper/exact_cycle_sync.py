"""Identity-scoped delivery for one already-frozen durable inventory cycle.

This is deliberately separate from :mod:`run_sync`: that worker performs a
workbook-wide pull and drains every local dirty row.  A named recovery must
never inherit those side effects.  This module writes only operations already
frozen in the selected cycle's inbox plans, then confirms each one from an
exact remote readback before releasing its durable inventory.
"""
from __future__ import annotations

import hashlib
import json
import copy
from typing import Mapping

from .publication_receipts import (LOCAL_COMMITTED, SYNC_CONFIRMED, SYNC_PENDING,
                                    record_fingerprints)
from .repository import UncertainWriteError, _equivalent
from .sqlite_repository import timestamp
from .exact_cycle_receipt import derive_receipt


CONTROL_EVIDENCE_VERSION = 1
PUBLICATION_PROJECTION_VERSION = 1
_CONTROL_FIELDS = ('company_id', 'requested_url', 'official_careers_url',
                   'company_status', 'claimed_by', 'claim_token')


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _fallback_receipt(cycle, company_id, plan, payload):
    """Compatibility name for the shared exact receipt contract."""
    return derive_receipt(cycle, company_id, payload, plan, timestamp())


def _readback(remote, operations):
    """Read only exact selected rows, never a whole tab.

    ``read_columns`` obtains just the identity columns needed to find each
    frozen target. ``read_rows`` then fetches only the matching row numbers
    for fingerprinting.  The global ``read``/``read_many`` APIs are forbidden
    here because they could make unrelated workbook state part of recovery.
    """
    targets = {}
    for operation in operations:
        identity = dict(operation['identity'])
        for key, value in operation.get('on_insert', {}).items():
            if key in identity:
                identity[key] = value
        for key, value in operation.get('values', {}).items():
            if key in identity:
                identity[key] = value
        targets.setdefault(operation['tab'], []).append(identity)
    rows = {}
    for tab, identities in targets.items():
        headers = sorted({key for identity in identities for key in identity})
        numbered = remote.read_columns(tab, headers)
        selected = []
        for identity in identities:
            matches = [row_number for row_number, row in numbered if all(
                _equivalent(header, row.get(header, ''), value)
                for header, value in identity.items())]
            if len(matches) == 1:
                selected.append(matches[0])
        exact = remote.read_rows(tab, selected) if selected else {}
        rows[tab] = list(exact.values())
    return record_fingerprints(operations, rows)


def _receipt_for_plan(inbox, cycle, company_id, plan, payload):
    """Use only the deterministically derived full immutable receipt binding."""
    expected = _fallback_receipt(cycle, company_id, plan, payload)
    # Legacy plans have no embedded receipt.  A same-record receipt from any
    # other request/source is evidence of ambiguity, never authority to reuse.
    other = inbox.find_receipt(company_id, expected['records'])
    if other is not None and other['binding'] != expected['binding']:
        raise ValueError('legacy_receipt_binding_mismatch')
    actual = inbox.receipt(expected)
    if actual is not None:
        if actual['records'] != expected['records'] or actual['schedule'] != expected['schedule']:
            raise ValueError('legacy_receipt_binding_mismatch')
        expected['timestamp'] = actual['created_at']
    return expected


def _chunks(operations, start, *, max_operations=100, max_bytes=500_000):
    index = start
    while index < len(operations):
        chunk, size = [], 0
        while index < len(operations) and len(chunk) < max_operations:
            operation = operations[index]
            cost = len(_canonical(operation).encode('utf-8'))
            if cost > max_bytes:
                raise ValueError('frozen_operation_exceeds_scoped_batch_limit')
            if chunk and size + cost > max_bytes:
                break
            chunk.append(operation); size += cost; index += 1
        yield index - len(chunk), chunk


def _validate_chunkable(operations):
    """Legacy plans can be chunked only when each remote identity is unique."""
    identities = set()
    for operation in operations:
        identity = dict(operation.get('identity', {}))
        for values in (operation.get('on_insert', {}), operation.get('values', {})):
            if not isinstance(values, Mapping):
                raise ValueError('operation_values_shape_invalid')
            identity.update({key: value for key, value in values.items() if key in identity})
        label = str(operation.get('tab', '')) + ':' + _canonical(identity)
        if label in identities:
            raise ValueError('duplicate_identity_without_atomic_group')
        identities.add(label)


def _chunk_digest(chunk):
    return hashlib.sha256(_canonical(chunk).encode('utf-8')).hexdigest()


def _unique_company(repository, company_id, headers):
    """Freshly read one exact Company using only explicitly named fields."""
    numbered = repository.read_columns('Companies', headers)
    matches = [row_number for row_number, row in numbered
               if _equivalent('Company ID', row.get('Company ID', ''), company_id)]
    if len(matches) != 1:
        raise ValueError('company_missing_or_ambiguous')
    # ``read_columns`` is itself the fresh bounded read and, unlike read_rows,
    # cannot pull compact-profile-excluded fields from Google accidentally.
    return next(row for row_number, row in numbered if row_number == matches[0])


def _company_guard(local, remote, company_id, requested_url):
    """Bind local-only controls to the compact remote Company projection.

    Claims, scan state, and automatic-retry holds are authoritative only in
    the local store under compact-v1.  Google is freshly read only for its
    three visible shared controls.  The returned six fields are therefore a
    composite snapshot, and the publisher can compare the exact same contract
    that sealed the plan without pretending local-only columns exist remotely.
    """
    requested = str(requested_url or '').strip()
    if not requested:
        raise ValueError('company_board_changed')
    local_headers = ['Company ID', 'Company Status', 'Official Careers URL',
                     'Claimed By', 'Claim Token', 'Scan State', 'Automatic Retry?']
    remote_headers = ['Company ID', 'Company Status', 'Official Careers URL']
    local_company = _unique_company(local, company_id, local_headers)
    remote_company = _unique_company(remote, company_id, remote_headers)
    local_status = str(local_company.get('Company Status', '')).strip()
    local_url = str(local_company.get('Official Careers URL', '')).strip()
    claimed_by = str(local_company.get('Claimed By', '')).strip()
    claim_token = str(local_company.get('Claim Token', '')).strip()
    if local_status.casefold() != 'active':
        raise ValueError('local_company_not_active')
    if claimed_by or claim_token:
        raise ValueError('local_company_claimed')
    if (str(local_company.get('Automatic Retry?', '')).strip().casefold() == 'no'
            and str(local_company.get('Scan State', '')).strip() == 'Blocked / Manual Review'):
        raise ValueError('local_company_manual_hold')
    if not _equivalent('Official Careers URL', local_url, requested):
        raise ValueError('local_company_board_changed')
    for header in remote_headers:
        if not _equivalent(header, remote_company.get(header, ''), local_company.get(header, '')):
            raise ValueError('local_remote_company_controls_changed')
    return {
        'company_id': str(local_company.get('Company ID', '')).strip(),
        'requested_url': requested,
        'official_careers_url': local_url,
        'company_status': local_status,
        'claimed_by': claimed_by,
        'claim_token': claim_token,
    }


def _validate_controls(plan, current):
    stored = plan.get('control_evidence')
    if (plan.get('control_evidence_version') != CONTROL_EVIDENCE_VERSION
            or not isinstance(stored, Mapping) or set(stored) != set(_CONTROL_FIELDS)
            or any(not isinstance(stored.get(key), str) for key in _CONTROL_FIELDS)):
        raise ValueError('plan_control_evidence_invalid')
    stored = {key: stored[key] for key in _CONTROL_FIELDS}
    stored_digest = hashlib.sha256(_canonical(stored).encode('utf-8')).hexdigest()
    if plan.get('control_evidence_digest') != stored_digest:
        raise ValueError('plan_control_evidence_digest_invalid')
    current_digest = hashlib.sha256(_canonical(current).encode('utf-8')).hexdigest()
    if stored_digest != current_digest:
        raise ValueError('company_control_evidence_changed')


def _digest(value):
    return hashlib.sha256(_canonical(value).encode('utf-8')).hexdigest()


def _publication_schema(remote, profile):
    """Return the current remote schema bound to a supported plan profile."""
    from .sheet_profile import profile_schemas

    schemas = getattr(remote, 'schemas', None)
    if not isinstance(schemas, Mapping) or not schemas:
        raise ValueError('publication_remote_schema_missing')
    if profile == 'full':
        publication = schemas
    else:
        try:
            publication = profile_schemas(profile)
        except Exception as exc:
            raise ValueError('publication_profile_invalid') from exc
        if publication is None:
            raise ValueError('publication_profile_invalid')
    normalized = {}
    for tab, headers in publication.items():
        if not isinstance(tab, str) or not tab or not isinstance(headers, (list, tuple)) or not headers:
            raise ValueError('publication_schema_invalid')
        values = tuple(str(header) for header in headers)
        if len(values) != len(set(values)):
            raise ValueError('publication_schema_invalid')
        normalized[tab] = values
    remote_normalized = {}
    for tab, headers in schemas.items():
        if not isinstance(tab, str) or not tab or not isinstance(headers, (list, tuple)) or not headers:
            raise ValueError('publication_remote_schema_invalid')
        values = tuple(str(header) for header in headers)
        if len(values) != len(set(values)):
            raise ValueError('publication_remote_schema_invalid')
        remote_normalized[tab] = values
    if normalized != remote_normalized:
        raise ValueError('publication_remote_schema_changed')
    return normalized


def _validate_sealed_plan(plan, payload, remote):
    """Reject altered or unprovable frozen plans before any remote action.

    Full-profile plans contain the complete local operation stream, so both
    local digests can be recomputed from the immutable plan.  A projected
    profile omits local-only mutations and therefore needs a separate durable
    local commit journal before it can ever be safe to publish.  No such
    journal is part of the current receipt contract, so those plans fail
    closed even when their remote projection is internally consistent.
    """
    operations = plan.get('operations') if isinstance(plan, Mapping) else None
    if not isinstance(operations, list) or not isinstance(plan.get('final'), Mapping):
        raise ValueError('sealed_plan_shape_invalid')
    if plan.get('publication_projection_version') != PUBLICATION_PROJECTION_VERSION:
        raise ValueError('publication_projection_version_invalid')
    profile = plan.get('publication_profile')
    if not isinstance(profile, str) or not profile:
        raise ValueError('publication_profile_invalid')
    publication = _publication_schema(remote, profile)
    schema_evidence = {tab: list(headers) for tab, headers in sorted(publication.items())}
    schema_digest = _digest(schema_evidence)
    if plan.get('publication_schema_digest') != schema_digest:
        raise ValueError('publication_schema_digest_invalid')
    if plan.get('remote_operations_digest') != _digest(operations):
        raise ValueError('remote_operations_digest_invalid')
    if plan.get('remote_projection_digest') != _digest({
            'profile': profile,
            'schema_digest': schema_digest,
            'operations': operations,
            }):
        raise ValueError('remote_projection_digest_invalid')
    if profile != 'full':
        raise ValueError('non_full_plan_requires_durable_local_commit_journal')
    if plan.get('local_operations_digest') != _digest(operations):
        raise ValueError('local_operations_digest_invalid')
    if plan.get('local_finalization_digest') != _digest({
            'operations': operations,
            'final': plan['final'],
            }):
        raise ValueError('local_finalization_digest_invalid')
    records = record_fingerprints(operations)
    required = ('operations', 'final', 'requested_url', 'control_evidence',
                'control_evidence_version', 'control_evidence_digest',
                'inventory_payload_digest', 'plan_records_digest',
                'final_projection', 'final_projection_digest',
                'publication_projection_version', 'publication_profile',
                'publication_schema_digest', 'local_operations_digest',
                'local_finalization_digest', 'remote_operations_digest',
                'remote_projection_digest')
    sealed = {key: plan.get(key) for key in required}
    if (plan.get('inventory_payload_digest') != _digest(payload)
            or plan.get('plan_records_digest') != _digest(records)
            or plan.get('plan_digest') != _digest(sealed)):
        raise ValueError('sealed_plan_digest_invalid')


def _local_operation_count(plan):
    """Select the only operation count that can authorize local durability.

    Full-profile operations are both the local stream and remote projection.
    A future projected plan must carry its complete immutable local stream;
    its shorter remote operations list can never authorize the local cursor.
    Current projected plans still fail earlier because no durable local commit
    journal contract exists.
    """
    if plan.get('publication_profile') == 'full':
        operations = plan.get('operations')
    else:
        operations = plan.get('local_operations')
    if not isinstance(operations, list) or not operations:
        raise ValueError('local_operation_stream_missing')
    return len(operations)


def _checkpoint_matches_final(checkpoint, plan):
    final = plan.get('final') if isinstance(plan, Mapping) else None
    projection = plan.get('final_projection') if isinstance(plan, Mapping) else None
    if (not isinstance(final, Mapping) or not isinstance(projection, Mapping)
            or projection != {key: final[key] for key in sorted(final)}
            or plan.get('final_projection_digest') != _digest(projection)):
        return False
    return {key: checkpoint.get(key) for key in projection} == dict(projection)



def _validate_exact_plan_v2(plan, payload, remote, cycle_id, company_id):
    """Validate every immutable v2 seal against the current remote schema."""
    from .exact_cycle_planner import _exact_plan_digest
    from .exact_local_plan import _validate_plan
    from .sheet_profile import COMPACT_PROFILE, profile_schemas

    plan, local_operations, remote_projection = _validate_plan(
        plan, cycle_id, company_id)
    schema = profile_schemas(COMPACT_PROFILE)
    normalized = {tab: list(headers) for tab, headers in sorted(schema.items())}
    remote_schema = getattr(remote, 'schemas', None)
    current_remote = ({tab: list(headers) for tab, headers in sorted(remote_schema.items())}
                      if isinstance(remote_schema, Mapping) else None)
    final = plan.get('final')
    final_projection = plan.get('final_projection')
    if (plan.get('publication_profile') != COMPACT_PROFILE
            or plan.get('publication_schema') != normalized
            or current_remote != normalized
            or plan.get('publication_schema_digest') != _digest(normalized)
            or plan.get('inventory_payload_digest') != _digest(payload)
            or plan.get('plan_digest') != _exact_plan_digest(plan)
            or plan.get('remote_projection_digest') != _digest(remote_projection)
            or plan.get('remote_records') != record_fingerprints(
                remote_projection,
                include_guard_only=plan.get('record_fingerprint_version', 1) == 2)
            or plan.get('remote_records_digest') != _digest(plan.get('remote_records'))
            or not isinstance(final, Mapping)
            or plan.get('local_finalization_digest') != _digest({
                'operations': local_operations, 'final': final,
            })
            or not isinstance(final_projection, Mapping)
            or final_projection != {key: final[key] for key in sorted(final)}
            or plan.get('final_projection_digest') != _digest(final_projection)):
        raise ValueError('exact_plan_v2_seal_or_schema_invalid')
    _validate_controls(plan, plan.get('control_evidence', {}))
    return plan, local_operations, remote_projection


def _remote_intent_id(cycle_id, company_id, plan_digest, projection_digest,
                      delivery_mode='write_once'):
    binding = {
        'cycle_id': cycle_id, 'company_id': company_id,
        'plan_digest': plan_digest, 'projection_digest': projection_digest,
    }
    if delivery_mode != 'write_once':
        binding['delivery_mode'] = delivery_mode
    return 'ERI-' + _digest(binding)[:32]


def _readback_records(exact_plan, readback):
    rows = {}
    for operation, observed in zip(exact_plan['operations'], readback['rows']):
        identity = dict(operation['identity'])
        for values in (operation.get('on_insert', {}), operation.get('values', {})):
            identity.update({key: value for key, value in values.items() if key in identity})
        row = dict(identity)
        row.update(observed['actual'])
        row.update(observed.get('remote_guards', {}))
        rows.setdefault(operation['tab'], []).append(row)
    return record_fingerprints(
        exact_plan['operations'], rows,
        include_guard_only=exact_plan.get('record_fingerprint_version', 1) == 2)


def _bounded_exact_chunks(exact_plan, *, max_operations=100, max_bytes=500_000):
    """Split an exact plan without separating its operation/row evidence."""
    operations = exact_plan['operations']
    rows = exact_plan['rows']
    chunks = []
    start = 0
    while start < len(operations):
        stop = start
        while stop < len(operations) and stop - start < max_operations:
            candidate = operations[start:stop + 1]
            if len(_canonical(candidate).encode('utf-8')) > max_bytes:
                break
            stop += 1
        if stop == start:
            raise ValueError('Exact Sheets single operation exceeds the remote byte bound.')
        selected = copy.deepcopy(operations[start:stop])
        chunks.append((start, {
            'operations': selected,
            'rows': copy.deepcopy(rows[start:stop]),
            'projection_digest': _digest(selected),
            'delivery_mode': exact_plan.get('delivery_mode', 'write_once'),
        }))
        start = stop
    return chunks


def _local_acknowledgement(local, cycle_id, company_id, plan_digest,
                           receipt_id, acknowledgement_id):
    if not hasattr(local, 'db'):
        return None
    parent = local.db.execute(
        'SELECT apply_id,state FROM exact_local_applications '
        'WHERE cycle=? AND company=? AND plan_digest=?',
        (cycle_id, company_id, plan_digest)).fetchone()
    if parent is None or parent[1] != 'VERIFIED':
        return None
    row = local.db.execute(
        'SELECT acknowledgement_id FROM exact_local_acknowledgements '
        'WHERE apply_id=? AND receipt_id=?', (parent[0], receipt_id)).fetchone()
    return bool(row and row[0] == acknowledgement_id)


def _save_inventory_checkpoint(state, cycle_id, company_id, payload):
    refreshed = state.cycle(cycle_id)
    if refreshed is None or company_id not in refreshed.get('companies', {}):
        raise ValueError('state_cycle_or_company_missing_before_inventory_checkpoint')
    refreshed = copy.deepcopy(refreshed)
    item = refreshed['companies'][company_id]
    item.update({key: copy.deepcopy(value) for key, value in payload.items()
                 if key != 'jobs'})
    item.update(stage='inventory', durable_inventory=True, locally_processed=True)
    item.pop('jobs', None)
    state.save_cycle(refreshed)


def _finalize_exact_company(inbox, state, cycle_id, company_id, plan, local):
    finalized = state.cycle(cycle_id)
    if finalized is None or company_id not in finalized.get('companies', {}):
        raise RuntimeError('state_cycle_or_company_missing_before_finalization')
    finalized = copy.deepcopy(finalized)
    final = plan.get('final', {})
    finalized['companies'][company_id].update(final)
    state.save_cycle(finalized)
    if final.get('stage') in {'complete', 'partial'}:
        inbox.acknowledge(cycle_id, company_id, local=local)
    else:
        inbox.block(cycle_id, company_id)


def _publish_exact_v2(inbox, cycle_id, company_id, plan, cursor, payload, remote,
                      state, company_guard, local, synchronizer):
    """Publish one v2 plan through only accepted exact-scope primitives."""
    from .exact_local_plan import VERIFIED, exact_local_plan
    from .sheets_sync import SheetsSynchronizer

    plan, local_operations, remote_projection = _validate_exact_plan_v2(
        plan, payload, remote, cycle_id, company_id)
    if local is None:
        raise ValueError('exact_plan_v2_requires_local_repository')
    if cursor != len(local_operations):
        raise ValueError('local_plan_not_durably_applied')
    inbox_local = inbox.exact_local_state(cycle_id, company_id)
    authoritative = exact_local_plan(local, cycle_id, company_id)
    verified = local.verify_exact_local_plan(
        cycle_id, company_id, plan, cursor=None)
    if (inbox_local is None or inbox_local['state'] != 'LOCAL_VERIFIED'
            or authoritative is None or authoritative['state'] != VERIFIED
            or inbox_local['plan_digest'] != plan['plan_digest']
            or inbox_local['local_apply_id'] != authoritative['apply_id']
            or inbox_local['local_records_digest'] != verified['records_digest']
            or verified['apply_id'] != authoritative['apply_id']
            or authoritative['plan_digest'] != plan['plan_digest']
            or authoritative['remote_projection_digest'] != plan['remote_projection_digest']):
        raise ValueError('exact_plan_v2_local_verification_mismatch')
    controls = company_guard(company_id, plan.get('requested_url'))
    _validate_controls(plan, controls)
    cycle = state.cycle(cycle_id)
    receipt = _fallback_receipt(cycle, company_id, plan, payload)
    receipt_id = inbox.ensure_receipt(receipt)
    current = inbox.receipt(receipt)
    if current is None:
        raise ValueError('exact_plan_v2_receipt_not_durable')
    remote_state = inbox.exact_remote_state(cycle_id, company_id)
    if (current['state'] == SYNC_CONFIRMED and remote_state is not None
            and current['acknowledgement_id']
            and _local_acknowledgement(
                local, cycle_id, company_id, plan['plan_digest'], receipt_id,
                current['acknowledgement_id'])):
        inbox.mark_exact_remote_locally_acknowledged(
            cycle_id, company_id, local=local,
            local_plan_digest=plan['plan_digest'],
            projection_digest=remote_state['projection_digest'],
            receipt_id=receipt_id, intent_id=remote_state['intent_id'],
            acknowledgement_id=current['acknowledgement_id'], timestamp=timestamp())
        _finalize_exact_company(inbox, state, cycle_id, company_id, plan, local)
        return {'confirmed': True, 'acknowledgement_id': current['acknowledgement_id']}

    _save_inventory_checkpoint(state, cycle_id, company_id, payload)
    sync = synchronizer or SheetsSynchronizer(local, remote)
    delivery = inbox.exact_legacy_delivery_evidence(cycle_id, company_id)
    delivery_mode = 'write_once'
    if delivery is not None:
        if (delivery.get('plan_digest') != plan['plan_digest']
                or delivery.get('state') != 'BOUND'):
            raise ValueError('exact_plan_v2_delivery_evidence_mismatch')
        delivery_mode = delivery.get('delivery_mode')
    exact_plan = sync.plan_exact_scope(
        authoritative['row_scope'], remote_projection,
        delivery_mode=delivery_mode)
    intent_id = _remote_intent_id(
        cycle_id, company_id, plan['plan_digest'], exact_plan['projection_digest'],
        delivery_mode)
    remote_state = inbox.freeze_exact_remote_plan(
        cycle_id, company_id, local_plan_digest=plan['plan_digest'],
        projection=exact_plan['operations'],
        projection_digest=exact_plan['projection_digest'], receipt_id=receipt_id,
        intent_id=intent_id, timestamp=timestamp(),
        delivery_mode=delivery_mode)
    if remote_state['state'] not in {'SYNC_CONFIRMED', 'LOCAL_ACKNOWLEDGED'}:
        chunks = _bounded_exact_chunks(exact_plan)
        starts = {start for start, _chunk in chunks}
        remote_cursor = remote_state['remote_cursor']
        if remote_cursor not in starts and remote_cursor != len(exact_plan['operations']):
            raise ValueError('exact_plan_v2_remote_cursor_not_at_chunk_boundary')
        for start, chunk in chunks:
            if start < remote_cursor:
                continue
            delivered = sync.publish_exact_scope(
                chunk, inbox=inbox, cycle_id=cycle_id, company_id=company_id,
                plan_digest=plan['plan_digest'], receipt_id=receipt_id,
                intent_id=intent_id,
                remote_projection_digest=exact_plan['projection_digest'],
                remote_cursor=start)
            remote_cursor = start + len(chunk['operations'])
        if remote_cursor != len(exact_plan['operations']):
            raise ValueError('exact_plan_v2_remote_cursor_incomplete')
    acknowledged = sync.confirm_and_acknowledge_exact_scope(
        inbox=inbox, cycle_id=cycle_id, company_id=company_id,
        plan_digest=plan['plan_digest'], receipt_id=receipt_id,
        intent_id=intent_id)
    acknowledgement_id = acknowledged['acknowledgement_id']
    inbox.mark_exact_remote_locally_acknowledged(
        cycle_id, company_id, local=local,
        local_plan_digest=plan['plan_digest'],
        projection_digest=exact_plan['projection_digest'], receipt_id=receipt_id,
        intent_id=intent_id, acknowledgement_id=acknowledgement_id,
        timestamp=timestamp())
    _finalize_exact_company(inbox, state, cycle_id, company_id, plan, local)
    return {'confirmed': True, 'acknowledgement_id': acknowledgement_id,
            'local_ack_recovered': acknowledged['recovered']}


def publish_exact_cycle(inbox, cycle_id, remote, *, company_ids, retry_blocked=False, state,
                        company_guard=None, local=None, synchronizer=None):
    """Deliver only the frozen plans for ``cycle_id``.

    Failures are intentionally contained per company.  No failure clears a
    cursor, receipt, inventory, or a plan from the named cycle; other cycles
    and any local SQLite publisher/outbox state are never inspected.
    """
    if not isinstance(cycle_id, str) or not cycle_id.strip():
        raise ValueError('Exact cycle ID is required.')
    if retry_blocked:
        raise ValueError('Exact selected-plan publication never retries blocked inventories.')
    if not isinstance(company_ids, (list, tuple)):
        raise ValueError('Exact selected-plan publication requires explicit company IDs.')
    if not callable(company_guard):
        raise ValueError('Exact selected-plan publication requires trusted local Company controls.')
    selected = [str(company_id).strip() for company_id in company_ids]
    if (not selected or len(selected) > 25 or any(not company_id for company_id in selected)
            or len(selected) != len(set(selected))):
        raise ValueError('Exact selected-plan company selection must be unique and bounded to 1-25.')
    cycle_id = cycle_id.strip()
    cycle = state.cycle(cycle_id)
    if cycle is None:
        raise ValueError('Exact State cycle is missing; frozen plans remain held.')
    report = {'cycle_id': cycle_id, 'confirmed': [], 'held': [], 'skipped': []}
    for company_id in selected:
        cycle = state.cycle(cycle_id)
        if cycle is None or company_id not in cycle.get('companies', {}):
            report['held'].append({'company_id': company_id, 'reason': 'state_cycle_or_company_missing'})
            continue
        checkpoint = cycle['companies'][company_id]
        checkpoint_recoverable = (checkpoint.get('stage') == 'inventory'
                                  and checkpoint.get('durable_inventory') is True
                                  and checkpoint.get('locally_processed') is True)
        saved = inbox.get(cycle_id, company_id)
        plan_state = inbox.plan(cycle_id, company_id)
        if saved is None:
            report['held'].append({'company_id': company_id, 'reason': 'durable_inventory_missing'})
            continue
        payload, blocked = saved
        if blocked:
            report['held'].append({'company_id': company_id, 'reason': 'durable_inventory_blocked'})
            continue
        if plan_state is None:
            report['skipped'].append({'company_id': company_id, 'reason': 'no_frozen_plan'})
            continue
        plan, cursor = plan_state
        if isinstance(plan, Mapping) and plan.get('exact_plan_version') == 2:
            try:
                result = _publish_exact_v2(
                    inbox, cycle_id, company_id, plan, cursor, payload, remote,
                    state, company_guard, local, synchronizer)
                if result['confirmed']:
                    report['confirmed'].append(company_id)
            except UncertainWriteError:
                report['held'].append({'company_id': company_id,
                                       'reason': 'uncertain_write'})
            except ValueError as exc:
                report['held'].append({'company_id': company_id,
                                       'reason': str(exc) or 'ValueError'})
            except Exception as exc:
                report['held'].append({'company_id': company_id,
                                       'reason': type(exc).__name__})
            continue
        operations = plan.get('operations')
        if not isinstance(operations, list) or not operations:
            report['held'].append({'company_id': company_id, 'reason': 'empty_frozen_plan'})
            continue
        if type(cursor) is not int or cursor < 0 or cursor > len(operations):
            report['held'].append({'company_id': company_id, 'reason': 'invalid_plan_cursor'})
            continue
        try:
            _validate_sealed_plan(plan, payload, remote)
            _validate_chunkable(operations)
        except ValueError as exc:
            report['held'].append({'company_id': company_id, 'reason': str(exc)})
            continue
        # sync_plans.cursor records durable *local SQLite application*.  It is
        # not a Sheets cursor and must never be reinterpreted as evidence that
        # any remote prefix was published.  Remote progress belongs solely to
        # the exact_sync_chunks journal plus the immutable receipt state.
        if cursor != _local_operation_count(plan):
            report['held'].append({'company_id': company_id,
                                   'reason': 'local_plan_not_durably_applied'})
            continue
        try:
            receipt = _receipt_for_plan(inbox, cycle, company_id, plan, payload)
            current = inbox.receipt(receipt)
            # The state save and inbox cleanup are deliberately separate
            # transactions.  Recover only the exact post-save/pre-cleanup
            # boundary, with no new write and no relaxed checkpoint match.
            if not checkpoint_recoverable:
                # An invalid/terminal checkpoint must not create a receipt.
                # It is eligible only for an already-confirmed cleanup after
                # an interrupted inbox acknowledgement/block transaction.
                final = plan.get('final', {})
                if (current is None or current['state'] != SYNC_CONFIRMED
                        or not _checkpoint_matches_final(checkpoint, plan)
                        ):
                    report['held'].append({'company_id': company_id,
                                           'reason': 'state_checkpoint_not_recoverable'})
                    continue
                controls = company_guard(company_id, plan.get('requested_url'))
                _validate_controls(plan, controls)
                if _readback(remote, operations) != receipt['records']:
                    report['held'].append({'company_id': company_id,
                                           'reason': 'state_checkpoint_not_recoverable'})
                    continue
                if final.get('stage') in {'complete', 'partial'}:
                    inbox.acknowledge(cycle_id, company_id)
                else:
                    inbox.block(cycle_id, company_id)
                report['confirmed'].append(company_id)
                continue
            controls = company_guard(company_id, plan.get('requested_url'))
            _validate_controls(plan, controls)
            inbox.ensure_receipt(receipt)
            current = inbox.receipt(receipt)
            if current is None:
                raise RuntimeError('Exact receipt was not persisted.')
            # A confirmed receipt can never authorize a tail replay.  It is
            # usable only for the same zero-write finalization boundary.
            if current['state'] == SYNC_CONFIRMED:
                if _readback(remote, operations) != receipt['records']:
                    report['held'].append({'company_id': company_id,
                                           'reason': 'confirmed_receipt_not_at_exact_end'})
                    continue
                final = plan.get('final', {})
                finalized = state.cycle(cycle_id)
                if finalized is None or company_id not in finalized.get('companies', {}):
                    raise RuntimeError('state_cycle_or_company_missing_before_finalization')
                finalized = copy.deepcopy(finalized)
                finalized['companies'][company_id].update(final)
                state.save_cycle(finalized)
                if final.get('stage') in {'complete', 'partial'}:
                    inbox.acknowledge(cycle_id, company_id)
                else:
                    inbox.block(cycle_id, company_id)
                report['confirmed'].append(company_id)
                continue
            # Set below only after this invocation read back and advanced the
            # immediately preceding chunk. A restart begins False.
            safe_next = False
            remote_cursor = 0
            while remote_cursor < len(operations):
                start, chunk = next(_chunks(operations, remote_cursor))
                digest = _chunk_digest(chunk)
                expected_chunk = record_fingerprints(chunk)
                observed_chunk = _readback(remote, chunk)
                attempt = inbox.exact_chunk(cycle_id, company_id, start)
                if attempt is not None and (attempt['count'] != len(chunk) or
                                            attempt['digest'] != digest):
                    report['held'].append({'company_id': company_id,
                                           'reason': 'chunk_journal_mismatch'})
                    break
                if observed_chunk == expected_chunk:
                    if attempt is None:
                        attempt = inbox.begin_exact_chunk(cycle_id, company_id, start, len(chunk), digest)
                    inbox.confirm_exact_chunk(cycle_id, company_id, start)
                    remote_cursor = start + len(chunk)
                    safe_next = True
                    continue
                if attempt is not None:
                    report['held'].append({'company_id': company_id, 'reason': 'pending_chunk_readback_mismatch'})
                    break
                if current['state'] == SYNC_PENDING and not safe_next:
                    report['held'].append({'company_id': company_id, 'reason': 'pending_readback_mismatch'})
                    break
                # A new cursor is safe to attempt once: persist both the
                # overall receipt and exact chunk journal before the request.
                if current['state'] == LOCAL_COMMITTED:
                    inbox.mark_receipt_pending(receipt, timestamp=timestamp())
                    current = inbox.receipt(receipt)
                inbox.begin_exact_chunk(cycle_id, company_id, start, len(chunk), digest)
                remote.commit(chunk)
                if _readback(remote, chunk) != expected_chunk:
                    report['held'].append({'company_id': company_id, 'reason': 'chunk_readback_mismatch'})
                    break
                inbox.confirm_exact_chunk(cycle_id, company_id, start)
                remote_cursor = start + len(chunk)
                safe_next = True
            else:
                observed = _readback(remote, operations)
                if observed != receipt['records']:
                    report['held'].append({'company_id': company_id, 'reason': 'readback_mismatch'})
                    continue
                acknowledgement = 'exact-readback:' + hashlib.sha256(
                    _canonical({'cycle_id': cycle_id, 'company_id': company_id,
                                'records': observed}).encode('utf-8')).hexdigest()
                if current['state'] == LOCAL_COMMITTED:
                    # A prior global/legacy application may already be
                    # visible before this selected publisher observed it.
                    # Exact readback makes the LOCAL->PENDING transition safe
                    # without issuing any remote replay.
                    inbox.mark_receipt_pending(receipt, timestamp=timestamp())
                if not inbox.reconcile_receipt(receipt, observed, acknowledgement,
                                               timestamp=timestamp()):
                    report['held'].append({'company_id': company_id, 'reason': 'receipt_not_confirmed'})
                    continue
                final = plan.get('final', {})
                # State.cycle returns a decoded snapshot, but reload and copy
                # it here so a failed save cannot leak this company's final
                # checkpoint into a later successful company's save.
                finalized = state.cycle(cycle_id)
                if finalized is None or company_id not in finalized.get('companies', {}):
                    raise RuntimeError('state_cycle_or_company_missing_before_finalization')
                finalized = copy.deepcopy(finalized)
                finalized['companies'][company_id].update(final)
                state.save_cycle(finalized)
                if final.get('stage') in {'complete', 'partial'}:
                    inbox.acknowledge(cycle_id, company_id)
                else:
                    inbox.block(cycle_id, company_id)
                report['confirmed'].append(company_id)
                continue
            continue
        except UncertainWriteError:
            report['held'].append({'company_id': company_id, 'reason': 'uncertain_write'})
        except ValueError as exc:
            report['held'].append({'company_id': company_id, 'reason': str(exc) or 'ValueError'})
        except Exception as exc:
            # Timeout, expected-value conflict, or unavailable readback all
            # retain the exact frozen state for a later explicit reconciliation.
            report['held'].append({'company_id': company_id, 'reason': type(exc).__name__})
    return report
