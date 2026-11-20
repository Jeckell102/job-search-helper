"""One explicit, signer-authorized retained Company-event execution path.

This is deliberately not part of the ordinary runner lifecycle.  It consumes
one bridge-owned request, and has no fallback to an Inbox, global synchronizer,
or broad cycle.
"""
from __future__ import annotations

import base64
from contextlib import nullcontext
import json
import os
from pathlib import Path
import sqlite3
import tempfile


def _verifier(key_id, public_key_base64):
    if not isinstance(key_id, str) or not key_id.strip():
        raise ValueError("retained_event_key_id_required")
    try:
        public_key = base64.b64decode(str(public_key_base64).encode("ascii"), validate=True)
    except Exception as error:
        raise ValueError("retained_event_public_key_invalid") from error
    if len(public_key) != 32:
        raise ValueError("retained_event_public_key_invalid")
    from .selected_recovery_authorization import Ed25519AuthorizationVerifier
    return Ed25519AuthorizationVerifier({key_id: public_key})


def _consume_request(root, request, *, preserve_replacement=False):
    """Archive then remove only the exact request that reached FIRST PASS.

    Every restart reuses the immutable archive.  A replacement request is
    never removed: it has a different canonical payload and fails closed.
    """
    from .retained_work_runner import digest
    request_path = root / "next-scan.json"
    archive = root / "company-event-bridge" / "consumed-requests" / (digest(request) + ".json")
    receipt = root / "company-event-bridge" / "consumption-receipts" / (digest(request) + ".json")
    def read(path):
        if not path.exists(): return None
        return json.loads(path.read_text(encoding="utf-8"))
    def write(path, value):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".consume-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(value, stream, sort_keys=True, separators=(",", ":")); stream.flush(); os.fsync(stream.fileno())
            os.replace(temporary, path)
            directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try: os.fsync(directory)
            finally: os.close(directory)
        finally:
            if os.path.exists(temporary): os.unlink(temporary)
    prior = read(archive)
    if prior is None: write(archive, request)
    elif prior != request: raise ValueError("retained_event_archive_changed")
    current = read(request_path)
    preserved = current is not None and current != request
    if current is not None:
        if preserved:
            if not preserve_replacement:
                raise ValueError("retained_event_request_replaced")
        else:
            request_path.unlink()
            directory = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try: os.fsync(directory)
            finally: os.close(directory)
    payload = {"request_sha256": digest(request), "state": "FIRST_PASS_RELEASED_CONSUMED"}
    prior = read(receipt)
    if prior is None: write(receipt, payload)
    elif prior != payload: raise ValueError("retained_event_consumption_receipt_changed")
    final_current = read(request_path)
    if (read(archive) != request or read(receipt) != payload
            or (not preserve_replacement and final_current is not None)
            or (preserve_replacement and final_current == request)):
        raise ValueError("retained_event_consumption_unconfirmed")
    return payload


