"""Reservation-only publisher for a sealed retained-work exact plan.

It deliberately does not accept ordinary cycle, inbox, receipt, plan, cursor,
or readback arguments.  Those facts are read from ``RetainedSessionStore``.
"""
from __future__ import annotations

from contextlib import closing
import hashlib
from pathlib import Path
import re

from .exact_cycle_planner import _exact_plan_digest
from .exact_local_plan import VERIFIED, _apply_id, exact_local_plan, verify_exact_local_plan
from .exact_cycle_sync import _company_guard, _validate_controls
from .repository import _equivalent
from .retained_dirty_provenance import (
    FIRST_PASS_RELEASED, REMOTE_CONFIRMED, REMOTE_PENDING, _session_binding, _verify_cells,
    bind_remote_session, confirm_remote_from_session, retained_publication, verify_dirty_provenance,
)
from .retained_first_pass import _read_release, release_retained_first_pass
from .retained_session_store import (
    SYNC_CONFIRMED, SYNC_PENDING, RetainedSessionStore, _IDENTITY_FIELDS, _intent_id, _receipt_id,
)
from .retained_work_runner import _read_existing_journal, digest, settle_retained_start
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


def recover_claimed_retained_chunk(reservation_digest, store, local, remote_reader, *,
                                   claim_id, runtime_binding):
    """Confirm one named pre-dispatch claim with exact Sheets reads only.

    The caller holds the scraper and writer leases and authenticates the
    original frozen approval/reservation before entry. Local jobs storage
    must be read-only. The sole write is confirmation of the existing claim
    in its private session store. An unclaimed suffix stays unclaimed.
    """
    from .cli import writer_lock
    root = _retained_readback_root(reservation_digest, store, local, claim_id, runtime_binding)
    with writer_lock(root / "retained-publication.lock"):
        session = store.load(reservation_digest)
        _validate_claim_readback_session(reservation_digest, session, local, runtime_binding)
        claim, chunk = _retained_readback_chunk(session, claim_id)
        if claim["state"] == "CLAIMED":
            sync = SheetsSynchronizer(local, remote_reader())
            readback = sync.readback_exact_scope(
                chunk, receipt_id=session["receipt_id"], intent_id=session["intent_id"],
                intent_projection_digest=chunk["projection_digest"],
            )
            session = store.confirm_chunk_readback(
                reservation_digest, claim_id=claim_id, readback=readback,
            )
            claim, _ = _retained_readback_chunk(session, claim_id)
            if claim["state"] != "CONFIRMED":
                raise ValueError("retained_claim_readback_confirmation_missing")
        remaining = len(session["projection"]) - session["remote_cursor"]
        return {
            "state": "HELD_UNCLAIMED_SUFFIX" if remaining else "READY_FOR_FULL_READBACK",
            "reservation_digest": reservation_digest, "claim_id": claim_id,
            "start_cursor": claim["start_cursor"], "operation_count": claim["operation_count"],
            "readback_digest": claim["readback_digest"], "remote_cursor": session["remote_cursor"],
            "unclaimed_operations": remaining, "receipt_id": session["receipt_id"],
            "intent_id": session["intent_id"], "session_state": session["state"],
        }


def finish_confirmed_retained_publication(reservation_digest, store, local, remote_reader,
                                          jobs_writer, *, claim_id, runtime_binding):
    """Settle a fully claimed reservation without any remote write capability.

    The caller authenticates the original binding and holds the scraper and
    writer leases. A read-only jobs connection and an exact final claim are
    required. The lazy jobs writer opens only for confirmed full readback.
    """
    from .cli import writer_lock

    root = _retained_readback_root(reservation_digest, store, local, claim_id, runtime_binding)
    with writer_lock(root / "retained-publication.lock"):
        session = store.load(reservation_digest)
        publication = _validate_terminal_readback_session(reservation_digest, session, local, runtime_binding)
        claim, _ = _retained_readback_chunk(session, claim_id)
        if claim["state"] != "CONFIRMED" or session["remote_cursor"] != len(session["projection"]):
            raise ValueError("retained_terminal_readback_claims_incomplete")
        _validate_terminal_start(root, reservation_digest, session, publication)

        exact_scope = session["exact_scope"]
        sync = SheetsSynchronizer(local, remote_reader())
        full = sync.readback_exact_scope(
            exact_scope, receipt_id=session["receipt_id"], intent_id=session["intent_id"],
            intent_projection_digest=session["projection_digest"],
        )
        _verify_full_claim_evidence(session, full)
        session = store.confirm_readback(reservation_digest, readback=full)
        selected_digest = digest(full["rows"])
        _validate_terminal_readback_session(
            reservation_digest, session, local, runtime_binding, selected_digest=selected_digest,
        )
        if publication["state"] != FIRST_PASS_RELEASED:
            with closing(jobs_writer()) as writer:
                if (getattr(writer, "readonly", None) is not False
                        or Path(writer.path).resolve() != root / "jobs.sqlite3"
                        or writer.spreadsheet_id != local.spreadsheet_id):
                    raise ValueError("retained_terminal_readback_writer_changed")
                _validate_terminal_readback_session(
                    reservation_digest, session, writer, runtime_binding, selected_digest=selected_digest,
                )
                _acknowledge_selected_dirty(
                    writer, exact_scope, full, plan_digest=session["plan_digest"],
                    receipt_id=session["receipt_id"], acknowledgement_id=session["acknowledgement_id"],
                )
                confirm_remote_from_session(writer, reservation_digest, session["plan"], session_store=store)
                release_retained_first_pass(writer, reservation_digest, session["plan"], root / "retained-first-pass")
        first_pass = _verify_operator_terminal_receipt(
            reservation_digest, session, local, runtime_binding=runtime_binding,
        )
        settlement = settle_retained_start(root, local.path, reservation_digest)
        return {
            "state": FIRST_PASS_RELEASED, "session_state": session["state"],
            "reservation_digest": reservation_digest, "claim_id": claim_id,
            "receipt_id": session["receipt_id"], "intent_id": session["intent_id"],
            "acknowledgement_id": session["acknowledgement_id"],
            "first_pass": first_pass, "settlement": settlement,
        }


