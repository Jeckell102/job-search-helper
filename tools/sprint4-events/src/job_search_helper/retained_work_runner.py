"""Dedicated local-only runner boundary for one retained-work exception.

This module deliberately does not import the normal runner, remote repository,
Sheets synchronizer, review lifecycle, or ordinary Engine.start_cycle path.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
import uuid

from job_search_helper.retained_work_exception import (
    admit_disjoint_company_request, canonical,
    canonical_admitted_company_identity, digest,
    validate_disjoint_company_preflight, validate_frozen_admission,
)
from job_search_helper.company_events import canonical_company_fact, source_revision
from job_search_helper.scan_request import (
    _read_request, _unfinished_cycle_ids,
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


def _inventory_snapshot(inventory, company, *, fetched_at, event_scope=False):
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
    statuses = {"complete", "partial"}
    if event_scope:
        from .ats import validate_outcome_failure
        statuses.update(("blocked", "failed", "unsupported"))
        raw_failure = getattr(inventory, "outcome_failure", None)
        fields["outcome_failure"] = validate_outcome_failure(raw_failure)
        if raw_failure is not None and fields["outcome_failure"] is None:
            raise ValueError("retained_event_inventory_failure_evidence_invalid")
        verified_zero = getattr(inventory, "verified_zero", None)
        if verified_zero is not None:
            fields["verified_zero"] = verified_zero
        if fields["outcome_failure"] is not None and fields["status"] == "complete":
            raise ValueError("retained_event_complete_inventory_has_failure")
    if (fields["status"] not in statuses
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
    if str(row.get("Company Status", "Active")).strip().casefold() != "active":
        raise ValueError("retained_exception_current_company_invalid")
    return row, fact, source_revision(row)


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


def _request_provenance_id(request):
    """Return the one immutable event-like reservation identity."""
    event = request.get("company_event") if isinstance(request, dict) else None
    if isinstance(event, dict) and isinstance(event.get("event_id"), str):
        return event["event_id"]
    operator = request.get("operator_request") if isinstance(request, dict) else None
    if isinstance(operator, dict) and isinstance(request.get("request_id"), str):
        return "operator:" + request["request_id"]
    raise ValueError("retained_runner_request_provenance_invalid")


def _trusted_snapshot(repository, state, state_directory, manifest, *,
                      expected_request=None, allow_manual_retained=False):
    root = Path(state_directory).resolve()
    request_path = root / "next-scan.json"
    if not request_path.exists() and expected_request is not None:
        request_path = root / "last-scan-request.json"
    request, company_ids = _read_request(request_path)
    if "manual_retained" in request and not allow_manual_retained:
        raise ValueError("retained_runner_manual_event_requires_signed_operator_path")
    if expected_request is not None and request != expected_request:
        raise ValueError("retained_runner_request_changed")
    if request.get("mode") != "company-only" or len(company_ids) != 1:
        raise ValueError("retained_runner_scoped_company_request_required")
    event = request.get("company_event")
    operator = request.get("operator_request")
    if isinstance(event, dict) and operator is None:
        event_id = event.get("event_id")
        if not isinstance(event_id, str) or not _EVENT_ID.fullmatch(event_id):
            raise ValueError("retained_runner_event_id_invalid")
        receipt_path = root / "company-event-bridge" / "receipts" / (event_id + ".json")
    elif isinstance(operator, dict) and event is None:
        request_id = request.get("request_id")
        if (operator.get("schema") != "operator-company-scan-request-v1"
                or operator.get("request_id") != request_id
                or operator.get("company_id") != company_ids[0]
                or operator.get("source_revision") != request.get("source_revision")):
            raise ValueError("retained_runner_operator_request_invalid")
        receipt_path = (root / "operator-company-requests" / "receipts"
                        / (digest({"request_id": request_id}) + ".json"))
    else:
        raise ValueError("retained_runner_request_provenance_invalid")
    receipt = _read_json(receipt_path)
    company, fact, revision = _company_snapshot(repository, company_ids[0])
    if revision != request.get("source_revision"):
        raise ValueError("retained_runner_company_revision_changed")
    probe = type("ReadOnlyEngineProbe", (), {"repo": repository})()
    blockers = sorted(_unfinished_cycle_ids(probe, state, include_remote=True))
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
    return {"request_id": row[0], "session_id": row[1],
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
    # The journal file/table may exist when a process crashed immediately
    # after opening it but before creating a row.  A jobs-database intake hold
    # is checked separately by the normal guard and makes that case fail
    # closed; an empty journal itself is not a session.
    if not rows:
        return None
    if len(rows) != 1:
        raise ValueError("retained_runner_recovery_journal_ambiguous")
    return _decode_journal_row(rows[0])


def _validate_released_reservation(jobs_path, reservation_digest):
    """Prove one retained reservation durably reached FIRST PASS release."""
    location = Path(jobs_path).resolve()
    if not location.is_file():
        raise ValueError("retained_runner_settlement_authority_missing")
    try:
        db = sqlite3.connect(location.as_uri() + "?mode=ro", uri=True)
        try:
            table = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='retained_publications'").fetchone()
            if not table:
                raise ValueError("retained_runner_settlement_authority_missing")
            row = db.execute(
                "SELECT state,queue_evidence,queue_evidence_digest "
                "FROM retained_publications WHERE reservation_digest=?",
                (reservation_digest,)).fetchone()
        finally:
            db.close()
    except ValueError:
        raise
    except (OSError, sqlite3.Error) as error:
        raise ValueError("retained_runner_settlement_authority_unreadable") from error
    if row is None or row[0] != "FIRST_PASS_RELEASED" or not row[1] or not row[2]:
        raise ValueError("retained_runner_first_pass_not_released")
    try:
        evidence = json.loads(row[1])
    except (TypeError, ValueError) as error:
        raise ValueError("retained_runner_release_evidence_corrupt") from error
    if (not isinstance(evidence, dict)
            or evidence.get("reservation_digest") != reservation_digest
            or digest(evidence) != row[2]):
        raise ValueError("retained_runner_release_evidence_corrupt")
    return evidence


def settle_retained_start(state_directory, jobs_path, reservation_digest):
    """Close a frozen start only after durable FIRST PASS release evidence.

    The durable publication and queue evidence remain the audit authority.
    The short-lived preflight embargo row is removed exactly so a later
    retained company can acquire the same single-active-session boundary.  A
    workspace with no start journal is a valid lower-level publication fixture,
    so this is a no-op in that case; any present journal must match exactly.
    Callers hold the normal scraper writer lock across this operation.
    """
    _validate_released_reservation(jobs_path, reservation_digest)
    path = Path(state_directory).resolve() / "retained-work-starts.sqlite3"
    if not path.exists():
        return {"settled": False, "reason": "journal_missing"}
    record = _read_existing_journal(path)
    if record is None:
        return {"settled": False, "reason": "journal_empty"}
    if record["binding"].get("reservation_digest") != reservation_digest:
        raise ValueError("retained_runner_settlement_binding_changed")
    if record["state"] != "FROZEN":
        raise ValueError("retained_runner_lifecycle_journal_invalid")
    db = sqlite3.connect(path)
    try:
        db.execute("BEGIN IMMEDIATE")
        changed = db.execute(
            "DELETE FROM retained_work_starts "
            "WHERE request_id=? AND cycle_id=? AND binding_digest=? "
            "AND state='FROZEN'",
            (record["request_id"], record["session_id"],
             record["binding_digest"])).rowcount
        if changed != 1:
            raise ValueError("retained_runner_settlement_state_changed")
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()
    return {"settled": True, "recovered": False,
            "session_id": record["session_id"]}


class ManualRetainedEventHold(ValueError):
    """A staged event owns the ordinary lifecycle boundary."""


def assert_no_manually_staged_event(state_directory):
    """Hold normal setup before it can construct a writer or start cleanup."""
    from .company_events import is_manual_retained_event_request

    path = Path(state_directory) / "next-scan.json"
    if path.is_symlink():
        raise ValueError("retained_runner_pending_request_symlink")
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return
    if is_manual_retained_event_request(json.loads(raw)):
        raise ManualRetainedEventHold("retained_runner_manual_event_holds_normal_lifecycle")


def assert_normal_lifecycle_not_held(state_directory, jobs_path=None, *, allow_staged_event=False,
                                     selected_retry_cycle_id=None, ordinary_event_cycle_id=None):
    """Fail closed before the normal runner can discover or sync work.

    A retained preflight is intentionally outside State and the normal inbox.
    Its frozen journal is nevertheless an exclusive intake boundary: the
    normal start/sync runner must not consume its request or begin a global
    Sheets lifecycle until the dedicated retained path has settled it.
    Callers hold the normal scraper writer lock while making this check.
    """
    from .retained_operator_journal import assert_no_unfinished_operator_journal

    if not allow_staged_event:
        assert_no_manually_staged_event(state_directory)
    from .selected_retry_lifecycle import assert_no_selected_retry_cycle
    assert_no_selected_retry_cycle(state_directory, permitted_cycle_id=selected_retry_cycle_id)
    from .ordinary_company_event_fetch import assert_no_active_ordinary_event_observation
    assert_no_active_ordinary_event_observation(state_directory, permitted_cycle_id=ordinary_event_cycle_id)
    assert_no_unfinished_operator_journal(state_directory)
    path = Path(state_directory).resolve() / "retained-work-starts.sqlite3"
    record = _read_existing_journal(path)
    if record is not None:
        if record["state"] != "FROZEN":
            raise ValueError("retained_runner_lifecycle_journal_invalid")
        raise ValueError(
            "Retained company-only preflight is frozen; normal lifecycle and "
            "generic sync are held pending its dedicated settlement.")
    # A crash can occur after the jobs-database hold commits and before the
    # separate session journal is created.  Inspect that durable first-stage
    # authority as well; malformed/unreadable hold data fails closed.
    location = Path(jobs_path or (Path(state_directory).resolve() / "jobs.sqlite3"))
    if not location.exists():
        return
    try:
        db = sqlite3.connect(location.as_uri() + "?mode=ro", uri=True)
        try:
            table = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='retained_intake_holds'").fetchone()
            if table:
                rows = db.execute(
                    "SELECT reservation_digest FROM retained_intake_holds "
                    "WHERE state='FROZEN' ORDER BY reservation_digest LIMIT 2").fetchall()
                if rows:
                    raise ValueError(
                        "Retained intake hold is frozen; normal lifecycle and "
                        "generic sync are held pending its dedicated settlement.")
        finally:
            db.close()
    except ValueError:
        raise
    except (OSError, sqlite3.Error) as error:
        raise ValueError("retained_runner_intake_hold_unreadable") from error


def _freeze_intake_hold(jobs_path, prepared, binding, binding_digest):
    """Record the pre-plan publication embargo in the local jobs database.

    The separate retained-start journal protects normal runner entry points.
    This minimal ledger is deliberately also visible to SheetsSynchronizer, so
    an in-process caller cannot bypass that entry point before a v2 plan has
    been reserved.  A crash after this write is conservative: it leaves an
    operator-visible hold rather than exposing generic publication.
    """
    request = prepared.snapshot["request"]
    values = (
        prepared.admission["reservation_digest"], request["request_id"],
        _request_provenance_id(request), request["company_ids"][0],
        prepared.admission["manifest_digest"], binding_digest, "FROZEN",
    )
    location = Path(jobs_path).resolve()
    db = sqlite3.connect(location)
    try:
        db.execute("BEGIN IMMEDIATE")
        db.execute("""CREATE TABLE IF NOT EXISTS retained_intake_holds (
            reservation_digest TEXT PRIMARY KEY,
            request_id TEXT NOT NULL UNIQUE,
            event_id TEXT NOT NULL UNIQUE,
            company_id TEXT NOT NULL,
            manifest_digest TEXT NOT NULL,
            start_binding_digest TEXT NOT NULL,
            state TEXT NOT NULL CHECK(state='FROZEN')
        )""")
        row = db.execute(
            "SELECT reservation_digest,request_id,event_id,company_id,"
            "manifest_digest,start_binding_digest,state "
            "FROM retained_intake_holds WHERE reservation_digest=?",
            (values[0],)).fetchone()
        if row is None:
            db.execute("INSERT INTO retained_intake_holds VALUES (?,?,?,?,?,?,?)", values)
        elif tuple(row) != values:
            raise ValueError("retained_runner_intake_hold_changed")
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


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
    validate_disjoint_company_preflight(
        store_path, verifier, cycle, inventory_path, jobs_path, manifest,
        request, first["receipt"], company, first["company_fact"],
        first["blocking_cycle_ids"], now=current,
        allow_test_verifier=allow_test_verifier)
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
    prepared = PreparedExceptionalStart(
        _TOKEN, first, company, cycle, inventory, admission,
        current.astimezone(timezone.utc).isoformat())
    _validate_immutable_admission_binding(prepared)
    repeated = validate_frozen_admission(
        store_path, verifier, cycle_final, inventory_path, jobs_path,
        admission, now=current, allow_test_verifier=allow_test_verifier)
    if repeated != admission:
        raise ValueError("retained_runner_admission_changed")
    return prepared


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
        binding = _start_binding(prepared)
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
                session_id = "RWS-" + uuid.uuid4().hex[:12].upper()
                self.db.execute(
                    "INSERT INTO retained_work_starts VALUES (?,?,?,?,?,?,?)",
                    (request_id, session_id, encoded, binding_digest,
                     prepared_encoded, prepared_digest, "FROZEN"))
            else:
                session_id = row[0]
                if (row[1] != encoded or row[2] != binding_digest
                        or row[3] != prepared_encoded or row[4] != prepared_digest
                        or row[5] != "FROZEN"):
                    raise ValueError("retained_runner_start_binding_changed")
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        return session_id, binding, binding_digest

    def only(self):
        rows = self.db.execute(
            "SELECT request_id,cycle_id,binding,binding_digest,prepared,"
            "prepared_digest,state FROM retained_work_starts").fetchall()
        if len(rows) != 1:
            raise ValueError("retained_runner_recovery_journal_ambiguous")
        return _decode_journal_row(rows[0])


def _start_binding(prepared):
    request = prepared.snapshot["request"]
    return {
        "request_id": request["request_id"],
        "event_id": _request_provenance_id(request),
        "company_id": request["company_ids"][0],
        "snapshot_digest": prepared.snapshot["snapshot_digest"],
        "manifest_digest": prepared.admission["manifest_digest"],
        "reservation_digest": prepared.admission["reservation_digest"],
        "inventory_digest": digest(prepared.inventory),
    }

def _validate_immutable_admission_binding(prepared):
    """Cross-check mutable journal payloads against the frozen reservation.

    Journal hashes detect accidental torn writes, not an attacker (or a bad
    repair tool) that rewrites every journal digest.  The admission store is
    the immutable authority.  Re-derive its protected Company/source/provider
    identity from the frozen inventory and the preflight snapshot on every
    fresh and recovered validation.
    """
    snapshot = prepared.snapshot
    admission = prepared.admission
    if not isinstance(snapshot, dict) or not isinstance(admission, dict):
        raise ValueError("retained_runner_admission_binding_invalid")
    request = snapshot.get("request")
    receipt = snapshot.get("receipt")
    payload = admission.get("reservation_payload")
    if (not isinstance(request, dict) or not isinstance(receipt, dict)
            or not isinstance(payload, dict)
            or set(payload) != {
                "request_id", "event_id", "exception_cycle", "company_id",
                "manifest_digest", "company_identity_digest", "request_digest",
                "event_receipt_digest", "defer_sync"}
            or admission.get("reservation_digest") != digest(payload)
            or admission.get("company_id") != payload["company_id"]
            or admission.get("manifest_digest") != payload["manifest_digest"]
            or payload.get("request_id") != request.get("request_id")
            or payload.get("event_id") != _request_provenance_id(request)
            or payload.get("company_id")
                != (request.get("company_ids") or [None])[0]
            or payload.get("request_digest") != digest(request)
            or payload.get("event_receipt_digest") != digest(receipt)
            or payload.get("defer_sync") is not True):
        raise ValueError("retained_runner_admission_binding_invalid")
    try:
        derived = canonical_admitted_company_identity(_admission_company(
            snapshot, prepared.company, prepared.inventory))
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("retained_runner_admission_binding_invalid") from error
    if payload["company_identity_digest"] != digest(derived):
        raise ValueError("retained_runner_admitted_identity_changed")


def _validate_prepared(prepared, repository, state, state_directory,
                       inventory_path, jobs_path, store_path, manifest,
                       verifier, *, session_id=None,
                       now=None, allow_test_verifier=False):
    if not isinstance(prepared, PreparedExceptionalStart) or prepared._token is not _TOKEN:
        raise ValueError("retained_runner_internal_admission_required")
    if session_id is not None and state.cycle(session_id) is not None:
        raise ValueError("retained_runner_session_leaked_to_state")
    current, company, cycle = _trusted_snapshot(
        repository, state, state_directory, manifest,
        expected_request=prepared.snapshot["request"])
    if (current != prepared.snapshot or company != prepared.company
            or cycle != prepared.exception_cycle):
        raise ValueError("retained_runner_trusted_snapshot_changed")
    _validate_immutable_admission_binding(prepared)
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
        session_id=record["session_id"],
        now=now, allow_test_verifier=allow_test_verifier)
    if (record["state"] != "FROZEN"
            or record["binding"] != _start_binding(prepared)
            or record["binding_digest"] != digest(record["binding"])):
        raise ValueError("retained_runner_recovery_journal_corrupt")
    return prepared


def commit_exceptional_start(prepared, repository, state,
                             state_directory, journal_path, manifest,
                             inventory_path, jobs_path, store_path, verifier,
                             *, now=None, allow_test_verifier=False,
                             state_factory=None, inbox_factory=None,
                             crash_after=None):
    """Durably freeze one exceptional session without normal lifecycle writes."""
    if not isinstance(prepared, PreparedExceptionalStart) or prepared._token is not _TOKEN:
        raise ValueError("retained_runner_internal_admission_required")
    if getattr(state, "readonly", False) is not True:
        raise ValueError("retained_runner_readonly_state_required")
    root = Path(state_directory).resolve()
    if (Path(journal_path).resolve() != root / "retained-work-starts.sqlite3"
            or Path(inventory_path).resolve() != root / "inventories.sqlite3"
            or Path(jobs_path).resolve() != root / "jobs.sqlite3"):
        raise ValueError("retained_runner_state_layout_invalid")
    # These legacy injection points remain accepted for source compatibility,
    # but a retained-work freeze must never construct either normal writer.
    del state_factory, inbox_factory
    if crash_after not in {None, "intake_hold", "reserve"}:
        raise ValueError("retained_runner_crash_point_invalid")
    # Share the normal runner's single-writer boundary.  This makes the
    # journal hold and the normal-runner guard race-free: either a normal run
    # finishes before the retained reservation exists, or it observes the
    # frozen reservation before creating a repository, sync, State, or inbox.
    from .cli import scraper_lock_name, writer_lock
    with writer_lock(root / scraper_lock_name()):
        retained = _read_existing_journal(journal_path)
        _validate_prepared(
            prepared, repository, state, state_directory,
            inventory_path, jobs_path, store_path, manifest, verifier,
            session_id=retained["session_id"] if retained else None,
            now=now, allow_test_verifier=allow_test_verifier)
        journal = _StartJournal(journal_path)
        try:
            # Establish the synchronizer-visible hold first.  It is safe for
            # an interrupted start to require dedicated recovery; it is not
            # safe to leave a window where generic dirty discovery can run.
            binding = _start_binding(prepared)
            binding_digest = digest(binding)
            _freeze_intake_hold(jobs_path, prepared, binding, binding_digest)
            if crash_after == "intake_hold":
                raise RuntimeError("injected_crash_after_intake_hold")
            session_id, binding, _binding_digest = journal.reserve(prepared)
            if crash_after == "reserve":
                raise RuntimeError("injected_crash_after_reserve")
            return {"session_id": session_id,
                    # Compatibility alias only: this is an RWS journal session,
                    # never a State cycle or ordinary lifecycle identifier.
                    "cycle_id": session_id,
                    "company_id": binding["company_id"],
                    "request_id": binding["request_id"], "state": "RETAINED_WORK_FROZEN",
                    "publication_deferred": True,
                    "reservation_digest": prepared.admission["reservation_digest"]}
        finally:
            journal.close()
