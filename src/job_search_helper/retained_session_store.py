"""Private durable authority for one retained-work publication reservation.

This deliberately is not an :class:`InventoryInbox` and has no discovery API.
Callers can address a session only by its reservation digest.  The store makes
the immutable admission, frozen inventory, frozen exact-v2 plan, and remote
delivery facts recoverable without creating an ordinary cycle/inbox record.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sqlite3
from threading import RLock
from typing import Mapping


RESERVED = "RESERVED"
SYNC_PENDING = "SYNC_PENDING"
SYNC_CONFIRMED = "SYNC_CONFIRMED"

_IDENTITY_FIELDS = (
    "request_id", "event_id", "exception_cycle_id", "cycle_id", "company_id",
    "source_revision", "manifest_digest", "start_binding_digest",
)


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value):
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _text(name, value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("retained_session_%s_invalid" % name)
    return value.strip()


def _sealed_plan(plan, identity):
    """Validate only the v2 facts this isolated store must bind."""
    if not isinstance(plan, Mapping) or plan.get("exact_plan_version") != 2:
        raise ValueError("retained_session_exact_plan_invalid")
    if (plan.get("cycle_id") != identity["cycle_id"]
            or plan.get("company_id") != identity["company_id"]
            or not isinstance(plan.get("remote_projection"), list)
            or not plan["remote_projection"]):
        raise ValueError("retained_session_exact_plan_binding_invalid")
    if plan.get("remote_projection_digest") != _digest(plan["remote_projection"]):
        raise ValueError("retained_session_projection_invalid")
    try:
        from .exact_cycle_planner import _exact_plan_digest
        expected = _exact_plan_digest(plan)
    except (ImportError, KeyError, TypeError, ValueError) as error:
        raise ValueError("retained_session_exact_plan_invalid") from error
    if plan.get("plan_digest") != expected:
        raise ValueError("retained_session_exact_plan_invalid")
    return copy.deepcopy(dict(plan))


def _receipt_id(reservation_digest, identity, inventory_digest, plan_digest,
                projection_digest):
    return _digest({"version": "retained-receipt-v1", "reservation_digest": reservation_digest,
                    "admission": identity, "inventory_digest": inventory_digest,
                    "plan_digest": plan_digest, "projection_digest": projection_digest})


def _intent_id(receipt_id, projection):
    return _digest({"version": "retained-intent-v1", "receipt_id": receipt_id,
                    "projection": projection})


def _acknowledgement_id(receipt_id, intent_id, projection_digest, rows):
    return _digest({"version": "retained-readback-v1", "receipt_id": receipt_id,
                    "intent_id": intent_id, "projection_digest": projection_digest,
                    "rows": rows})


class RetainedSessionStore:
    """A reservation-addressed SQLite journal; it never lists sessions."""

    def __init__(self, path):
        self.path = str(path)
        location = Path(path)
        if self.path == ":memory:":
            raise ValueError("retained_session_file_required")
        location.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.connection = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        self.lock = RLock()
        try:
            self.connection.execute("PRAGMA journal_mode=WAL")
            self.connection.execute("PRAGMA synchronous=FULL")
            self.connection.execute("PRAGMA foreign_keys=ON")
            with self.connection:
                self.connection.execute("""CREATE TABLE IF NOT EXISTS retained_sessions (
                    reservation_digest TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL, event_id TEXT NOT NULL,
                    exception_cycle_id TEXT NOT NULL, cycle_id TEXT NOT NULL UNIQUE,
                    company_id TEXT NOT NULL, source_revision TEXT NOT NULL,
                    manifest_digest TEXT NOT NULL, start_binding_digest TEXT NOT NULL,
                    inventory TEXT NOT NULL, inventory_digest TEXT NOT NULL,
                    plan TEXT NOT NULL, plan_digest TEXT NOT NULL UNIQUE,
                    projection TEXT NOT NULL, projection_digest TEXT NOT NULL,
                    exact_scope TEXT, exact_scope_digest TEXT,
                    receipt_id TEXT, intent_id TEXT, remote_cursor INTEGER NOT NULL DEFAULT 0,
                    acknowledgement_id TEXT,
                    state TEXT NOT NULL CHECK(state IN ('RESERVED','SYNC_PENDING','SYNC_CONFIRMED')),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )""")
                columns = {row[1] for row in self.connection.execute(
                    "PRAGMA table_info(retained_sessions)")}
                for name, ddl in (("exact_scope", "TEXT"),
                                  ("exact_scope_digest", "TEXT")):
                    if name not in columns:
                        self.connection.execute(
                            "ALTER TABLE retained_sessions ADD COLUMN %s %s" % (name, ddl))
                self.connection.execute("""CREATE TABLE IF NOT EXISTS retained_remote_chunks (
                    reservation_digest TEXT NOT NULL,
                    start_cursor INTEGER NOT NULL, operation_count INTEGER NOT NULL,
                    operation_digest TEXT NOT NULL, claim_id TEXT NOT NULL UNIQUE,
                    state TEXT NOT NULL CHECK(state IN ('CLAIMED','CONFIRMED')),
                    readback_digest TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    confirmed_at TEXT,
                    PRIMARY KEY(reservation_digest,start_cursor),
                    FOREIGN KEY(reservation_digest) REFERENCES retained_sessions(reservation_digest)
                )""")
        except BaseException:
            self.connection.close()
            raise
        location.chmod(0o600)

    def close(self):
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *_ignored):
        self.close()

    @staticmethod
    def _identity(admission):
        if not isinstance(admission, Mapping):
            raise ValueError("retained_session_admission_invalid")
        identity = {name: _text(name, admission.get(name)) for name in _IDENTITY_FIELDS}
        if identity["exception_cycle_id"] == identity["cycle_id"]:
            raise ValueError("retained_session_historical_cycle_selected")
        return identity

    @staticmethod
    def _row(row):
        if row is None:
            raise ValueError("retained_session_missing")
        keys = ("reservation_digest", *_IDENTITY_FIELDS, "inventory", "inventory_digest",
                "plan", "plan_digest", "projection", "projection_digest", "exact_scope",
                "exact_scope_digest", "receipt_id",
                "intent_id", "remote_cursor", "acknowledgement_id", "state")
        result = dict(zip(keys, row))
        try:
            result["inventory"] = json.loads(result["inventory"])
            result["plan"] = json.loads(result["plan"])
            result["projection"] = json.loads(result["projection"])
            result["exact_scope"] = (None if result["exact_scope"] is None
                                     else json.loads(result["exact_scope"]))
        except (TypeError, ValueError) as error:
            raise ValueError("retained_session_corrupt") from error
        if (result["inventory_digest"] != _digest(result["inventory"])
                or result["projection_digest"] != _digest(result["projection"])
                or result["plan"].get("plan_digest") != result["plan_digest"]
                or result["plan"].get("inventory_payload_digest") != result["inventory_digest"]
                or result["plan"].get("remote_projection") != result["projection"]):
            raise ValueError("retained_session_corrupt")
        if ((result["exact_scope"] is None) != (result["exact_scope_digest"] is None)
                or (result["exact_scope"] is not None
                    and result["exact_scope_digest"] != _digest(result["exact_scope"]))):
            raise ValueError("retained_session_corrupt")
        return copy.deepcopy(result)

    def _fetch(self, reservation_digest):
        return self.connection.execute(
            "SELECT reservation_digest,request_id,event_id,exception_cycle_id,cycle_id,"
            "company_id,source_revision,manifest_digest,start_binding_digest,inventory,"
            "inventory_digest,plan,plan_digest,projection,projection_digest,exact_scope,"
            "exact_scope_digest,receipt_id,intent_id,remote_cursor,acknowledgement_id,state FROM retained_sessions "
            "WHERE reservation_digest=?", (reservation_digest,)).fetchone()

    def _chunks(self, reservation_digest):
        return [{"start_cursor": row[0], "operation_count": row[1],
                 "operation_digest": row[2], "claim_id": row[3], "state": row[4],
                 "readback_digest": row[5]}
                for row in self.connection.execute(
                    "SELECT start_cursor,operation_count,operation_digest,claim_id,state,"
                    "readback_digest FROM retained_remote_chunks WHERE reservation_digest=? "
                    "ORDER BY start_cursor", (reservation_digest,))]

    def freeze(self, reservation_digest, *, admission, inventory, plan):
        """Create or exactly re-open a sealed reservation without replacement."""
        reservation_digest = _text("reservation_digest", reservation_digest)
        identity = self._identity(admission)
        plan = _sealed_plan(plan, identity)
        inventory_digest = _digest(inventory)
        if plan.get("inventory_payload_digest") != inventory_digest:
            raise ValueError("retained_session_inventory_plan_mismatch")
        encoded_inventory = _canonical(inventory)
        encoded_plan = _canonical(plan)
        encoded_projection = _canonical(plan["remote_projection"])
        expected = (tuple(identity[name] for name in _IDENTITY_FIELDS),
                    inventory_digest, plan["plan_digest"],
                    plan["remote_projection_digest"])
        with self.lock, self.connection:
            row = self._fetch(reservation_digest)
            if row is None:
                self.connection.execute(
                    "INSERT INTO retained_sessions(reservation_digest,request_id,event_id,"
                    "exception_cycle_id,cycle_id,company_id,source_revision,manifest_digest,"
                    "start_binding_digest,inventory,inventory_digest,plan,plan_digest,"
                    "projection,projection_digest,state) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (reservation_digest, *expected[0], encoded_inventory, expected[1],
                     encoded_plan, expected[2], encoded_projection, expected[3], RESERVED))
            else:
                current = self._row(row)
                actual = (tuple(current[name] for name in _IDENTITY_FIELDS),
                          current["inventory_digest"], current["plan_digest"],
                          current["projection_digest"])
                if actual != expected:
                    raise ValueError("retained_session_reservation_changed")
        return self.load(reservation_digest)

    def load(self, reservation_digest):
        """Load one reservation; intentionally no list/discovery operation exists."""
        reservation_digest = _text("reservation_digest", reservation_digest)
        with self.lock:
            result = self._row(self._fetch(reservation_digest))
            result["chunks"] = self._chunks(reservation_digest)
            return result

    def load_optional(self, reservation_digest):
        """Read one explicitly named reservation without enabling discovery."""
        reservation_digest = _text("reservation_digest", reservation_digest)
        with self.lock:
            row = self._fetch(reservation_digest)
            if row is None:
                return None
            result = self._row(row)
            result["chunks"] = self._chunks(reservation_digest)
            return result

    @staticmethod
    def _sealed_scope(current, exact_scope):
        if (not isinstance(exact_scope, Mapping)
                or set(exact_scope) != {"operations", "rows", "projection_digest"}
                or exact_scope.get("operations") != current["projection"]
                or exact_scope.get("projection_digest") != current["projection_digest"]
                or not isinstance(exact_scope.get("rows"), list)
                or len(exact_scope["rows"]) != len(current["projection"])):
            raise ValueError("retained_session_exact_scope_invalid")
        for row, operation in zip(exact_scope["rows"], exact_scope["operations"]):
            required = {"tab", "row_id", "identity", "fields", "sent", "operation"}
            if (not isinstance(row, Mapping) or not required <= set(row)
                    or row.get("operation") != operation
                    or row.get("tab") != operation.get("tab")
                    or type(row.get("row_id")) is not int
                    or not isinstance(row.get("identity"), Mapping)
                    or not isinstance(row.get("fields"), list)
                    or not isinstance(row.get("sent"), Mapping)):
                raise ValueError("retained_session_exact_scope_invalid")
            fields = set(row["fields"])
            if (len(fields) != len(row["fields"])
                    or not all(isinstance(field, str) and field for field in fields)
                    or not (set(operation.get("on_insert", {}))
                            | set(operation.get("values", {}))
                            | set(operation.get("append_notes", {}))) <= fields
                    or not fields <= set(row["sent"])):
                raise ValueError("retained_session_exact_scope_invalid")
        return copy.deepcopy(dict(exact_scope))

    @staticmethod
    def _scope_slice(current, start, count):
        scope = current["exact_scope"]
        operations = copy.deepcopy(scope["operations"][start:start + count])
        rows = copy.deepcopy(scope["rows"][start:start + count])
        return {"operations": operations, "rows": rows,
                "projection_digest": _digest(operations)}

    def freeze_remote_intent(self, reservation_digest, *, exact_scope):
        """Derive and persist immutable receipt/intent before any remote call."""
        reservation_digest = _text("reservation_digest", reservation_digest)
        with self.lock, self.connection:
            current = self._row(self._fetch(reservation_digest))
            scope = self._sealed_scope(current, exact_scope)
            identity = {name: current[name] for name in _IDENTITY_FIELDS}
            receipt_id = _receipt_id(reservation_digest, identity, current["inventory_digest"],
                                     current["plan_digest"], current["projection_digest"])
            intent_id = _intent_id(receipt_id, current["projection"])
            binding = (current["receipt_id"], current["intent_id"])
            if current["state"] == RESERVED:
                self.connection.execute(
                    "UPDATE retained_sessions SET exact_scope=?,exact_scope_digest=?,"
                    "receipt_id=?,intent_id=?,state=?,"
                    "updated_at=CURRENT_TIMESTAMP WHERE reservation_digest=? AND state=?",
                    (_canonical(scope), _digest(scope), receipt_id, intent_id,
                     SYNC_PENDING, reservation_digest, RESERVED))
            elif (binding != (receipt_id, intent_id)
                  or current["exact_scope"] != scope):
                raise ValueError("retained_session_remote_intent_changed")
        return self.load(reservation_digest)

    def claim_chunk(self, reservation_digest, *, operation_count):
        """Persist a pre-dispatch claim.  A retained claim may only be read back."""
        reservation_digest = _text("reservation_digest", reservation_digest)
        if type(operation_count) is not int or operation_count < 1:
            raise ValueError("retained_session_chunk_invalid")
        with self.lock, self.connection:
            current = self._row(self._fetch(reservation_digest))
            if current["state"] != SYNC_PENDING:
                raise ValueError("retained_session_not_pending")
            start = current["remote_cursor"]
            if start + operation_count > len(current["projection"]):
                raise ValueError("retained_session_chunk_invalid")
            exact_scope = self._scope_slice(current, start, operation_count)
            operation_digest = exact_scope["projection_digest"]
            claim_id = _digest({"version": "retained-chunk-v1", "intent_id": current["intent_id"],
                                "start_cursor": start, "operation_digest": operation_digest})
            existing = self.connection.execute(
                "SELECT operation_count,operation_digest,claim_id,state FROM retained_remote_chunks "
                "WHERE reservation_digest=? AND start_cursor=?", (reservation_digest, start)).fetchone()
            if existing is None:
                self.connection.execute(
                    "INSERT INTO retained_remote_chunks(reservation_digest,start_cursor,operation_count,"
                    "operation_digest,claim_id,state) VALUES (?,?,?,?,?,?)",
                    (reservation_digest, start, operation_count, operation_digest, claim_id, "CLAIMED"))
                return {"claim_id": claim_id, "start_cursor": start,
                        "exact_scope": exact_scope, "dispatch_allowed": True}
            if tuple(existing[:3]) != (operation_count, operation_digest, claim_id):
                raise ValueError("retained_session_chunk_changed")
            return {"claim_id": claim_id, "start_cursor": start,
                    "exact_scope": exact_scope, "dispatch_allowed": False,
                    "retry_requires_readback": existing[3] == "CLAIMED"}

    @staticmethod
    def _verified_readback(current, exact_scope, readback):
        if not isinstance(readback, Mapping):
            raise ValueError("retained_session_readback_invalid")
        required = {"receipt_id", "intent_id", "intent_projection_digest",
                    "projection_digest", "rows", "acknowledgement_id"}
        if set(readback) != required:
            raise ValueError("retained_session_readback_invalid")
        if (readback["receipt_id"], readback["intent_id"],
                readback["intent_projection_digest"], readback["projection_digest"]) != (
                current["receipt_id"], current["intent_id"], exact_scope["projection_digest"],
                exact_scope["projection_digest"]):
            raise ValueError("retained_session_readback_binding_changed")
        if not isinstance(readback["rows"], list) or len(readback["rows"]) != len(exact_scope["rows"]):
            raise ValueError("retained_session_readback_changed")
        from .repository import _equivalent
        for evidence, operation, observed in zip(exact_scope["rows"], exact_scope["operations"], readback["rows"]):
            if (not isinstance(observed, Mapping)
                    or any(observed.get(key) != evidence.get(key)
                           for key in ("tab", "row_id", "identity", "fields", "sent"))
                    or not isinstance(observed.get("actual"), Mapping)
                    or set(observed["actual"]) != set(evidence["fields"])):
                raise ValueError("retained_session_readback_changed")
            for values in (operation.get("on_insert", {}), operation.get("values", {})):
                if any(not _equivalent(header, observed["actual"].get(header, ""), value)
                       for header, value in values.items() if header in evidence["fields"]):
                    raise ValueError("retained_session_readback_changed")
            for header, suffix in operation.get("append_notes", {}).items():
                if header in evidence["fields"] and str(suffix) not in str(observed["actual"].get(header, "")):
                    raise ValueError("retained_session_readback_changed")
            if any(not _equivalent(header, observed["actual"].get(header, ""),
                                   evidence["sent"].get(header, ""))
                   for header in evidence["fields"]
                   if header not in operation.get("append_notes", {})):
                raise ValueError("retained_session_readback_changed")
        acknowledgement = _digest({"receipt_id": current["receipt_id"],
                                   "intent_id": current["intent_id"],
                                   "projection_digest": exact_scope["projection_digest"],
                                   "observed": readback["rows"]})
        if readback["acknowledgement_id"] != acknowledgement:
            raise ValueError("retained_session_readback_acknowledgement_invalid")
        return acknowledgement

    def confirm_chunk_readback(self, reservation_digest, *, claim_id, readback):
        """Confirm exactly the outstanding pre-dispatch claim from complete readback."""
        reservation_digest, claim_id = _text("reservation_digest", reservation_digest), _text("claim_id", claim_id)
        with self.lock, self.connection:
            current = self._row(self._fetch(reservation_digest))
            if current["state"] != SYNC_PENDING:
                raise ValueError("retained_session_not_pending")
            claim = self.connection.execute(
                "SELECT start_cursor,operation_count,state,readback_digest FROM retained_remote_chunks "
                "WHERE reservation_digest=? AND claim_id=?", (reservation_digest, claim_id)).fetchone()
            if claim is None:
                raise ValueError("retained_session_chunk_not_contiguous")
            exact_scope = self._scope_slice(current, claim[0], claim[1])
            readback_digest = self._verified_readback(current, exact_scope, readback)
            if claim[2] == "CLAIMED":
                if claim[0] != current["remote_cursor"]:
                    raise ValueError("retained_session_chunk_not_contiguous")
                self.connection.execute(
                    "UPDATE retained_remote_chunks SET state='CONFIRMED',readback_digest=?,"
                    "confirmed_at=CURRENT_TIMESTAMP WHERE reservation_digest=? AND claim_id=? "
                    "AND state='CLAIMED'", (readback_digest, reservation_digest, claim_id))
                self.connection.execute(
                    "UPDATE retained_sessions SET remote_cursor=?,updated_at=CURRENT_TIMESTAMP "
                    "WHERE reservation_digest=? AND remote_cursor=?",
                    (claim[0] + claim[1], reservation_digest, claim[0]))
            elif claim[2] != "CONFIRMED" or claim[3] != readback_digest:
                raise ValueError("retained_session_chunk_confirmation_changed")
        return self.load(reservation_digest)

    def confirm_readback(self, reservation_digest, *, readback):
        """Accept only complete deterministic readback after contiguous chunk proofs."""
        reservation_digest = _text("reservation_digest", reservation_digest)
        with self.lock, self.connection:
            current = self._row(self._fetch(reservation_digest))
            if current["exact_scope"] is None:
                raise ValueError("retained_session_exact_scope_missing")
            acknowledgement_id = self._verified_readback(current, current["exact_scope"], readback)
            if current["state"] == SYNC_PENDING:
                if current["remote_cursor"] != len(current["projection"]):
                    raise ValueError("retained_session_remote_incomplete")
                chunks = self._chunks(reservation_digest)
                cursor = 0
                for chunk in chunks:
                    if (chunk["state"] != "CONFIRMED" or chunk["start_cursor"] != cursor):
                        raise ValueError("retained_session_chunk_not_contiguous")
                    cursor += chunk["operation_count"]
                if cursor != len(current["projection"]):
                    raise ValueError("retained_session_chunk_not_contiguous")
                self.connection.execute(
                    "UPDATE retained_sessions SET acknowledgement_id=?,state=?,"
                    "updated_at=CURRENT_TIMESTAMP WHERE reservation_digest=? AND state=?",
                    (acknowledgement_id, SYNC_CONFIRMED, reservation_digest, SYNC_PENDING))
            elif (current["state"] != SYNC_CONFIRMED
                  or current["acknowledgement_id"] != acknowledgement_id):
                raise ValueError("retained_session_confirmation_changed")
        return self.load(reservation_digest)
