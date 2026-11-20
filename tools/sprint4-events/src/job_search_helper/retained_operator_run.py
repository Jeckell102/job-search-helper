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
from .retained_operator_authorization import (
    ACTION, EVENT_ACTION, verify_expired_event_authorization, verify_retained_scope_authorization,
)
from .retained_operator_journal import (
    FETCH_OUTCOME, INVENTORY_FROZEN, PREPARED, SETTLED, VERIFIED_ZERO, RetainedOperatorJournal,
    _expected_consumption, operator_journal_binding,
)
from .retained_operator_preflight import collect_operator_membership, verify_operator_source_identity
from .retained_session_store import SYNC_CONFIRMED, SYNC_PENDING, RetainedSessionStore
from .retained_work_exception import digest
from .retained_work_orchestrator import _run_retained_reservation_locked
from .retained_work_publication import (
    _verify_operator_terminal_receipt, finish_confirmed_retained_publication, recover_claimed_retained_chunk,
)
from .retained_work_runner import (
    PreparedExceptionalStart, _TOKEN, _StartJournal, _freeze_intake_hold, _inventory_snapshot,
    _read_existing_journal, _start_binding,
    assert_normal_lifecycle_not_held, settle_retained_start,
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


def _consume_settled(root, local, journal, binding, record, *, local_writer):
    evidence = record["settlement_evidence"]
    event_scope = binding["claims"]["action"] == EVENT_ACTION
    if not (event_scope and evidence.get("state") in {VERIFIED_ZERO, FETCH_OUTCOME}):
        if _terminal_evidence(root, local, binding, record["inventory_sha256"]) != evidence:
            raise ValueError("retained_operator_terminal_evidence_changed")
    request_hash = binding["claims"]["request_sha256"]
    archive = root / "company-event-bridge/consumed-requests" / (request_hash + ".json")
    source = archive if archive.exists() else root / "next-scan.json"
    if source.is_symlink():
        raise ValueError("retained_operator_terminal_request_changed")
    request = json.loads(source.read_text(encoding="utf-8"))
    if digest(request) != request_hash:
        raise ValueError("retained_operator_terminal_request_changed")
    result = dict(evidence)
    if event_scope:
        from .retained_event_outcome import retained_event_outcome_facts
        with writer_lock(root / "writer.lock"):
            reservation = binding["reservation_digest"]
            _facts, outcome = retained_event_outcome_facts(local, request_hash, reservation)
            if outcome is None:
                with closing(local_writer()) as writer:
                    if Path(writer.path).resolve() != Path(local.path).resolve():
                        raise ValueError("retained_operator_repository_identity_changed")
                    outcome = writer.record_retained_event_outcome(request_hash, reservation)
                _facts, verified = retained_event_outcome_facts(local, request_hash, reservation)
                if verified != outcome:
                    raise ValueError("retained_event_outcome_write_unverified")
        result["outcome_id"] = outcome["outcome_id"]
    expected = _expected_consumption(binding, evidence)
    consumption = _consume_request(
        root, request, preserve_replacement=True, consumption_state=expected["state"],
    )
    journal.release_after_settlement(binding, inventory_sha256=record["inventory_sha256"], consumption=consumption)
    return {**result, "consumption": consumption}


def _settle_event_without_publication(root, local, journal, binding, record, local_writer):
    from .retained_event_outcome import returned_failure_evidence, sealed_event_source, verified_zero_evidence

    with writer_lock(root / "writer.lock"):
        path = root / "next-scan.json"
        if path.is_symlink():
            raise ValueError("retained_operator_terminal_request_changed")
        request = json.loads(path.read_text(encoding="utf-8"))
        event_id, fact, current = sealed_event_source(root, local, binding["claims"], request)
        if record["inventory"]["status"] == "complete":
            evidence = verified_zero_evidence(local, binding, record, fact)
        else:
            evidence, _fresh, _stale = returned_failure_evidence(
                local, binding, record, event_id, fact, source_current=current,
            )
        record = journal.record_settlement(
            binding, inventory_sha256=record["inventory_sha256"], evidence=evidence,
        )
    return _consume_settled(root, local, journal, binding, record, local_writer=local_writer)


def _cancel_stale_frozen_event(root, local, journal, binding, record, local_writer):
    """Stop a superseded fetch only while its reservation has no publication."""
    from .retained_event_outcome import returned_failure_evidence, sealed_event_source

    with writer_lock(root / "writer.lock"):
        if (_stored_session(root, binding["reservation_digest"]) is not None
                or _read_existing_journal(root / "retained-work-starts.sqlite3") is not None):
            return None
        path = root / "next-scan.json"
        if path.is_symlink():
            raise ValueError("retained_operator_terminal_request_changed")
        request = json.loads(path.read_text(encoding="utf-8"))
        event_id, fact, current = sealed_event_source(root, local, binding["claims"], request)
        if current:
            return None
        evidence, _fresh, _stale = returned_failure_evidence(
            local, binding, record, event_id, fact, source_current=False,
        )
        record = journal.record_settlement(
            binding, inventory_sha256=record["inventory_sha256"], evidence=evidence,
        )
    return _consume_settled(root, local, journal, binding, record, local_writer=local_writer)


def _recover_event_publication(root, local, remote_reader, local_writer, journal, binding, record):
    """Read only an already authorized durable claim and settle its exact result."""
    if record is None:
        raise ValueError("retained_event_expired_without_admitted_claim")
    if record["state"] == SETTLED:
        return _consume_settled(root, local, journal, binding, record, local_writer=local_writer)
    if record["state"] == INVENTORY_FROZEN:
        inventory = record["inventory"]
        if inventory["status"] != "complete" or not inventory["jobs"]:
            return _settle_event_without_publication(root, local, journal, binding, record, local_writer)
    reservation = binding["reservation_digest"]
    with writer_lock(root / "writer.lock"):
        path = root / "retained-sessions.sqlite3"
        if record["state"] != INVENTORY_FROZEN or not path.is_file() or path.is_symlink():
            raise ValueError("retained_event_expired_without_admitted_claim")
        claims = binding["claims"]
        with closing(RetainedSessionStore(path)) as store:
            session = store.load(reservation)
            if (session["state"] not in {SYNC_PENDING, SYNC_CONFIRMED}
                    or any(session[key] != claims[key] for key in ("request_id", "company_id", "source_revision"))
                    or not session["chunks"]):
                raise ValueError("retained_event_expired_without_admitted_claim")
            claim_id = session["chunks"][-1]["claim_id"]
            if session["state"] == SYNC_PENDING:
                result = recover_claimed_retained_chunk(
                    reservation, store, local, remote_reader, claim_id=claim_id, runtime_binding=binding["runtime"],
                )
                if result["state"] == "HELD_UNCLAIMED_SUFFIX":
                    return result
            if retained_publication(local, reservation)["state"] == FIRST_PASS_RELEASED:
                _terminal_evidence(root, local, binding, record["inventory_sha256"])
                settle_retained_start(root, local.path, reservation)
            else:
                finish_confirmed_retained_publication(
                    reservation, store, local, remote_reader, local_writer, claim_id=claim_id,
                    runtime_binding=binding["runtime"],
                )
            evidence = _terminal_evidence(root, local, binding, record["inventory_sha256"])
            record = journal.record_settlement(
                binding, inventory_sha256=record["inventory_sha256"], evidence=evidence,
            )
    return _consume_settled(root, local, journal, binding, record, local_writer=local_writer)


def run_operator_membership(local_reader, remote_reader, state, state_directory, manifest, runtime, *,
                            approval, verifier, fetcher, local_writer, remote_writer,
                            request_id, company_id, max_operations=100, now=None, action=ACTION):
    """Run inside the inherited scraper lease. Factories are entered only on demand."""
    root = Path(state_directory).resolve()
    jobs = root / "jobs.sqlite3"
    if type(max_operations) is not int or not 1 <= max_operations <= 100:
        raise ValueError("retained_operator_max_operations_invalid")
    claims = approval.get("payload") if isinstance(approval, dict) else None
    if (not isinstance(claims, dict) or claims.get("request_id") != request_id
            or claims.get("company_id") != company_id or claims.get("cycle_id") != manifest["cycle_id"]):
        raise ValueError("retained_operator_authorization_scope_changed")
    expired = False
    try:
        authorization = verify_retained_scope_authorization(approval, claims, verifier, action=action, now=now)
    except ValueError as error:
        if action != EVENT_ACTION or str(error) != "selected_recovery_authorization_expired":
            raise
        authorization = verify_expired_event_authorization(approval, claims, verifier, now=now)
        expired = True
    binding = operator_journal_binding(claims, runtime, authorization)
    journal = RetainedOperatorJournal(root)
    record = journal.read(binding)
    if expired:
        return _recover_event_publication(root, local_reader, remote_reader, local_writer, journal, binding, record)
    if record is not None and record["state"] == SETTLED:
        return _consume_settled(root, local_reader, journal, binding, record, local_writer=local_writer)
    if record is not None and record["state"] == INVENTORY_FROZEN:
        inventory = record["inventory"]
        if action == EVENT_ACTION and (inventory["status"] != "complete" or not inventory["jobs"]):
            return _settle_event_without_publication(root, local_reader, journal, binding, record, local_writer)
        session = _stored_session(root, binding["reservation_digest"])
        if action == EVENT_ACTION and session is None:
            cancelled = _cancel_stale_frozen_event(root, local_reader, journal, binding, record, local_writer)
            if cancelled is not None:
                return cancelled
        if action == EVENT_ACTION and session is not None and session["state"] == SYNC_CONFIRMED:
            return _recover_event_publication(root, local_reader, remote_reader, local_writer, journal, binding, record)
        if (session is not None and session["state"] == SYNC_CONFIRMED
                and retained_publication(local_reader, binding["reservation_digest"])["state"] == FIRST_PASS_RELEASED):
            with writer_lock(root / "writer.lock"):
                evidence = _terminal_evidence(root, local_reader, binding, record["inventory_sha256"])
                record = journal.record_settlement(
                    binding, inventory_sha256=record["inventory_sha256"], evidence=evidence,
                )
            return _consume_settled(root, local_reader, journal, binding, record, local_writer=local_writer)
    if record is None:
        assert_normal_lifecycle_not_held(root, jobs, allow_staged_event=action == EVENT_ACTION)
    elif record["state"] not in {PREPARED, INVENTORY_FROZEN}:
        raise ValueError("retained_operator_journal_fetch_ambiguous")
    measured, snapshot, company, cycle = collect_operator_membership(
        local_reader, remote_reader(), state, root, manifest, runtime, expires_at=claims["expires_at"],
        request_id=request_id, company_id=company_id, action=action,
        resuming_frozen_inventory=record is not None and record["state"] == INVENTORY_FROZEN,
    )
    if measured != claims:
        raise ValueError("retained_operator_authorization_scope_changed")
    if record is None or record["state"] == PREPARED:
        if action == EVENT_ACTION and local_reader.db.execute(
                "SELECT 1 FROM scrape_outcomes WHERE request_id=? LIMIT 1", (request_id,),
        ).fetchone():
            raise ValueError("retained_event_outcome_exists_before_admission")
        verify_retained_scope_authorization(approval, measured, verifier, action=action, now=now)
    record = journal.prepare(binding)
    if record["state"] == PREPARED:
        claim = journal.claim_fetch(binding)
        fetch_started_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
        fetched = fetcher(company.get("ATS / Source", ""), company["Official Careers URL"], company_id,
                          company["Company"])
        stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
        inventory = _inventory_snapshot(
            fetched, company, fetched_at=stamp, event_scope=action == EVENT_ACTION,
        )
        inventory["fetch_started_at"] = fetch_started_at
        verify_operator_source_identity(manifest, {"company_id": company_id}, company, snapshot["company_fact"],
                                        inventory=inventory)
        record = journal.freeze_inventory(binding, claim, inventory)
        if action == EVENT_ACTION and (inventory["status"] != "complete" or not inventory["jobs"]):
            return _settle_event_without_publication(root, local_reader, journal, binding, record, local_writer)
        if action == EVENT_ACTION:
            cancelled = _cancel_stale_frozen_event(root, local_reader, journal, binding, record, local_writer)
            if cancelled is not None:
                return cancelled
        reread, current_snapshot, current_company, current_cycle = collect_operator_membership(
            local_reader, remote_reader(), state, root, manifest, runtime, expires_at=claims["expires_at"],
            request_id=request_id, company_id=company_id, action=action,
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
        verify_retained_scope_authorization(approval, claims, verifier, action=action, now=now)
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
                    writer_already_held=True, authorization_now=now,
                )
        if result["publication"]["state"] != FIRST_PASS_RELEASED:
            raise ValueError("retained_operator_publication_unsettled")
        evidence = _terminal_evidence(root, local_reader, binding, record["inventory_sha256"])
        record = journal.record_settlement(binding, inventory_sha256=record["inventory_sha256"], evidence=evidence)
    return _consume_settled(root, local_reader, journal, binding, record, local_writer=local_writer)
