"""Freeze selected durable inventories without fetching or publishing.

This recovery boundary deliberately stops before the selected-plan publisher.
It consumes a saved inventory for an explicit company in one unfinished cycle,
creates immutable keyed operations in :class:`InventoryInbox`, and records a
recoverable ``inventory`` checkpoint.  It never starts ``LocalPipeline``,
constructs a Sheets synchronizer, reads Google, or commits the local cache.

The caller supplies the narrow current-remote Company guard.  Keeping that
read outside this module makes the planner testable and prevents an accidental
fallback to a broad workbook pull.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Callable, Iterable, Mapping

from .batching import PendingState, PlanningRepository
from .core import job_key, material_hash
from .engine import now
from .exact_cycle_receipt import (
    ORDINARY_EVENT_PLAN_BINDING, REPAIR_RETRY_PLAN_BINDING, derive_receipt, has_ordinary_event_scope,
    has_repair_retry_scope, ordinary_event_receipt_binding, require_current_repair_retry,
    require_unambiguous_repair_retry_receipt,
)


ALLOWED_INVENTORY_STATUSES = frozenset({'complete', 'partial'})
CONTROL_EVIDENCE_VERSION = 1
PUBLICATION_PROJECTION_VERSION = 1
EXACT_PLAN_VERSION = 2


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
    ).encode('utf-8')).hexdigest()


def _receipt(cycle, company_id, payload, plan, stamp):
    return derive_receipt(cycle, company_id, payload, plan, stamp)


def _checkpoint_item(item, payload):
    """Keep the payload durable in the inbox while preventing a refetch."""
    updated = copy.deepcopy(item)
    updated.update({key: value for key, value in payload.items() if key != 'jobs'})
    updated.update(stage='inventory', durable_inventory=True, locally_processed=True)
    updated.pop('jobs', None)
    return updated


def _control_evidence(value, company_id, requested_url):
    """Require stable, bounded current-control evidence from the caller."""
    if not isinstance(value, Mapping):
        raise ValueError('company_guard_must_return_control_evidence')
    evidence = {str(key): value[key] for key in sorted(value)}
    required = {'company_id', 'requested_url', 'official_careers_url',
                'company_status', 'claimed_by', 'claim_token'}
    if set(evidence) != required or any(not isinstance(value, str) for value in evidence.values()):
        raise ValueError('company_guard_control_evidence_shape_invalid')
    if (evidence['company_id'].strip() != company_id
            or evidence['requested_url'].strip() != requested_url
            or evidence['official_careers_url'].strip() != requested_url
            or evidence['company_status'].strip().casefold() != 'active'
            or evidence['claimed_by'].strip() or evidence['claim_token'].strip()):
        raise ValueError('company_guard_control_evidence_identity_mismatch')
    return evidence, _digest(evidence)


def _plan_digest(plan):
    """Historical full-profile plan seal (legacy cursor semantics)."""
    return _digest({key: plan.get(key) for key in (
        'operations', 'final', 'requested_url', 'control_evidence',
        'control_evidence_version', 'control_evidence_digest',
        'inventory_payload_digest', 'plan_records_digest',
        'final_projection', 'final_projection_digest',
        'publication_projection_version', 'publication_profile',
        'publication_schema_digest', 'local_operations_digest',
        'local_finalization_digest', 'remote_operations_digest',
        'remote_projection_digest',
    )})


def _exact_plan_digest(plan):
    """Seal every v2 field except the seal itself."""
    return _digest({key: copy.deepcopy(value) for key, value in plan.items()
                    if key != 'plan_digest'})


def _publication_schema(repository):
    """Resolve the configured Google projection without guessing a profile.

    A repository without metadata support is the historical full-Sheets
    repository.  A repository that does expose ``sheets_profile`` must either
    name a supported profile or explicitly leave it empty for the full schema.
    """
    from .sheet_profile import profile_schemas
    schemas = getattr(repository, 'schemas', None)
    if not isinstance(schemas, Mapping):
        raise ValueError('local_repository_schema_missing')
    getter = getattr(repository, 'get_meta', None)
    profile = getter('sheets_profile') if callable(getter) else None
    publication = profile_schemas(profile)
    if publication is None:
        publication = schemas
        profile = 'full'
    normalized = {}
    for tab, headers in publication.items():
        if tab not in schemas:
            raise ValueError('publication_schema_unknown_tab')
        if not isinstance(headers, (list, tuple)) or not headers:
            raise ValueError('publication_schema_invalid')
        if len(headers) != len(set(headers)) or set(headers) - set(schemas[tab]):
            raise ValueError('publication_schema_not_local_subset')
        normalized[str(tab)] = tuple(str(header) for header in headers)
    if not normalized:
        raise ValueError('publication_schema_empty')
    return str(profile), normalized


def _project_operations(operations, publication):
    """Return only remote-publishable fields, preserving every safe guard."""
    if not isinstance(operations, list) or not operations:
        raise ValueError('local_plan_operations_empty')
    projected = []
    allowed_keys = {'tab', 'identity', 'values', 'on_insert', 'append_if_missing',
                    'append_notes', 'expected'}
    mapping_keys = ('identity', 'values', 'on_insert', 'append_notes', 'expected')
    for operation in operations:
        if not isinstance(operation, Mapping) or set(operation) - allowed_keys:
            raise ValueError('local_plan_operation_shape_invalid')
        tab = operation.get('tab')
        if not isinstance(tab, str) or not tab:
            raise ValueError('local_plan_operation_tab_invalid')
        # A known local-only tab is deliberately finalized in SQLite but is
        # not a Google operation under compact-v1.
        if tab not in publication:
            from .repository import SCHEMAS
            if tab not in SCHEMAS:
                raise ValueError('local_plan_operation_unknown_tab')
            continue
        headers = set(publication[tab])
        result = {'tab': tab}
        for key in mapping_keys:
            values = operation.get(key, {})
            if not isinstance(values, Mapping):
                raise ValueError('local_plan_operation_mapping_invalid')
            retained = {str(header): copy.deepcopy(value) for header, value in values.items()
                        if header in headers}
            if key == 'identity':
                if not values or len(retained) != len(values):
                    raise ValueError('publication_projection_would_remove_identity')
                result[key] = retained
            elif retained:
                result[key] = retained
        if operation.get('append_if_missing'):
            result['append_if_missing'] = True
        mutations = any(result.get(key) for key in ('values', 'on_insert', 'append_notes'))
        if not mutations:
            raise ValueError('publication_projection_operation_empty')
        projected.append(result)
    if not projected:
        raise ValueError('publication_projection_operations_empty')
    return projected


def _canonical_remote_projection(operations):
    return [{
        'tab': operation['tab'],
        'identity': copy.deepcopy(operation['identity']),
        'values': copy.deepcopy(operation.get('values', {})),
        'append_if_missing': bool(operation.get('append_if_missing')),
        'on_insert': copy.deepcopy(operation.get('on_insert', {})),
        'expected': copy.deepcopy(operation.get('expected', {})),
        'append_notes': copy.deepcopy(operation.get('append_notes', {})),
    } for operation in operations]


def _projection_by_target(operations):
    """Compare a frozen projection by exact record, independent of stream order."""
    if not isinstance(operations, list) or not operations:
        raise ValueError('remote_projection_operations_invalid')
    keyed = {}
    for operation in operations:
        key = _target_label(operation)
        if key in keyed:
            raise ValueError('remote_projection_duplicate_target')
        keyed[key] = copy.deepcopy(operation)
    return keyed


def _target_label(operation):
    """Return the stable final identity of one frozen operation."""
    identity = operation.get('identity')
    if not isinstance(identity, Mapping) or not identity:
        raise ValueError('local_plan_operation_identity_invalid')
    final = {str(key): copy.deepcopy(value) for key, value in identity.items()}
    for values in (operation.get('on_insert', {}), operation.get('values', {})):
        if not isinstance(values, Mapping):
            raise ValueError('local_plan_operation_mapping_invalid')
        for key in tuple(final):
            if key in values:
                final[key] = copy.deepcopy(values[key])
    return str(operation.get('tab') or ''), tuple(sorted(final.items()))


def _require_independent_targets(operations):
    """Reject plans whose chunk boundaries could split one atomic record."""
    seen = set()
    for operation in operations:
        label = _target_label(operation)
        if label in seen:
            raise ValueError('duplicate_local_operation_target_requires_atomic_group')
        seen.add(label)


def _normalize_salary_fallback(operations, originals):
    """Preserve a plausible user estimate when extraction is actually empty.

    The local operation retains an expected-value guard but no salary
    mutation.  Consequently compact projection cannot overwrite the estimate,
    while a post-freeze user edit still makes the authoritative commit hold.
    """
    from .sheets_sync import _missing_extracted_salary, _plausible_salary_estimate
    for operation in operations:
        if operation.get('tab') not in {'Job History', 'Opportunities'}:
            continue
        values = operation.get('values', {})
        inserts = operation.get('on_insert', {})
        candidates = []
        for mapping in (values, inserts):
            if isinstance(mapping, Mapping) and 'Salary / Range' in mapping:
                candidates.append(mapping['Salary / Range'])
        if not candidates or not all(_missing_extracted_salary(value) for value in candidates):
            continue
        prior_rows = []
        for (tab, _number), row in originals.items():
            if tab != operation['tab']:
                continue
            if all(str(row.get(key, '')) == str(value)
                   for key, value in operation.get('identity', {}).items()):
                prior_rows.append(row)
        if len(prior_rows) > 1:
            raise ValueError('salary_fallback_identity_ambiguous')
        prior = prior_rows[0].get('Salary / Range', '') if prior_rows else ''
        if prior_rows and _plausible_salary_estimate(prior):
            operation.setdefault('expected', {})['Salary / Range'] = prior
        for mapping in (values, inserts):
            if isinstance(mapping, dict):
                mapping.pop('Salary / Range', None)


def _remove_noop_values(operations, originals):
    """Make a compact frozen projection equal the actual dirty-cell result."""
    from .repository import _equivalent

    retained = []
    for operation in operations:
        identity = operation.get('identity', {})
        prior_rows = [row for (tab, _number), row in originals.items()
                      if tab == operation.get('tab') and all(
                          _equivalent(key, row.get(key, ''), value)
                          for key, value in identity.items())]
        if len(prior_rows) == 1:
            prior = prior_rows[0]
            values = operation.get('values', {})
            if isinstance(values, dict):
                for header in tuple(values):
                    if _equivalent(header, prior.get(header, ''), values[header]):
                        values.pop(header)
            expected = operation.setdefault('expected', {})
            for header in set(values) | set(operation.get('append_notes', {})):
                expected.setdefault(header, copy.deepcopy(prior.get(header, '')))
            if not operation.get('append_if_missing'):
                operation.pop('on_insert', None)
        mutations = any(operation.get(key) for key in (
            'values', 'on_insert', 'append_notes'))
        if operation.get('append_if_missing') or mutations:
            retained.append(operation)
    operations[:] = retained


def _seal_plan(plan, payload, repository):
    from .publication_receipts import record_fingerprints
    local_operations = copy.deepcopy(plan['operations'])
    profile, publication = _publication_schema(repository)
    plan['operations'] = _project_operations(local_operations, publication)
    plan['publication_projection_version'] = PUBLICATION_PROJECTION_VERSION
    plan['publication_profile'] = profile
    schema_evidence = {tab: list(headers) for tab, headers in sorted(publication.items())}
    plan['publication_schema_digest'] = _digest(schema_evidence)
    plan['local_operations_digest'] = _digest(local_operations)
    plan['local_finalization_digest'] = _digest({
        'operations': local_operations,
        'final': plan['final'],
    })
    plan['remote_operations_digest'] = _digest(plan['operations'])
    plan['remote_projection_digest'] = _digest({
        'profile': profile,
        'schema_digest': plan['publication_schema_digest'],
        'operations': plan['operations'],
    })
    plan['inventory_payload_digest'] = _digest(payload)
    plan['plan_records_digest'] = _digest(record_fingerprints(plan['operations']))
    plan['final_projection'] = {key: plan['final'][key] for key in sorted(plan['final'])}
    plan['final_projection_digest'] = _digest(plan['final_projection'])
    plan['plan_digest'] = _plan_digest(plan)
    return plan


def _seal_exact_plan_v2(plan, payload, repository, cycle_id, company_id):
    """Seal both full local work and its immutable compact projection."""
    from .publication_receipts import record_fingerprints

    local_operations = copy.deepcopy(plan['operations'])
    _require_independent_targets(local_operations)
    profile, publication = _publication_schema(repository)
    if profile == 'full':
        raise ValueError('exact_plan_v2_requires_projected_profile')
    remote_projection = _project_operations(local_operations, publication)
    # Exact Sheets planning emits a total, canonical operation shape.  Freeze
    # that same shape so equality is structural rather than dependent on
    # whether an empty optional mapping was omitted during projection.
    remote_projection = _canonical_remote_projection(remote_projection)
    schema_evidence = {tab: list(headers) for tab, headers in sorted(publication.items())}
    local_records = record_fingerprints(local_operations)
    remote_records = record_fingerprints(remote_projection)
    sealed = {
        'exact_plan_version': 2,
        'cycle_id': cycle_id,
        'company_id': company_id,
        'requested_url': plan['requested_url'],
        'control_evidence': copy.deepcopy(plan['control_evidence']),
        'control_evidence_version': plan['control_evidence_version'],
        'control_evidence_digest': plan['control_evidence_digest'],
        'inventory_payload_digest': _digest(payload),
        'publication_profile': profile,
        'publication_schema': schema_evidence,
        'publication_schema_digest': _digest(schema_evidence),
        'local_operations': local_operations,
        'local_operations_digest': _digest(local_operations),
        'local_expected_records': local_records,
        'local_expected_records_digest': _digest(local_records),
        'remote_projection': remote_projection,
        'remote_projection_digest': _digest(remote_projection),
        'remote_records': remote_records,
        'remote_records_digest': _digest(remote_records),
        'local_finalization': copy.deepcopy(plan['final']),
        'local_finalization_digest': _digest({
            'operations': local_operations, 'final': plan['final'],
        }),
        'final': copy.deepcopy(plan['final']),
    }
    sealed['final_projection'] = {
        key: sealed['final'][key] for key in sorted(sealed['final'])}
    sealed['final_projection_digest'] = _digest(sealed['final_projection'])
    if plan.get('retained_membership_only') is True:
        sealed['retained_membership_only'] = True
    sealed['plan_digest'] = _exact_plan_digest(sealed)
    return sealed


def _validate_existing_exact_plan_v2(plan, payload, repository, cycle_id,
                                     company_id, evidence_digest):
    from .publication_receipts import record_fingerprints
    if (not isinstance(plan, Mapping) or plan.get('exact_plan_version') != 2
            or plan.get('cycle_id') != cycle_id
            or plan.get('company_id') != company_id
            or plan.get('requested_url') != payload['requested_url']
            or plan.get('inventory_payload_digest') != _digest(payload)
            or plan.get('control_evidence_digest') != evidence_digest
            or plan.get('plan_digest') != _exact_plan_digest(plan)):
        raise ValueError('existing_exact_plan_v2_invalid')
    profile, publication = _publication_schema(repository)
    schema = {tab: list(headers) for tab, headers in sorted(publication.items())}
    local_operations = plan.get('local_operations')
    remote_projection = plan.get('remote_projection')
    if (profile == 'full' or plan.get('publication_profile') != profile
            or plan.get('publication_schema') != schema
            or plan.get('publication_schema_digest') != _digest(schema)
            or not isinstance(local_operations, list) or not local_operations
            or plan.get('local_operations_digest') != _digest(local_operations)
            or not isinstance(remote_projection, list) or not remote_projection
            or plan.get('remote_projection_digest') != _digest(remote_projection)
            or _projection_by_target(_canonical_remote_projection(
                _project_operations(local_operations, publication)))
            != _projection_by_target(remote_projection)
            or plan.get('local_expected_records') != record_fingerprints(
                local_operations,
                include_guard_only=plan.get('record_fingerprint_version', 1) == 2)
            or plan.get('local_expected_records_digest') != _digest(plan.get('local_expected_records'))
            or plan.get('remote_records') != record_fingerprints(
                remote_projection,
                include_guard_only=plan.get('record_fingerprint_version', 1) == 2)
            or plan.get('remote_records_digest') != _digest(plan.get('remote_records'))
            or plan.get('local_finalization_digest') != _digest({
                'operations': local_operations, 'final': plan.get('final'),
            })):
        raise ValueError('existing_exact_plan_v2_projection_invalid')
    _require_independent_targets(local_operations)
    return plan


def _validate_existing_plan(inbox, cycle, company_id, payload, plan, evidence_digest, stamp,
                            repository, cursor):
    """Validate an interrupted plan/receipt pair before repairing State.

    Only ``LOCAL_COMMITTED`` is accepted: ``SYNC_PENDING`` or confirmed states
    belong to the publisher/reconciliation boundary, never this planner.
    """
    from .publication_receipts import LOCAL_COMMITTED, record_fingerprints
    if (not isinstance(plan, Mapping)
            or plan.get('publication_projection_version') != PUBLICATION_PROJECTION_VERSION):
        if isinstance(cursor, int) and cursor > 0:
            raise ValueError('existing_frozen_plan_projection_incompatible_nonzero_cursor')
        raise ValueError('existing_frozen_plan_projection_incompatible')
    if (not isinstance(plan, dict) or not isinstance(plan.get('operations'), list)
            or not isinstance(plan.get('final'), dict)
            or plan.get('requested_url') != payload['requested_url']
            or plan.get('control_evidence_version') != CONTROL_EVIDENCE_VERSION
            or plan.get('control_evidence_digest') != _digest(plan.get('control_evidence', {}))
            or plan.get('inventory_payload_digest') != _digest(payload)
            or plan.get('plan_records_digest') != _digest(record_fingerprints(plan['operations']))
            or plan.get('plan_digest') != _plan_digest(plan)):
        raise ValueError('existing_frozen_plan_invalid')
    profile, publication = _publication_schema(repository)
    schema_digest = _digest({tab: list(headers) for tab, headers in sorted(publication.items())})
    if (plan.get('publication_profile') != profile
            or plan.get('publication_schema_digest') != schema_digest
            or plan.get('remote_operations_digest') != _digest(plan['operations'])
            or plan.get('remote_projection_digest') != _digest({
                'profile': profile, 'schema_digest': schema_digest,
                'operations': plan['operations'],
            })
            or _project_operations(plan['operations'], publication) != plan['operations']
            or not isinstance(plan.get('local_operations_digest'), str)
            or not plan['local_operations_digest']
            or not isinstance(plan.get('local_finalization_digest'), str)
            or not plan['local_finalization_digest']):
        raise ValueError('existing_frozen_plan_projection_invalid')
    if plan['control_evidence_digest'] != evidence_digest:
        raise ValueError('company_control_evidence_changed')
    expected = _receipt(cycle, company_id, payload, plan, stamp)
    found = inbox.find_receipt(company_id, expected['records'])
    actual = inbox.receipt(expected)
    if found is None:
        raise ValueError('existing_frozen_plan_receipt_missing')
    if actual is None:
        raise ValueError('existing_frozen_plan_receipt_mismatch')
    if (found['binding'] != expected['binding'] or found['records'] != expected['records']
            or found['schedule'] != expected['schedule']
            or actual['binding'] != expected['binding'] or actual['records'] != expected['records']
            or actual['schedule'] != expected['schedule']):
        raise ValueError('existing_frozen_plan_receipt_mismatch')
    if actual['state'] != LOCAL_COMMITTED:
        raise ValueError('existing_frozen_plan_receipt_state_not_recoverable')


def _normalize_history_guards(planner, originals):
    """Carry LocalPipeline's manual-choice/legacy-identity protections.

    The frozen plan must guard the value a user had when planning began, not
    merely the simulated value after local staging.
    """
    for operation in planner.operations:
        if operation['tab'] != 'Job History':
            continue
        expected = operation.get('expected', {})
        for number, row in planner.indexes['Job History'].matches(operation['identity']):
            prior = originals.get(('Job History', number), {})
            # A compact planning row materializes omitted protected fields as
            # blanks.  Once targeted hydration found a real row, that blank is
            # never a trustworthy manual-choice guard.
            manual = (prior.get('Added to Opportunities?', '') if ('Job History', number) in originals
                      else expected.get('Added to Opportunities?', ''))
            # Keep every source/review/decision guard emitted by Engine.  The
            # retained planner has no ordinary lifecycle checkpoint to repair
            # a lost race later, so narrowing this set would silently weaken
            # the normal manual-choice and managed-review protections.
            operation['expected'] = {
                field: prior.get(field, value)
                for field, value in expected.items()
            }
            operation['expected']['Added to Opportunities?'] = manual
            if 'Job Key' in expected:
                operation['expected']['Job Key'] = expected['Job Key']


def _hydrate_authoritative_operation_scope(planner, operation, originals):
    """Replace only an operation's partial cache rows with full local values.

    ``PlanningRepository`` intentionally begins with compact rows.  That is
    sufficient to choose an identity, but it is not sufficient to decide a
    no-op or preserve a manual/salary field.  SQLite's targeted ``matches``
    gives the full record for precisely that identity without enumerating a
    whole tab.  The replacement happens before simulated commit so later
    operations retain the same full user-owned values.
    """
    from .repository import _equivalent

    tab, identity = operation.get('tab'), operation.get('identity')
    if tab not in planner.rows or not isinstance(identity, Mapping) or not identity:
        raise ValueError('planner_operation_scope_invalid')
    cached = planner.indexes[tab].matches(identity)
    matcher = getattr(planner.base, 'matches', None)
    if not callable(matcher):
        # In-memory fixtures use full rows from PlanningRepository's fallback
        # loader.  A compact cache without targeted lookup must fail closed.
        if hasattr(planner.base, 'read_cached_columns'):
            raise ValueError('authoritative_operation_scope_unavailable')
        for number, row in cached:
            originals.setdefault((tab, number), copy.deepcopy(row))
        return
    authoritative = matcher(tab, identity)
    if len(authoritative) != len(cached):
        raise ValueError('authoritative_operation_scope_changed')
    pairs = list(zip(cached, authoritative))
    if len(cached) > 1:
        # Local Opportunities may deliberately fan one Company/URL operation
        # out by stable Opportunity ID.  Do not pair two otherwise-identical
        # compact rows by incidental repository order.
        cached_ids = {str(row.get('Opportunity ID') or ''): (number, row)
                      for number, row in cached}
        full_ids = {str(row.get('Opportunity ID') or ''): row for _, row in authoritative}
        if (tab != 'Opportunities' or '' in cached_ids or '' in full_ids
                or len(cached_ids) != len(cached) or set(cached_ids) != set(full_ids)):
            raise ValueError('authoritative_operation_scope_ambiguous')
        pairs = [(cached_ids[key], (key, full_ids[key])) for key in sorted(cached_ids)]
    compact_fields = {
        'Job History': {
            'Company', 'Job Key', 'Official Job URL', 'Requisition ID', 'Job Title',
            'Current Snapshot', 'Added to Opportunities?', 'Review Status', 'Review Started At',
            'Decision', 'Reconsideration Count', 'Description Hash', 'Source Hash',
            'Rejection Reason', 'Review Notes', 'Job Status', 'Consecutive Missing Scans', 'Prior Job Key',
        },
        'Job Evidence': {'Job Key', 'Source Hash'},
        'Opportunities': {'Company', 'Job URL'},
        'Scan Cycles': {'Cycle ID'},
    }
    # A full snapshot already observed every field; a compact snapshot observed
    # only PlanningRepository's selected columns.  In both cases a visible
    # change is a stale planning guard, not a missing field to hydrate.
    # Companies is deliberately loaded by full ``read('Companies')`` even in
    # a compact planning repository.  It is therefore never an omitted-field
    # hydration target.
    visible = (set(planner.schemas[tab]) if tab == 'Companies' or not hasattr(planner.base, 'read_cached_columns')
               else compact_fields.get(tab, set()))
    if tab == 'Opportunities' and 'Opportunity ID' in planner.schemas[tab]:
        visible.add('Opportunity ID')
    for (number, partial), (_row_id, full) in pairs:
        if not isinstance(full, Mapping) or not all(
                _equivalent(header, full.get(header, ''), value)
                for header, value in identity.items()):
            raise ValueError('authoritative_operation_scope_identity_changed')
        # The compact identity must still refer to the exact authoritative
        # record; a mismatch is not an invitation to guess a replacement.
        if not all(_equivalent(header, partial.get(header, ''), value)
                   for header, value in identity.items()):
            raise ValueError('planning_operation_scope_identity_changed')
        if any(not _equivalent(header, partial.get(header, ''), full.get(header, ''))
               for header in visible):
            raise ValueError('authoritative_operation_scope_visible_drift')
        expected = operation.get('expected')
        if isinstance(expected, dict):
            for header, value in tuple(expected.items()):
                # Replace only a guard that exactly reflects the compact cache
                # placeholder.  A deliberately different guard remains a
                # guard and is never rewritten by hydration.
                if header not in visible and _equivalent(header, value, partial.get(header, '')):
                    expected[header] = copy.deepcopy(full.get(header, ''))
        hydrated = copy.deepcopy(dict(full))
        planner.rows[tab][number] = hydrated
        # ``IdentityIndex.put`` updates only columns already materialized by
        # prior exact matches.  It avoids rebuilding every column/index for
        # the user's whole Jobs cache after each selected operation.
        planner.indexes[tab].put(number, hydrated)
        originals.setdefault((tab, number), copy.deepcopy(hydrated))


def _company_from(planner, company_id):
    matches = [row for row in planner.read('Companies')
               if str(row.get('Company ID') or '').strip() == company_id]
    if len(matches) != 1:
        raise ValueError('local_company_missing_or_ambiguous')
    company = matches[0]
    if str(company.get('Company Status', '')).strip().casefold() in {'pause', 'paused', 'remove'}:
        raise ValueError('local_company_paused')
    if company.get('Claimed By') or company.get('Claim Token'):
        raise ValueError('local_company_claimed')
    if (str(company.get('Automatic Retry?', '')).strip().casefold() == 'no'
            and str(company.get('Scan State', '')).strip() == 'Blocked / Manual Review'):
        raise ValueError('local_company_manual_hold')
    return company


def _validate_payload(payload):
    if not isinstance(payload, dict):
        raise ValueError('invalid_inventory_payload')
    if payload.get('inventory_status') not in ALLOWED_INVENTORY_STATUSES:
        raise ValueError('inventory_status_not_plannable')
    if not isinstance(payload.get('jobs'), list):
        raise ValueError('inventory_jobs_not_a_list')
    if not str(payload.get('requested_url') or '').strip():
        raise ValueError('inventory_requested_url_missing')


def _validate_cycle(engine, cycle_id):
    if not isinstance(cycle_id, str) or not cycle_id.strip():
        raise ValueError('exact_cycle_id_required')
    cycle_id = cycle_id.strip()
    cycle = engine.state.cycle(cycle_id)
    if cycle is None:
        raise ValueError('exact_cycle_missing')
    if cycle.get('id') != cycle_id:
        raise ValueError('exact_cycle_identity_mismatch')
    if cycle.get('status') in {'Complete', 'Complete with exceptions'}:
        raise ValueError('exact_cycle_not_unfinished')
    from .scan_request import superseded_cycle_ids
    if cycle_id in superseded_cycle_ids(engine.state.cycles()):
        raise ValueError('exact_cycle_superseded')
    return cycle_id, cycle


def _check_membership_posting_operation(operation, planner, company, posting):
    """Return the current exact row, if any, for a permitted positive sighting."""
    if not isinstance(operation, dict):
        raise ValueError('retained_membership_only_posting_operation_invalid')
    key = job_key(company['Company ID'], posting['ats'], posting.get('posting_id', ''), posting['url'])
    source_hash = material_hash(posting)
    tab = operation.get('tab')
    values = operation.get('values')
    expected = operation.get('expected', {})
    if (tab not in {'Job History', 'Job Evidence'}
            or set(operation) - {'tab', 'identity', 'values', 'expected', 'append_if_missing', 'append_notes'}
            or operation.get('append_if_missing') is not True or operation.get('append_notes', {}) != {}
            or not isinstance(values, Mapping) or not isinstance(expected, dict)
            or set(values) - set(planner.schemas[tab])
            or set(expected) - set(planner.schemas[tab])
            or values.get('Company') != company['Company']
            or values.get('Job Title') != posting['title']
            or values.get('Official Job URL') != posting['url']):
        raise ValueError('retained_membership_only_posting_operation_invalid')

    identity = {'Job Key': key}
    if tab == 'Job History':
        if (values.get('Job Key') != key or values.get('Source Hash') != source_hash
                or values.get('Job Status') != 'Open and verified'
                or type(values.get('Consecutive Missing Scans')) is not int
                or values['Consecutive Missing Scans'] != 0):
            raise ValueError('retained_membership_only_history_not_positive_sighting')
    else:
        identity['Source Hash'] = source_hash
        if set(values) != {'Company', 'Job Title', 'Official Job URL', 'Captured At', 'Job Description'}:
            raise ValueError('retained_membership_only_evidence_operation_invalid')
    if operation.get('identity') != identity:
        raise ValueError('retained_membership_only_posting_identity_changed')

    # The compact planning cache omits the owner on Evidence and the salary
    # on History. Check the exact authoritative row before simulating either.
    matches = planner.base.matches(tab, identity)
    if len(matches) > 1:
        raise ValueError('retained_membership_only_posting_identity_ambiguous')
    existing = matches[0][1] if matches else None
    if existing is not None:
        if existing.get('Company') != company['Company']:
            raise ValueError('retained_membership_only_posting_owner_changed')
        if str(existing.get('Job Status', '')).strip().casefold() == 'closed':
            raise ValueError('retained_membership_only_closed_history_protected')
    operation.setdefault('expected', {})['Company'] = existing['Company'] if existing is not None else ''
    return existing


_ORDINARY_COMPANY_SOURCE_FIELDS = frozenset({
    'Company ID', 'Company', 'Company Status', 'Official Careers URL', 'ATS / Source',
})


def _ordinary_company_operation(operation, company):
    """Omit equivalent source values and reject changes to the admitted Company."""
    from .repository import _equivalent

    if (operation.get('identity') != {'Company ID': company['Company ID']}
            or operation.get('append_if_missing')
            or _ORDINARY_COMPANY_SOURCE_FIELDS.intersection(operation.get('append_notes', {}))):
        raise ValueError('Ordinary Company-event finisher changed protected Company scope.')
    operation = copy.deepcopy(operation)
    for stream in ('values', 'on_insert'):
        values = operation.get(stream, {})
        for field in _ORDINARY_COMPANY_SOURCE_FIELDS.intersection(values):
            prior, proposed = company.get(field, ''), values[field]
            if field in {'Company Status', 'ATS / Source'}:
                same = str(prior).strip().casefold() == str(proposed).strip().casefold()
            elif field == 'Official Careers URL':
                same = _equivalent(field, prior, proposed)
            else:
                same = prior == proposed
            if not same:
                raise ValueError('Ordinary Company-event finisher changed protected Company source field: ' + field)
            del values[field]
    return operation


def _require_ordinary_event_source_unchanged(plan, company_id):
    """Check the already-sealed streams without reinterpreting stored values."""
    for stream in ('local_operations', 'remote_projection'):
        operations = plan.get(stream)
        if not isinstance(operations, list) or not operations:
            raise ValueError('Ordinary Company-event receipt requires both sealed operation streams.')
        for operation in operations:
            if operation.get('tab') == 'Companies' and (
                    operation.get('identity') != {'Company ID': company_id}
                    or operation.get('append_if_missing')
                    or any(_ORDINARY_COMPANY_SOURCE_FIELDS.intersection(operation.get(field, {}))
                           for field in ('values', 'on_insert', 'append_notes'))):
                raise ValueError('Ordinary Company-event sealed plan changes protected Company scope or source.')


def _freeze(engine, planner, cycle, company_id, payload, *, drop_noops=False, membership_only=False,
            protect_ordinary_source=False):
    """Compute a frozen plan entirely in memory, with no repository commit."""
    company = _company_from(planner, company_id)
    engine._verify_same_board({'Official Careers URL': payload['requested_url']}, company)
    local_cycle = copy.deepcopy(cycle)
    local_item = local_cycle['companies'][company_id]
    local_item.update(payload, stage='inventory', staging_complete=True, next_job_index=0)

    before_rows = copy.deepcopy(planner.rows)
    originals = {}
    commit = planner.commit
    current_posting = None

    def track(operations):
        if membership_only and current_posting is None:
            # Only the known Company-finisher operation may be withheld here.
            # Run the finisher so its session evidence remains unchanged.
            if (len(operations) != 1 or set(operations[0]) != {'tab', 'identity', 'values'}
                    or operations[0]['tab'] != 'Companies'
                    or operations[0]['identity'] != {'Company ID': company_id}
                    or not isinstance(operations[0]['values'], Mapping)):
                raise ValueError('retained_membership_only_company_finalization_invalid')
            return {'staged': 0}
        if protect_ordinary_source:
            operations = [
                _ordinary_company_operation(operation, company) if operation.get('tab') == 'Companies' else operation
                for operation in operations
            ]
        for operation in operations:
            _hydrate_authoritative_operation_scope(planner, operation, originals)
            existing = (_check_membership_posting_operation(operation, planner, company, current_posting)
                        if membership_only else None)
            tab = operation['tab']
            for number, row in planner.indexes[tab].matches(operation['identity']):
                # The narrow planning cache omits values that commit guards
                # need, including Location and the estimated salary.
                original = existing if existing is not None else row
                originals.setdefault((tab, number), copy.deepcopy(original))
        return commit(operations)
    original_repo, original_state, original_notices = engine.repo, engine.state, engine._notices
    engine.repo, engine.state, engine._notices = planner, PendingState(original_state), []
    planner.commit = track
    planner.begin()
    try:
        for posting in payload['jobs']:
            if not isinstance(posting, dict):
                raise ValueError('inventory_job_not_an_object')
            current_posting = posting
            engine._stage_posting(local_cycle, company, posting)
        current_posting = None
        if not membership_only and payload['inventory_status'] == 'complete':
            engine._reconcile_absences(local_cycle, company, payload['jobs'])
        engine._finish_company(local_cycle, company)
        _normalize_history_guards(planner, originals)
        _normalize_salary_fallback(planner.operations, originals)
        if drop_noops:
            _remove_noop_values(planner.operations, originals)
        return {
            'operations': copy.deepcopy(planner.operations),
            'final': {key: value for key, value in local_item.items() if key != 'jobs'},
            'requested_url': payload['requested_url'],
        }
    except BaseException:
        # Planning is in-memory until InventoryInbox.save_plan.  A malformed
        # selected payload must not poison the shared planning snapshot used by
        # another explicitly requested company.
        planner.rows = before_rows
        planner._reindex()
        raise
    finally:
        engine.repo, engine.state, engine._notices = original_repo, original_state, original_notices
        planner.commit = commit


def freeze_retained_exact_plan(engine, cycle_id, company_id, payload,
                               control_evidence, *, started_at=None, membership_only=False):
    """Build one v2 plan from a frozen retained inventory, without State/inbox.

    The caller owns the retained reservation and supplies the exact composite
    Company controls.  This function performs only in-memory business-rule
    planning against the local repository and never saves an ordinary cycle,
    inbox plan, receipt, or checkpoint. Set membership_only only after the
    operator admission proves the retained overlap is membership alone and
    the selected posting targets are independent of protected historical work.
    That mode omits all Company updates and absence reconciliation.
    """
    cycle_id = str(cycle_id or '').strip()
    company_id = str(company_id or '').strip()
    if not cycle_id or not company_id:
        raise ValueError('retained_exact_plan_identity_required')
    if type(membership_only) is not bool:
        raise ValueError('retained_exact_plan_membership_mode_invalid')
    if membership_only and getattr(engine.repo, 'is_local', False) is not True:
        raise ValueError('retained_membership_only_local_repository_required')
    _validate_payload(payload)
    evidence, evidence_digest = _control_evidence(
        control_evidence, company_id, payload['requested_url'])
    planner = PlanningRepository(engine.repo)
    company = _company_from(planner, company_id)
    cycle = {
        'id': cycle_id, 'status': 'In Progress',
        'started_at': started_at or now(), 'all': False,
        'companies': {company_id: {
            'company': company.get('Company', ''), 'stage': 'queued',
        }},
    }
    profile, _publication = _publication_schema(engine.repo)
    if profile == 'full':
        raise ValueError('retained_exact_plan_requires_projected_profile')
    plan = _freeze(
        engine, planner, cycle, company_id, copy.deepcopy(payload),
        drop_noops=True, membership_only=membership_only)
    # A retained session is not an ordinary State cycle. Preserve normal job
    # semantics and Company results, but do not claim ordinary cycle ownership.
    for operation in plan['operations']:
        if operation.get('tab') == 'Companies':
            for field in ('values', 'on_insert', 'expected'):
                operation.get(field, {}).pop('Active Cycle ID', None)
    plan['control_evidence'] = evidence
    plan['control_evidence_version'] = CONTROL_EVIDENCE_VERSION
    plan['control_evidence_digest'] = evidence_digest
    if membership_only:
        plan['retained_membership_only'] = True
    return _seal_exact_plan_v2(
        plan, payload, engine.repo, cycle_id, company_id)


def _require_current_ordinary_event(engine, cycle, company_id, binding):
    from .company_events import read_verified_ordinary_event_admission, source_revision

    engine.assert_runtime_binding(cycle['id'], sync_only=True)
    admission = read_verified_ordinary_event_admission(engine.repo, engine.state, cycle['id'])
    matches = engine.repo.matches('Companies', {'Company ID': company_id})
    company = matches[0][1] if len(matches) == 1 else {}
    if (admission['request_sha256'] != binding['request_sha256']
            or _digest(admission['receipt']) != binding['bridge_receipt_sha256']
            or not admission['source_current']
            or company.get('Active Cycle ID') != cycle['id']
            or company.get('Company') != cycle['companies'][company_id].get('company')
            or company.get('Claimed By') or company.get('Claim Token')
            or (str(company.get('Automatic Retry?', '')).strip().casefold() == 'no'
                and company.get('Scan State') == 'Blocked / Manual Review')
            or source_revision(company) != binding['source_revision']):
        raise ValueError('Ordinary Company-event local source or owner changed before planning.')


def _ordinary_event_plan_binding(engine, cycle, company_id, payload, context):
    from .sheet_profile import COMPACT_PROFILE

    binding = ordinary_event_receipt_binding(cycle, company_id, payload, context)
    root = context.state_directory
    if (Path(engine.state.path).resolve() != root / 'state.db'
            or Path(engine.repo.path).resolve() != root / 'jobs.sqlite3'
            or Path(engine.inbox.path).resolve() != root / 'inventories.sqlite3'
            or _publication_schema(engine.repo)[0] != COMPACT_PROFILE
            or engine.repo.spreadsheet_id != context.spreadsheet_id
            or engine.inbox.destination_id(engine.inbox.path) != context.spreadsheet_id):
        raise ValueError('Ordinary Company-event exact planning requires its verified compact workbook.')
    _require_current_ordinary_event(engine, cycle, company_id, binding)
    return binding


def freeze_exact_cycle_plans(engine, cycle_id: str, company_ids: Iterable[str], *,
                             company_guard: Callable[[str, str], None], max_companies: int = 5,
                             stamp: str | None = None, bind_selected_retry=False,
                             ordinary_event_context=None):
    """Freeze plans for explicit saved inventories, never fetching or publishing.

    ``company_guard`` must perform the narrow *current remote* Company control
    check for its exact ``(company_id, requested_url)`` pair, raising to hold
    the item.  The function intentionally has no remote repository argument.
    An ordinary event additionally requires its verified observation context.

    ``InventoryInbox.save_plan`` atomically saves the immutable plan and its
    ``LOCAL_COMMITTED`` receipt.  The State checkpoint is a separate SQLite
    database, so it follows second.  A crash between them leaves a deliberate
    plan/checkpoint split; a later identical request reconciles the checkpoint
    from the frozen plan without replacing it.
    """
    if engine.inbox is None:
        raise ValueError('exact_planner_requires_inventory_inbox')
    if not callable(company_guard):
        raise ValueError('exact_planner_requires_company_guard')
    if not isinstance(max_companies, int) or not 1 <= max_companies <= 25:
        raise ValueError('exact_planner_max_companies_must_be_1_to_25')
    requested = [str(cid).strip() for cid in company_ids]
    if not requested or any(not cid for cid in requested):
        raise ValueError('explicit_company_ids_required')
    if len(requested) != len(set(requested)):
        raise ValueError('duplicate_company_id_in_exact_plan_request')
    if len(requested) > max_companies:
        raise ValueError('exact_plan_request_exceeds_bound')
    cycle_id, cycle = _validate_cycle(engine, cycle_id)
    ordinary_event = has_ordinary_event_scope(cycle)
    repair_retry = has_repair_retry_scope(cycle)
    if ordinary_event_context is not None and not ordinary_event:
        raise ValueError('Ordinary Company-event plan context requires an admitted event cycle.')
    if ordinary_event and (len(requested) != 1 or bind_selected_retry):
        raise ValueError('Ordinary Company-event exact planning requires its sole Company and no alternate lineage.')
    if repair_retry and (len(requested) != 1 or ordinary_event or bind_selected_retry):
        raise ValueError('Repair retry exact planning requires its sole Company and no alternate lineage.')
    planner = PlanningRepository(engine.repo)
    stamp = stamp or now()
    report = {'cycle_id': cycle_id, 'planned': [], 'recovered': [], 'held': []}

    for company_id in requested:
        try:
            item = cycle.get('companies', {}).get(company_id)
            if not isinstance(item, dict):
                raise ValueError('company_not_in_exact_cycle')
            if item.get('stage') not in {'queued', 'inventory'}:
                raise ValueError('checkpoint_stage_not_recoverable')
            saved = engine.inbox.get(cycle_id, company_id)
            if saved is None:
                raise ValueError('durable_inventory_missing')
            payload, blocked = saved
            if blocked:
                raise ValueError('durable_inventory_blocked')
            _validate_payload(payload)
            # Reject local holds before spending a narrow remote-control read.
            local_company = _company_from(planner, company_id)
            engine._verify_same_board({'Official Careers URL': payload['requested_url']}, local_company)
            event_binding = None
            retry_binding = None
            existing = engine.inbox.plan(cycle_id, company_id)
            if repair_retry:
                engine.assert_runtime_binding(cycle_id, sync_only=True)
                retry_binding = require_current_repair_retry(
                    cycle, company_id, engine.repo, Path(engine.state.path).parent)
                if existing is not None and (
                        not isinstance(existing[0], Mapping)
                        or existing[0].get(REPAIR_RETRY_PLAN_BINDING) != retry_binding):
                    raise ValueError('Repair retry existing plan is missing its exact frozen receipt binding.')
            elif existing is not None and isinstance(existing[0], Mapping) and REPAIR_RETRY_PLAN_BINDING in existing[0]:
                raise ValueError('Repair retry frozen plan has no matching admitted cycle.')
            if ordinary_event:
                event_binding = _ordinary_event_plan_binding(
                    engine, cycle, company_id, payload, ordinary_event_context,
                )
                if existing is not None and (
                        not isinstance(existing[0], Mapping) or existing[0].get('exact_plan_version') != 2
                        or existing[0].get(ORDINARY_EVENT_PLAN_BINDING) != event_binding
                        or 'selected_retry_receipt_binding' in existing[0] or 'retained_membership_only' in existing[0]):
                    raise ValueError('Ordinary Company-event existing plan is outside its exact receipt authority.')
            elif existing is not None and isinstance(existing[0], Mapping) and ORDINARY_EVENT_PLAN_BINDING in existing[0]:
                raise ValueError('Ordinary Company-event frozen plan has no matching admitted cycle.')
            # This injected guard is deliberately before plan persistence.
            evidence, evidence_digest = _control_evidence(
                company_guard(company_id, payload['requested_url']), company_id, payload['requested_url'])
            if event_binding is not None:
                _require_current_ordinary_event(engine, cycle, company_id, event_binding)
            if retry_binding is not None and require_current_repair_retry(
                    engine.state.cycle(cycle_id), company_id, engine.repo, Path(engine.state.path).parent) != retry_binding:
                raise ValueError('Repair retry receipt binding changed during exact planning.')
            binding = None
            if bind_selected_retry:
                from .exact_cycle_receipt import selected_retry_receipt_binding
                binding = selected_retry_receipt_binding(cycle, company_id)
            if existing is None:
                profile, _publication = _publication_schema(engine.repo)
                if binding is not None and profile == 'full':
                    raise ValueError('selected_retry_publication_requires_compact_profile')
                if retry_binding is not None and profile == 'full':
                    raise ValueError('Repair retry publication requires the compact-v2 plan.')
                plan = _freeze(
                    engine, planner, cycle, company_id, payload,
                    drop_noops=profile != 'full',
                    protect_ordinary_source=event_binding is not None or retry_binding is not None)
                plan['control_evidence'] = evidence
                plan['control_evidence_version'] = CONTROL_EVIDENCE_VERSION
                plan['control_evidence_digest'] = evidence_digest
                if profile == 'full':
                    _seal_plan(plan, payload, engine.repo)
                    receipt = _receipt(cycle, company_id, payload, plan, stamp)
                    engine.inbox.save_plan(cycle_id, company_id, plan, receipt)
                else:
                    plan = _seal_exact_plan_v2(
                        plan, payload, engine.repo, cycle_id, company_id)
                    if binding is not None:
                        plan['selected_retry_receipt_binding'] = binding
                        plan['plan_digest'] = _exact_plan_digest(plan)
                    if event_binding is not None:
                        plan[ORDINARY_EVENT_PLAN_BINDING] = event_binding
                        plan['plan_digest'] = _exact_plan_digest(plan)
                        derive_receipt(cycle, company_id, payload, plan, stamp,
                                       ordinary_event_context=ordinary_event_context)
                    if retry_binding is not None:
                        plan[REPAIR_RETRY_PLAN_BINDING] = retry_binding
                        plan['plan_digest'] = _exact_plan_digest(plan)
                        receipt = derive_receipt(cycle, company_id, payload, plan, stamp)
                        require_unambiguous_repair_retry_receipt(engine.inbox, cycle_id, receipt)
                    engine.inbox.save_exact_plan(
                        cycle_id, company_id, plan, timestamp=stamp)
                action = 'planned'
            else:
                plan, cursor = existing
                if binding is not None and (
                        not isinstance(plan, Mapping) or plan.get('selected_retry_receipt_binding') != binding):
                    raise ValueError('selected_retry_frozen_plan_binding_changed')
                if isinstance(plan, Mapping) and plan.get('exact_plan_version') == 2:
                    _validate_existing_exact_plan_v2(
                        plan, payload, engine.repo, cycle_id, company_id,
                        evidence_digest)
                    local_state = engine.inbox.exact_local_state(cycle_id, company_id)
                    if (local_state is None
                            or local_state['plan_digest'] != plan['plan_digest']
                            or local_state['local_operations_digest'] != plan['local_operations_digest']
                            or local_state['remote_projection_digest'] != plan['remote_projection_digest']):
                        raise ValueError('existing_exact_plan_v2_local_state_mismatch')
                    if event_binding is not None:
                        derive_receipt(cycle, company_id, payload, plan, stamp,
                                       ordinary_event_context=ordinary_event_context)
                    if retry_binding is not None:
                        receipt = derive_receipt(cycle, company_id, payload, plan, stamp)
                        require_unambiguous_repair_retry_receipt(engine.inbox, cycle_id, receipt)
                else:
                    _validate_existing_plan(engine.inbox, cycle, company_id, payload, plan,
                                            evidence_digest, stamp, engine.repo, cursor)
                action = 'recovered'

            # A projected v2 plan is frozen before local mutation.  State must
            # remain queued until the separate local journal is VERIFIED.
            if isinstance(plan, Mapping) and plan.get('exact_plan_version') == 2:
                report[action].append(company_id)
                continue

            # This is intentionally second: plan + receipt are the durable
            # authority if saving the separate State database is interrupted.
            refreshed = engine.state.cycle(cycle_id)
            if refreshed is None or refreshed.get('id') != cycle_id:
                raise RuntimeError('exact_cycle_disappeared_before_checkpoint')
            refreshed_item = refreshed.get('companies', {}).get(company_id)
            if not isinstance(refreshed_item, dict):
                raise RuntimeError('company_disappeared_before_checkpoint')
            refreshed['companies'][company_id] = _checkpoint_item(refreshed_item, payload)
            engine.state.save_cycle(refreshed)
            report[action].append(company_id)
        except Exception as exc:
            report['held'].append({'company_id': company_id, 'reason': str(exc) or type(exc).__name__})
    return report
