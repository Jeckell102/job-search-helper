"""One-reservation bridge from a frozen retained start through FIRST PASS."""
from __future__ import annotations

import copy
from contextlib import nullcontext
from pathlib import Path

from .exact_cycle_planner import _exact_plan_digest, freeze_retained_exact_plan
from .exact_cycle_sync import _company_guard
from .exact_local_plan import commit_exact_local_plan, exact_local_plan
from .retained_dirty_provenance import (
    FIRST_PASS_RELEASED, reserve_dirty_provenance, retained_publication,
)
from .retained_session_store import SYNC_CONFIRMED, SYNC_PENDING
from .retained_work_publication import _publish_retained_reservation, _verify_retained_plan_runtime
from .retained_work_runner import (
    PreparedExceptionalStart, _TOKEN, _read_existing_journal, _start_binding,
    _request_provenance_id, digest,
)

_OPERATOR_RESERVATION_FIELDS = {"claims", "runtime", "authorization"}


def _inventory_payload(prepared):
    frozen = copy.deepcopy(prepared.inventory)
    status = frozen.pop("status", None)
    frozen["inventory_status"] = status
    return frozen


def _cycle_id(reservation_digest):
    return "CYC-R" + digest({"reservation_digest": reservation_digest})[:12].upper()


def _retained_root(prepared, engine, local, store, state_directory):
    if (not isinstance(prepared, PreparedExceptionalStart)
            or prepared._token is not _TOKEN):
        raise ValueError("retained_orchestrator_internal_start_required")
    if engine.repo is not local:
        raise ValueError("retained_orchestrator_local_engine_binding_invalid")
    root = Path(state_directory or Path(store.path).resolve().parent).resolve()
    if Path(store.path).resolve().parent != root or Path(local.path).resolve().parent != root:
        raise ValueError("retained_orchestrator_state_layout_invalid")
    return root


def run_retained_reservation(prepared, engine, local, remote, store, *,
                             state_directory=None, max_operations=100):
    """Run the existing v1 retained reservation under the normal scraper lock."""
    from .cli import scraper_lock_name, writer_lock
    root = _retained_root(prepared, engine, local, store, state_directory)
    with writer_lock(root / scraper_lock_name()):
        return _run_retained_reservation_locked(
            prepared, engine, local, remote, store,
            state_directory=root, max_operations=max_operations)


