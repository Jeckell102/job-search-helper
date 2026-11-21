"""Bounded composition of exact local planning and selected-plan delivery."""
from __future__ import annotations

from pathlib import Path
import copy
import stat

from .exact_cycle_planner import freeze_exact_cycle_plans
from .exact_cycle_sync import _company_guard, publish_exact_cycle


__all__ = (
    'recover_exact_cycle',
    'recover_exact_cycle_with_factory',
)


def _canonical_file_backed_state_path(state_db_path):
    if not isinstance(state_db_path, (str, Path)) or not str(state_db_path):
        raise RuntimeError('exact_recovery_requires_file_backed_state')
    try:
        state_path = Path(state_db_path).expanduser().resolve(strict=True)
        mode = state_path.stat().st_mode
    except (OSError, RuntimeError, ValueError) as exc:
        raise RuntimeError('exact_recovery_requires_file_backed_state') from exc
    if not stat.S_ISREG(mode):
        raise RuntimeError('exact_recovery_requires_file_backed_state')
    return state_path


def _normal_scraper_lock(state_path):
    from .cli import scraper_lock_name, writer_lock

    return writer_lock(state_path.parent / scraper_lock_name())


def _require_engine_state_path(engine, locked_state_path):
    engine_path = _canonical_file_backed_state_path(getattr(engine.state, 'path', None))
    if engine_path != locked_state_path:
        raise RuntimeError('exact_recovery_engine_state_path_mismatch')


def _normalize_request(cycle_id, company_ids):
    if not isinstance(cycle_id, str) or not cycle_id.strip():
        raise ValueError('exact_recovery_cycle_id_required')
    cycle_id = cycle_id.strip()
    if not isinstance(company_ids, (list, tuple)):
        raise ValueError('exact_recovery_explicit_company_ids_required')
    selected = [str(value).strip() for value in company_ids]
    if (not selected or len(selected) > 5 or any(not value for value in selected)
            or len(selected) != len(set(selected))):
        raise ValueError('exact_recovery_selection_must_be_unique_and_bounded_to_1_5')
    return cycle_id, selected


def _deferred_repair_checkpoint(engine, cycle, company_id, payload):
    """Recognize the normal defer-sync checkpoint for one owned release retry."""
    from .company_events import canonical_company_fact, source_revision
    from .exact_cycle_planner import _validate_payload
    from .repair_retry import retry_request, validate_retry_request
    from .scan_request import _read_request, request_fingerprint
    from .sheet_profile import COMPACT_PROFILE

    companies = cycle.get('companies', {})
    item = companies.get(company_id, {})
    if (cycle.get('repair_retry') is None or cycle.get('all') is not False
            or set(companies) != {company_id} or cycle.get('status') != 'In Progress'
            or any(key in cycle for key in ('company_event', 'operator_request', 'temporary_retry',
                                            'selected_retry_reservation_sha256', 'retained_work_exception',
                                            'recovery_pause'))
            or item.get('stage') != 'inventory' or item.get('durable_inventory') is not True
            or 'locally_processed' in item or 'jobs' in item
            or getattr(engine.repo, 'is_local', False) is not True
            or engine.repo.get_meta('sheets_profile') != COMPACT_PROFILE):
        return False
    _validate_payload(payload)
    if (engine.inbox.get(cycle['id'], company_id) != (payload, False)
            or any(key not in item or item[key] != value
                   for key, value in payload.items() if key != 'jobs')):
        raise ValueError('exact_v2_deferred_repair_inventory_changed')

    request_path = Path(engine.state.path).parent / 'last-scan-request.json'
    if request_path.is_symlink() or not request_path.is_file():
        raise ValueError('exact_v2_deferred_repair_request_missing')
    request, selected = _read_request(request_path)
    retry = validate_retry_request(request, selected)
    if (selected != [company_id] or retry != cycle['repair_retry']
            or request != retry_request(retry, enqueued_at=retry['activated_at'])
            or request['request_id'] != cycle.get('start_request_id')
            or request_fingerprint(request, selected) != cycle.get('request_fingerprint')):
        raise ValueError('exact_v2_deferred_repair_request_changed')

    runtime = engine.assert_runtime_binding(cycle['id'], sync_only=True)
    release = retry['release']
    if runtime != {'state': 'COMPLETE', **{key: value for key, value in release.items() if key != 'schema'}}:
        raise ValueError('exact_v2_deferred_repair_runtime_changed')
    engine._assert_repair_retry_release(cycle)
    matches = engine.repo.matches('Companies', {'Company ID': company_id})
    if len(matches) != 1:
        raise ValueError('exact_v2_deferred_repair_company_changed')
    company = matches[0][1]
    fact = canonical_company_fact(company)
    if (not fact['eligible'] or fact != item.get('outcome_source_fact')
            or company.get('Active Cycle ID') != cycle['id']
            or company.get('Claimed By') or company.get('Claim Token')
            or payload['requested_url'] != company.get('Official Careers URL')
            or source_revision(company) != retry['source_revision']
            or item.get('outcome_source_revision') != retry['source_revision']):
        raise ValueError('exact_v2_deferred_repair_company_changed')
    return True


