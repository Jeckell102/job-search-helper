"""Bounded composition of exact local planning and selected-plan delivery."""
from __future__ import annotations

from pathlib import Path

from .exact_cycle_planner import freeze_exact_cycle_plans
from .exact_cycle_sync import _company_guard, publish_exact_cycle


def _normal_scraper_lock(engine):
    """Acquire the normal scraper lock derived from the engine's State file."""
    from .cli import scraper_lock_name, writer_lock

    state_path = getattr(engine.state, 'path', None)
    if not isinstance(state_path, str) or not state_path or state_path == ':memory:':
        raise RuntimeError('exact_recovery_requires_file_backed_state')
    return writer_lock(Path(state_path).parent / scraper_lock_name())


def recover_exact_cycle(engine, remote, cycle_id, company_ids):
    """Recover at most five explicitly named durable inventories.

    This intentionally accepts all dependencies from the caller: it never
    constructs a repository, starts a global synchronizer, or discovers work.
    It acquires the same lock as the normal scraper before reading State,
    inventory, or remote data; callers cannot substitute a lock assertion.
    """
    if not isinstance(cycle_id, str) or not cycle_id.strip():
        raise ValueError('exact_recovery_cycle_id_required')
    cycle_id = cycle_id.strip()
    if not isinstance(company_ids, (list, tuple)):
        raise ValueError('exact_recovery_explicit_company_ids_required')
    selected = [str(value).strip() for value in company_ids]
    if (not selected or len(selected) > 5 or any(not value for value in selected)
            or len(selected) != len(set(selected))):
        raise ValueError('exact_recovery_selection_must_be_unique_and_bounded_to_1_5')
    with _normal_scraper_lock(engine):
        cycle = engine.state.cycle(cycle_id)
        if not isinstance(cycle, dict) or cycle.get('id') != cycle_id:
            raise ValueError('exact_recovery_cycle_missing')
        if cycle.get('status') in {'Complete', 'Complete with exceptions'}:
            raise ValueError('exact_recovery_cycle_finished')
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
        report = {'cycle_id': cycle_id, 'planned': [], 'recovered': [], 'confirmed': [], 'held': [], 'skipped': []}

        def guard(company_id, requested_url):
            # The publisher helper reads only the selected Company row and returns
            # the exact six-field evidence required by the planner contract.
            return _company_guard(remote, company_id, {'requested_url': requested_url})

        for company_id in selected:
            facts = preflight[company_id]
            # A queued checkpoint and plan is the deliberate plan-save/State-save
            # split: re-enter the planner to validate/reconcile it before delivery.
            needs_plan = not facts['has_plan'] or facts['stage'] == 'queued'
            if needs_plan:
                planned = freeze_exact_cycle_plans(engine, cycle_id, [company_id], company_guard=guard,
                                                    max_companies=1)
                report['planned'].extend(planned['planned'])
                report['recovered'].extend(planned['recovered'])
                report['held'].extend(planned['held'])
                if planned['held']:
                    continue
            delivered = publish_exact_cycle(engine.inbox, cycle_id, remote, company_ids=[company_id],
                                            retry_blocked=False, state=engine.state)
            report['confirmed'].extend(delivered['confirmed'])
            report['held'].extend(delivered['held'])
            report['skipped'].extend(delivered['skipped'])
        return report
