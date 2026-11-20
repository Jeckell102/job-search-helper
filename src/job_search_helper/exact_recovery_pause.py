"""Immutable local scope freeze for a future exact recovery pause.

This module has no remote repository and no apply path. It proves that the
saved-work publisher is empty, terminal holds were freshly revalidated, and
the remaining pause scope is frozen before a future adapter can journal a
single remote request.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path


VERSION = "exact-recovery-pause-journal-v1"
TERMINAL_MANIFEST_VERSION = "exact-recovery-terminal-hold-v1"
MAX_REASON_LENGTH = 256


def _canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


class PauseJournalStore:
    """One immutable pause-scope journal per exact cycle."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(self.path)
        with self.db:
            self.db.execute("""CREATE TABLE IF NOT EXISTS exact_recovery_pause_journals (
                cycle TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                digest TEXT NOT NULL
            )""")
        self.path.chmod(0o600)

    def close(self):
        self.db.close()

    def read(self, cycle_id):
        row = self.db.execute(
            "SELECT payload,digest FROM exact_recovery_pause_journals WHERE cycle=?",
            (cycle_id,),
        ).fetchone()
        if row is None:
            return None
        try:
            value = json.loads(row[0])
        except (TypeError, ValueError) as exc:
            raise ValueError("exact_pause_journal_corrupt") from exc
        if (not isinstance(value, dict) or value.get("version") != VERSION
                or value.get("cycle_id") != cycle_id or _digest(value) != row[1]):
            raise ValueError("exact_pause_journal_corrupt")
        result = dict(value)
        result["journal_digest"] = row[1]
        return result

    def freeze(self, journal):
        if not isinstance(journal, dict) or journal.get("version") != VERSION:
            raise ValueError("exact_pause_journal_invalid")
        payload = _canonical(journal)
        digest = _digest(journal)
        cycle_id = journal["cycle_id"]
        with self.db:
            row = self.db.execute(
                "SELECT payload,digest FROM exact_recovery_pause_journals WHERE cycle=?",
                (cycle_id,),
            ).fetchone()
            if row is not None:
                retained = self.read(cycle_id)
                if row != (payload, digest) or retained["journal_digest"] != digest:
                    raise ValueError("exact_pause_journal_changed")
                return retained
            self.db.execute(
                "INSERT INTO exact_recovery_pause_journals VALUES (?,?,?)",
                (cycle_id, payload, digest),
            )
        result = dict(journal)
        result["journal_digest"] = digest
        return result


def _file_fact(path):
    if path is None:
        return {"present": False, "digest": ""}
    candidate = Path(path)
    if not candidate.exists():
        return {"present": False, "digest": ""}
    return {
        "present": True,
        "digest": hashlib.sha256(candidate.read_bytes()).hexdigest(),
    }


def _manifest_digest(manifest):
    return _digest({
        key: value for key, value in manifest.items() if key != "manifest_digest"
    })


def _validate_manifest(manifest, cycle_id):
    required = {
        "version", "cycle_id", "company_id", "stage", "inventory_digest",
        "plan", "receipt", "manifest_digest",
    }
    if (not isinstance(manifest, dict) or not required.issubset(manifest)
            or manifest.get("version") != TERMINAL_MANIFEST_VERSION
            or manifest.get("cycle_id") != cycle_id
            or manifest.get("manifest_digest") != _manifest_digest(manifest)):
        raise ValueError("terminal_manifest_invalid")
    return manifest


def _facts(state, inbox, cycle_id, manifests, manifest_revalidator, *,
           reason, timestamp, next_scan_path):
    if (not isinstance(cycle_id, str) or not cycle_id.strip()
            or cycle_id != cycle_id.strip()):
        raise ValueError("exact_cycle_id_required")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("exact_pause_reason_invalid")
    reason = reason.strip()
    if len(reason) > MAX_REASON_LENGTH:
        raise ValueError("exact_pause_reason_invalid")
    if not isinstance(timestamp, str) or not timestamp.strip():
        raise ValueError("exact_pause_timestamp_invalid")
    timestamp = timestamp.strip()
    if not callable(manifest_revalidator):
        raise ValueError("terminal_manifest_revalidator_required")

    cycle = state.cycle(cycle_id)
    if (not isinstance(cycle, dict) or cycle.get("id") != cycle_id
            or cycle.get("status") in {"Complete", "Complete with exceptions"}):
        raise ValueError("exact_cycle_not_unfinished")
    if inbox.pending(cycle_id, include_blocked=False):
        raise ValueError("unblocked_saved_work_remains")
    if not isinstance(manifests, list):
        raise ValueError("terminal_manifests_required")

    holds = {}
    for supplied in manifests:
        manifest = _validate_manifest(supplied, cycle_id)
        fresh = _validate_manifest(manifest_revalidator(manifest), cycle_id)
        if (_canonical(fresh) != _canonical(manifest)
                or fresh["manifest_digest"] != manifest["manifest_digest"]):
            raise ValueError("terminal_manifest_revalidation_failed")
        company_id = manifest.get("company_id")
        item = cycle.get("companies", {}).get(company_id)
        if (company_id in holds or not isinstance(item, dict)
                or item.get("stage") not in {"blocked", "unsupported"}
                or manifest.get("stage") != item.get("stage")):
            raise ValueError("terminal_manifest_coverage_invalid")
        holds[company_id] = manifest["manifest_digest"]

    blocked = {
        company_id
        for company_id in inbox.pending(cycle_id, include_blocked=True)
        if inbox.get(cycle_id, company_id)[1]
    }
    if set(holds) != blocked:
        raise ValueError("terminal_manifest_coverage_incomplete")

    candidates = [
        (company_id, item.get("stage"))
        for company_id, item in cycle.get("companies", {}).items()
        if item.get("stage") in {"queued", "inventory"} and company_id not in holds
    ]
    if not candidates:
        raise ValueError("exact_pause_has_no_candidates")

    return {
        "version": VERSION,
        "cycle_id": cycle_id,
        "reason": reason,
        "timestamp": timestamp,
        "candidate_ids": [company_id for company_id, _stage in candidates],
        "candidate_pre_stages": dict(candidates),
        "terminal_hold_manifest_digests": dict(sorted(holds.items())),
        "cycle_prestate_digest": _digest(cycle),
        "next_scan": _file_fact(next_scan_path),
    }


def freeze_exact_pause_journal(state, inbox, store, cycle_id, manifests, *,
                               manifest_revalidator, reason, timestamp,
                               next_scan_path=None):
    """Persist the exact future pause scope without changing State or remote data."""
    journal = _facts(
        state, inbox, cycle_id, manifests, manifest_revalidator,
        reason=reason, timestamp=timestamp, next_scan_path=next_scan_path,
    )
    return store.freeze(journal)


def revalidate_pause_journal(state, inbox, store, cycle_id, manifests, *,
                             manifest_revalidator, next_scan_path=None):
    """Recompute current facts and compare them to the immutable journal."""
    stored = store.read(cycle_id)
    if stored is None:
        raise ValueError("exact_pause_journal_missing")
    fresh = _facts(
        state, inbox, cycle_id, manifests, manifest_revalidator,
        reason=stored["reason"], timestamp=stored["timestamp"],
        next_scan_path=next_scan_path,
    )
    if _digest(fresh) != stored["journal_digest"]:
        raise ValueError("exact_pause_journal_changed_before_apply")
    return stored
