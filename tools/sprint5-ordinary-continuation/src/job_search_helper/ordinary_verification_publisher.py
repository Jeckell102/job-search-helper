"""Exact publication phase for an already prepared ordinary verification."""

from . import ordinary_verification_pending as pending
from .engine import Engine
from .ordinary_verification_outcome import existing_outcome
from .repository import RepositoryError


def publish_prepared_ordinary(stores, runtime, cycle_id, company_id, open_remote):
    """Publish the selected inventory under caller-owned scraper and writer leases.

    This phase opens Sheets only for the named prepared inventory. A proven
    completed publication is returned from its archived local receipt.
    """
    from .exact_cycle_planner import freeze_exact_cycle_plans
    from .exact_cycle_recovery import _prepare_exact_v2_local
    from .exact_cycle_sync import _company_guard, _validate_controls, publish_exact_cycle
    from .ordinary_verification_publication import (
        bind_publication, read_publication_proof, require_bound_plan,
    )

    cycle = stores.state.cycle(cycle_id)
    if not isinstance(cycle, dict) or cycle.get('id') != cycle_id:
        raise RepositoryError('The ordinary verification publication cycle is missing.')
    Engine.validate_cycle_runtime_binding(cycle, runtime, sync_only=True)
    archived = read_publication_proof(stores, cycle_id, company_id)
    if archived is not None:
        return {'state': 'ALREADY_PUBLISHED', 'proof': archived}
    if stores.jobs.readonly:
        raise RepositoryError('Ordinary verification publication needs the owned writable Jobs handle.')
    cycle, (payload, blocked) = pending.read_prepared_inventory(stores, cycle_id, company_id)
    marker = pending.read_marker(cycle, company_id)
    if blocked or payload.get('inventory_status') not in {'partial', 'complete'}:
        raise RepositoryError('Ordinary verification has no publishable prepared inventory.')
    if existing_outcome(stores.jobs, marker['owner']) is not None:
        raise RepositoryError('The exact ordinary attempt already has an immutable outcome.')
    frozen = stores.inbox.plan(cycle_id, company_id)
    if frozen is None:
        bind_publication(stores, cycle_id, company_id)
    else:
        require_bound_plan(stores, cycle_id, company_id, frozen[0])

    with open_remote() as remote:
        if remote.spreadsheet_id != stores.jobs.spreadsheet_id:
            raise RepositoryError('Ordinary verification publication destination changed.')
        engine = Engine(stores.jobs, stores.state, inbox=stores.inbox, runtime_binding=runtime)

        def controls(cid, requested_url):
            return _company_guard(stores.jobs, remote, cid, requested_url, additional_fields=('ATS / Source',))

        if frozen is None:
            report = freeze_exact_cycle_plans(engine, cycle_id, [company_id],
                                              company_guard=controls, max_companies=1,
                                              ordinary_verification_stores=stores)
            if report['held']:
                return {'state': 'PUBLICATION_HELD', 'report': report}
            frozen = stores.inbox.plan(cycle_id, company_id)
            if frozen is None:
                raise RepositoryError('The ordinary verification plan did not freeze.')
        plan, _ = frozen
        require_bound_plan(stores, cycle_id, company_id, plan)
        # On replay, a frozen plan is still required to match current remote
        # controls before completing its local application.
        _validate_controls(plan, controls(company_id, plan['requested_url']))
        _prepare_exact_v2_local(engine, cycle_id, company_id, plan, payload,
                                ordinary_verification_stores=stores)
        report = publish_exact_cycle(
            stores.inbox, cycle_id, remote, company_ids=[company_id], state=stores.state,
            company_guard=controls, local=stores.jobs, ordinary_verification_stores=stores,
        )
        if report['confirmed'] != [company_id] or report['held'] or report['skipped']:
            return {'state': 'PUBLICATION_HELD', 'report': report}
    proof = read_publication_proof(stores, cycle_id, company_id)
    if proof is None:
        raise RepositoryError('Ordinary verification publication has no archived exact proof.')
    return {'state': 'PUBLISHED', 'proof': proof}


def verification_input_after_publication(stores, cycle_id, company_id):
    """Recover the original typed verifier input from an exact published dispatch."""
    from .ordinary_verification_publication import read_publication_proof

    proof = read_publication_proof(stores, cycle_id, company_id)
    if proof is None:
        raise RepositoryError('The ordinary verification publication proof is unavailable.')
    cycle = stores.state.cycle(cycle_id)
    marker = pending.read_marker(cycle, company_id)
    if marker is None or pending.digest(marker) != proof['owner']['prepared_sha256']:
        raise RepositoryError('The published ordinary verification marker changed.')
    pending._check_stores(stores, marker['owner'])
    pending._check_company(stores, cycle, marker['owner'])
    from .ordinary_verification_worker import OrdinaryVerificationHandoff
    OrdinaryVerificationHandoff._current_company(stores, company_id)
    if marker['observation'] is None:
        raise RepositoryError('There is no typed enrolled Rippling mismatch to verify.')
    return {key: marker[key] for key in ('schema', 'owner', 'admission', 'observation')}
