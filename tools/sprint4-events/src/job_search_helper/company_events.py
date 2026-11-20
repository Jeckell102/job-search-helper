"""Canonical Company change facts for the durable intake outbox.

This module deliberately knows nothing about Sheets, scheduling, or network
delivery.  It turns the small set of fields that can change a scrape into a
stable, auditable fact.  The SQLite repository records those facts in the
same transaction as a supported Company mutation.
"""
from __future__ import annotations

from contextlib import closing
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
from datetime import datetime, timezone

from .repository import RepositoryError, _url
from .cli import scraper_lock_name, state_path, writer_lock


RELEVANT_FIELDS = ("Company ID", "Company Status", "Official Careers URL", "ATS / Source")
INELIGIBLE_STATUSES = frozenset({"pause", "paused", "remove", "removed"})


def _text(value):
    return str(value or "").strip()


def canonical_company_fact(company):
    """Return the immutable scrape-relevant Company fact.

    A missing ID or careers URL is intentionally *not* eligible.  The store
    leaves a newly incomplete Company alone, but records a withdrawal if an
    already eligible Company loses its source so consumers can cancel scope.
    """
    company_id = _text(company.get("Company ID"))
    if not company_id:
        raise RepositoryError("Company event requires a stable Company ID.")
    status = _text(company.get("Company Status") or "Active").casefold()
    careers_url = _text(company.get("Official Careers URL"))
    source = _text(company.get("ATS / Source")).casefold()
    return {
        "company_id": company_id,
        "company_status": status,
        "official_careers_url": _url(careers_url) if careers_url else "",
        "ats_source": source,
        "eligible": bool(careers_url) and status not in INELIGIBLE_STATUSES,
    }


