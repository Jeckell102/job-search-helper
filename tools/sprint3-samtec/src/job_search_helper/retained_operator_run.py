"""Execute and recover one signed operator Company request under scraper admission."""
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from .cli import writer_lock
from .engine import Engine
from .retained_company_event import _consume_request
from .retained_dirty_provenance import FIRST_PASS_RELEASED, retained_publication
from .retained_operator_authorization import verify_operator_membership_authorization
from .retained_operator_journal import (
    INVENTORY_FROZEN, PREPARED, SETTLED, RetainedOperatorJournal, operator_journal_binding,
)
from .retained_operator_preflight import collect_operator_membership, verify_operator_source_identity
from .retained_session_store import SYNC_CONFIRMED, RetainedSessionStore
from .retained_work_exception import digest
from .retained_work_orchestrator import _run_retained_reservation_locked
from .retained_work_publication import _verify_operator_terminal_receipt
from .retained_work_runner import (
    PreparedExceptionalStart, _TOKEN, _StartJournal, _freeze_intake_hold, _inventory_snapshot,
    _read_existing_journal, _start_binding,
    assert_normal_lifecycle_not_held,
)


def _stored_session(root, reservation):
    path = root / "retained-sessions.sqlite3"
    if not path.exists():
        return None
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        row = db.execute(
            "SELECT request_id,company_id,source_revision,cycle_id,state,plan,plan_digest,projection_digest,"
            "receipt_id,intent_id,acknowledgement_id FROM retained_sessions WHERE reservation_digest=?",
            (reservation,),
        ).fetchone()
    return dict(row) if row is not None else None


def _terminal_evidence(root, local, binding, inventory_sha256):
    reservation = binding["reservation_digest"]
    claims = binding["claims"]
    session = _stored_session(root, reservation)
    if (session is None or session["state"] != SYNC_CONFIRMED
            or any(session[key] != claims[key] for key in ("request_id", "company_id", "source_revision"))):
        raise ValueError("retained_operator_terminal_session_unverified")
    provenance = retained_publication(local, reservation)
    if (provenance["manifest_digest"] != claims["historical_manifest_sha256"]
            or provenance["exception_cycle"] != claims["cycle_id"]):
        raise ValueError("retained_operator_terminal_provenance_changed")
    session["plan"] = json.loads(session["plan"])
    queue = _verify_operator_terminal_receipt(reservation, session, local, runtime_binding=binding["runtime"])
    evidence = {
        key: session[key] for key in ("request_id", "company_id", "source_revision", "plan_digest",
                                     "projection_digest", "receipt_id", "intent_id", "acknowledgement_id")
    }
    if any(not value for value in evidence.values()):
        raise ValueError("retained_operator_terminal_receipt_incomplete")
    return {
        **evidence, "state": SYNC_CONFIRMED, "reservation_digest": reservation,
        "inventory_sha256": inventory_sha256, "runtime_binding_sha256": claims["runtime_sha256"],
        "first_pass_evidence_sha256": digest(queue),
    }


def _consume_settled(root, local, journal, binding, record):
    evidence = _terminal_evidence(root, local, binding, record["inventory_sha256"])
    if evidence != record["settlement_evidence"]:
        raise ValueError("retained_operator_terminal_evidence_changed")
    request_hash = binding["claims"]["request_sha256"]
    archive = root / "company-event-bridge/consumed-requests" / (request_hash + ".json")
    source = archive if archive.exists() else root / "next-scan.json"
    request = json.loads(source.read_text(encoding="utf-8"))
    if digest(request) != request_hash:
        raise ValueError("retained_operator_terminal_request_changed")
    consumption = _consume_request(root, request, preserve_replacement=True)
    journal.release_after_settlement(binding, inventory_sha256=record["inventory_sha256"], consumption=consumption)
    return {**evidence, "consumption": consumption}


