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


def _checkpoint_matches_final(checkpoint, plan):
    final = plan.get('final') if isinstance(plan, Mapping) else None
    projection = plan.get('final_projection') if isinstance(plan, Mapping) else None
    if (not isinstance(final, Mapping) or not isinstance(projection, Mapping)
            or projection != {key: final[key] for key in sorted(final)}
            or plan.get('final_projection_digest') != _digest(projection)):
        return False
    return {key: checkpoint.get(key) for key in projection} == dict(projection)


def publish_exact_cycle(inbox, cycle_id, remote, *, company_ids, retry_blocked=False, state,
                        company_guard=None):
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
        if cursor != len(operations):
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
