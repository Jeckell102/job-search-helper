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


def _prepare_exact_v2_local(engine, cycle_id, company_id, plan, payload):
    """Apply and prove one frozen v2 local stream before any remote write."""
    from .exact_cycle_planner import _checkpoint_item
    from .exact_cycle_receipt import derive_receipt
    from .exact_local_plan import VERIFIED
    from .sqlite_repository import timestamp

    frozen = engine.inbox.plan(cycle_id, company_id)
    if frozen is None or frozen[0].get('plan_digest') != plan['plan_digest']:
        raise ValueError('exact_v2_frozen_plan_changed_before_local_apply')
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
    if item.get('stage') == 'queued':
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
        receipt_cycle, company_id, payload, plan, timestamp())
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


def recover_exact_cycle_with_factory_admitted(state_db_path,
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
                                require_frozen_plans=False):
    cycle = engine.state.cycle(cycle_id)
    if not isinstance(cycle, dict) or cycle.get('id') != cycle_id:
        raise ValueError('exact_recovery_cycle_missing')
    if cycle.get('status') in {'Complete', 'Complete with exceptions'}:
        raise ValueError('exact_recovery_cycle_finished')
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
        has_plan = engine.inbox.plan(cycle_id, company_id) is not None
        if require_frozen_plans and not has_plan:
            raise ValueError('exact_recovery_frozen_plan_required')
        # Allowed local combinations: queued with/without a plan (the
        # plan-save/State-save split), inventory with a plan, or a terminal
        # final checkpoint with its retained plan for cleanup-only recovery.
        if stage == 'queued':
            pass
        elif stage == 'inventory' and has_plan:
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
            )
            report['planned'].extend(planned['planned'])
            report['recovered'].extend(planned['recovered'])
            report['held'].extend(planned['held'])
            if planned['held']:
                continue
        plan_state = engine.inbox.plan(cycle_id, company_id)
        if (plan_state is not None and isinstance(plan_state[0], dict)
                and plan_state[0].get('exact_plan_version') == 2):
            try:
                _prepare_exact_v2_local(
                    engine, cycle_id, company_id, plan_state[0],
                    engine.inbox.get(cycle_id, company_id)[0])
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
        )
        report['confirmed'].extend(delivered['confirmed'])
        report['held'].extend(delivered['held'])
        report['skipped'].extend(delivered['skipped'])
    return report