def _retained_readback_root(reservation_digest, store, local, claim_id, runtime_binding):
    if (not _is_sha256(reservation_digest) or not _is_sha256(claim_id)
            or runtime_binding is None or not isinstance(store, RetainedSessionStore)
            or getattr(local, "readonly", None) is not True):
        raise ValueError("retained_claim_readback_binding_invalid")
    session_path = Path(store.path).resolve()
    root = session_path.parent
    if (session_path.name != "retained-sessions.sqlite3"
            or Path(local.path).resolve() != root / "jobs.sqlite3"):
        raise ValueError("retained_claim_readback_store_changed")
    return root


def _validate_terminal_start(root, reservation_digest, session, publication):
    start = _read_existing_journal(root / "retained-work-starts.sqlite3")
    if start is None:
        if publication["state"] != FIRST_PASS_RELEASED:
            raise ValueError("retained_terminal_readback_start_missing")
        return
    expected = {"request_id": session["request_id"], "event_id": session["event_id"],
                "company_id": session["company_id"], "manifest_digest": session["manifest_digest"],
                "reservation_digest": reservation_digest}
    if (start["state"] != "FROZEN" or start["binding_digest"] != session["start_binding_digest"]
            or any(start["binding"].get(key) != value for key, value in expected.items())):
        raise ValueError("retained_terminal_readback_start_binding_changed")


def _verify_full_claim_evidence(session, full):
    for claim in session["chunks"]:
        start = claim["start_cursor"]
        stop = start + claim["operation_count"]
        expected = digest({
            "receipt_id": session["receipt_id"], "intent_id": session["intent_id"],
            "projection_digest": claim["operation_digest"], "observed": full["rows"][start:stop],
        })
        if claim["readback_digest"] != expected:
            raise ValueError("retained_terminal_readback_claim_evidence_changed")


def _validate_terminal_readback_session(reservation_digest, session, local, runtime_binding, *,
                                        selected_digest=None):
    acknowledgement = session["acknowledgement_id"]
    if not ((session["state"] == SYNC_PENDING and acknowledgement is None)
            or (session["state"] == SYNC_CONFIRMED and _is_sha256(acknowledgement))):
        raise ValueError("retained_terminal_readback_session_changed")
    apply_id = _apply_id(session["cycle_id"], session["company_id"], session["plan_digest"])
    accepted = local.db.execute(
        "SELECT acknowledgement_id,selected_fields_digest FROM exact_local_acknowledgements "
        "WHERE apply_id=? AND receipt_id=?", (apply_id, session["receipt_id"]),
    ).fetchone()
    if accepted is not None and (
            acknowledgement is None or accepted[0] != acknowledgement or not _is_sha256(accepted[1])
            or (selected_digest is not None and accepted[1] != selected_digest)):
        raise ValueError("retained_terminal_readback_local_acknowledgement_changed")
    publication = _validate_retained_readback_binding(
        reservation_digest, session, local, runtime_binding, cleared=accepted is not None,
    )
    if publication["state"] == REMOTE_PENDING:
        if publication["acknowledgement_id"] is not None:
            raise ValueError("retained_terminal_readback_local_acknowledgement_changed")
    elif (publication["state"] not in {REMOTE_CONFIRMED, FIRST_PASS_RELEASED}
          or accepted is None or publication["acknowledgement_id"] != acknowledgement):
        raise ValueError("retained_terminal_readback_local_acknowledgement_changed")
    return publication