def _prepare_exact_v2_local(engine, cycle_id, company_id, plan, payload, ordinary_event_context=None):
    """Apply and prove one frozen v2 local stream before any remote write."""
    from .exact_cycle_planner import _checkpoint_item
    from .exact_cycle_receipt import (
        REPAIR_RETRY_PLAN_BINDING, derive_receipt, has_repair_retry_scope, require_unambiguous_repair_retry_receipt,
    )
    from .exact_local_plan import VERIFIED
    from .sqlite_repository import timestamp

    frozen = engine.inbox.plan(cycle_id, company_id)
    if frozen is None or frozen[0].get('plan_digest') != plan['plan_digest']:
        raise ValueError('exact_v2_frozen_plan_changed_before_local_apply')
    original = engine.state.cycle(cycle_id)
    if original is None or company_id not in original.get('companies', {}):
        raise RuntimeError('exact_v2_state_company_missing_before_local_apply')
    item = original['companies'][company_id]
    repair_retry = has_repair_retry_scope(original) or REPAIR_RETRY_PLAN_BINDING in plan
    deferred = (item.get('stage') == 'inventory'
                and (item.get('durable_inventory') is not True or item.get('locally_processed') is not True))
    if deferred:
        from .exact_cycle_planner import _validate_existing_exact_plan_v2
        if (ordinary_event_context is not None or any(key in plan for key in (
                'ordinary_company_event', 'selected_retry_receipt_binding', 'retained_membership_only',
                'selected_legacy_control_before_prefix_recovery'))
                or not _deferred_repair_checkpoint(engine, original, company_id, payload)):
            raise ValueError('exact_v2_inventory_checkpoint_invalid')
        _validate_existing_exact_plan_v2(
            plan, payload, engine.repo, cycle_id, company_id, plan.get('control_evidence_digest'))
    if repair_retry:
        engine._assert_repair_retry_release(original)
        receipt = derive_receipt(original, company_id, payload, plan, timestamp())
        require_unambiguous_repair_retry_receipt(engine.inbox, cycle_id, receipt)
    cursor = frozen[1]
    local_count = len(plan['local_operations'])
    if type(cursor) is not int or not 0 <= cursor <= local_count:
        raise ValueError('exact_v2_local_cursor_invalid')
    while cursor < local_count:
        chunk = engine.repo.apply_exact_local_plan(
            cycle_id, company_id, plan, cursor, max_operations=100)
        verified_chunk = engine.repo.verify_exact_local_plan(
            cycle_id, company_id, plan, cursor=cursor)
        if (verified_chunk['state'] != VERIFIED
                or verified_chunk['apply_id'] != chunk['apply_id']
                or verified_chunk['count'] != chunk['count']):
            raise ValueError('exact_v2_local_chunk_verification_mismatch')
        next_cursor = cursor + chunk['count']
        engine.inbox.advance_exact_local_cursor(
            cycle_id, company_id, next_cursor, expected=cursor)
        cursor = next_cursor
    applied = engine.repo.verify_exact_local_plan(
        cycle_id, company_id, plan, cursor=None)
    if applied['state'] != VERIFIED:
        raise ValueError('exact_v2_local_application_not_verified')
    stamp = timestamp()
    mirrored = engine.inbox.exact_local_state(cycle_id, company_id)
    if mirrored is None or mirrored['plan_digest'] != plan['plan_digest']:
        raise ValueError('exact_v2_frozen_local_mirror_missing')
    if mirrored['state'] == 'FROZEN':
        mirrored = engine.inbox.mark_exact_local_applied(
            cycle_id, company_id, plan_digest=plan['plan_digest'],
            apply_id=applied['apply_id'], records_digest=applied['records_digest'],
            timestamp=stamp)
    if mirrored['state'] == 'LOCAL_APPLIED':
        mirrored = engine.inbox.mark_exact_local_verified(
            cycle_id, company_id, plan_digest=plan['plan_digest'],
            apply_id=applied['apply_id'], records_digest=applied['records_digest'],
            timestamp=stamp)
    if (mirrored['state'] != 'LOCAL_VERIFIED'
            or mirrored['local_apply_id'] != applied['apply_id']
            or mirrored['local_records_digest'] != applied['records_digest']):
        raise ValueError('exact_v2_local_verification_mirror_mismatch')

    frozen = engine.inbox.plan(cycle_id, company_id)
    if frozen is None or frozen[0].get('plan_digest') != plan['plan_digest']:
        raise ValueError('exact_v2_frozen_plan_changed_after_local_apply')
    cursor = frozen[1]
    if cursor != local_count:
        raise ValueError('exact_v2_local_cursor_invalid')

    refreshed = engine.state.cycle(cycle_id)
    if refreshed is None or company_id not in refreshed.get('companies', {}):
        raise RuntimeError('exact_v2_state_company_missing_after_local_apply')
    item = refreshed['companies'][company_id]
    if deferred and (refreshed != original or not _deferred_repair_checkpoint(engine, refreshed, company_id, payload)):
        raise ValueError('exact_v2_inventory_checkpoint_invalid')
    if item.get('stage') == 'queued' or deferred:
        refreshed = copy.deepcopy(refreshed)
        refreshed['companies'][company_id] = _checkpoint_item(item, payload)
        engine.state.save_cycle(refreshed)
    elif item.get('stage') == 'inventory':
        if (item.get('durable_inventory') is not True
                or item.get('locally_processed') is not True):
            raise ValueError('exact_v2_inventory_checkpoint_invalid')
    elif item.get('stage') not in {'complete', 'partial'}:
        raise ValueError('exact_v2_state_checkpoint_not_recoverable')

    receipt_cycle = engine.state.cycle(cycle_id)
    receipt = derive_receipt(
        receipt_cycle, company_id, payload, plan, timestamp(),
        **({'ordinary_event_context': ordinary_event_context} if ordinary_event_context is not None else {}),
    )
    if repair_retry:
        require_unambiguous_repair_retry_receipt(engine.inbox, cycle_id, receipt)
    engine.inbox.ensure_receipt(receipt)
    return applied