def _run_retained_reservation_locked(prepared, engine, local, remote, store, *,
                                    state_directory=None, max_operations=100,
                                    membership_only=False, runtime_binding=None,
                                    writer_already_held=False, authorization_now=None):
    """Apply one frozen start with the scraper lock already held.

    The verified membership-only path takes writer.lock before the publisher's
    private lock. Its caller can hold writer.lock earlier to open the write
    factories safely. The prepared inventory is the only job input.
    """
    from .cli import writer_lock
    root = _retained_root(prepared, engine, local, store, state_directory)
    if type(writer_already_held) is not bool or (writer_already_held and membership_only is not True):
        raise ValueError("retained_operator_writer_lock_contract_invalid")
    reservation = prepared.admission["reservation_digest"]
    binding = _start_binding(prepared)
    binding_digest = digest(binding)
    company_id = binding["company_id"]
    cycle_id = _cycle_id(reservation)
    payload = _inventory_payload(prepared)
    request = prepared.snapshot["request"]
    identity = {"reservation_digest": reservation, "cycle_id": cycle_id, "company_id": company_id}
    reservation_payload = prepared.admission.get("reservation_payload", {})
    authorization_expires_at = None
    if membership_only is True:
        if runtime_binding is None:
            raise ValueError("retained_operator_runtime_binding_required")
        from .retained_operator_authorization import EVENT_ACTION
        from .retained_operator_journal import operator_journal_binding
        from .runner import _canonical_runtime_binding
        runtime_binding = _canonical_runtime_binding(runtime_binding)
        if (not isinstance(reservation_payload, dict)
                or set(reservation_payload) != _OPERATOR_RESERVATION_FIELDS
                or reservation_payload["runtime"] != runtime_binding):
            raise ValueError("retained_operator_reservation_runtime_changed")
        claims = reservation_payload["claims"]
        expected = operator_journal_binding(claims, runtime_binding, reservation_payload["authorization"])
        event_mode = claims["action"] == EVENT_ACTION
        if event_mode:
            authorization_expires_at = claims["expires_at"]
        expected_provenance = (request["request_id"].removeprefix("company-event:")
                               if event_mode else "operator:" + request["request_id"])
        if (expected["reservation_digest"] != reservation
                or claims["request_id"] != request["request_id"]
                or claims["request_sha256"] != digest(request)
                or claims["receipt_sha256"] != digest(prepared.snapshot.get("receipt"))
                or claims["company_row_sha256"] != digest(prepared.company)
                or claims["company_id"] != company_id
                or claims["source_revision"] != prepared.snapshot["source_revision"]
                or claims["cycle_id"] != prepared.exception_cycle["id"]
                or claims["historical_manifest_sha256"] != prepared.admission["manifest_digest"]
                or (request.get("company_event") is not None) != event_mode
                or (request.get("operator_request") is not None) == event_mode
                or _request_provenance_id(request) != expected_provenance):
            raise ValueError("retained_operator_reservation_identity_changed")
        identity["runtime_binding_sha256"] = digest(runtime_binding)
    elif (membership_only is not False or runtime_binding is not None
          or (isinstance(reservation_payload, dict)
              and _OPERATOR_RESERVATION_FIELDS & reservation_payload.keys())):
        raise ValueError("retained_operator_membership_binding_required")
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

    with (writer_lock(root / "writer.lock") if membership_only and not writer_already_held else nullcontext()):
        journal = _read_existing_journal(root / "retained-work-starts.sqlite3")
        existing = store.load_optional(reservation)
        if existing is not None:
            _verify_retained_plan_runtime(existing["plan"], runtime_binding)
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
                max_operations=max_operations, runtime_binding=runtime_binding,
                authorization_expires_at=authorization_expires_at, authorization_now=authorization_now)
            return {
                **identity, "session": session,
                "provenance": publication_state,
                "local": exact_local_plan(local, cycle_id, company_id),
                "publication": publication, "recovered": True,
            }
        if (journal["state"] != "FROZEN"
                or journal["binding"] != binding
                or journal["binding_digest"] != binding_digest):
            raise ValueError("retained_orchestrator_frozen_start_changed")
        saved_admission = journal["prepared"].get("admission", {})
        saved_payload = saved_admission.get("reservation_payload", {})
        if (not membership_only and isinstance(saved_payload, dict)
                and _OPERATOR_RESERVATION_FIELDS & saved_payload.keys()):
            raise ValueError("retained_operator_membership_binding_required")
        if membership_only:
            frozen = {
                "snapshot": prepared.snapshot, "company": prepared.company,
                "exception_cycle": prepared.exception_cycle,
                "inventory": prepared.inventory, "admission": prepared.admission,
                "started_at": prepared.started_at,
            }
            if digest(journal["prepared"]) != digest(frozen):
                raise ValueError("retained_operator_frozen_preparation_changed")
        if membership_only:
            if local.spreadsheet_id != remote.spreadsheet_id:
                raise ValueError("retained_operator_workbook_identity_changed")
            rows = local.matches("Companies", {"Company ID": company_id})
            if len(rows) != 1 or digest(rows[0][1]) != claims["company_row_sha256"]:
                raise ValueError("retained_operator_company_row_changed")
        if existing is None or membership_only:
            controls = _company_guard(
                local, remote, company_id, payload["requested_url"])
            if membership_only and digest({
                    "controls": controls, "schemas_sha256": digest(remote.schemas),
            }) != claims["workbook_controls_sha256"]:
                raise ValueError("retained_operator_workbook_controls_changed")
        if existing is None:
            plan = freeze_retained_exact_plan(
                engine, cycle_id, company_id, payload, controls,
                started_at=prepared.started_at,
                **({"membership_only": True} if membership_only else {}))
            if membership_only:
                plan["runtime_binding_sha256"] = identity["runtime_binding_sha256"]
                plan["plan_digest"] = _exact_plan_digest(plan)
                _verify_retained_plan_runtime(plan, runtime_binding)
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
        if membership_only and session["state"] in {SYNC_PENDING, SYNC_CONFIRMED}:
            # Publication already owns the verified local plan. An interrupted
            # acknowledgement may also have cleared its selected dirty cells.
            local_result = exact_local_plan(local, cycle_id, company_id)
        else:
            local_result = commit_exact_local_plan(
                local, cycle_id, company_id, plan,
                max_operations=max_operations, reservation_digest=reservation,
                recover_retained_chunks=membership_only)
        publication = _publish_retained_reservation(
            reservation, store, local, remote,
            max_operations=max_operations, runtime_binding=runtime_binding,
            authorization_expires_at=authorization_expires_at, authorization_now=authorization_now)
        if membership_only:
            session = store.load(reservation)
    return {
        **identity, "session": session,
        "provenance": provenance, "local": local_result,
        "publication": publication, "recovered": False,
    }