def _is_sha256(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _validate_claim_readback_session(reservation_digest, session, local, runtime_binding):
    if session["state"] != SYNC_PENDING or session["acknowledgement_id"] is not None:
        raise ValueError("retained_claim_readback_requires_pending_session")
    publication = _validate_retained_readback_binding(reservation_digest, session, local, runtime_binding)
    if publication["state"] != REMOTE_PENDING:
        raise ValueError("retained_claim_readback_durable_binding_changed")


def _validate_retained_readback_binding(reservation_digest, session, local, runtime_binding, *, cleared=False):
    plan = session["plan"]
    _verify_retained_plan_runtime(plan, runtime_binding)
    publication, cells_digest = _verify_cells(local, reservation_digest, plan, cleared=cleared)
    _session_binding(publication, session, plan)
    RetainedSessionStore._sealed_scope(session, session["exact_scope"])
    identity = {name: session[name] for name in _IDENTITY_FIELDS}
    receipt = _receipt_id(reservation_digest, identity, session["inventory_digest"],
                          session["plan_digest"], session["projection_digest"])
    intent = _intent_id(receipt, session["projection"])
    apply_id = _apply_id(session["cycle_id"], session["company_id"], session["plan_digest"])
    application = local.db.execute(
        "SELECT plan_digest,inventory_payload_digest,remote_projection_digest,state "
        "FROM exact_local_applications WHERE apply_id=? AND cycle=? AND company=?",
        (apply_id, session["cycle_id"], session["company_id"]),
    ).fetchone()
    if (publication["local_apply_id"] != apply_id
            or publication["cells_digest"] != cells_digest
            or (session["receipt_id"], session["intent_id"]) != (receipt, intent)
            or (publication["receipt_id"], publication["intent_id"],
                publication["intent_projection_digest"]) != (receipt, intent, session["projection_digest"])
            or application != (session["plan_digest"], session["inventory_digest"],
                               session["projection_digest"], VERIFIED)):
        raise ValueError("retained_claim_readback_durable_binding_changed")
    return publication


def _retained_readback_chunk(session, claim_id):
    """Re-derive the contiguous prefix and the one stored claim without claiming."""
    cursor = 0
    outstanding = None
    selected = None
    projection_length = len(session["projection"])
    for claim in session["chunks"]:
        count = claim["operation_count"]
        if (outstanding is not None or claim["start_cursor"] != cursor
                or type(count) is not int or not 1 <= count <= projection_length - cursor):
            raise ValueError("retained_claim_readback_cursor_changed")
        chunk = RetainedSessionStore._scope_slice(session, cursor, count)
        expected_id = digest({"version": "retained-chunk-v1", "intent_id": session["intent_id"],
                              "start_cursor": cursor, "operation_digest": chunk["projection_digest"]})
        if (claim["claim_id"], claim["operation_digest"]) != (expected_id, chunk["projection_digest"]):
            raise ValueError("retained_claim_readback_claim_binding_changed")
        if claim["state"] == "CONFIRMED" and _is_sha256(claim["readback_digest"]):
            cursor += count
        elif claim["state"] == "CLAIMED" and claim["readback_digest"] is None:
            outstanding = claim
        else:
            raise ValueError("retained_claim_readback_claim_binding_changed")
        if claim["claim_id"] == claim_id:
            selected = (claim, chunk)
    if session["remote_cursor"] != cursor:
        raise ValueError("retained_claim_readback_cursor_changed")
    if (selected is None
            or (outstanding is not None and selected[0] != outstanding)
            or (outstanding is None and selected[0]["start_cursor"] + selected[0]["operation_count"] != cursor)):
        raise ValueError("retained_claim_readback_exact_claim_missing")
    return selected


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
                                         max_operations=100, runtime_binding=None,
                                         authorization_expires_at=None, authorization_now=None):
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
        prior = None
        if runtime_binding is not None:
            # Only an unclaimed suffix may use a new batch limit. Reopen the
            # recorded claim at its original count so it remains readback-only.
            prior = next((item for item in session["chunks"]
                          if item["start_cursor"] == session["remote_cursor"]), None)
            if prior is not None:
                if prior["state"] != "CLAIMED":
                    raise ValueError("retained_operator_remote_cursor_changed")
                operation_count = prior["operation_count"]
        if prior is None and authorization_expires_at is not None:
            from .selected_recovery_authorization import _expiry
            _expiry(authorization_expires_at, authorization_now)
        claim = store.claim_chunk(reservation_digest, operation_count=operation_count)
        chunk = claim["exact_scope"]
        if claim["dispatch_allowed"]:
            # Re-check both Company controls and selected local guards at the
            # write boundary.  A change leaves the durable claim in place.
            current_controls = _company_guard(
                local, remote, session["company_id"], requested_url)
            _validate_controls(plan, current_controls)
            sync._revalidate_exact_rows(chunk)
            if authorization_expires_at is not None:
                from .selected_recovery_authorization import _expiry
                _expiry(authorization_expires_at, authorization_now)
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
                                  synchronizer=None, max_operations=100, runtime_binding=None,
                                  authorization_expires_at=None, authorization_now=None):
    """Take the private publisher lock after the caller's scraper lock.

    The pinned operator orchestrator also owns writer.lock before entry.
    """
    from .cli import writer_lock
    lock_path = Path(store.path).resolve().parent / "retained-publication.lock"
    with writer_lock(lock_path):
        return _publish_retained_reservation_locked(
            reservation_digest, store, local, remote,
            synchronizer=synchronizer, max_operations=max_operations,
            runtime_binding=runtime_binding, authorization_expires_at=authorization_expires_at,
            authorization_now=authorization_now)
