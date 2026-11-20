"""Dedicated local-only runner boundary for one retained-work exception.

This module deliberately does not import the normal runner, remote repository,
Sheets synchronizer, review lifecycle, or ordinary Engine.start_cycle path.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
import uuid

from job_search_helper.retained_work_exception import (
    admit_disjoint_company_request, canonical, digest, revalidate_manifest,
    validate_frozen_admission,
)
from job_search_helper.company_events import canonical_company_fact, source_revision
from job_search_helper.scan_request import (
    _read_request, _unfinished_cycle_ids, request_fingerprint,
)


_TOKEN = object()
_EVENT_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")


def _read_json(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError("retained_runner_json_unreadable") from error
    if not isinstance(value, dict):
        raise ValueError("retained_runner_json_invalid")
    return value


def _inventory_snapshot(inventory, company, *, fetched_at):
    fields = {
        "status": getattr(inventory, "status", None),
        "jobs": getattr(inventory, "jobs", None),
        "reason": getattr(inventory, "reason", ""),
        "source_url": getattr(inventory, "source_url", None),
        "ats": getattr(inventory, "ats", None),
        "browser_pending_urls": getattr(inventory, "browser_pending_urls", []),
        "browser_discovery_incomplete": getattr(
            inventory, "browser_discovery_incomplete", False),
        "fetched_at": fetched_at,
        "requested_url": company["Official Careers URL"],
    }
    if (fields["status"] not in {"complete", "partial"}
            or not isinstance(fields["jobs"], list)
            or not isinstance(fields["source_url"], str)
            or not fields["source_url"].strip()
            or not isinstance(fields["ats"], str)
            or not fields["ats"].strip()):
        raise ValueError("retained_runner_preflight_inventory_invalid")
    # A canonical round-trip detaches the trusted result from a mutable fetcher
    # object and proves every value can be durably represented.
    return json.loads(canonical(fields))


def _company_snapshot(repository, company_id):
    if (getattr(repository, "is_local", False) is not True
            or getattr(repository, "readonly", False) is not True):
        raise ValueError("retained_runner_readonly_local_repository_required")
    matches = repository.matches("Companies", {"Company ID": company_id})
    if len(matches) != 1:
        raise ValueError("retained_runner_company_missing_or_ambiguous")
    row = dict(matches[0][1])
    fact = canonical_company_fact(row)
    if not fact["eligible"] or not str(row.get("Company", "")).strip():
        raise ValueError("retained_runner_company_ineligible")
    if str(row.get("Claimed By", "")).strip() or str(row.get("Claim Token", "")).strip():
        raise ValueError("retained_runner_company_claimed")
    return row, fact, source_revision(row)


def _read_inventory(path, cycle_id, company_id):
    location = Path(path).resolve()
    db = sqlite3.connect(location.as_uri() + "?mode=ro", uri=True)
    try:
        row = db.execute(
            "SELECT payload,blocked FROM inventories WHERE cycle=? AND company=?",
            (cycle_id, company_id)).fetchone()
    finally:
        db.close()
    if row is None:
        return None
    try:
        return json.loads(row[0]), bool(row[1])
    except (TypeError, ValueError) as error:
        raise ValueError("retained_runner_inventory_readback_changed") from error


def _admission_company(snapshot, company, inventory):
    request = snapshot["request"]
    return {
        "company_id": request["company_ids"][0],
        "company_name": str(company.get("Company", "")).strip(),
        "official_careers_url": snapshot["company_fact"]["official_careers_url"],
        "source_url": inventory["source_url"], "ats": inventory["ats"],
        "source_revision": snapshot["source_revision"],
        "company_status": str(company.get("Company Status", "Active")),
        "claimed_by": str(company.get("Claimed By", "")),
        "claim_token": str(company.get("Claim Token", "")),
    }


def _trusted_snapshot(repository, state, state_directory, manifest, *,
                      expected_request=None, discount_cycle_id=None):
    root = Path(state_directory).resolve()
    request_path = root / "next-scan.json"
    if not request_path.exists() and expected_request is not None:
        request_path = root / "last-scan-request.json"
    request, company_ids = _read_request(request_path)
    if expected_request is not None and request != expected_request:
        raise ValueError("retained_runner_request_changed")
    if (request.get("mode") != "company-only" or len(company_ids) != 1
            or not isinstance(request.get("company_event"), dict)):
        raise ValueError("retained_runner_bridge_company_request_required")
    event = request["company_event"]
    event_id = event.get("event_id")
    if not isinstance(event_id, str) or not _EVENT_ID.fullmatch(event_id):
        raise ValueError("retained_runner_event_id_invalid")
    receipt_path = root / "company-event-bridge" / "receipts" / (event_id + ".json")
    receipt = _read_json(receipt_path)
    company, fact, revision = _company_snapshot(repository, company_ids[0])
    if revision != request.get("source_revision"):
        raise ValueError("retained_runner_company_revision_changed")
    probe = type("ReadOnlyEngineProbe", (), {"repo": repository})()
    blockers = sorted(_unfinished_cycle_ids(probe, state, include_remote=True))
    if discount_cycle_id is not None:
        blockers = [value for value in blockers if value != discount_cycle_id]
    cycle = state.cycle(manifest["cycle_id"])
    if not isinstance(cycle, dict):
        raise ValueError("retained_runner_exception_cycle_missing")
    evidence = {
        "request": request,
        "request_digest": digest(request),
        "receipt": receipt,
        "receipt_digest": digest(receipt),
        "company_fact": fact,
        "company_row_digest": digest(company),
        "source_revision": revision,
        "blocking_cycle_ids": blockers,
        "exception_cycle_digest": digest(cycle),
        "manifest_digest": manifest["manifest_digest"],
    }
    evidence["snapshot_digest"] = digest(evidence)
    return evidence, company, cycle


@dataclass(frozen=True)
class PreparedExceptionalStart:
    _token: object
    snapshot: dict
    company: dict
    exception_cycle: dict
    inventory: dict
    admission: dict
    started_at: str


def _decode_journal_row(row):
    try:
        binding, prepared = json.loads(row[2]), json.loads(row[4])
    except (TypeError, ValueError) as error:
        raise ValueError("retained_runner_recovery_journal_corrupt") from error
    if (digest(binding) != row[3] or digest(prepared) != row[5]
            or binding.get("request_id") != row[0]):
        raise ValueError("retained_runner_recovery_journal_corrupt")
    return {"request_id": row[0], "cycle_id": row[1],
            "binding": binding, "binding_digest": row[3],
            "prepared": prepared, "state": row[6]}


def _read_existing_journal(path):
    location = Path(path).resolve()
    if not location.is_file():
        return None
    db = sqlite3.connect(location.as_uri() + "?mode=ro", uri=True)
    try:
        tables = {row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if "retained_work_starts" not in tables:
            raise ValueError("retained_runner_recovery_journal_corrupt")
        rows = db.execute(
            "SELECT request_id,cycle_id,binding,binding_digest,prepared,"
            "prepared_digest,state FROM retained_work_starts").fetchall()
    finally:
        db.close()
    if len(rows) != 1:
        raise ValueError("retained_runner_recovery_journal_ambiguous")
    return _decode_journal_row(rows[0])


def prepare_exceptional_start(repository, state, state_directory,
                              inventory_path, jobs_path, store_path,
                              manifest, verifier, prefetcher, *, now=None,
                              allow_test_verifier=False):
    """Read, prefetch, admit and reread without creating a cycle."""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("retained_runner_clock_timezone_required")
    if getattr(state, "readonly", False) is not True:
        raise ValueError("retained_runner_readonly_state_required")
    root = Path(state_directory).resolve()
    if (Path(inventory_path).resolve().parent != root
            or Path(jobs_path).resolve().parent != root
            or Path(store_path).resolve().parent != root
            or Path(store_path).name != "retained-work-exceptions.sqlite3"
            or (getattr(state, "path", ":memory:") != ":memory:"
                and Path(state.path).resolve() != root / "state.db")):
        raise ValueError("retained_runner_state_layout_invalid")
    first, company, cycle = _trusted_snapshot(
        repository, state, state_directory, manifest)
    request = first["request"]
    inventory_object = prefetcher(
        str(company.get("ATS / Source", "")),
        str(company.get("Official Careers URL", "")),
        request["company_ids"][0], str(company.get("Company", "")))
    inventory = _inventory_snapshot(
        inventory_object, company, fetched_at=current.astimezone(
            timezone.utc).isoformat())
    second, company_again, cycle_again = _trusted_snapshot(
        repository, state, state_directory, manifest)
    if (second != first or company_again != company or cycle_again != cycle):
        raise ValueError("retained_runner_trusted_snapshot_changed")
    current_company = _admission_company(second, company_again, inventory)
    admission = admit_disjoint_company_request(
        store_path, verifier, cycle_again, inventory_path, jobs_path,
        request, second["receipt"], current_company,
        second["blocking_cycle_ids"], operation="start-company-only",
        defer_sync=True, now=current,
        allow_test_verifier=allow_test_verifier)
    third, company_final, cycle_final = _trusted_snapshot(
        repository, state, state_directory, manifest)
    if (third != second or company_final != company_again
            or cycle_final != cycle_again):
        raise ValueError("retained_runner_trusted_snapshot_changed")
    repeated = validate_frozen_admission(
        store_path, verifier, cycle_final, inventory_path, jobs_path,
        admission, now=current, allow_test_verifier=allow_test_verifier)
    if repeated != admission:
        raise ValueError("retained_runner_admission_changed")
    return PreparedExceptionalStart(
        _TOKEN, first, company, cycle, inventory, admission,
        current.astimezone(timezone.utc).isoformat())


class _StartJournal:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(self.path)
        with self.db:
            self.db.execute("""CREATE TABLE IF NOT EXISTS retained_work_starts (
                request_id TEXT PRIMARY KEY, cycle_id TEXT NOT NULL UNIQUE,
                binding TEXT NOT NULL, binding_digest TEXT NOT NULL,
                prepared TEXT NOT NULL, prepared_digest TEXT NOT NULL,
                state TEXT NOT NULL)""")
        self.path.chmod(0o600)

    def close(self):
        self.db.close()

    def reserve(self, prepared):
        request_id = prepared.snapshot["request"]["request_id"]
        binding = {
            "request_id": request_id,
            "event_id": prepared.snapshot["request"]["company_event"]["event_id"],
            "company_id": prepared.snapshot["request"]["company_ids"][0],
            "snapshot_digest": prepared.snapshot["snapshot_digest"],
            "manifest_digest": prepared.admission["manifest_digest"],
            "reservation_digest": prepared.admission["reservation_digest"],
            "inventory_digest": digest(prepared.inventory),
        }
        encoded, binding_digest = canonical(binding), digest(binding)
        prepared_payload = {
            "snapshot": prepared.snapshot, "company": prepared.company,
            "exception_cycle": prepared.exception_cycle,
            "inventory": prepared.inventory, "admission": prepared.admission,
            "started_at": prepared.started_at,
        }
        prepared_encoded = canonical(prepared_payload)
        prepared_digest = digest(prepared_payload)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute(
                "SELECT cycle_id,binding,binding_digest,prepared,prepared_digest,state "
                "FROM retained_work_starts WHERE request_id=?", (request_id,)).fetchone()
            if row is None:
                cycle_id = "CYC-" + uuid.uuid4().hex[:12].upper()
                self.db.execute(
                    "INSERT INTO retained_work_starts VALUES (?,?,?,?,?,?,?)",
                    (request_id, cycle_id, encoded, binding_digest,
                     prepared_encoded, prepared_digest, "RESERVED"))
            else:
                cycle_id = row[0]
                if (row[1] != encoded or row[2] != binding_digest
                        or row[3] != prepared_encoded
                        or row[4] != prepared_digest):
                    raise ValueError("retained_runner_start_binding_changed")
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        return cycle_id, binding, binding_digest

    def only(self):
        rows = self.db.execute(
            "SELECT request_id,cycle_id,binding,binding_digest,prepared,"
            "prepared_digest,state FROM retained_work_starts").fetchall()
        if len(rows) != 1:
            raise ValueError("retained_runner_recovery_journal_ambiguous")
        return _decode_journal_row(rows[0])

    def advance(self, request_id, expected, replacement):
        order = {"RESERVED": 0, "STATE_SAVED": 1,
                 "INVENTORY_SAVED": 2, "COMMITTED": 3}
        with self.db:
            changed = self.db.execute(
                "UPDATE retained_work_starts SET state=? WHERE request_id=? AND state=?",
                (replacement, request_id, expected)).rowcount
            if not changed:
                row = self.db.execute(
                    "SELECT state FROM retained_work_starts WHERE request_id=?",
                    (request_id,)).fetchone()
                if (row is None or row[0] not in order
                        or order[row[0]] < order[replacement]):
                    raise ValueError("retained_runner_start_state_changed")


def _cycle_for(prepared, cycle_id, binding_digest):
    request = prepared.snapshot["request"]
    company_id = request["company_ids"][0]
    return {
        "id": cycle_id, "started_at": prepared.started_at,
        "status": "In Progress", "all": False,
        "companies": {company_id: {
            "company": str(prepared.company["Company"]),
            "stage": "inventory",
            "inventory_status": prepared.inventory["status"],
            "reason": prepared.inventory["reason"],
            "source_url": prepared.inventory["source_url"],
            "ats": prepared.inventory["ats"],
            "fetched_at": prepared.inventory["fetched_at"],
            "requested_url": prepared.inventory["requested_url"],
            "staging_complete": False, "next_job_index": 0,
        }},
        "start_request_id": request["request_id"],
        "request_fingerprint": request_fingerprint(request, [company_id]),
        "company_event": dict(request["company_event"]),
        "supersedes": [],
        "retained_work_exception": {
            "manifest_digest": prepared.admission["manifest_digest"],
            "reservation_digest": prepared.admission["reservation_digest"],
            "start_binding_digest": binding_digest,
            "source_identity_digest": digest({
                "source_url": prepared.inventory["source_url"],
                "ats": prepared.inventory["ats"],
            }),
            "publication_deferred": True,
        },
    }


def _validate_prepared(prepared, repository, state, state_directory,
                       inventory_path, jobs_path, store_path, manifest,
                       verifier, *, cycle_id=None, binding_digest=None,
                       now=None, allow_test_verifier=False):
    if not isinstance(prepared, PreparedExceptionalStart) or prepared._token is not _TOKEN:
        raise ValueError("retained_runner_internal_admission_required")
    discount = None
    if cycle_id is not None:
        existing = state.cycle(cycle_id)
        if existing is not None:
            if binding_digest is None or existing != _cycle_for(
                    prepared, cycle_id, binding_digest):
                raise ValueError("retained_runner_existing_cycle_binding_changed")
            discount = cycle_id
    current, company, cycle = _trusted_snapshot(
        repository, state, state_directory, manifest,
        expected_request=prepared.snapshot["request"],
        discount_cycle_id=discount)
    if (current != prepared.snapshot or company != prepared.company
            or cycle != prepared.exception_cycle):
        raise ValueError("retained_runner_trusted_snapshot_changed")
    repeated = validate_frozen_admission(
        store_path, verifier, cycle, inventory_path, jobs_path,
        prepared.admission, now=now,
        allow_test_verifier=allow_test_verifier)
    if repeated != prepared.admission:
        raise ValueError("retained_runner_admission_changed")
    return current


def recover_prepared_exceptional_start(repository, state,
                                       state_directory, journal_path,
                                       inventory_path, jobs_path, store_path,
                                       manifest, verifier, *, now=None,
                                       allow_test_verifier=False):
    """Cold-load an exact frozen preflight without invoking a provider."""
    record = _read_existing_journal(journal_path)
    if record is None:
        raise ValueError("retained_runner_recovery_journal_missing")
    payload = record["prepared"]
    required = {"snapshot", "company", "exception_cycle", "inventory",
                "admission", "started_at"}
    if not isinstance(payload, dict) or set(payload) != required:
        raise ValueError("retained_runner_recovery_journal_corrupt")
    prepared = PreparedExceptionalStart(
        _TOKEN, payload["snapshot"], payload["company"],
        payload["exception_cycle"], payload["inventory"],
        payload["admission"], payload["started_at"])
    _validate_prepared(
        prepared, repository, state, state_directory,
        inventory_path, jobs_path, store_path, manifest, verifier,
        cycle_id=record["cycle_id"], binding_digest=record["binding_digest"],
        now=now, allow_test_verifier=allow_test_verifier)
    saved = _read_inventory(
        inventory_path, record["cycle_id"], record["binding"]["company_id"])
    if saved is not None and saved != (prepared.inventory, False):
        raise ValueError("retained_runner_inventory_readback_changed")
    if (record["state"] in {"INVENTORY_SAVED", "COMMITTED"}
            and saved != (prepared.inventory, False)):
        raise ValueError("retained_runner_inventory_missing_after_checkpoint")
    return prepared


def _fsync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def commit_exceptional_start(prepared, repository, state,
                             state_directory, journal_path, manifest,
                             inventory_path, jobs_path, store_path, verifier,
                             *, now=None, allow_test_verifier=False,
                             state_factory=None, inbox_factory=None,
                             crash_after=None):
    """Converge a reserved start through local State, inbox and request rename."""
    if not isinstance(prepared, PreparedExceptionalStart) or prepared._token is not _TOKEN:
        raise ValueError("retained_runner_internal_admission_required")
    if getattr(state, "readonly", False) is not True:
        raise ValueError("retained_runner_readonly_state_required")
    root = Path(state_directory).resolve()
    if (Path(journal_path).resolve() != root / "retained-work-starts.sqlite3"
            or Path(inventory_path).resolve() != root / "inventories.sqlite3"
            or Path(jobs_path).resolve() != root / "jobs.sqlite3"):
        raise ValueError("retained_runner_state_layout_invalid")
    retained = _read_existing_journal(journal_path)
    _validate_prepared(
        prepared, repository, state, state_directory,
        inventory_path, jobs_path, store_path, manifest, verifier,
        cycle_id=retained["cycle_id"] if retained else None,
        binding_digest=retained["binding_digest"] if retained else None,
        now=now, allow_test_verifier=allow_test_verifier)
    journal = _StartJournal(journal_path)
    writable_state = writable_inbox = None
    try:
        cycle_id, binding, binding_digest = journal.reserve(prepared)
        request_id = binding["request_id"]
        if crash_after == "reserve":
            raise RuntimeError("injected_crash_after_reserve")
        if state_factory is None:
            from job_search_helper.engine import State
            state_factory = lambda: State(str(root / "state.db"))
        writable_state = state_factory()
        if (getattr(writable_state, "readonly", True) is not False
                or Path(getattr(writable_state, "path", "")).resolve()
                    != root / "state.db"):
            raise ValueError("retained_runner_writable_state_invalid")
        cycle = _cycle_for(prepared, cycle_id, binding_digest)
        bound = [item for item in writable_state.cycles()
                 if item.get("start_request_id") == request_id]
        if len(bound) > 1:
            raise ValueError("retained_runner_duplicate_request_cycles")
        if bound and (bound[0].get("id") != cycle_id or bound[0] != cycle):
            raise ValueError("retained_runner_existing_cycle_binding_changed")
        existing = writable_state.cycle(cycle_id)
        if existing is None:
            writable_state.save_cycle(cycle)
            existing = writable_state.cycle(cycle_id)
        if existing != cycle:
            raise ValueError("retained_runner_cycle_readback_changed")
        if crash_after == "state_write":
            raise RuntimeError("injected_crash_after_state_write")
        journal.advance(request_id, "RESERVED", "STATE_SAVED")
        if crash_after == "state":
            raise RuntimeError("injected_crash_after_state")
        if inbox_factory is None:
            from job_search_helper.inbox import InventoryInbox
            destination = InventoryInbox.destination_id(inventory_path)
            inbox_factory = lambda: InventoryInbox(inventory_path, destination)
        writable_inbox = inbox_factory()
        if Path(getattr(writable_inbox, "path", "")).resolve() != Path(inventory_path).resolve():
            raise ValueError("retained_runner_writable_inbox_invalid")
        company_id = binding["company_id"]
        saved = writable_inbox.get(cycle_id, company_id)
        if saved is None:
            writable_inbox.save(cycle_id, company_id, prepared.inventory)
            saved = writable_inbox.get(cycle_id, company_id)
        if saved != (prepared.inventory, False):
            raise ValueError("retained_runner_inventory_readback_changed")
        if crash_after == "inventory_write":
            raise RuntimeError("injected_crash_after_inventory_write")
        journal.advance(request_id, "STATE_SAVED", "INVENTORY_SAVED")
        if crash_after == "inventory":
            raise RuntimeError("injected_crash_after_inventory")
        revalidate_manifest(
            manifest, prepared.exception_cycle, inventory_path, jobs_path)
        request_path = root / "next-scan.json"
        last_path = root / "last-scan-request.json"
        if request_path.exists():
            if digest(_read_json(request_path)) != prepared.snapshot["request_digest"]:
                raise ValueError("retained_runner_request_changed_before_rename")
            if last_path.exists() and digest(_read_json(last_path)) != prepared.snapshot["request_digest"]:
                raise ValueError("retained_runner_last_request_collision")
            os.replace(request_path, last_path)
            _fsync_directory(root)
        elif (not last_path.exists()
              or digest(_read_json(last_path)) != prepared.snapshot["request_digest"]):
            raise ValueError("retained_runner_request_missing_after_start")
        if crash_after == "rename_write":
            raise RuntimeError("injected_crash_after_rename_write")
        journal.advance(request_id, "INVENTORY_SAVED", "COMMITTED")
        if crash_after == "rename":
            raise RuntimeError("injected_crash_after_rename")
        return {"cycle_id": cycle_id, "company_id": company_id,
                "request_id": request_id, "state": "LOCAL_INVENTORY_FROZEN",
                "publication_deferred": True,
                "reservation_digest": prepared.admission["reservation_digest"]}
    finally:
        if writable_inbox is not None:
            writable_inbox.close()
        if writable_state is not None:
            writable_state.close()
        journal.close()