def recover_exact_cycle(engine, remote, cycle_id, company_ids):
    """Recover at most five explicitly named durable inventories.

    This intentionally accepts all dependencies from the caller: it never
    constructs a repository, starts a global synchronizer, or discovers work.
    It acquires the same lock as the normal scraper before reading State,
    inventory, or remote data; callers cannot substitute a lock assertion.
    """
    cycle_id, selected = _normalize_request(cycle_id, company_ids)
    state_path = _canonical_file_backed_state_path(getattr(engine.state, 'path', None))
    with _normal_scraper_lock(state_path):
        from .retained_work_runner import assert_normal_lifecycle_not_held
        assert_normal_lifecycle_not_held(
            state_path.parent,
            getattr(engine.repo, 'path', state_path.parent / 'jobs.sqlite3'))
        _require_engine_state_path(engine, state_path)
        return _recover_exact_cycle_locked(engine, remote, cycle_id, selected)


def recover_exact_cycle_with_factory(state_db_path, dependency_context_factory,
                                     cycle_id, company_ids, *,
                                     require_frozen_plans=False):
    """Construct exact-recovery dependencies only while the normal lock is held."""
    cycle_id, selected = _normalize_request(cycle_id, company_ids)
    if not callable(dependency_context_factory):
        raise ValueError('exact_recovery_dependency_context_factory_required')
    state_path = _canonical_file_backed_state_path(state_db_path)
    with _normal_scraper_lock(state_path):
        return _recover_exact_cycle_with_factory_locked(
            state_path, dependency_context_factory, cycle_id, selected,
            require_frozen_plans=require_frozen_plans)


def _recover_exact_cycle_with_factory_admitted(state_db_path,
                                               dependency_context_factory,
                                               cycle_id, company_ids, *,
                                               require_frozen_plans=False):
    """Use an admission lock already validated and continuously inherited.

    This is the bootstrapped runner seam.  It deliberately does not reacquire
    the normal scraper lock; callers outside that runner must use the public
    locking function above.
    """
    cycle_id, selected = _normalize_request(cycle_id, company_ids)
    state_path = _canonical_file_backed_state_path(state_db_path)
    return _recover_exact_cycle_with_factory_locked(
        state_path, dependency_context_factory, cycle_id, selected,
        require_frozen_plans=require_frozen_plans)


