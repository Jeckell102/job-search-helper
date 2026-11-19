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
from typing import Callable, Iterable, Mapping

from .batching import PendingState, PlanningRepository
from .engine import now
from .exact_cycle_receipt import derive_receipt


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
            or _canonical_remote_projection(
                _project_operations(local_operations, publication)) != remote_projection
            or plan.get('local_expected_records') != record_fingerprints(local_operations)
            or plan.get('local_expected_records_digest') != _digest(plan.get('local_expected_records'))
            or plan.get('remote_records') != record_fingerprints(remote_projection)
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
            manual = expected.get('Added to Opportunities?', prior.get('Added to Opportunities?', ''))
            operation['expected'] = {'Added to Opportunities?': manual}
            if str(manual).strip().casefold() == 'manual review':
                for field in ('Review Status', 'Source Hash'):
                    operation['expected'][field] = expected.get(field, prior.get(field, ''))
            if 'Job Key' in expected:
                operation['expected']['Job Key'] = expected['Job Key']


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


def _freeze(engine, planner, cycle, company_id, payload, *, drop_noops=False):
    """Compute a frozen plan entirely in memory, with no repository commit."""
    company = _company_from(planner, company_id)
    engine._verify_same_board({'Official Careers URL': payload['requested_url']}, company)
    local_cycle = copy.deepcopy(cycle)
    local_item = local_cycle['companies'][company_id]
    local_item.update(payload, stage='inventory', staging_complete=True, next_job_index=0)

    before_rows = copy.deepcopy(planner.rows)
    originals = {}
    commit = planner.commit
    def track(operations):
        for operation in operations:
            for number, row in planner.indexes[operation['tab']].matches(operation['identity']):
                originals.setdefault((operation['tab'], number), copy.deepcopy(row))
        return commit(operations)
    original_repo, original_state, original_notices = engine.repo, engine.state, engine._notices
    engine.repo, engine.state, engine._notices = planner, PendingState(original_state), []
    planner.commit = track
    planner.begin()
    try:
        for posting in payload['jobs']:
            if not isinstance(posting, dict):
                raise ValueError('inventory_job_not_an_object')
            engine._stage_posting(local_cycle, company, posting)
        if payload['inventory_status'] == 'complete':
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


def freeze_exact_cycle_plans(engine, cycle_id: str, company_ids: Iterable[str], *,
                             company_guard: Callable[[str, str], None], max_companies: int = 5,
                             stamp: str | None = None):
    """Freeze plans for explicit saved inventories, never fetching or publishing.

    ``company_guard`` must perform the narrow *current remote* Company control
    check for its exact ``(company_id, requested_url)`` pair, raising to hold
    the item.  The function intentionally has no remote repository argument.

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
            # This injected guard is deliberately before plan persistence.
            evidence, evidence_digest = _control_evidence(
                company_guard(company_id, payload['requested_url']), company_id, payload['requested_url'])
            existing = engine.inbox.plan(cycle_id, company_id)
            if existing is None:
                profile, _publication = _publication_schema(engine.repo)
                plan = _freeze(
                    engine, planner, cycle, company_id, payload,
                    drop_noops=profile != 'full')
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
                    engine.inbox.save_exact_plan(
                        cycle_id, company_id, plan, timestamp=stamp)
                action = 'planned'
            else:
                plan, cursor = existing
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