def run_operator_membership(local_reader, remote_reader, state, state_directory, manifest, runtime, *,
                            approval, verifier, fetcher, local_writer, remote_writer,
                            request_id, company_id, max_operations=100, now=None):
    """Run inside the inherited scraper lease. Factories are entered only on demand."""
    root = Path(state_directory).resolve()
    jobs = root / "jobs.sqlite3"
    if type(max_operations) is not int or not 1 <= max_operations <= 100:
        raise ValueError("retained_operator_max_operations_invalid")
    claims = approval.get("payload") if isinstance(approval, dict) else None
    if (not isinstance(claims, dict) or claims.get("request_id") != request_id
            or claims.get("company_id") != company_id or claims.get("cycle_id") != manifest["cycle_id"]):
        raise ValueError("retained_operator_authorization_scope_changed")
    authorization = verify_operator_membership_authorization(approval, claims, verifier, now=now)
    binding = operator_journal_binding(claims, runtime, authorization)
    journal = RetainedOperatorJournal(root)
    record = journal.read(binding)
    if record is not None and record["state"] == SETTLED:
        return _consume_settled(root, local_reader, journal, binding, record)
    if record is None:
        assert_normal_lifecycle_not_held(root, jobs)
    elif record["state"] not in {PREPARED, INVENTORY_FROZEN}:
        raise ValueError("retained_operator_journal_fetch_ambiguous")
    measured, snapshot, company, cycle = collect_operator_membership(
        local_reader, remote_reader(), state, root, manifest, runtime, expires_at=claims["expires_at"],
        request_id=request_id, company_id=company_id,
        resuming_frozen_inventory=record is not None and record["state"] == INVENTORY_FROZEN,
    )
    if measured != claims:
        raise ValueError("retained_operator_authorization_scope_changed")
    if record is None or record["state"] == PREPARED:
        verify_operator_membership_authorization(approval, measured, verifier, now=now)
    record = journal.prepare(binding)
    if record["state"] == PREPARED:
        claim = journal.claim_fetch(binding)
        fetch_started_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
        fetched = fetcher(company.get("ATS / Source", ""), company["Official Careers URL"], company_id,
                          company["Company"])
        stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
        inventory = _inventory_snapshot(fetched, company, fetched_at=stamp)
        inventory["fetch_started_at"] = fetch_started_at
        verify_operator_source_identity(manifest, {"company_id": company_id}, company, snapshot["company_fact"],
                                        inventory=inventory)
        record = journal.freeze_inventory(binding, claim, inventory)
        reread, current_snapshot, current_company, current_cycle = collect_operator_membership(
            local_reader, remote_reader(), state, root, manifest, runtime, expires_at=claims["expires_at"],
            request_id=request_id, company_id=company_id,
        )
        if (reread, current_snapshot, current_company, current_cycle) != (claims, snapshot, company, cycle):
            raise ValueError("retained_operator_prefetch_evidence_changed")
    inventory = record["inventory"]
    verify_operator_source_identity(manifest, {"company_id": company_id}, company, snapshot["company_fact"],
                                    inventory=inventory)
    if inventory["status"] != "complete":
        raise ValueError("retained_operator_complete_inventory_required")
    reservation = binding["reservation_digest"]
    prepared = PreparedExceptionalStart(
        _TOKEN, snapshot, company, cycle, inventory,
        {"reservation_digest": reservation, "manifest_digest": manifest["manifest_digest"],
         "reservation_payload": {key: binding[key] for key in ("claims", "runtime", "authorization")}},
        inventory["fetched_at"],
    )
    start_path = root / "retained-work-starts.sqlite3"
    with writer_lock(root / "writer.lock"):
        start = _read_existing_journal(start_path)
        if start is not None and start["binding"] != _start_binding(prepared):
            raise ValueError("retained_operator_existing_start_conflict")
        if start is None and _stored_session(root, reservation) is None:
            start_binding = _start_binding(prepared)
            _freeze_intake_hold(jobs, prepared, start_binding, digest(start_binding))
            with closing(_StartJournal(start_path)) as starts:
                starts.reserve(prepared)
        with closing(local_writer()) as local:
            engine = Engine(local, state, error_log_path=root / "retained-errors.jsonl")
            with closing(RetainedSessionStore(root / "retained-sessions.sqlite3")) as sessions:
                result = _run_retained_reservation_locked(
                    prepared, engine, local, remote_writer(), sessions, state_directory=root,
                    max_operations=max_operations, membership_only=True, runtime_binding=runtime,
                    writer_already_held=True,
                )
        if result["publication"]["state"] != FIRST_PASS_RELEASED:
            raise ValueError("retained_operator_publication_unsettled")
        evidence = _terminal_evidence(root, local_reader, binding, record["inventory_sha256"])
        record = journal.record_settlement(binding, inventory_sha256=record["inventory_sha256"], evidence=evidence)
    return _consume_settled(root, local_reader, journal, binding, record)
