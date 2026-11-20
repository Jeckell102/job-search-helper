"""Reservation-bound provenance for exceptional exact local publication.

The retained-work path is allowed to create only the dirty cells produced by
one frozen v2 plan.  This journal lives beside ``dirty`` in jobs.sqlite3 so a
local mutation and the evidence naming its cells commit in one transaction.
It does not publish, read Google, or discover another cycle or Company.
"""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Mapping

from .repository import RepositoryError
from .sqlite_repository import timestamp


RESERVED = "RESERVED"
LOCAL_VERIFIED = "LOCAL_VERIFIED"
REMOTE_PENDING = "REMOTE_PENDING"
REMOTE_CONFIRMED = "REMOTE_CONFIRMED"
FIRST_PASS_RELEASED = "FIRST_PASS_RELEASED"


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def _digest(value):
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _required_text(name, value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("retained_dirty_%s_invalid" % name)
    return value.strip()


def _install(repository):
    if getattr(repository, "readonly", True):
        raise RepositoryError(
            "Retained dirty provenance requires a writable local repository.")
    repository.db.executescript("""
    CREATE TABLE IF NOT EXISTS retained_publications (
      reservation_digest TEXT PRIMARY KEY,
      request_id TEXT NOT NULL,
      event_id TEXT NOT NULL,
      exception_cycle TEXT NOT NULL,
      cycle TEXT NOT NULL UNIQUE,
      company TEXT NOT NULL,
      source_revision TEXT NOT NULL,
      manifest_digest TEXT NOT NULL,
      start_binding_digest TEXT NOT NULL,
      plan_digest TEXT NOT NULL UNIQUE,
      remote_projection_digest TEXT NOT NULL,
      local_apply_id TEXT,
      cells_digest TEXT,
      receipt_id TEXT,
      intent_id TEXT,
      intent_projection_digest TEXT,
      acknowledgement_id TEXT,
      queue_evidence TEXT,
      queue_evidence_digest TEXT,
      state TEXT NOT NULL CHECK(state IN
        ('RESERVED','LOCAL_VERIFIED','REMOTE_PENDING','REMOTE_CONFIRMED',
         'FIRST_PASS_RELEASED')),
      created_at TEXT NOT NULL,
      local_verified_at TEXT,
      remote_confirmed_at TEXT,
      first_pass_released_at TEXT
    );
    CREATE TABLE IF NOT EXISTS retained_dirty_cells (
      reservation_digest TEXT NOT NULL,
      tab TEXT NOT NULL,
      row_id INTEGER NOT NULL,
      header TEXT NOT NULL,
      identity TEXT NOT NULL,
      identity_digest TEXT NOT NULL,
      value_digest TEXT NOT NULL,
      start_cursor INTEGER NOT NULL,
      PRIMARY KEY(reservation_digest,tab,row_id,header),
      FOREIGN KEY(reservation_digest)
        REFERENCES retained_publications(reservation_digest)
    );
    CREATE TABLE IF NOT EXISTS retained_dirty_chunks (
      reservation_digest TEXT NOT NULL,
      apply_id TEXT NOT NULL,
      start_cursor INTEGER NOT NULL,
      operation_count INTEGER NOT NULL,
      cells_digest TEXT NOT NULL,
      recorded_at TEXT NOT NULL,
      PRIMARY KEY(reservation_digest,start_cursor),
      FOREIGN KEY(reservation_digest)
        REFERENCES retained_publications(reservation_digest)
    );
    """)


def _validate_plan(plan, cycle_id, company_id):
    from .exact_cycle_planner import _exact_plan_digest
    if (not isinstance(plan, Mapping) or plan.get("exact_plan_version") != 2
            or plan.get("cycle_id") != cycle_id
            or plan.get("company_id") != company_id
            or plan.get("plan_digest") != _exact_plan_digest(plan)
            or not isinstance(plan.get("remote_projection"), list)
            or not plan["remote_projection"]
            or plan.get("remote_projection_digest")
            != _digest(plan["remote_projection"])):
        raise ValueError("retained_dirty_exact_plan_invalid")


def _dirty(repository):
    return {(str(tab), int(row_id), str(header)) for tab, row_id, header
            in repository.db.execute(
                "SELECT tab,row_id,header FROM dirty ORDER BY tab,row_id,header")}


def _identity(operation):
    identity = copy.deepcopy(operation.get("identity", {}))
    if not isinstance(identity, dict) or not identity:
        raise ValueError("retained_dirty_operation_identity_invalid")
    for values in (operation.get("on_insert", {}), operation.get("values", {})):
        if not isinstance(values, Mapping):
            raise ValueError("retained_dirty_operation_values_invalid")
        for key in tuple(identity):
            if key in values:
                identity[key] = copy.deepcopy(values[key])
    return identity


def _targets(repository, plan):
    targets = {}
    for operation in plan["remote_projection"]:
        tab = operation.get("tab")
        identity = _identity(operation)
        matches = repository.matches(tab, identity)
        if len(matches) != 1:
            raise ValueError("retained_dirty_identity_missing_or_ambiguous")
        row_id = matches[0][0]
        key = (tab, row_id)
        if key in targets:
            raise ValueError("retained_dirty_repeated_target")
        fields = set(identity)
        for name in ("on_insert", "values", "append_notes"):
            values = operation.get(name, {})
            if not isinstance(values, Mapping):
                raise ValueError("retained_dirty_operation_values_invalid")
            fields.update(values)
        targets[key] = {"identity": identity, "fields": fields}
    return targets


def _publication_row(repository, reservation_digest):
    row = repository.db.execute(
        "SELECT request_id,event_id,exception_cycle,cycle,company,source_revision,"
        "manifest_digest,start_binding_digest,plan_digest,remote_projection_digest,"
        "local_apply_id,cells_digest,receipt_id,intent_id,"
        "intent_projection_digest,acknowledgement_id,queue_evidence,"
        "queue_evidence_digest,state FROM retained_publications "
        "WHERE reservation_digest=?", (reservation_digest,)).fetchone()
    if row is None:
        raise ValueError("retained_dirty_reservation_missing")
    keys = ("request_id", "event_id", "exception_cycle", "cycle", "company",
            "source_revision", "manifest_digest", "start_binding_digest",
            "plan_digest", "remote_projection_digest", "local_apply_id",
            "cells_digest", "receipt_id", "intent_id",
            "intent_projection_digest", "acknowledgement_id", "queue_evidence",
            "queue_evidence_digest", "state")
    return dict(zip(keys, row))


def _require_inbox(repository, inbox):
    from .inbox import InventoryInbox
    if not isinstance(inbox, InventoryInbox):
        raise ValueError("retained_dirty_durable_inbox_required")
    with inbox.lock:
        destinations = inbox.connection.execute(
            "SELECT id FROM destination").fetchall()
    if destinations != [(repository.spreadsheet_id,)]:
        raise ValueError("retained_dirty_inbox_destination_mismatch")
    return inbox


def reserve_dirty_provenance(repository, *, reservation_digest, request_id,
                             event_id, exception_cycle_id, cycle_id, company_id,
                             source_revision, manifest_digest,
                             start_binding_digest, plan):
    """Freeze one clean-start publication boundary before local mutation."""
    values = {
        "reservation_digest": _required_text("reservation_digest", reservation_digest),
        "request_id": _required_text("request_id", request_id),
        "event_id": _required_text("event_id", event_id),
        "exception_cycle": _required_text("exception_cycle", exception_cycle_id),
        "cycle": _required_text("cycle", cycle_id),
        "company": _required_text("company", company_id),
        "source_revision": _required_text("source_revision", source_revision),
        "manifest_digest": _required_text("manifest_digest", manifest_digest),
        "start_binding_digest": _required_text(
            "start_binding_digest", start_binding_digest),
    }
    if values["exception_cycle"] == values["cycle"]:
        raise ValueError("retained_dirty_historical_cycle_selected")
    _validate_plan(plan, values["cycle"], values["company"])
    _install(repository)
    expected = (
        values["request_id"], values["event_id"], values["exception_cycle"],
        values["cycle"], values["company"], values["source_revision"],
        values["manifest_digest"], values["start_binding_digest"],
        plan["plan_digest"], plan["remote_projection_digest"],
    )
    with repository.transaction():
        row = repository.db.execute(
            "SELECT request_id,event_id,exception_cycle,cycle,company,source_revision,"
            "manifest_digest,start_binding_digest,plan_digest,"
            "remote_projection_digest,state FROM retained_publications "
            "WHERE reservation_digest=?", (values["reservation_digest"],)).fetchone()
        if row is None:
            # The frozen intake hold is the pre-plan generic-sync embargo.
            # Claim it atomically with this ledger row, which immediately
            # replaces it as the synchronizer-visible hold.
            table = repository.db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='retained_intake_holds'").fetchone()
            if not table:
                raise ValueError("retained_dirty_intake_hold_missing")
            hold = repository.db.execute(
                "SELECT request_id,event_id,company_id,manifest_digest,"
                "start_binding_digest,state FROM retained_intake_holds "
                "WHERE reservation_digest=?", (values["reservation_digest"],)).fetchone()
            expected_hold = (values["request_id"], values["event_id"],
                             values["company"], values["manifest_digest"],
                             values["start_binding_digest"], "FROZEN")
            if hold != expected_hold:
                raise ValueError("retained_dirty_intake_hold_changed")
            if _dirty(repository):
                raise ValueError("retained_dirty_preexisting_cells")
            repository.db.execute(
                "INSERT INTO retained_publications("
                "reservation_digest,request_id,event_id,exception_cycle,cycle,company,"
                "source_revision,manifest_digest,start_binding_digest,plan_digest,"
                "remote_projection_digest,state,created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (values["reservation_digest"], *expected, RESERVED, timestamp()))
            repository.db.execute(
                "DELETE FROM retained_intake_holds WHERE reservation_digest=? "
                "AND request_id=? AND event_id=? AND company_id=? "
                "AND manifest_digest=? AND start_binding_digest=? AND state='FROZEN'",
                (values["reservation_digest"], *expected_hold[:-1]))
            state = RESERVED
        else:
            state = row[-1]
            if (tuple(row[:-1]) != expected
                    or state not in {RESERVED, LOCAL_VERIFIED, REMOTE_PENDING,
                                     REMOTE_CONFIRMED, FIRST_PASS_RELEASED}):
                raise ValueError("retained_dirty_reservation_changed")
            ledger = {(tab, row_id, header) for tab, row_id, header
                      in repository.db.execute(
                          "SELECT tab,row_id,header FROM retained_dirty_cells "
                          "WHERE reservation_digest=?", (values["reservation_digest"],))}
            current = _dirty(repository)
            if state in {RESERVED, LOCAL_VERIFIED} and current != ledger:
                raise ValueError("retained_dirty_reservation_changed")
            if state == REMOTE_PENDING and current not in (ledger, set()):
                raise ValueError("retained_dirty_reservation_changed")
            if state in {REMOTE_CONFIRMED, FIRST_PASS_RELEASED} and current:
                raise ValueError("retained_dirty_reservation_changed")
    return {**values, "plan_digest": plan["plan_digest"], "state": state}


def record_dirty_provenance_chunk(repository, reservation_digest, *, apply_id,
                                  start_cursor, operation_count, plan,
                                  dirty_before, dirty_after):
    """Record the exact new dirty cells inside the caller's mutation transaction."""
    reservation_digest = _required_text("reservation_digest", reservation_digest)
    apply_id = _required_text("apply_id", apply_id)
    if (type(start_cursor) is not int or start_cursor < 0
            or type(operation_count) is not int or operation_count < 1):
        raise ValueError("retained_dirty_chunk_boundary_invalid")
    publication = _publication_row(repository, reservation_digest)
    _validate_plan(plan, publication["cycle"], publication["company"])
    if (publication["state"] != RESERVED
            or publication["plan_digest"] != plan["plan_digest"]
            or publication["remote_projection_digest"]
            != plan["remote_projection_digest"]
            or publication["local_apply_id"] not in (None, apply_id)):
        raise ValueError("retained_dirty_publication_binding_changed")
    before = {tuple(item) for item in dirty_before}
    after = {tuple(item) for item in dirty_after}
    journaled = {(tab, row_id, header) for tab, row_id, header
                 in repository.db.execute(
                     "SELECT tab,row_id,header FROM retained_dirty_cells "
                     "WHERE reservation_digest=?", (reservation_digest,))}
    if before != journaled or not before <= after:
        raise ValueError("retained_dirty_unjournaled_cell_present")
    added = after - before
    targets = _targets(repository, plan)
    records = []
    for tab, row_id, header in sorted(added):
        target = targets.get((tab, row_id))
        if target is None or header not in target["fields"]:
            raise ValueError("retained_dirty_cell_outside_frozen_scope")
        row = repository.row(tab, row_id)
        identity = target["identity"]
        if row is None or any(row.get(key, "") != value
                              for key, value in identity.items()):
            raise ValueError("retained_dirty_cell_identity_changed")
        records.append((reservation_digest, tab, row_id, header,
                        _canonical(identity), _digest(identity),
                        _digest(row.get(header, "")), start_cursor))
    cells_digest = _digest([
        {"tab": row[1], "row_id": row[2], "header": row[3],
         "identity_digest": row[5], "value_digest": row[6]}
        for row in records
    ])
    existing = repository.db.execute(
        "SELECT apply_id,operation_count,cells_digest FROM retained_dirty_chunks "
        "WHERE reservation_digest=? AND start_cursor=?",
        (reservation_digest, start_cursor)).fetchone()
    expected = (apply_id, operation_count, cells_digest)
    if existing is not None:
        if tuple(existing) != expected:
            raise ValueError("retained_dirty_chunk_changed")
        return {"cells": len(records), "recovered": True}
    repository.db.executemany(
        "INSERT INTO retained_dirty_cells VALUES (?,?,?,?,?,?,?,?)", records)
    repository.db.execute(
        "INSERT INTO retained_dirty_chunks VALUES (?,?,?,?,?,?)",
        (reservation_digest, apply_id, start_cursor, operation_count,
         cells_digest, timestamp()))
    repository.db.execute(
        "UPDATE retained_publications SET local_apply_id=? "
        "WHERE reservation_digest=? AND state=? AND "
        "(local_apply_id IS NULL OR local_apply_id=?)",
        (apply_id, reservation_digest, RESERVED, apply_id))
    return {"cells": len(records), "recovered": False}


def _verify_cells(repository, reservation_digest, plan, *, cleared=False):
    publication = _publication_row(repository, reservation_digest)
    _validate_plan(plan, publication["cycle"], publication["company"])
    rows = repository.db.execute(
        "SELECT tab,row_id,header,identity,identity_digest,value_digest,start_cursor "
        "FROM retained_dirty_cells WHERE reservation_digest=? "
        "ORDER BY tab,row_id,header", (reservation_digest,)).fetchall()
    if not rows:
        raise ValueError("retained_dirty_cells_missing")
    expected_dirty = {(row[0], row[1], row[2]) for row in rows}
    current_dirty = _dirty(repository)
    if current_dirty != (set() if cleared else expected_dirty):
        raise ValueError("retained_dirty_set_changed")
    evidence = []
    for tab, row_id, header, encoded_identity, identity_digest, value_digest, cursor in rows:
        try:
            identity = json.loads(encoded_identity)
        except (TypeError, ValueError) as error:
            raise ValueError("retained_dirty_identity_corrupt") from error
        row = repository.row(tab, row_id)
        if (_digest(identity) != identity_digest or row is None
                or any(row.get(key, "") != value for key, value in identity.items())
                or _digest(row.get(header, "")) != value_digest):
            raise ValueError("retained_dirty_readback_changed")
        evidence.append({"tab": tab, "row_id": row_id, "header": header,
                         "identity_digest": identity_digest,
                         "value_digest": value_digest, "start_cursor": cursor})
    return publication, _digest(evidence)


def verify_dirty_provenance(repository, reservation_digest, plan):
    """Seal the ledger only after the authoritative local plan is VERIFIED."""
    from .exact_local_plan import VERIFIED, exact_local_plan
    reservation_digest = _required_text("reservation_digest", reservation_digest)
    publication, cells_digest = _verify_cells(repository, reservation_digest, plan)
    application = exact_local_plan(
        repository, publication["cycle"], publication["company"])
    chunks = repository.db.execute(
        "SELECT start_cursor,operation_count,state FROM exact_local_apply_chunks "
        "WHERE apply_id=? ORDER BY start_cursor",
        (publication["local_apply_id"],)).fetchall()
    provenance = repository.db.execute(
        "SELECT start_cursor,operation_count FROM retained_dirty_chunks "
        "WHERE reservation_digest=? ORDER BY start_cursor",
        (reservation_digest,)).fetchall()
    if (application is None or application["state"] != VERIFIED
            or application["apply_id"] != publication["local_apply_id"]
            or application["plan_digest"] != plan["plan_digest"]
            or [(row[0], row[1]) for row in chunks if row[2] == VERIFIED]
            != list(provenance)
            or any(row[2] != VERIFIED for row in chunks)):
        raise ValueError("retained_dirty_local_verification_mismatch")
    with repository.transaction():
        current = _publication_row(repository, reservation_digest)
        if current["state"] == RESERVED:
            changed = repository.db.execute(
                "UPDATE retained_publications SET state=?,cells_digest=?,"
                "local_verified_at=? WHERE reservation_digest=? AND state=?",
                (LOCAL_VERIFIED, cells_digest, timestamp(), reservation_digest,
                 RESERVED)).rowcount
            if changed != 1:
                raise ValueError("retained_dirty_state_changed")
        elif (current["state"] not in {
                LOCAL_VERIFIED, REMOTE_PENDING, REMOTE_CONFIRMED,
                FIRST_PASS_RELEASED}
              or current["cells_digest"] != cells_digest):
            raise ValueError("retained_dirty_state_changed")
    return {"reservation_digest": reservation_digest,
            "apply_id": publication["local_apply_id"],
            "cells_digest": cells_digest, "state": LOCAL_VERIFIED}


def bind_remote_intent(repository, reservation_digest, plan, *, inbox):
    """Bind the local hold to the inbox's already-frozen exact remote intent."""
    reservation_digest = _required_text("reservation_digest", reservation_digest)
    inbox = _require_inbox(repository, inbox)
    publication = _publication_row(repository, reservation_digest)
    if publication["state"] == LOCAL_VERIFIED:
        verified = verify_dirty_provenance(repository, reservation_digest, plan)
        publication = _publication_row(repository, reservation_digest)
    elif publication["state"] in {
            REMOTE_PENDING, REMOTE_CONFIRMED, FIRST_PASS_RELEASED}:
        _publication, cells_digest = _verify_cells(
            repository, reservation_digest, plan, cleared=not _dirty(repository))
        if publication["cells_digest"] != cells_digest:
            raise ValueError("retained_dirty_state_changed")
        verified = {"reservation_digest": reservation_digest,
                    "apply_id": publication["local_apply_id"],
                    "cells_digest": cells_digest, "state": publication["state"]}
    else:
        raise ValueError("retained_dirty_local_verification_required")
    remote = inbox.exact_remote_state(publication["cycle"], publication["company"])
    if (not isinstance(remote, Mapping)
            or remote.get("local_plan_digest") != publication["plan_digest"]
            or remote.get("projection_digest") != plan["remote_projection_digest"]
            or not str(remote.get("receipt_id") or "").strip()
            or not str(remote.get("intent_id") or "").strip()
            or remote.get("state") not in {
                "FROZEN", "SYNC_PENDING", "SYNC_CONFIRMED", "LOCAL_ACKNOWLEDGED"}):
        raise ValueError("retained_dirty_remote_intent_mismatch")
    with repository.transaction():
        row = _publication_row(repository, reservation_digest)
        expected = (remote["receipt_id"], remote["intent_id"],
                    remote["projection_digest"])
        if row["state"] == LOCAL_VERIFIED:
            changed = repository.db.execute(
                "UPDATE retained_publications SET state=?,receipt_id=?,intent_id=?,"
                "intent_projection_digest=? WHERE reservation_digest=? AND state=?",
                (REMOTE_PENDING, *expected, reservation_digest,
                 LOCAL_VERIFIED)).rowcount
            if changed != 1:
                raise ValueError("retained_dirty_state_changed")
        elif (row["state"] not in {
                REMOTE_PENDING, REMOTE_CONFIRMED, FIRST_PASS_RELEASED}
              or (row["receipt_id"], row["intent_id"],
                  row["intent_projection_digest"]) != expected):
            raise ValueError("retained_dirty_remote_intent_changed")
    durable = _publication_row(repository, reservation_digest)
    return {**verified, "state": durable["state"],
            "receipt_id": remote["receipt_id"], "intent_id": remote["intent_id"],
            "intent_projection_digest": remote["projection_digest"]}


def confirm_remote_from_authorities(repository, reservation_digest, plan, *, inbox):
    """Converge from durable inbox/readback/local-ack facts, never caller IDs."""
    reservation_digest = _required_text("reservation_digest", reservation_digest)
    inbox = _require_inbox(repository, inbox)
    publication, cells_digest = _verify_cells(
        repository, reservation_digest, plan, cleared=True)
    if publication["state"] not in {
            REMOTE_PENDING, REMOTE_CONFIRMED, FIRST_PASS_RELEASED}:
        raise ValueError("retained_dirty_remote_intent_not_bound")
    remote = inbox.exact_remote_state(publication["cycle"], publication["company"])
    if (not isinstance(remote, Mapping)
            or remote.get("local_plan_digest") != publication["plan_digest"]
            or remote.get("projection_digest")
            != publication["intent_projection_digest"]
            or remote.get("receipt_id") != publication["receipt_id"]
            or remote.get("intent_id") != publication["intent_id"]
            or not str(remote.get("acknowledgement_id") or "").strip()
            or remote.get("state") not in {"SYNC_CONFIRMED", "LOCAL_ACKNOWLEDGED"}):
        raise ValueError("retained_dirty_remote_confirmation_mismatch")
    acknowledgement_id = remote["acknowledgement_id"]
    inbox.require_exact_remote_confirmed(
        publication["cycle"], publication["company"],
        local_plan_digest=publication["plan_digest"],
        projection_digest=publication["intent_projection_digest"],
        receipt_id=publication["receipt_id"], intent_id=publication["intent_id"],
        acknowledgement_id=acknowledgement_id)
    acknowledgement = repository.db.execute(
        "SELECT selected_fields_digest FROM exact_local_acknowledgements "
        "WHERE apply_id=? AND receipt_id=? AND acknowledgement_id=?",
        (publication["local_apply_id"], publication["receipt_id"],
         acknowledgement_id)).fetchone()
    if (publication["cells_digest"] != cells_digest
            or acknowledgement is None or not str(acknowledgement[0] or "")):
        raise ValueError("retained_dirty_remote_acknowledgement_missing")
    with repository.transaction():
        row = _publication_row(repository, reservation_digest)
        if row["state"] == REMOTE_PENDING:
            changed = repository.db.execute(
                "UPDATE retained_publications SET state=?,receipt_id=?,"
                "acknowledgement_id=?,remote_confirmed_at=? "
                "WHERE reservation_digest=? AND state=?",
                (REMOTE_CONFIRMED, publication["receipt_id"], acknowledgement_id,
                 timestamp(), reservation_digest, REMOTE_PENDING)).rowcount
            if changed != 1:
                raise ValueError("retained_dirty_state_changed")
        elif (row["state"] not in {REMOTE_CONFIRMED, FIRST_PASS_RELEASED}
              or row["receipt_id"] != publication["receipt_id"]
              or row["acknowledgement_id"] != acknowledgement_id):
            raise ValueError("retained_dirty_remote_confirmation_changed")
    return {"reservation_digest": reservation_digest, "state": REMOTE_CONFIRMED,
            "receipt_id": publication["receipt_id"],
            "acknowledgement_id": acknowledgement_id}


def _require_retained_session(session_store):
    from .retained_session_store import RetainedSessionStore
    if not isinstance(session_store, RetainedSessionStore):
        raise ValueError("retained_dirty_session_store_required")
    return session_store


def _session_binding(publication, session, plan):
    expected = {
        "request_id": publication["request_id"],
        "event_id": publication["event_id"],
        "exception_cycle_id": publication["exception_cycle"],
        "cycle_id": publication["cycle"],
        "company_id": publication["company"],
        "source_revision": publication["source_revision"],
        "manifest_digest": publication["manifest_digest"],
        "start_binding_digest": publication["start_binding_digest"],
        "plan_digest": publication["plan_digest"],
        "projection_digest": publication["remote_projection_digest"],
    }
    if (any(session.get(key) != value for key, value in expected.items())
            or session.get("plan") != plan
            or session.get("projection") != plan.get("remote_projection")):
        raise ValueError("retained_dirty_session_binding_changed")
    return expected


def bind_remote_session(repository, reservation_digest, plan, *, session_store):
    """Bind the local dirty hold to the private retained remote journal."""
    from .retained_session_store import SYNC_CONFIRMED, SYNC_PENDING
    reservation_digest = _required_text("reservation_digest", reservation_digest)
    session_store = _require_retained_session(session_store)
    publication = _publication_row(repository, reservation_digest)
    # SessionStore is the sole remote authority.  If its full readback is
    # already confirmed, a crash may have occurred after exact local dirty
    # acknowledgement but before this shared provenance ledger advanced.
    # Accept that cleared set only after the later acknowledgement binding is
    # revalidated by ``confirm_remote_from_session``; never reopen a write.
    session = session_store.load(reservation_digest)
    if publication["state"] == LOCAL_VERIFIED:
        verified = verify_dirty_provenance(repository, reservation_digest, plan)
        publication = _publication_row(repository, reservation_digest)
    elif publication["state"] in {
            REMOTE_PENDING, REMOTE_CONFIRMED, FIRST_PASS_RELEASED}:
        publication, cells_digest = _verify_cells(
            repository, reservation_digest, plan,
            cleared=(publication["state"] in {REMOTE_CONFIRMED, FIRST_PASS_RELEASED}
                     or (session.get("state") == SYNC_CONFIRMED
                         and not _dirty(repository))))
        verified = {"reservation_digest": reservation_digest,
                    "apply_id": publication["local_apply_id"],
                    "cells_digest": cells_digest, "state": publication["state"]}
    else:
        raise ValueError("retained_dirty_local_verification_required")
    _session_binding(publication, session, plan)
    if (session.get("state") not in {SYNC_PENDING, SYNC_CONFIRMED}
            or not str(session.get("receipt_id") or "").strip()
            or not str(session.get("intent_id") or "").strip()
            or session.get("exact_scope") is None):
        raise ValueError("retained_dirty_session_intent_missing")
    expected = (session["receipt_id"], session["intent_id"],
                session["projection_digest"])
    with repository.transaction():
        row = _publication_row(repository, reservation_digest)
        if row["state"] == LOCAL_VERIFIED:
            changed = repository.db.execute(
                "UPDATE retained_publications SET state=?,receipt_id=?,intent_id=?,"
                "intent_projection_digest=? WHERE reservation_digest=? AND state=?",
                (REMOTE_PENDING, *expected, reservation_digest,
                 LOCAL_VERIFIED)).rowcount
            if changed != 1:
                raise ValueError("retained_dirty_state_changed")
        elif (row["state"] not in {
                REMOTE_PENDING, REMOTE_CONFIRMED, FIRST_PASS_RELEASED}
              or (row["receipt_id"], row["intent_id"],
                  row["intent_projection_digest"]) != expected):
            raise ValueError("retained_dirty_session_intent_changed")
    return {**verified, "state": _publication_row(
                repository, reservation_digest)["state"],
            "receipt_id": session["receipt_id"],
            "intent_id": session["intent_id"],
            "intent_projection_digest": session["projection_digest"]}


def confirm_remote_from_session(repository, reservation_digest, plan, *,
                                session_store):
    """Confirm from the private journal plus the exact local acknowledgement."""
    from .retained_session_store import SYNC_CONFIRMED
    reservation_digest = _required_text("reservation_digest", reservation_digest)
    session_store = _require_retained_session(session_store)
    publication, cells_digest = _verify_cells(
        repository, reservation_digest, plan, cleared=True)
    if publication["state"] not in {
            REMOTE_PENDING, REMOTE_CONFIRMED, FIRST_PASS_RELEASED}:
        raise ValueError("retained_dirty_remote_intent_not_bound")
    session = session_store.load(reservation_digest)
    _session_binding(publication, session, plan)
    acknowledgement_id = str(session.get("acknowledgement_id") or "").strip()
    if (session.get("state") != SYNC_CONFIRMED or not acknowledgement_id
            or session.get("receipt_id") != publication["receipt_id"]
            or session.get("intent_id") != publication["intent_id"]
            or session.get("projection_digest")
            != publication["intent_projection_digest"]):
        raise ValueError("retained_dirty_session_confirmation_mismatch")
    acknowledgement = repository.db.execute(
        "SELECT selected_fields_digest FROM exact_local_acknowledgements "
        "WHERE apply_id=? AND receipt_id=? AND acknowledgement_id=?",
        (publication["local_apply_id"], publication["receipt_id"],
         acknowledgement_id)).fetchone()
    if (publication["cells_digest"] != cells_digest
            or acknowledgement is None or not str(acknowledgement[0] or "")):
        raise ValueError("retained_dirty_remote_acknowledgement_missing")
    with repository.transaction():
        row = _publication_row(repository, reservation_digest)
        if row["state"] == REMOTE_PENDING:
            changed = repository.db.execute(
                "UPDATE retained_publications SET state=?,acknowledgement_id=?,"
                "remote_confirmed_at=? WHERE reservation_digest=? AND state=?",
                (REMOTE_CONFIRMED, acknowledgement_id, timestamp(),
                 reservation_digest, REMOTE_PENDING)).rowcount
            if changed != 1:
                raise ValueError("retained_dirty_state_changed")
        elif (row["state"] not in {REMOTE_CONFIRMED, FIRST_PASS_RELEASED}
              or row["acknowledgement_id"] != acknowledgement_id):
            raise ValueError("retained_dirty_remote_confirmation_changed")
    return {"reservation_digest": reservation_digest, "state": REMOTE_CONFIRMED,
            "receipt_id": publication["receipt_id"],
            "acknowledgement_id": acknowledgement_id}


def retained_publication(repository, reservation_digest):
    """Return the bounded journal row without discovering other work."""
    if not repository.db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='retained_publications'").fetchone():
        raise ValueError("retained_dirty_schema_missing")
    result = _publication_row(
        repository, _required_text("reservation_digest", reservation_digest))
    if result["queue_evidence"] is not None:
        try:
            result["queue_evidence"] = json.loads(result["queue_evidence"])
        except (TypeError, ValueError) as error:
            raise ValueError("retained_dirty_queue_evidence_corrupt") from error
    return result
