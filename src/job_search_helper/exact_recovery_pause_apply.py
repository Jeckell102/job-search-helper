"""Durable intent ledger for exact recovery-pause application.

The ledger contains no remote or State mutation logic. It enforces the crash
ordering that a future adapter must follow: freeze the full run, confirm every
predeclared Company chunk, confirm exact State finalization, then confirm the
exact Scan Cycles row finalization.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path


RUN_VERSION = "exact-recovery-pause-apply-v1"
INTENT = "INTENT"
CONFIRMED = "CONFIRMED"
FROZEN = "FROZEN"
COMPLETE = "COMPLETE"
KINDS = {"CHUNK", "STATE_FINALIZATION", "SCAN_CYCLE_FINALIZATION"}


def _canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


class PauseApplyStore:
    """Immutable run and monotonic intent state for one exact cycle."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(self.path)
        with self.db:
            self.db.execute("""CREATE TABLE IF NOT EXISTS pause_apply_runs (
                cycle TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                digest TEXT NOT NULL,
                state TEXT NOT NULL
            )""")
            self.db.execute("""CREATE TABLE IF NOT EXISTS pause_apply_intents (
                cycle TEXT NOT NULL,
                kind TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                payload TEXT NOT NULL,
                digest TEXT NOT NULL,
                state TEXT NOT NULL,
                acknowledgement TEXT,
                PRIMARY KEY(cycle,kind,ordinal)
            )""")
        self.path.chmod(0o600)

    def close(self):
        self.db.close()

    @staticmethod
    def _validate_run_payload(cycle_id, payload):
        required = {
            "version", "cycle_id", "journal_digest", "chunks",
            "state_finalization_digest", "scan_cycle_finalization_digest",
        }
        if (not isinstance(payload, dict) or set(payload) != required
                or payload.get("version") != RUN_VERSION
                or payload.get("cycle_id") != cycle_id
                or not isinstance(payload.get("journal_digest"), str)
                or not payload["journal_digest"]
                or not isinstance(payload.get("chunks"), list)
                or not payload["chunks"]
                or not isinstance(payload.get("state_finalization_digest"), str)
                or not payload["state_finalization_digest"]
                or not isinstance(payload.get("scan_cycle_finalization_digest"), str)
                or not payload["scan_cycle_finalization_digest"]):
            raise ValueError("pause_apply_run_invalid")
        starts = []
        for chunk in payload["chunks"]:
            if (not isinstance(chunk, dict) or set(chunk) != {"start", "count", "digest"}
                    or type(chunk["start"]) is not int or chunk["start"] < 0
                    or type(chunk["count"]) is not int or chunk["count"] <= 0
                    or not isinstance(chunk["digest"], str) or not chunk["digest"]):
                raise ValueError("pause_apply_run_invalid")
            starts.append(chunk["start"])
        if len(starts) != len(set(starts)) or starts != sorted(starts):
            raise ValueError("pause_apply_run_invalid")
        return payload

    def run(self, cycle_id):
        row = self.db.execute(
            "SELECT payload,digest,state FROM pause_apply_runs WHERE cycle=?",
            (cycle_id,),
        ).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(row[0])
        except (TypeError, ValueError) as exc:
            raise ValueError("pause_apply_store_corrupt") from exc
        try:
            self._validate_run_payload(cycle_id, payload)
        except ValueError as exc:
            raise ValueError("pause_apply_store_corrupt") from exc
        if _digest(payload) != row[1] or row[2] not in {FROZEN, COMPLETE}:
            raise ValueError("pause_apply_store_corrupt")
        if row[2] == COMPLETE:
            expected = [
                ("CHUNK", chunk["start"], chunk["digest"])
                for chunk in payload["chunks"]
            ] + [
                ("STATE_FINALIZATION", 0, payload["state_finalization_digest"]),
                ("SCAN_CYCLE_FINALIZATION", 0, payload["scan_cycle_finalization_digest"]),
            ]
            for kind, ordinal, expected_digest in expected:
                intent = self.intent(cycle_id, kind, ordinal)
                if (intent is None or intent["state"] != CONFIRMED
                        or intent["digest"] != expected_digest):
                    raise ValueError("pause_apply_store_corrupt")
        return {"payload": payload, "digest": row[1], "state": row[2]}

    def freeze_run(self, cycle_id, payload):
        self._validate_run_payload(cycle_id, payload)
        encoded = _canonical(payload)
        digest = _digest(payload)
        retained = self.run(cycle_id)
        if retained is not None:
            if retained["digest"] != digest or _canonical(retained["payload"]) != encoded:
                raise ValueError("pause_apply_run_changed")
            return retained
        with self.db:
            self.db.execute(
                "INSERT INTO pause_apply_runs VALUES (?,?,?,?)",
                (cycle_id, encoded, digest, FROZEN),
            )
        return self.run(cycle_id)

    def intent(self, cycle_id, kind, ordinal=0):
        row = self.db.execute(
            "SELECT payload,digest,state,acknowledgement FROM pause_apply_intents "
            "WHERE cycle=? AND kind=? AND ordinal=?",
            (cycle_id, kind, ordinal),
        ).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(row[0])
        except (TypeError, ValueError) as exc:
            raise ValueError("pause_apply_store_corrupt") from exc
        if (_digest(payload) != row[1] or row[2] not in {INTENT, CONFIRMED}
                or (row[2] == CONFIRMED and not str(row[3] or "").strip())
                or (row[2] == INTENT and row[3] is not None)):
            raise ValueError("pause_apply_store_corrupt")
        return {
            "payload": payload,
            "digest": row[1],
            "state": row[2],
            "acknowledgement": row[3],
        }

    def _expected_digest(self, cycle_id, kind, ordinal):
        run = self.run(cycle_id)
        if run is None:
            raise ValueError("pause_apply_run_missing")
        if run["state"] == COMPLETE:
            raise ValueError("pause_apply_run_complete")
        payload = run["payload"]
        if kind == "CHUNK":
            matches = [chunk for chunk in payload["chunks"] if chunk["start"] == ordinal]
            if len(matches) != 1:
                raise ValueError("pause_apply_chunk_not_frozen")
            return matches[0]["digest"]
        if ordinal != 0:
            raise ValueError("pause_apply_intent_invalid")
        if kind == "STATE_FINALIZATION":
            if any(self.intent(cycle_id, "CHUNK", chunk["start"]) is None
                   or self.intent(cycle_id, "CHUNK", chunk["start"])["state"] != CONFIRMED
                   for chunk in payload["chunks"]):
                raise ValueError("pause_apply_chunks_unconfirmed")
            return payload["state_finalization_digest"]
        if kind == "SCAN_CYCLE_FINALIZATION":
            state_intent = self.intent(cycle_id, "STATE_FINALIZATION", 0)
            if state_intent is None or state_intent["state"] != CONFIRMED:
                raise ValueError("pause_apply_state_unconfirmed")
            return payload["scan_cycle_finalization_digest"]
        raise ValueError("pause_apply_intent_invalid")

    def begin(self, cycle_id, kind, ordinal, payload):
        if kind not in KINDS or type(ordinal) is not int or ordinal < 0:
            raise ValueError("pause_apply_intent_invalid")
        digest = _digest(payload)
        if digest != self._expected_digest(cycle_id, kind, ordinal):
            raise ValueError("pause_apply_intent_not_frozen")
        retained = self.intent(cycle_id, kind, ordinal)
        if retained is not None:
            if retained["digest"] != digest:
                raise ValueError("pause_apply_intent_changed")
            return retained
        with self.db:
            self.db.execute(
                "INSERT INTO pause_apply_intents VALUES (?,?,?,?,?,?,?)",
                (cycle_id, kind, ordinal, _canonical(payload), digest, INTENT, None),
            )
        return self.intent(cycle_id, kind, ordinal)

    def confirm(self, cycle_id, kind, ordinal, digest, acknowledgement):
        if not isinstance(acknowledgement, str) or not acknowledgement.strip():
            raise ValueError("pause_apply_ack_required")
        retained = self.intent(cycle_id, kind, ordinal)
        if retained is None:
            raise ValueError("pause_apply_intent_missing")
        if retained["digest"] != digest:
            raise ValueError("pause_apply_digest_mismatch")
        if retained["state"] == CONFIRMED:
            if retained["acknowledgement"] != acknowledgement:
                raise ValueError("pause_apply_ack_conflict")
            return retained
        with self.db:
            updated = self.db.execute(
                "UPDATE pause_apply_intents SET state=?,acknowledgement=? "
                "WHERE cycle=? AND kind=? AND ordinal=? AND state=?",
                (CONFIRMED, acknowledgement, cycle_id, kind, ordinal, INTENT),
            ).rowcount
            if updated != 1:
                raise ValueError("pause_apply_intent_changed")
            if kind == "SCAN_CYCLE_FINALIZATION":
                completed = self.db.execute(
                    "UPDATE pause_apply_runs SET state=? WHERE cycle=? AND state=?",
                    (COMPLETE, cycle_id, FROZEN),
                ).rowcount
                if completed != 1:
                    raise ValueError("pause_apply_run_state_changed")
        return self.intent(cycle_id, kind, ordinal)
