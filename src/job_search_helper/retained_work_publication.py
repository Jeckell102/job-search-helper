"""Reservation-only publisher for a sealed retained-work exact plan.

It deliberately does not accept ordinary cycle, inbox, receipt, plan, cursor,
or readback arguments.  Those facts are read from ``RetainedSessionStore``.
"""
from __future__ import annotations

from pathlib import Path

from .exact_local_plan import VERIFIED, exact_local_plan, verify_exact_local_plan
from .exact_cycle_sync import _company_guard, _validate_controls
from .repository import _equivalent
from .retained_dirty_provenance import (
    FIRST_PASS_RELEASED, bind_remote_session, confirm_remote_from_session,
    retained_publication, verify_dirty_provenance,
)
from .retained_first_pass import release_retained_first_pass
from .retained_session_store import SYNC_CONFIRMED
from .retained_work_runner import settle_retained_start
from .sheets_sync import SheetsSynchronizer
from .sqlite_repository import timestamp


def _verified_session(reservation_digest, store, local):
    session = store.load(reservation_digest)
    plan = session["plan"]
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
                                         max_operations=100):
    """Publish exactly one frozen retained reservation, with readback recovery.

    A claimed chunk is never committed again: a subsequent invocation only
    reads it back and either confirms it or leaves it claimed for manual
    recovery.  Network calls intentionally occur outside SQLite transactions.
    """
    if type(max_operations) is not int or max_operations < 1:
        raise ValueError("retained_publication_chunk_limit_invalid")
    session, plan, application = _verified_session(reservation_digest, store, local)
    publication = retained_publication(local, reservation_digest)
    if publication["state"] == FIRST_PASS_RELEASED:
        provenance = confirm_remote_from_session(
            local, reservation_digest, plan, session_store=store)
        first_pass = release_retained_first_pass(
            local, reservation_digest, plan,
            Path(store.path).parent / "retained-first-pass")
        settlement = settle_retained_start(
            Path(store.path).parent, local.path, reservation_digest)
        return {"reservation_digest": reservation_digest,
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
        claim = store.claim_chunk(reservation_digest, operation_count=min(max_operations, remaining))
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
    settlement = settle_retained_start(
        Path(store.path).parent, local.path, reservation_digest)
    return {"reservation_digest": reservation_digest,
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
                                  synchronizer=None, max_operations=100):
    """Serialize the complete retained publication/recovery transition."""
    from .cli import writer_lock
    lock_path = Path(store.path).resolve().parent / "retained-publication.lock"
    with writer_lock(lock_path):
        return _publish_retained_reservation_locked(
            reservation_digest, store, local, remote,
            synchronizer=synchronizer, max_operations=max_operations)