def _recover_exact_cycle_with_factory_locked(state_path,
                                              dependency_context_factory,
                                              cycle_id, selected, *,
                                              require_frozen_plans=False):
    # Check before the factory can construct a writable local repository,
    # State/inbox, or Google client.
    from .cli import job_database_path
    from .retained_work_runner import assert_normal_lifecycle_not_held
    assert_normal_lifecycle_not_held(state_path.parent, job_database_path())
    dependency_context = dependency_context_factory()
    with dependency_context as dependencies:
        if not isinstance(dependencies, tuple) or len(dependencies) != 2:
            raise ValueError('exact_recovery_dependency_context_must_yield_engine_remote')
        engine, remote = dependencies
        _require_engine_state_path(engine, state_path)
        return _recover_exact_cycle_locked(
            engine, remote, cycle_id, selected,
            require_frozen_plans=require_frozen_plans)


def _recover_exact_cycle_locked(engine, remote, cycle_id, selected, *,
                                require_frozen_plans=False, bind_selected_retry=False,
                                ordinary_event_context=None, ordinary_event_guard=None):
    cycle = engine.state.cycle(cycle_id)
    if not isinstance(cycle, dict) or cycle.get('id') != cycle_id:
        raise ValueError('exact_recovery_cycle_missing')
    if getattr(engine, 'runtime_binding', None) is not None or 'runtime_binding' in cycle:
        engine.assert_runtime_binding(cycle_id, sync_only=True)
    if cycle.get('status') in {'Complete', 'Complete with exceptions'}:
        raise ValueError('exact_recovery_cycle_finished')
    if bind_selected_retry and len(selected) != 1:
        raise ValueError('selected_retry_publication_requires_one_company')
    if ordinary_event_context is not None and (
            bind_selected_retry or len(selected) != 1 or not callable(ordinary_event_guard)):
        raise ValueError('ordinary_event_publication_requires_one_exact_company')
    event_options = ({'ordinary_event_context': ordinary_event_context}
                     if ordinary_event_context is not None else {})
    from .scan_request import superseded_cycle_ids
    if cycle_id in superseded_cycle_ids(engine.state.cycles()):
        raise ValueError('exact_recovery_cycle_superseded')
    # Complete all local validation before the first selected remote read.
    preflight = {}
    for company_id in selected:
        item = cycle.get('companies', {}).get(company_id)
        saved = engine.inbox.get(cycle_id, company_id)
        if not isinstance(item, dict):
            raise ValueError('exact_recovery_company_not_in_cycle')
        if saved is None:
            raise ValueError('exact_recovery_durable_inventory_missing')
        if saved[1]:
            raise ValueError('exact_recovery_durable_inventory_blocked')
        stage = item.get('stage')
        existing = engine.inbox.plan(cycle_id, company_id)
        has_plan = existing is not None
        if has_plan and 'selected_retry_receipt_binding' in existing[0] and not bind_selected_retry:
            raise ValueError('selected_retry_needs_dedicated_publisher')
        if has_plan and 'ordinary_company_event' in existing[0] and ordinary_event_context is None:
            raise ValueError('ordinary_event_needs_dedicated_publisher')
        if bind_selected_retry:
            _validate_selected_retry_source(engine, cycle, company_id, existing[0] if has_plan else None)
        if require_frozen_plans and not has_plan:
            raise ValueError('exact_recovery_frozen_plan_required')
        # The normal defer-sync route already records inventory in State.
        # A new exact plan can follow only for the exact owned release retry.
        if stage == 'queued':
            pass
        elif stage == 'inventory' and (has_plan or (
                not bind_selected_retry and ordinary_event_context is None
                and _deferred_repair_checkpoint(engine, cycle, company_id, saved[0]))):
            pass
        elif stage in {'complete', 'partial'} and has_plan:
            pass
        else:
            raise ValueError('exact_recovery_state_plan_combination_invalid')
        preflight[company_id] = {'stage': stage, 'has_plan': has_plan}
    report = {'cycle_id': cycle_id, 'planned': [], 'recovered': [],
              'confirmed': [], 'held': [], 'skipped': []}

    def guard(company_id, requested_url):
        # Claims/manual holds are local-only under compact-v1.  This fresh
        # composite read occurs under the normal scraper lock and compares the
        # three shared controls to Google's compact projection.
        if ordinary_event_context is not None:
            return ordinary_event_guard(company_id, requested_url)
        if bind_selected_retry:
            from .exact_cycle_sync import _unique_company
            from .repository import _equivalent
            _validate_selected_retry_source(engine, engine.state.cycle(cycle_id), company_id)
            headers = ['Company ID', 'ATS / Source', 'Automatic Retry?']
            local_company = _unique_company(engine.repo, company_id, headers)
            remote_company = _unique_company(remote, company_id, headers)
            if (str(remote_company.get('Automatic Retry?') or '').strip().casefold() == 'no'
                    or str(local_company.get('Automatic Retry?') or '').strip().casefold() == 'no'
                    or any(not _equivalent(key, local_company.get(key, ''), remote_company.get(key, ''))
                           for key in headers)):
                raise ValueError('selected_retry_publication_workbook_company_changed')
        return _company_guard(engine.repo, remote, company_id, requested_url)

    for company_id in selected:
        # Recheck immediately before each selected delivery.  Another saved
        # cycle can supersede this one between companies without ending it.
        if cycle_id in superseded_cycle_ids(engine.state.cycles()):
            raise ValueError('exact_recovery_cycle_superseded')
        facts = preflight[company_id]
        # A queued checkpoint and plan is the deliberate plan-save/State-save
        # split: re-enter the planner to validate/reconcile it before delivery.
        needs_plan = not facts['has_plan'] or (
            facts['stage'] == 'queued' and not require_frozen_plans)
        if needs_plan:
            planned = freeze_exact_cycle_plans(
                engine, cycle_id, [company_id], company_guard=guard,
                max_companies=1,
                **event_options,
                **({'bind_selected_retry': True} if bind_selected_retry else {}),
            )
            report['planned'].extend(planned['planned'])
            report['recovered'].extend(planned['recovered'])
            report['held'].extend(planned['held'])
            if planned['held']:
                continue
        plan_state = engine.inbox.plan(cycle_id, company_id)
        if ordinary_event_context is not None:
            if plan_state is None or 'ordinary_company_event' not in plan_state[0]:
                raise ValueError('ordinary_event_frozen_plan_required')
            from .exact_cycle_receipt import ordinary_event_receipt_binding
            from .exact_cycle_sync import _validate_controls
            payload = engine.inbox.get(cycle_id, company_id)[0]
            if plan_state[0]['ordinary_company_event'] != ordinary_event_receipt_binding(
                    engine.state.cycle(cycle_id), company_id, payload, ordinary_event_context):
                raise ValueError('ordinary_event_frozen_plan_binding_changed')
            _validate_controls(plan_state[0], guard(company_id, plan_state[0]['requested_url']))
        if bind_selected_retry:
            if plan_state is None:
                raise ValueError('selected_retry_frozen_plan_required')
            _validate_selected_retry_source(engine, engine.state.cycle(cycle_id), company_id, plan_state[0])
            if not needs_plan:
                from .exact_cycle_sync import _validate_controls
                _validate_controls(plan_state[0], guard(company_id, plan_state[0]['requested_url']))
        if (plan_state is not None and isinstance(plan_state[0], dict)
                and plan_state[0].get('exact_plan_version') == 2):
            try:
                _prepare_exact_v2_local(
                    engine, cycle_id, company_id, plan_state[0],
                    engine.inbox.get(cycle_id, company_id)[0], **event_options)
            except Exception as exc:
                report['held'].append({
                    'company_id': company_id,
                    'reason': str(exc) or type(exc).__name__,
                })
                continue
        delivered = publish_exact_cycle(
            engine.inbox, cycle_id, remote, company_ids=[company_id],
            retry_blocked=False, state=engine.state, company_guard=guard,
            local=getattr(engine, 'repo', None),
            **event_options,
            **({'bind_selected_retry': True} if bind_selected_retry else {}),
        )
        report['confirmed'].extend(delivered['confirmed'])
        report['held'].extend(delivered['held'])
        report['skipped'].extend(delivered['skipped'])
    return report


def _validate_selected_retry_source(engine, cycle, company_id, plan=None):
    """Check source and receipt identity before any selected publication effect."""
    from .company_events import current_company_source_revision
    from .exact_cycle_receipt import selected_retry_receipt_binding

    binding = selected_retry_receipt_binding(cycle, company_id)
    rows = engine.repo.matches('Companies', {'Company ID': company_id})
    if (len(rows) != 1 or rows[0][1].get('Active Cycle ID') != cycle.get('id')
            or current_company_source_revision(engine.repo, company_id) != binding['source_revision']):
        raise ValueError('selected_retry_publication_source_changed')
    if plan is not None and (
            plan.get('exact_plan_version') != 2 or plan.get('selected_retry_receipt_binding') != binding):
        raise ValueError('selected_retry_frozen_plan_binding_changed')
    return binding
