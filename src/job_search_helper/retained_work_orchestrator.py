"""One-reservation bridge from a frozen retained start through FIRST PASS."""
from __future__ import annotations

import copy
from pathlib import Path

from .exact_cycle_planner import freeze_retained_exact_plan
from .exact_cycle_sync import _company_guard
from .exact_local_plan import commit_exact_local_plan, exact_local_plan
from .retained_dirty_provenance import (
    FIRST_PASS_RELEASED, reserve_dirty_provenance, retained_publication,
)
from .retained_work_publication import _publish_retained_reservation
from .retained_work_runner import (
    PreparedExceptionalStart, _TOKEN, _read_existing_journal, _start_binding,
    _request_provenance_id, digest,
)


def _inventory_payload(prepared):
    frozen = copy.deepcopy(prepared.inventory)
    status = frozen.pop("status", None)
    frozen["inventory_status"] = status
    return frozen


def _cycle_id(reservation_digest):
    return "CYC-R" + digest({"reservation_digest": reservation_digest})[:12].upper()


def run_retained_reservation(prepared, engine, local, remote, store, *,
                             state_directory=None, max_operations=100):
    """Plan, locally apply, publish and release exactly one frozen reservation.

    ``prepared`` must be the opaque value returned by retained-work prepare or
    cold recovery, and its committed FROZEN journal must still be present. The
    function shares the normal scraper lock and never discovers ordinary State,
    Inbox, cycles, companies, dirty rows, or queues beyond the named binding.
    """
    if (not isinstance(prepared, PreparedExceptionalStart)
            or prepared._token is not _TOKEN):
        raise ValueError("retained_orchestrator_internal_start_required")
    if engine.repo is not local:
        raise ValueError("retained_orchestrator_local_engine_binding_invalid")
    root = Path(state_directory or Path(store.path).resolve().parent).resolve()
    if Path(store.path).resolve().parent != root or Path(local.path).resolve().parent != root:
        raise ValueError("retained_orchestrator_state_layout_invalid")
    reservation = prepared.admission["reservation_digest"]
    binding = _start_binding(prepared)
    binding_digest = digest(binding)
    company_id = binding["company_id"]
    cycle_id = _cycle_id(reservation)
    payload = _inventory_payload(prepared)
    request = prepared.snapshot["request"]
    admission = {
        "request_id": request["request_id"],
        "event_id": _request_provenance_id(request),
        "exception_cycle_id": prepared.exception_cycle["id"],
        "cycle_id": cycle_id,
        "company_id": company_id,
        "source_revision": prepared.snapshot["source_revision"],
        "manifest_digest": prepared.admission["manifest_digest"],
        "start_binding_digest": binding_digest,
    }

    from .cli import scraper_lock_name, writer_lock
    with writer_lock(root / scraper_lock_name()):
        journal = _read_existing_journal(root / "retained-work-starts.sqlite3")
        existing = store.load_optional(reservation)
        if journal is None:
            if existing is None:
                raise ValueError("retained_orchestrator_frozen_start_changed")
            # A caller may lose the successful command response after FIRST
            # PASS and exact embargo cleanup. Rebind every sealed input and
            # return the durable result without regenerating or replaying work.
            session = store.freeze(
                reservation, admission=admission, inventory=payload,
                plan=existing["plan"])
            publication_state = retained_publication(local, reservation)
            if publication_state["state"] != FIRST_PASS_RELEASED:
                raise ValueError("retained_orchestrator_frozen_start_changed")
            publication = _publish_retained_reservation(
                reservation, store, local, remote,
                max_operations=max_operations)
            return {
                "reservation_digest": reservation, "cycle_id": cycle_id,
                "company_id": company_id, "session": session,
                "provenance": publication_state,
                "local": exact_local_plan(local, cycle_id, company_id),
                "publication": publication, "recovered": True,
            }
        if (journal["state"] != "FROZEN"
                or journal["binding"] != binding
                or journal["binding_digest"] != binding_digest):
            raise ValueError("retained_orchestrator_frozen_start_changed")
        if existing is None:
            controls = _company_guard(
                local, remote, company_id, payload["requested_url"])
            plan = freeze_retained_exact_plan(
                engine, cycle_id, company_id, payload, controls,
                started_at=prepared.started_at)
        else:
            plan = existing["plan"]
        session = store.freeze(
            reservation, admission=admission, inventory=payload, plan=plan)
        provenance = reserve_dirty_provenance(
            local, reservation_digest=reservation,
            request_id=admission["request_id"], event_id=admission["event_id"],
            exception_cycle_id=admission["exception_cycle_id"],
            cycle_id=cycle_id, company_id=company_id,
            source_revision=admission["source_revision"],
            manifest_digest=admission["manifest_digest"],
            start_binding_digest=binding_digest, plan=plan)
        local_result = commit_exact_local_plan(
            local, cycle_id, company_id, plan,
            max_operations=max_operations, reservation_digest=reservation)
        publication = _publish_retained_reservation(
            reservation, store, local, remote,
            max_operations=max_operations)
    return {
        "reservation_digest": reservation, "cycle_id": cycle_id,
        "company_id": company_id, "session": session,
        "provenance": provenance, "local": local_result,
        "publication": publication, "recovered": False,
    }