def _recover_settled_consumption(root):
    """Finish a post-settlement consumption crash without factories/replay."""
    from .retained_work_runner import digest
    archive_dir = root / "company-event-bridge" / "consumed-requests"
    if not archive_dir.is_dir(): return None
    pending = []
    for path in sorted(archive_dir.glob("*.json")):
        try:
            request = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise ValueError("retained_event_consumption_archive_corrupt")
        if not isinstance(request, dict) or path.stem != digest(request):
            raise ValueError("retained_event_consumption_archive_corrupt")
        receipt_path = (root / "company-event-bridge" / "consumption-receipts"
                        / (digest(request) + ".json"))
        expected_receipt = {"request_sha256": digest(request),
                            "state": "FIRST_PASS_RELEASED_CONSUMED"}
        if receipt_path.exists():
            try:
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as error:
                raise ValueError("retained_event_consumption_receipt_corrupt") from error
            if receipt != expected_receipt:
                raise ValueError("retained_event_consumption_receipt_changed")
            # This archive is complete historical evidence, not recovery work.
            continue
        pending.append((path, request))
    if len(pending) > 1:
        raise ValueError("retained_event_consumption_archive_ambiguous")
    if not pending:
        return None
    for path, request in pending:
        from .scan_request import _read_request
        from .retained_work_runner import _request_provenance_id
        try:
            archived, company_ids = _read_request(path)
        except (OSError, ValueError) as error:
            raise ValueError("retained_event_consumption_archive_corrupt") from error
        if archived != request or len(company_ids) != 1:
            raise ValueError("retained_event_consumption_archive_corrupt")
        event = request.get("company_event")
        operator = request.get("operator_request")
        if request.get("repair_retry") is not None:
            raise ValueError("retained_event_consumption_archive_corrupt")
        if isinstance(event, dict):
            from .company_intake_dispatcher import is_event_bound_company_request
            if not is_event_bound_company_request(request):
                raise ValueError("retained_event_consumption_archive_corrupt")
        elif not (isinstance(operator, dict)
                  and operator.get("schema") == "operator-company-scan-request-v1"
                  and operator.get("request_id") == request.get("request_id")
                  and operator.get("company_id") == company_ids[0]
                  and operator.get("source_revision") == request.get("source_revision")):
            raise ValueError("retained_event_consumption_archive_corrupt")
        provenance_id = _request_provenance_id(request)
        # Re-read the original admission receipt.  The frozen admission must
        # not become a substitute for the bridge/operator provenance proof.
        if isinstance(event, dict):
            receipt_path = root / "company-event-bridge" / "receipts" / (event["event_id"] + ".json")
            required = {"schema", "event_id", "company_id", "revision", "source_revision", "state", "recorded_at", "request_sha256"}
            expected = {"schema": "company-event-scan-request-v1", "event_id": event["event_id"],
                        "company_id": company_ids[0], "revision": event["revision"],
                        "source_revision": request["source_revision"]}
            allowed_states = {"REQUEST_WRITTEN", "REQUEST_CONFIRMED", "REQUEST_SUPERSEDED_OLDER"}
        else:
            receipt_path = root / "operator-company-requests" / "receipts" / (digest({"request_id": request["request_id"]}) + ".json")
            required = {"schema", "request_id", "company_id", "source_revision", "state", "request_sha256"}
            expected = {"schema": "operator-company-scan-request-v1", "request_id": request["request_id"],
                        "company_id": company_ids[0], "source_revision": request["source_revision"]}
            allowed_states = {"REQUEST_WRITTEN", "REQUEST_ALREADY_DURABLE"}
        try:
            provenance_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise ValueError("retained_event_consumption_provenance_receipt_missing") from error
        if (not isinstance(provenance_receipt, dict) or set(provenance_receipt) != required
                or any(provenance_receipt.get(key) != value for key, value in expected.items())
                or provenance_receipt.get("state") not in allowed_states
                or provenance_receipt.get("request_sha256") != digest(request)):
            raise ValueError("retained_event_consumption_provenance_receipt_changed")
        try:
            exception_path = root / "retained-work-exceptions.sqlite3"
            jobs_path = root / "jobs.sqlite3"
            if not exception_path.is_file() or not jobs_path.is_file():
                raise ValueError("retained_event_consumption_authority_missing")
            with sqlite3.connect(exception_path.as_uri() + "?mode=ro", uri=True) as db:
                admission = db.execute(
                    "SELECT request_id,event_id,exception_cycle,company_id,manifest_digest,"
                    "payload,payload_digest,state FROM retained_work_admissions "
                    "WHERE request_id=?", (request.get("request_id"),)).fetchone()
                exception = db.execute(
                    "SELECT manifest_digest,state FROM retained_work_exceptions WHERE cycle=?",
                    (admission[2],) if admission is not None else (None,)).fetchone()
            if admission is None:
                raise ValueError("retained_event_consumption_admission_missing")
            try:
                payload = json.loads(admission[5])
            except (TypeError, ValueError) as error:
                raise ValueError("retained_event_consumption_admission_corrupt") from error
            if (admission[7] != "FROZEN" or not isinstance(payload, dict)
                    or admission[6] != digest(payload)
                    or payload.get("request_digest") != digest(request)
                    or payload.get("event_receipt_digest") != digest(provenance_receipt)
                    or (admission[0], admission[1], admission[2], admission[3], admission[4])
                    != (request.get("request_id"), provenance_id,
                        payload.get("exception_cycle"), company_ids[0],
                        payload.get("manifest_digest"))
                    or payload.get("event_id") != provenance_id
                    or payload.get("company_id") != company_ids[0]
                    or exception != (admission[4], "ACTIVE")):
                raise ValueError("retained_event_consumption_admission_changed")
            with sqlite3.connect(jobs_path.as_uri() + "?mode=ro", uri=True) as db:
                released = db.execute(
                    "SELECT request_id,event_id,exception_cycle,company,manifest_digest,"
                    "queue_evidence,queue_evidence_digest,state FROM retained_publications "
                    "WHERE reservation_digest=?", (admission[6],)).fetchone()
        except ValueError:
            raise
        except (OSError, sqlite3.Error) as error:
            raise ValueError("retained_event_consumption_authority_unreadable") from error
        if released is None:
            raise ValueError("retained_event_consumption_release_missing")
        try:
            evidence = json.loads(released[5])
        except (TypeError, ValueError) as error:
            raise ValueError("retained_event_consumption_release_corrupt") from error
        if (released[7] != "FIRST_PASS_RELEASED" or not isinstance(evidence, dict)
                or released[6] != digest(evidence)
                or evidence.get("reservation_digest") != admission[6]
                or tuple(released[:5]) != (request.get("request_id"),
                    provenance_id, admission[2], company_ids[0], admission[4])):
            raise ValueError("retained_event_consumption_release_changed")
        # A newer canonical request may already have arrived.  It is not this
        # settled event and must survive while this archived event gets its own
        # durable receipt.
        return {"consumption": _consume_request(root, request, preserve_replacement=True),
                "company_id": company_ids[0], "reservation_digest": admission[6]}
    raise AssertionError("one pending archive must return or fail")