def source_revision(company):
    """Hash the canonical fact; cosmetic/progress fields never affect it."""
    fact = canonical_company_fact(company)
    encoded = json.dumps(fact, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return sha256(encoded.encode("utf-8")).hexdigest()


def current_company_source_revision(repository, company_id):
    """Read one eligible Company's current revision from the local authority.

    This is the narrow trust boundary used by the external wrapper coordinator.
    It intentionally returns no revision for missing, duplicate, malformed, or
    paused Companies: any of those conditions must keep a previously held
    repair paused instead of allowing a caller to reuse stale scope.
    """
    if not isinstance(company_id, str) or not company_id.strip():
        return None
    try:
        matches = repository.matches("Companies", {"Company ID": company_id.strip()})
        if len(matches) != 1:
            return None
        company = matches[0][1]
        if not canonical_company_fact(company)["eligible"]:
            return None
        return source_revision(company)
    except (RepositoryError, ValueError, TypeError):
        return None


def current_company_repair_snapshot(repository, company_id):
    """Read the one eligible Company fact allowed to bind an M4 profile.

    The external coordinator receives this narrow, recomputable snapshot from
    the local authority instead of accepting a company name or URL supplied by
    a repair request.  Missing, duplicate, paused, or malformed Companies
    return ``None`` so the repair remains held.
    """
    if not isinstance(company_id, str) or not company_id.strip():
        return None
    try:
        matches = repository.matches("Companies", {"Company ID": company_id.strip()})
        if len(matches) != 1:
            return None
        company = matches[0][1]
        fact = canonical_company_fact(company)
        name = _text(company.get("Company"))
        if not fact["eligible"] or not name:
            return None
        return {"company_id": fact["company_id"], "source_revision": source_revision(company),
                "company": name, "official_careers_url": fact["official_careers_url"],
                "ats_source": fact["ats_source"]}
    except (RepositoryError, ValueError, TypeError):
        return None


def company_revision_resolver(repository):
    """Make the coordinator's Company-freshness callback from one repository."""
    return lambda company_id: current_company_source_revision(repository, company_id)


def event_kind(fact):
    if fact["eligible"]:
        return "company.eligible"
    return "company.withdrawn" if not fact["official_careers_url"] else "company.ineligible"


BRIDGE_CONSUMER = "company-scan-request-bridge"
BRIDGE_SCHEMA = "company-event-scan-request-v1"
_EVENT_ID = re.compile(r"CEV-[0-9a-f]{32}")
_DELIVERED_STATES = {"REQUEST_WRITTEN", "REQUEST_CONFIRMED", "REQUEST_SUPERSEDED_OLDER"}
MANUAL_RETAINED_SCHEMA = "manual-retained-company-event-v1"
MANUAL_RETAINED_HOLD = "HELD_MANUAL_RETAINED_EVENT"


def is_manual_retained_event_request(request):
    """Presence alone holds automatic routes, including malformed markers."""
    return isinstance(request, dict) and "manual_retained" in request


def has_pending_eligible_company_event(repository):
    """Check the full current eligible outbox without a delivery-page limit."""
    if not repository._company_event_tables_present():
        return False
    return repository.db.execute(
        "SELECT 1 FROM company_event_outbox o "
        "JOIN (SELECT company_id,MAX(revision) AS revision FROM company_event_outbox GROUP BY company_id) latest "
        "ON latest.company_id=o.company_id AND latest.revision=o.revision "
        "LEFT JOIN company_event_deliveries d ON d.event_id=o.event_id AND d.consumer=? "
        "LEFT JOIN company_event_watermarks w ON w.company_id=o.company_id AND w.consumer=? "
        "WHERE o.kind='company.eligible' AND d.event_id IS NULL "
        "AND (w.revision IS NULL OR o.revision>w.revision) LIMIT 1",
        (BRIDGE_CONSUMER, BRIDGE_CONSUMER),
    ).fetchone() is not None


def _outbox_observation(repository, event):
    """Read the immutable observation from the same transaction as the revision."""
    row = repository.db.execute(
        "SELECT company_id,revision,source_revision,kind,created_at "
        "FROM company_event_outbox WHERE event_id=?", (event["event_id"],),
    ).fetchone()
    expected = tuple(event[key] for key in ("company_id", "revision", "source_revision"))
    if row is None or tuple(row[:4]) != (*expected, "company.eligible"):
        raise ValueError("Company event has no matching eligible outbox observation.")
    return row[4]


def read_verified_queued_event(repository, root):
    """Read exact bytes and durable ordinary event provenance without writing."""
    root = Path(root)
    path = root / "next-scan.json"
    if path.is_symlink():
        raise ValueError("Company-event request must be a regular queue file.")
    payload = path.read_bytes()
    request = json.loads(payload)
    if not isinstance(request, dict):
        raise ValueError("Company-event request must be an object.")
    if is_manual_retained_event_request(request):
        raise ValueError("Pending manual retained Company event is outside ordinary admission.")
    event = request.get("company_event")
    expected_keys = {
        "mode", "request_id", "company_ids", "source_revision", "enqueued_at",
        "start_last", "company_event",
    }
    if "company_event_timing" in request:
        expected_keys.add("company_event_timing")
    if (set(request) != expected_keys or request["start_last"] != []
            or not isinstance(event, dict)
            or set(event) != {"schema", "event_id", "company_id", "revision", "source_revision"}
            or not isinstance(event.get("event_id"), str) or not _EVENT_ID.fullmatch(event["event_id"])
            or request["request_id"] != "company-event:" + event["event_id"]
            or type(event.get("revision")) is not int or event["revision"] < 1):
        raise ValueError("Pending request is not an ordinary Company-event request.")
    CompanyEventBridge._require_event_bound_request(request, event)
    observed_at = _outbox_observation(repository, event)
    from .scan_request import _company_event_timing, _enqueued_at, _timestamp
    _enqueued_at(request)
    _timestamp(observed_at, "Company event observation")
    timing = _company_event_timing(request)
    if timing and timing["observed_at"] != observed_at:
        raise ValueError("Company-event request observation disagrees with its outbox.")
    receipt = CompanyEventBridge._read_json(
        root / "company-event-bridge" / "receipts" / (event["event_id"] + ".json"),
    )
    if (receipt is None or set(receipt) != set(event) | {"state", "recorded_at", "request_sha256"}
            or any(receipt[key] != value for key, value in event.items())
            or receipt["state"] not in _DELIVERED_STATES
            or receipt["request_sha256"] != _json_digest(request)):
        raise ValueError("Company-event request receipt does not bind the pending request.")
    _timestamp(receipt["recorded_at"], "Company-event request receipt")
    recorded = repository.db.execute(
        "SELECT r.revision,r.source_revision,d.event_id FROM company_revisions r "
        "LEFT JOIN company_event_deliveries d ON d.event_id=? AND d.consumer=? "
        "WHERE r.company_id=? ORDER BY r.revision DESC LIMIT 1",
        (event["event_id"], BRIDGE_CONSUMER, event["company_id"]),
    ).fetchone()
    if (recorded is None or tuple(recorded) != (event["revision"], event["source_revision"], event["event_id"])
            or current_company_source_revision(repository, event["company_id"]) != event["source_revision"]):
        raise ValueError("Company-event request is stale or lacks exact acknowledgement.")
    return payload, request


class CompanyEventBridge:
    """Turn durable Company facts into one safe, narrow scan request.

    The bridge deliberately owns *only* its request file and its evidence
    directory. It reads effective cycle state under the scraper lease and
    never alters a cycle or checkpoint. A later withdrawal is safe when it has
    already been admitted to an active cycle: the bridge records a cancellation
    instruction for the normal owner instead of trying to stop the cycle.

    Delivery is at-least-once.  An event is acknowledged only after the exact
    request (or cancellation instruction) has been atomically written and read
    back from disk.  A crash between those two operations is therefore a safe
    replay, rather than a second request.
    """

    def __init__(self, repository, state_directory, *, consumer=BRIDGE_CONSUMER,
                 now=None, state_database=None):
        if not isinstance(consumer, str) or not consumer.strip():
            raise ValueError("company-event bridge consumer is required")
        self.repository = repository
        self.root = Path(state_directory)
        if state_database is None:
            configured = state_path()
            state_database = configured if configured.parent.resolve() == self.root.resolve() else self.root / "state.db"
        self.state_database = Path(state_database)
        if self.state_database.parent.resolve() != self.root.resolve():
            raise ValueError("Company-event bridge state and scraper lock must share a directory.")
        self.consumer = consumer.strip()
        self._now = now or (lambda: datetime.now(timezone.utc))

    @property
    def request_path(self):
        return self.root / "next-scan.json"

    @property
    def evidence_directory(self):
        return self.root / "company-event-bridge"

    def manually_held_request(self):
        """Read whether the slot is reserved for manually staged retained intake."""
        request = self._manual_slot()
        if not is_manual_retained_event_request(request):
            return False
        if "company_event_timing" not in request:
            raise ValueError("Manual retained Company-event request is missing its intake evidence.")
        return True

    def stage_manual_retained_event(self, event_id, *, company_id, source_revision, blocking_cycle_id):
        """Stage one exact eligible event behind a retained blocker; never dispatch.

        The queued bytes are the crash reservation. Publish them exclusively,
        acknowledge the durable event, and publish the existing bridge receipt
        last. The receipt is the readiness boundary for signed admission.
        """
        with writer_lock(self.root / scraper_lock_name()), writer_lock(self.root / "writer.lock"):
            return self._stage_manual_retained_event_locked(
                event_id, company_id=company_id, source_revision=source_revision,
                blocking_cycle_id=blocking_cycle_id,
            )

    def _stage_manual_retained_event_locked(self, event_id, *, company_id, source_revision, blocking_cycle_id):
        """Stage after the caller verifies the inherited scraper lease."""
        marker = self._manual_marker(event_id, company_id, source_revision, blocking_cycle_id)
        if self.consumer != BRIDGE_CONSUMER or getattr(self.repository, "is_local", False) is not True:
            raise ValueError("Manual retained staging requires the ordinary SQLite event authority.")
        from .retained_work_runner import assert_normal_lifecycle_not_held
        from .integration_release import assert_release_settled
        assert_normal_lifecycle_not_held(self.root, self.repository.path, allow_staged_event=True)
        assert_release_settled(self.root)
        with self.repository.transaction():
            event, acknowledged = self._manual_event(event_id, company_id, source_revision)
            cycles = self._manual_blocker(company_id, blocking_cycle_id)
            self._require_no_dispatch_owner("company-event:" + event_id)
            current = self._manual_slot()
            if current is None:
                if acknowledged or self._manual_receipt(event) is not None:
                    raise ValueError("Manual retained event was already delivered or has prior receipt evidence.")
                current = self._request_for(event, cycles)
                from .scan_request import company_event_timing
                current["company_event_timing"] = company_event_timing(
                    _outbox_observation(self.repository, event), [blocking_cycle_id], *cycles,
                )
                current["manual_retained"] = marker
                self._write_atomic_json(self.request_path, current, exclusive=True)
            self._require_manual_request(current, event, marker)
            self._require_same_request(self._manual_slot(), current)
            receipt = self._manual_receipt(event, current)
            if receipt is not None and not acknowledged:
                raise ValueError("Manual retained receipt exists before its event acknowledgement.")
        if not acknowledged:
            self.repository.acknowledge_company_event(
                event_id, self.consumer, source_revision=source_revision,
            )
        with self.repository.transaction():
            # The producer may advance between SQLite transactions even
            # while the scraper lease protects the exact request slot.
            _, acknowledged = self._manual_event(event_id, company_id, source_revision)
            self._manual_blocker(company_id, blocking_cycle_id)
            self._require_no_dispatch_owner("company-event:" + event_id)
            self._require_same_request(self._manual_slot(), current)
            if not acknowledged:
                raise ValueError("Manual retained event acknowledgement was not committed.")
            receipt = self._manual_receipt(event, current)
            if receipt is None:
                self._write_receipt(event, "REQUEST_WRITTEN", request=current)
                receipt = self._manual_receipt(event, current)
            if receipt is None:
                raise ValueError("Manual retained event receipt was not committed.")
            return self._manual_evidence(event, current, receipt, blocking_cycle_id)

    def verify_manual_retained_event(self, event_id, *, company_id, source_revision, blocking_cycle_id):
        """Read exact staged proof under the caller's existing scraper lease."""
        marker = self._manual_marker(event_id, company_id, source_revision, blocking_cycle_id)
        if self.consumer != BRIDGE_CONSUMER or getattr(self.repository, "is_local", False) is not True:
            raise ValueError("Manual retained verification requires the ordinary SQLite event authority.")
        event, acknowledged = self._manual_event(event_id, company_id, source_revision)
        self._manual_blocker(company_id, blocking_cycle_id)
        self._require_no_dispatch_owner("company-event:" + event_id)
        request = self._manual_slot()
        self._require_manual_request(request, event, marker)
        receipt = self._manual_receipt(event, request)
        if not acknowledged or receipt is None:
            raise ValueError("Manual retained event staging is incomplete.")
        return self._manual_evidence(event, request, receipt, blocking_cycle_id)

    @staticmethod
    def _manual_marker(event_id, company_id, source_revision, blocking_cycle_id):
        if (not isinstance(event_id, str) or not _EVENT_ID.fullmatch(event_id)
                or not isinstance(source_revision, str) or not re.fullmatch(r"[0-9a-f]{64}", source_revision)
                or any(not isinstance(value, str) or not value or value.strip() != value
                       for value in (company_id, blocking_cycle_id))):
            raise ValueError("Manual retained staging requires exact event, Company, revision and blocker.")
        return {"schema": MANUAL_RETAINED_SCHEMA, "blocking_cycle_id": blocking_cycle_id}

    def _manual_slot(self):
        if self.request_path.is_symlink():
            raise ValueError("Company-event request must be a regular queue file.")
        return self._read_json(self.request_path)

    def _manual_event(self, event_id, company_id, source_revision):
        row = self.repository.db.execute(
            "SELECT o.payload,d.event_id FROM company_event_outbox o "
            "JOIN company_revisions r ON r.company_id=o.company_id AND r.revision=o.revision "
            "AND r.source_revision=o.source_revision AND r.eligible=1 "
            "LEFT JOIN company_event_deliveries d ON d.event_id=o.event_id AND d.consumer=? "
            "WHERE o.event_id=? AND o.company_id=? AND o.source_revision=? AND o.kind='company.eligible' "
            "AND NOT EXISTS (SELECT 1 FROM company_revisions newer "
            "WHERE newer.company_id=o.company_id AND newer.revision>o.revision)",
            (BRIDGE_CONSUMER, event_id, company_id, source_revision),
        ).fetchone()
        if row is None or current_company_source_revision(self.repository, company_id) != source_revision:
            raise ValueError("Manual retained event is unknown, superseded or currently ineligible.")
        event = json.loads(row[0])
        self._validate_event(event)
        if (event["event_id"], event["company_id"], event["source_revision"]) != (event_id, company_id, source_revision):
            raise ValueError("Manual retained outbox identity disagrees with its event.")
        _outbox_observation(self.repository, event)
        return event, row[1] == event_id

    def _manual_blocker(self, company_id, blocking_cycle_id):
        from .scan_request import _unfinished_from_views, cycle_metadata
        local, remote = self._cycles()
        saved = [row for row in local if row.get("id") == blocking_cycle_id]
        mirrored = [row for row in remote if row.get("Cycle ID") == blocking_cycle_id]
        if _unfinished_from_views(local, remote) != {blocking_cycle_id} or len(saved) != 1 or len(mirrored) != 1:
            raise ValueError("Manual retained staging requires one exact local and mirrored unfinished blocker.")
        companies = saved[0].get("companies")
        mirror_companies = cycle_metadata(mirrored[0]).get("company_ids")
        if (saved[0].get("status") not in {"In Progress", "Awaiting Review"}
                or mirrored[0].get("Cycle Status") != saved[0]["status"]
                or not isinstance(companies, dict) or not companies
                or not isinstance(mirror_companies, list)
                or any(not isinstance(member, str) or not member for member in mirror_companies)
                or sorted(mirror_companies) != sorted(companies) or company_id in companies):
            raise ValueError("Manual retained blocker scope is ambiguous or overlaps the selected Company.")
        return local, remote

    def _require_no_dispatch_owner(self, request_id):
        path = self.root / "company-intake-dispatch.sqlite3"
        if path.is_symlink():
            raise ValueError("Dispatch ownership journal must be a regular file.")
        if path.exists():
            with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
                owner = db.execute(
                    "SELECT 1 FROM request_ownership WHERE request_id=? OR state='NORMAL_STARTING' "
                    "OR (route='RETAINED' AND state!='RETAINED_CONSUMED') LIMIT 1", (request_id,),
                ).fetchone()
                if owner is not None:
                    raise ValueError("Manual retained staging conflicts with a dispatcher owner.")

    def _require_manual_request(self, request, event, marker):
        from .scan_request import _company_event_timing
        if (not is_manual_retained_event_request(request) or request.get("manual_retained") != marker
                or set(request) != {"mode", "request_id", "company_ids", "source_revision", "enqueued_at",
                                    "start_last", "company_event", "company_event_timing", "manual_retained"}
                or request.get("request_id") != "company-event:" + event["event_id"]
                or request.get("start_last") != []
                or not isinstance(request.get("company_event"), dict)
                or set(request["company_event"]) != {"schema", "event_id", "company_id", "revision", "source_revision"}):
            raise ValueError("Manual retained staging cannot replace the occupied request slot.")
        self._require_event_bound_request(request, event)
        timing = _company_event_timing(request)
        if (timing is None or timing["observed_at"] != _outbox_observation(self.repository, event)
                or timing["condition"] != "unverified"
                or marker["blocking_cycle_id"] not in timing["blocking_cycle_ids"]):
            raise ValueError("Manual retained request timing does not bind its unfinished blocker.")

    def _manual_receipt(self, event, request=None):
        from .scan_request import _timestamp
        path = self.evidence_directory / "receipts" / (event["event_id"] + ".json")
        if path.is_symlink():
            raise ValueError("Manual retained receipt must be a regular file.")
        receipt = self._read_json(path)
        if receipt is not None and request is not None:
            provenance = request["company_event"]
            if (set(receipt) != set(provenance) | {"state", "recorded_at", "request_sha256"}
                    or any(receipt[key] != value for key, value in provenance.items())
                    or receipt["state"] != "REQUEST_WRITTEN"
                    or receipt["request_sha256"] != _json_digest(request)):
                raise ValueError("Manual retained receipt does not bind the exact staged request.")
            _timestamp(receipt["recorded_at"], "Manual retained event receipt")
        return receipt

    def _manual_evidence(self, event, request, receipt, blocker):
        return dict(self._result(event, "MANUAL_RETAINED_STAGED"), request_id=request["request_id"],
                    blocking_cycle_id=blocker, request_sha256=_json_digest(request),
                    receipt_sha256=_json_digest(receipt))

    def process_pending(self, *, limit=100, writer_lock_held=False):
        """Deliver the newest pending revision per company once.

        Coalescing is intentional: if a Company changes twice before intake
        catches up, only the newest immutable fact may create work.  The
        repository's acknowledgement watermark records that supersession.
        """
        if writer_lock_held:
            return self._process_pending_locked(limit=limit)
        # This is the exact lock held by normal request intake.  Atomic rename
        # protects readers from partial JSON; this lock also protects the
        # read/decide/write sequence from a competing bridge or intake process.
        with writer_lock(self.root / scraper_lock_name()):
            return self._process_pending_locked(limit=limit)

    def _process_pending_locked(self, *, limit):
        if self.manually_held_request():
            return [{"state": MANUAL_RETAINED_HOLD}]
        events = self.repository.pending_latest_company_events(self.consumer, limit=limit)
        latest = {}
        for event in events:
            self._validate_event(event)
            company_id = event["company_id"]
            current = latest.get(company_id)
            if current is None or event["revision"] > current["revision"]:
                latest[company_id] = event
        if not latest:
            return []
        cycles = self._cycles() if any(event["kind"] == "company.eligible" for event in latest.values()) else None
        return [self._deliver(event, cycles) for event in sorted(
            latest.values(), key=lambda value: (value["company_id"], value["revision"])
        )]

    def _cycles(self):
        from .engine import State
        from .scan_request import _cycle_views
        state = (State(self.state_database, readonly=True) if self.state_database.exists() else None)
        try:
            return _cycle_views(self.repository, state)
        finally:
            if state is not None:
                state.close()

    def deliver(self, event):
        """Durably deliver one Company event through the same scraper lease."""
        self._validate_event(event)
        with writer_lock(self.root / scraper_lock_name()):
            if self.manually_held_request():
                return self._result(event, MANUAL_RETAINED_HOLD)
            cycles = self._cycles() if event["kind"] == "company.eligible" else None
            return self._deliver(event, cycles)

    def _deliver(self, event, cycles):
        if event["kind"] == "company.eligible":
            from .scan_request import _unfinished_from_views
            blockers = sorted(_unfinished_from_views(*cycles))
            if blockers:
                observed_at = self._remember_blockers(event, blockers)
                return dict(self._result(event, "WAITING_FOR_UNFINISHED_CYCLE"),
                            observed_at=observed_at, blocking_cycle_ids=blockers)
            result = self._deliver_eligible(event, cycles)
        else:
            result = self._deliver_cancellation(event)
        if result["state"] not in {
            "WAITING_FOR_SAFE_REQUEST_BOUNDARY", "SUPERSEDED_BY_DURABLE_REQUEST",
        }:
            self.repository.acknowledge_company_event(
                event["event_id"], self.consumer, source_revision=event["source_revision"],
            )
        return result

    def _deliver_eligible(self, event, cycles):
        existing = self._read_json(self.request_path)
        if existing is not None:
            existing_event = self._request_event(existing)
            is_bridge_request = self._is_bridge_request(existing)
            if is_bridge_request and existing_event == event["event_id"]:
                self._require_event_bound_request(existing, event)
                self._write_receipt(event, "REQUEST_CONFIRMED", request=existing)
                return self._result(event, "REQUEST_CONFIRMED")
            # A not-yet-admitted bridge request for the same Company may be
            # safely replaced by its newer revision.  A request for another
            # Company is a single-writer boundary and must be left untouched.
            if (is_bridge_request and existing_event and self._request_company_id(existing) == event["company_id"]
                    and self._request_revision(existing) < event["revision"]):
                request = self._request_for(event, cycles)
                self._write_atomic_json(self.request_path, request)
                self._require_same_request(self._read_json(self.request_path), request)
                self._write_receipt(event, "REQUEST_SUPERSEDED_OLDER", request=request)
                return self._result(event, "REQUEST_SUPERSEDED_OLDER")
            if is_bridge_request and existing_event and self._request_company_id(existing) == event["company_id"]:
                # The newer event is already durable.  Do not overwrite it
                # with an older redelivery.
                self._write_receipt(event, "SUPERSEDED_BY_DURABLE_REQUEST")
                return self._result(event, "SUPERSEDED_BY_DURABLE_REQUEST")
            return self._result(event, "WAITING_FOR_SAFE_REQUEST_BOUNDARY")

        request = self._request_for(event, cycles)
        self._write_atomic_json(self.request_path, request)
        self._require_same_request(self._read_json(self.request_path), request)
        self._write_receipt(event, "REQUEST_WRITTEN", request=request)
        return self._result(event, "REQUEST_WRITTEN")

    def _deliver_cancellation(self, event):
        # A delayed withdrawal must never cancel a newer eligible request for
        # the same company.  Leave both the newer request and its evidence
        # untouched; the normal newest-per-company drain will acknowledge the
        # newer fact and supersede this stale delivery.
        existing = self._read_json(self.request_path)
        if (existing is not None and self._is_bridge_request(existing)
                and self._request_company_id(existing) == event["company_id"]
                and self._request_event(existing)
                and self._request_revision(existing) > event["revision"]):
            self._write_receipt(event, "SUPERSEDED_BY_DURABLE_REQUEST")
            return self._result(event, "SUPERSEDED_BY_DURABLE_REQUEST")
        instruction = {
            "schema": BRIDGE_SCHEMA,
            "event_id": event["event_id"],
            "company_id": event["company_id"],
            "revision": event["revision"],
            "source_revision": event["source_revision"],
            "kind": event["kind"],
            "recorded_at": self._timestamp(),
            "action": "cancel-company-only-work-if-not-started",
        }
        cancellation_path = self.evidence_directory / "cancellations" / self._company_filename(event)
        self._write_atomic_json(cancellation_path, instruction)
        self._require_same_json(self._read_json(cancellation_path), instruction)

        # ``next-scan.json`` means normal intake has not consumed the request.
        # Archive it first, then remove only this bridge-owned pending request.
        # If it has already disappeared, a cycle may be active; its state is
        # intentionally left alone and the cancellation instruction remains.
        if (existing is not None and self._is_bridge_request(existing)
                and self._request_company_id(existing) == event["company_id"]
                and self._request_event(existing)):
            archive = self.evidence_directory / "cancelled-requests" / (self._company_filename(event))
            self._write_atomic_json(archive, existing)
            self._require_same_json(self._read_json(archive), existing)
            self.request_path.unlink()
            self._fsync_directory(self.request_path.parent)
            if self.request_path.exists():
                raise RuntimeError("bridge could not remove its cancelled pending request")
            status = "PENDING_REQUEST_CANCELLED"
        else:
            status = "CANCELLATION_RECORDED_ACTIVE_OR_ABSENT"
        self._write_receipt(event, status, cancellation=instruction)
        return self._result(event, status)

    def _delay_path(self, event):
        return self.evidence_directory / "deferred" / (sha256(event["event_id"].encode()).hexdigest() + ".json")

    def _delay_evidence(self, event):
        observed_at = _outbox_observation(self.repository, event)
        identity = {key: event[key] for key in ("event_id", "company_id", "revision", "source_revision")}
        identity["observed_at"] = observed_at
        existing = self._read_json(self._delay_path(event))
        blockers = []
        if existing is not None:
            blockers = existing.get("blocking_cycle_ids")
            if (set(existing) != set(identity) | {"blocking_cycle_ids"}
                    or any(existing[key] != value for key, value in identity.items())
                    or not isinstance(blockers, list)
                    or any(not isinstance(value, str) or not value for value in blockers)
                    or blockers != sorted(set(blockers))):
                raise ValueError("Company event deferral evidence is invalid.")
        return identity, blockers

    def _remember_blockers(self, event, blockers):
        identity, existing = self._delay_evidence(event)
        known = sorted(set(existing) | set(blockers))
        if known != existing:
            self._write_atomic_json(self._delay_path(event), dict(identity, blocking_cycle_ids=known))
        return identity["observed_at"]

    def observed_timing(self, event, cycles):
        """Read the event observation and any durable deferral evidence."""
        from .scan_request import company_event_timing
        identity, blockers = self._delay_evidence(event)
        return company_event_timing(identity["observed_at"], blockers, *cycles)

    def _request_for(self, event, cycles):
        return {
            "mode": "company-only",
            "request_id": "company-event:" + event["event_id"],
            "company_ids": [event["company_id"]],
            "source_revision": event["source_revision"],
            "enqueued_at": self._timestamp(),
            "start_last": [],
            "company_event_timing": self.observed_timing(event, cycles),
            "company_event": {
                "schema": BRIDGE_SCHEMA,
                "event_id": event["event_id"],
                "company_id": event["company_id"],
                "revision": event["revision"],
                "source_revision": event["source_revision"],
            },
        }

    def _write_receipt(self, event, state, *, request=None, cancellation=None):
        receipt = {
            "schema": BRIDGE_SCHEMA, "event_id": event["event_id"],
            "company_id": event["company_id"], "revision": event["revision"],
            "source_revision": event["source_revision"], "state": state,
            "recorded_at": self._timestamp(),
        }
        if request is not None:
            receipt["request_sha256"] = _json_digest(request)
        if cancellation is not None:
            receipt["cancellation_sha256"] = _json_digest(cancellation)
        path = self.evidence_directory / "receipts" / (event["event_id"] + ".json")
        existing = self._read_json(path)
        if existing is None:
            self._write_atomic_json(path, receipt)
        elif existing.get("event_id") != event["event_id"]:
            raise RuntimeError("company-event receipt identity collision")

    def _result(self, event, state):
        return {"event_id": event["event_id"], "company_id": event["company_id"],
                "revision": event["revision"], "state": state}

    def _timestamp(self):
        value = self._now()
        if value.tzinfo is None:
            raise ValueError("company-event bridge clock must return a timezone-aware value")
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _validate_event(event):
        if not isinstance(event, dict):
            raise ValueError("company-event bridge requires object events")
        strings = ("event_id", "company_id", "source_revision", "kind")
        if any(not isinstance(event.get(key), str) or not event[key].strip() for key in strings):
            raise ValueError("company-event bridge requires immutable event identity")
        if type(event.get("revision")) is not int or event["revision"] < 1:
            raise ValueError("company-event bridge requires a positive revision")
        if event["kind"] not in {"company.eligible", "company.ineligible", "company.withdrawn"}:
            raise ValueError("company-event bridge received an unknown event kind")

    @staticmethod
    def _read_json(path):
        if not path.exists():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"bridge cannot safely read {path.name}") from exc
        if not isinstance(value, dict):
            raise RuntimeError(f"bridge requires object JSON in {path.name}")
        return value

    @staticmethod
    def _request_event(request):
        value = request.get("company_event")
        return value.get("event_id") if isinstance(value, dict) else None

    @staticmethod
    def _request_company_id(request):
        value = request.get("company_event")
        return value.get("company_id") if isinstance(value, dict) else None

    @staticmethod
    def _request_revision(request):
        value = request.get("company_event")
        return value.get("revision", 0) if isinstance(value, dict) and isinstance(value.get("revision"), int) else 0

    @staticmethod
    def _is_bridge_request(request):
        value = request.get("company_event")
        return isinstance(value, dict) and value.get("schema") == BRIDGE_SCHEMA

    @staticmethod
    def _require_same_request(actual, expected):
        if actual is None or _json_digest(actual) != _json_digest(expected):
            raise RuntimeError("bridge durable request readback does not match event")

    @staticmethod
    def _require_event_bound_request(request, event):
        event_part = request.get("company_event")
        expected = {key: event[key] for key in ("event_id", "company_id", "revision", "source_revision")}
        if (request.get("mode") != "company-only" or request.get("company_ids") != [event["company_id"]]
                or request.get("source_revision") != event["source_revision"]
                or not isinstance(event_part, dict)
                or event_part.get("schema") != BRIDGE_SCHEMA
                or {key: event_part.get(key) for key in expected} != expected):
            raise RuntimeError("bridge request identity is not bound to its event")

    @staticmethod
    def _require_same_json(actual, expected):
        if actual is None or _json_digest(actual) != _json_digest(expected):
            raise RuntimeError("bridge durable write readback does not match")

    @staticmethod
    def _company_filename(event):
        # Do not use a Company ID as a path component; it comes from external
        # data and only needs a stable opaque cancellation key here.
        return sha256((event["company_id"] + "\\0" + str(event["revision"])).encode()).hexdigest() + ".json"

    @staticmethod
    def _fsync_directory(directory):
        try:
            descriptor = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        except OSError:
            return
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _write_atomic_json(self, path, value, *, exclusive=False):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        encoded = (json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")
        descriptor, temporary = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            if exclusive:
                os.link(temporary, path)
                os.unlink(temporary)
            else:
                os.replace(temporary, path)
            self._fsync_directory(path.parent)
        except BaseException:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise


def _json_digest(value):
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return sha256(encoded.encode("utf-8")).hexdigest()
