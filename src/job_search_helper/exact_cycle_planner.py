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
    return _digest({key: plan.get(key) for key in (
        'operations', 'final', 'requested_url', 'control_evidence',
        'control_evidence_version', 'control_evidence_digest', 'inventory_payload_digest', 'plan_records_digest',
        'final_projection', 'final_projection_digest',
    )})


def _seal_plan(plan, payload):
    from .publication_receipts import record_fingerprints
    plan['inventory_payload_digest'] = _digest(payload)
    plan['plan_records_digest'] = _digest(record_fingerprints(plan['operations']))
    plan['final_projection'] = {key: plan['final'][key] for key in sorted(plan['final'])}
    plan['final_projection_digest'] = _digest(plan['final_projection'])
    plan['plan_digest'] = _plan_digest(plan)
    return plan


def _validate_existing_plan(inbox, cycle, company_id, payload, plan, evidence_digest, stamp):
    """Validate an interrupted plan/receipt pair before repairing State.

    Only ``LOCAL_COMMITTED`` is accepted: ``SYNC_PENDING`` or confirmed states
    belong to the publisher/reconciliation boundary, never this planner.
    """
    from .publication_receipts import LOCAL_COMMITTED, record_fingerprints
    if (not isinstance(plan, dict) or not isinstance(plan.get('operations'), list)
            or not isinstance(plan.get('final'), dict)
            or plan.get('requested_url') != payload['requested_url']
            or plan.get('control_evidence_version') != CONTROL_EVIDENCE_VERSION
            or plan.get('control_evidence_digest') != _digest(plan.get('control_evidence', {}))
            or plan.get('inventory_payload_digest') != _digest(payload)
            or plan.get('plan_records_digest') != _digest(record_fingerprints(plan['operations']))
            or plan.get('plan_digest') != _plan_digest(plan)):
        raise ValueError('existing_frozen_plan_invalid')
    if plan['control_evidence_digest'] != evidence_digest:
        raise ValueError('company_control_evidence_changed')
    expected = _receipt(cycle, company_id, payload, plan, stamp)
    # ``find_receipt`` detects another receipt with the same records, but is
    # insufficient by itself; require the precise immutable binding as well.
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


def _freeze(engine, planner, cycle, company_id, payload):
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
                plan = _freeze(engine, planner, cycle, company_id, payload)
                plan['control_evidence'] = evidence
                plan['control_evidence_version'] = CONTROL_EVIDENCE_VERSION
                plan['control_evidence_digest'] = evidence_digest
                _seal_plan(plan, payload)
                receipt = _receipt(cycle, company_id, payload, plan, stamp)
                engine.inbox.save_plan(cycle_id, company_id, plan, receipt)
                action = 'planned'
            else:
                plan, _cursor = existing
                _validate_existing_plan(engine.inbox, cycle, company_id, payload, plan, evidence_digest, stamp)
                action = 'recovered'

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