def activate_signed_exception(*, state_directory, cycle_id, approval, verifier):
    """Rebuild live evidence then verify an external Ed25519 envelope."""
    from .cli import scraper_lock_name, writer_lock
    from .engine import State
    from .retained_work_exception import activate_exception, revalidate_manifest
    root = Path(state_directory).resolve()
    # Activation freezes an approval against current blocker evidence; holding
    # the normal scraper lock prevents concurrent intake from moving that
    # evidence between revalidation, signature verification and store freeze.
    with writer_lock(root / scraper_lock_name()):
        state = State(str(root / "state.db"), readonly=True)
        try:
            cycle = state.cycle(cycle_id)
        finally:
            state.close()
        if not isinstance(cycle, dict): raise ValueError("retained_event_cycle_missing")
        if not isinstance(approval, dict) or set(approval) != {"manifest", "envelope"}:
            raise ValueError("retained_event_activation_bundle_invalid")
        manifest, envelope = approval["manifest"], approval["envelope"]
        if not isinstance(manifest, dict) or manifest.get("cycle_id") != cycle_id:
            raise ValueError("retained_event_activation_manifest_invalid")
        revalidate_manifest(manifest, cycle, root / "inventories.sqlite3", root / "jobs.sqlite3")
        return activate_exception(manifest, envelope, verifier,
                                  root / "retained-work-exceptions.sqlite3")


