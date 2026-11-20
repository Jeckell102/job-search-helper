"""Reservation-only publisher for a sealed retained-work exact plan.

It deliberately does not accept ordinary cycle, inbox, receipt, plan, cursor,
or readback arguments.  Those facts are read from ``RetainedSessionStore``.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import re

from .exact_cycle_planner import _exact_plan_digest
from .exact_local_plan import VERIFIED, _apply_id, exact_local_plan, verify_exact_local_plan
from .exact_cycle_sync import _company_guard, _validate_controls
from .repository import _equivalent
from .retained_dirty_provenance import (
    FIRST_PASS_RELEASED, _session_binding, bind_remote_session, confirm_remote_from_session,
    retained_publication, verify_dirty_provenance,
)
from .retained_first_pass import _read_release, release_retained_first_pass
from .retained_session_store import SYNC_CONFIRMED, _intent_id, _receipt_id
from .retained_work_runner import digest, settle_retained_start
from .sheets_sync import SheetsSynchronizer
from .sqlite_repository import timestamp


def _verify_retained_plan_runtime(plan, runtime_binding):
    """Verify a v2 seal against the current operator lease before using it."""
    if runtime_binding is None:
        if "retained_membership_only" in plan or "runtime_binding_sha256" in plan:
            raise ValueError("retained_operator_runtime_binding_required")
        return None

    from .runner import _canonical_runtime_binding
    runtime_digest = digest(_canonical_runtime_binding(runtime_binding))
    if (plan.get("retained_membership_only") is not True
            or plan.get("runtime_binding_sha256") != runtime_digest
            or plan.get("plan_digest") != _exact_plan_digest(plan)):
        raise ValueError("retained_operator_saved_plan_runtime_changed")
    for stream in ("local_operations", "remote_projection"):
        operations = plan.get(stream)
        if not isinstance(operations, list) or not operations:
            raise ValueError("retained_operator_saved_plan_scope_changed")
        for operation in operations:
            if not isinstance(operation, dict) or operation.get("tab") not in {"Job History", "Job Evidence"}:
                raise ValueError("retained_operator_saved_plan_scope_changed")
            for field in ("on_insert", "values"):
                values = operation.get(field, {})
                if (not isinstance(values, dict)
                        or values.get("Job Status", "Open and verified") != "Open and verified"
                        or values.get("Consecutive Missing Scans", 0) != 0):
                    raise ValueError("retained_operator_saved_plan_scope_changed")
    return runtime_digest


def _verified_session(reservation_digest, store, local, runtime_binding):
    session = store.load(reservation_digest)
    plan = session["plan"]
    _verify_retained_plan_runtime(plan, runtime_binding)
    if runtime_binding is not None:
        _session_binding(retained_publication(local, reservation_digest), session, plan)
    cycle_id, company_id = session["cycle_id"], session["company_id"]
    application = exact_local_plan(local, cycle_id, company_id)
    verified = verify_exact_local_plan(local, cycle_id, company_id, plan)
    if (application is None or application["state"] != VERIFIED
            or application["plan_digest"] != plan["plan_digest"]
            or application["apply_id"] != verified["apply_id"]):
        raise ValueError("retained_publication_local_plan_not_verified")
    # This also proves the retained dirty set is still exactly the sealed set.
    if session["state"] != SYNC_CONFIRMED:
        verify_dirty_provenance(local, reservation_digest, plan)
    return session, plan, application


def _verify_operator_terminal_receipt(reservation_digest, session, local, *, runtime_binding):
    """Read-only cross-check of the terminal session, local ack and queue files.

    The caller supplies the stored session with its plan decoded and holds the
    scraper lease. No repository factory, refresh, DDL or Sheets access occurs.
    """
    plan = session["plan"]
    if _verify_retained_plan_runtime(plan, runtime_binding) is None:
        raise ValueError("retained_operator_runtime_binding_required")
    publication = retained_publication(local, reservation_digest)
    identity = {
        "request_id": publication["request_id"], "event_id": publication["event_id"],
        "exception_cycle_id": publication["exception_cycle"], "cycle_id": publication["cycle"],
        "company_id": publication["company"], "source_revision": publication["source_revision"],
        "manifest_digest": publication["manifest_digest"],
        "start_binding_digest": publication["start_binding_digest"],
    }
    plan_digest = plan["plan_digest"]
    projection_digest = plan["remote_projection_digest"]
    inventory_digest = plan["inventory_payload_digest"]
    receipt_id = _receipt_id(reservation_digest, identity, inventory_digest, plan_digest, projection_digest)
    intent_id = _intent_id(receipt_id, plan["remote_projection"])
    acknowledgement_id = session.get("acknowledgement_id")
    receipt = {"plan_digest": plan_digest, "receipt_id": receipt_id, "intent_id": intent_id,
               "acknowledgement_id": acknowledgement_id}
    required_identity = ("request_id", "company_id", "source_revision", "cycle_id")
    if (session["state"] != SYNC_CONFIRMED or publication["state"] != FIRST_PASS_RELEASED
            or any(session.get(key) != identity[key] for key in required_identity)
            or any(session[key] != value for key, value in identity.items() if key in session)
            or plan["cycle_id"] != identity["cycle_id"] or plan["company_id"] != identity["company_id"]
            or any(session.get(key) != value or publication[key] != value for key, value in receipt.items())
            or projection_digest != digest(plan["remote_projection"])
            or projection_digest != session["projection_digest"]
            or projection_digest != publication["remote_projection_digest"]
            or projection_digest != publication["intent_projection_digest"]
            or not isinstance(acknowledgement_id, str)
            or re.fullmatch(r"[0-9a-f]{64}", acknowledgement_id) is None):
        raise ValueError("retained_operator_terminal_receipt_changed")
    apply_id = _apply_id(identity["cycle_id"], identity["company_id"], plan_digest)
    application = local.db.execute(
        "SELECT plan_digest,inventory_payload_digest,remote_projection_digest,state "
        "FROM exact_local_applications WHERE apply_id=? AND cycle=? AND company=?",
        (apply_id, identity["cycle_id"], identity["company_id"])).fetchone()
    ack = local.db.execute(
        "SELECT selected_fields_digest FROM exact_local_acknowledgements "
        "WHERE apply_id=? AND receipt_id=? AND acknowledgement_id=?",
        (apply_id, receipt_id, acknowledgement_id)).fetchone()
    if (publication["local_apply_id"] != apply_id
            or application != (plan_digest, inventory_digest, projection_digest, VERIFIED)
            or ack is None or not isinstance(ack[0], str) or re.fullmatch(r"[0-9a-f]{64}", ack[0]) is None):
        raise ValueError("retained_operator_terminal_local_acknowledgement_changed")
    queue = publication["queue_evidence"]
    directory = Path(local.path).resolve().parent / "retained-first-pass" / (
        "retained-" + hashlib.sha256(reservation_digest.encode("utf-8")).hexdigest()[:24])
    expected = {"reservation_digest": reservation_digest, "cycle_id": identity["cycle_id"],
                "company_id": identity["company_id"], "plan_digest": plan_digest,
                "receipt_id": receipt_id, "acknowledgement_id": acknowledgement_id,
                "output_dir": str(directory)}
    if (not isinstance(queue, dict) or digest(queue) != publication["queue_evidence_digest"]
            or any(queue.get(key) != value for key, value in expected.items())
            or directory.resolve() != directory or _read_release(directory) != queue):
        raise ValueError("retained_operator_terminal_queue_evidence_changed")
    return queue


def _acknowledge_selected_dirty(local, exact_scope, readback, *, plan_digest,
                                receipt_id, acknowledgement_id):
    """Persist the exact readback and clear only equal selected dirty fields."""
    from .exact_cycle_planner import _digest
    selected_digest = _digest(readback["rows"])
    with local.transaction():
        parent = local.db.execute(
            "SELECT apply_id,plan_digest,state FROM exact_local_applications "
            "WHERE plan_digest=?", (plan_digest,)).fetchone()
        if parent is None or parent[1:] != (plan_digest, VERIFIED):
            raise ValueError("retained_publication_local_plan_not_verified")
        prior = local.db.execute(
            "SELECT acknowledgement_id,selected_fields_digest "
            "FROM exact_local_acknowledgements WHERE apply_id=? AND receipt_id=?",
            (parent[0], receipt_id)).fetchone()
        if prior is not None:
            if prior != (acknowledgement_id, selected_digest):
                raise ValueError("retained_publication_acknowledgement_changed")
            return {"apply_id": parent[0], "recovered": True}
        for evidence, observed in zip(exact_scope["rows"], readback["rows"]):
            if any(observed.get(key) != evidence.get(key)
                   for key in ("tab", "row_id", "identity", "fields", "sent")):
                raise ValueError("retained_publication_readback_binding_changed")
            row = local.row(evidence["tab"], evidence["row_id"])
            if row is None or any(not _equivalent(name, row.get(name, ""), value)
                                  for name, value in evidence["identity"].items()):
                raise ValueError("retained_publication_local_identity_changed")
            if any(not _equivalent(name, row.get(name, ""), value)
                   for name, value in evidence.get("guards", {}).items()):
                raise ValueError("retained_publication_local_guard_changed")
            baseline = local.baseline(evidence["tab"], evidence["row_id"]) or {}
            for header in evidence["fields"]:
                actual = observed["actual"].get(header, "")
                sent = evidence["sent"].get(header, "")
                if not _equivalent(header, actual, sent):
                    raise ValueError("retained_publication_remote_value_changed")
                baseline[header] = actual
                if _equivalent(header, row.get(header, ""), sent):
                    local.db.execute(
                        "DELETE FROM dirty WHERE tab=? AND row_id=? AND header=?",
                        (evidence["tab"], evidence["row_id"], header))
            local._baseline(evidence["tab"], evidence["row_id"], baseline)
        local.db.execute(
            "INSERT INTO exact_local_acknowledgements VALUES (?,?,?,?,?)",
            (parent[0], receipt_id, acknowledgement_id,
             selected_digest, timestamp()))
    return {"apply_id": parent[0], "recovered": False}


def _publish_retained_reservation_locked(reservation_digest, store, local,
                                         remote, *, synchronizer=None,
                                         max_operations=100, runtime_binding=None):
    """Publish exactly one frozen retained reservation, with readback recovery.

    A claimed chunk is never committed again: a subsequent invocation only
    reads it back and either confirms it or leaves it claimed for manual
    recovery.  Network calls intentionally occur outside SQLite transactions.
    """
    if type(max_operations) is not int or max_operations < 1:
        raise ValueError("retained_publication_chunk_limit_invalid")
    session, plan, application = _verified_session(reservation_digest, store, local, runtime_binding)
    identity = {"reservation_digest": reservation_digest}
    if runtime_binding is not None:
        identity["runtime_binding_sha256"] = plan["runtime_binding_sha256"]
    publication = retained_publication(local, reservation_digest)
    if publication["state"] == FIRST_PASS_RELEASED:
        if runtime_binding is not None:
            _verify_operator_terminal_receipt(reservation_digest, session, local, runtime_binding=runtime_binding)
        provenance = confirm_remote_from_session(
            local, reservation_digest, plan, session_store=store)
        first_pass = release_retained_first_pass(
            local, reservation_digest, plan,
            Path(store.path).parent / "retained-first-pass")
        settlement = settle_retained_start(
            Path(store.path).parent, local.path, reservation_digest)
        return {**identity,
                "state": FIRST_PASS_RELEASED,
                "session_state": session["state"],
                "receipt_id": session["receipt_id"],
                "acknowledgement_id": session["acknowledgement_id"],
                "provenance": provenance, "first_pass": first_pass,
                "settlement": settlement}
    requested_url = plan.get("requested_url") or local.matches(
        "Companies", {"Company ID": session["company_id"]})[0][1].get("Official Careers URL")
    if synchronizer is None:
        sync = SheetsSynchronizer(local, remote)
    elif (not isinstance(synchronizer, SheetsSynchronizer)
          or synchronizer.local is not local or synchronizer.remote is not remote):
        raise ValueError("retained_publication_synchronizer_binding_invalid")
    else:
        sync = synchronizer
    # Fresh controls before scope sealing; plan_exact_scope binds only the
    # verified local row scope and frozen remote projection.
    controls = _company_guard(
        local, remote, session["company_id"], requested_url)
    _validate_controls(plan, controls)
    exact_scope = (session["exact_scope"] if session.get("exact_scope") is not None
                   else sync.plan_exact_scope(
                       application["row_scope"], plan["remote_projection"]))
    session = store.freeze_remote_intent(
        reservation_digest, exact_scope=exact_scope)
    bind_remote_session(
        local, reservation_digest, plan, session_store=store)

    while session["state"] != SYNC_CONFIRMED and session["remote_cursor"] < len(exact_scope["operations"]):
        remaining = len(exact_scope["operations"]) - session["remote_cursor"]
        operation_count = min(max_operations, remaining)
        if runtime_binding is not None:
            # Only an unclaimed suffix may use a new batch limit. Reopen the
            # recorded claim at its original count so it remains readback-only.
            prior = next((item for item in session["chunks"]
                          if item["start_cursor"] == session["remote_cursor"]), None)
            if prior is not None:
                if prior["state"] != "CLAIMED":
                    raise ValueError("retained_operator_remote_cursor_changed")
                operation_count = prior["operation_count"]
        claim = store.claim_chunk(reservation_digest, operation_count=operation_count)
        chunk = claim["exact_scope"]
        if claim["dispatch_allowed"]:
            # Re-check both Company controls and selected local guards at the
            # write boundary.  A change leaves the durable claim in place.
            current_controls = _company_guard(
                local, remote, session["company_id"], requested_url)
            _validate_controls(plan, current_controls)
            sync._revalidate_exact_rows(chunk)
            remote.commit(chunk["operations"])
        latest = store.load(reservation_digest)
        readback = sync.readback_exact_scope(
            chunk, receipt_id=latest["receipt_id"], intent_id=latest["intent_id"],
            intent_projection_digest=chunk["projection_digest"])
        session = store.confirm_chunk_readback(
            reservation_digest, claim_id=claim["claim_id"], readback=readback)

    session = store.load(reservation_digest)
    full = sync.readback_exact_scope(
        exact_scope, receipt_id=session["receipt_id"], intent_id=session["intent_id"],
        intent_projection_digest=exact_scope["projection_digest"])
    session = store.confirm_readback(reservation_digest, readback=full)
    _acknowledge_selected_dirty(
        local, exact_scope, full, plan_digest=plan["plan_digest"],
        receipt_id=session["receipt_id"],
        acknowledgement_id=session["acknowledgement_id"])
    provenance = confirm_remote_from_session(
        local, reservation_digest, plan, session_store=store)
    first_pass = release_retained_first_pass(
        local, reservation_digest, plan,
        Path(store.path).parent / "retained-first-pass")
    if runtime_binding is not None:
        _verify_operator_terminal_receipt(reservation_digest, session, local, runtime_binding=runtime_binding)
    settlement = settle_retained_start(
        Path(store.path).parent, local.path, reservation_digest)
    return {**identity,
            "state": FIRST_PASS_RELEASED, "session_state": session["state"],
            "receipt_id": session["receipt_id"],
            "acknowledgement_id": session["acknowledgement_id"],
            "provenance": provenance, "first_pass": first_pass,
            "settlement": settlement}


def publish_retained_reservation(reservation_digest, store, local, remote, *,
                                 synchronizer=None, max_operations=100):
    """Serialize one retained delivery against normal scraper lifecycle work."""
    from .cli import scraper_lock_name, writer_lock
    root = Path(store.path).resolve().parent
    # The retained store belongs beside the normal state files.  Use that same
    # lock domain; a private lock would still permit a normal start/recovery to
    # race Company controls, dirty provenance, or the one-shot remote claim.
    with writer_lock(root / scraper_lock_name()):
        return _publish_retained_reservation(
            reservation_digest, store, local, remote, synchronizer=synchronizer,
            max_operations=max_operations)


def _publish_retained_reservation(reservation_digest, store, local, remote, *,
                                  synchronizer=None, max_operations=100, runtime_binding=None):
    """Take the private publisher lock after the caller's scraper lock.

    The pinned operator orchestrator also owns writer.lock before entry.
    """
    from .cli import writer_lock
    lock_path = Path(store.path).resolve().parent / "retained-publication.lock"
    with writer_lock(lock_path):
        return _publish_retained_reservation_locked(
            reservation_digest, store, local, remote,
            synchronizer=synchronizer, max_operations=max_operations,
            runtime_binding=runtime_binding)