def run_retained_company_event(*, state_directory, local_factory, remote_factory,
                               verifier, fetcher, max_operations=100):
    """Run exactly one already-authorized bridge event to FIRST PASS release.

    Factories are intentionally invoked only after the normal lifecycle hold
    has been checked.  The read-only local/state preflight happens before the
    writable local/remote publication phase; no ordinary Inbox is constructed.
    """
    root = Path(state_directory).resolve()
    if not 1 <= max_operations <= 500:
        raise ValueError("retained_event_max_operations_invalid")
    from .cli import scraper_lock_name, writer_lock
    from .engine import Engine, State
    from .integration_release import assert_release_settled
    from .retained_session_store import RetainedSessionStore
    from .retained_work_exception import _active_record
    from .retained_work_orchestrator import run_retained_reservation
    from .retained_work_runner import (assert_normal_lifecycle_not_held,
                                       commit_exceptional_start,
                                       prepare_exceptional_start,
                                       recover_prepared_exceptional_start)

    store_path = root / "retained-work-exceptions.sqlite3"
    journal_path = root / "retained-work-starts.sqlite3"
    inventory_path = root / "inventories.sqlite3"
    jobs_path = root / "jobs.sqlite3"
    state_path = root / "state.db"
    # After settlement the start journal is intentionally gone.  A durable
    # archive plus both admission and FIRST_PASS evidence is the only safe
    # authority for completing an interrupted consumption; do no fetch/work.
    from .cli import writer_lock
    with writer_lock(root / scraper_lock_name()):
        recovered_consumption = _recover_settled_consumption(root)
    if recovered_consumption:
        return {"state": "FIRST_PASS_RELEASED", "recovered": True,
                "consumption": recovered_consumption["consumption"],
                "company_id": recovered_consumption["company_id"],
                "reservation_digest": recovered_consumption["reservation_digest"]}
    # Do not acquire the scraper lock here: commit_exceptional_start and the
    # retained publisher each own their real nonreentrant lock boundary and
    # revalidate the immutable prepared binding while holding it.  An outer
    # flock would deadlock those established ownership boundaries.
    with nullcontext():
        assert_release_settled(root)
        # A settled journal is the only permitted idempotent recovery; a live
        # normal lifecycle hold always wins and blocks factory construction.
        # A pre-existing retained journal is its own idempotent recovery
        # authority.  Without it, any lifecycle hold is an unsafe collision.
        if not journal_path.exists():
            assert_normal_lifecycle_not_held(root, jobs_path)
        state = State(str(state_path), readonly=True)
        try:
            # The blocker set is State-only; reject a changed/multiple scope
            # before constructing a local or remote repository factory.
            cycle_ids = [item["id"] for item in state.cycles()
                         if item.get("status") not in {"Complete", "Complete with exceptions"}]
            if len(cycle_ids) != 1:
                raise ValueError("retained_event_blocker_scope_changed")
            local_ro = local_factory(readonly=True)
            try:
                # The exception store itself re-verifies the real Ed25519
                # signature and expiry before a mutable reservation is made.
                record = _active_record(store_path, cycle_ids[0], verifier)
                manifest = record["manifest"]
                try:
                    prepared = recover_prepared_exceptional_start(
                        local_ro, state, root, journal_path, inventory_path,
                        jobs_path, store_path, manifest, verifier)
                    recovered_start = True
                except ValueError as error:
                    if str(error) != "retained_runner_recovery_journal_missing":
                        raise
                    prepared = prepare_exceptional_start(
                        local_ro, state, root, inventory_path, jobs_path,
                        store_path, manifest, verifier, fetcher)
                    recovered_start = False
                if not recovered_start:
                    # This writes only the dedicated hold/journal, never State or
                    # Inbox; it repeats safely after a lost command response.
                    commit_exceptional_start(
                        prepared, local_ro, state, root, journal_path, manifest,
                        inventory_path, jobs_path, store_path, verifier)
            finally:
                local_ro.close()
        finally:
            state.close()
        local = local_factory(readonly=False)
        try:
            remote = remote_factory()
            session = RetainedSessionStore(root / "retained-sessions.sqlite3")
            try:
                engine = Engine(local, State(readonly=True), error_log_path=root / "retained-errors.jsonl")
                try:
                    result = run_retained_reservation(
                        prepared, engine, local, remote, session,
                        state_directory=root, max_operations=max_operations)
                finally:
                    engine.state.close()
            finally:
                session.close()
        finally:
            local.close()
    consumption = None
    if result["publication"]["state"] == "FIRST_PASS_RELEASED":
        settlement = result["publication"].get("settlement")
        recovered_publication = (bool(result.get("recovered"))
                                 and isinstance(settlement, dict)
                                 and settlement.get("reason") in {"journal_missing", "journal_empty"})
        if not (isinstance(settlement, dict)
                and (settlement.get("settled") is True or recovered_publication)):
            raise ValueError("retained_event_publication_unsettled")
        # Archive/read/unlink/receipt is one scraper-locked bridge transition.
        # The retained publisher has already released its own lock.
        with writer_lock(root / scraper_lock_name()):
            consumption = _consume_request(root, prepared.snapshot["request"])
    return {"state": result["publication"]["state"], "company_id": result["company_id"],
            "reservation_digest": result["reservation_digest"],
            "recovered": recovered_start or bool(result.get("recovered")),
            "consumption": consumption}


def production_command(*, state_directory, key_id, public_key_base64,
                       request_interval=1.1, max_operations=100):
    """Build production factories only after explicit CLI authorization."""
    from . import cli
    verifier = _verifier(key_id, public_key_base64)
    def local_factory(*, readonly):
        return cli.get_repository(write=not readonly, interactive=False)
    def remote_factory():
        return cli.get_remote_repository(write=True, interactive=True,
                                         renew_both=True,
                                         min_request_interval=request_interval)
    from .ats import fetch_inventory
    from .browser_scraper import with_browser_fallback
    return run_retained_company_event(
        state_directory=state_directory, local_factory=local_factory,
        remote_factory=remote_factory, verifier=verifier,
        fetcher=with_browser_fallback(fetch_inventory), max_operations=max_operations)
