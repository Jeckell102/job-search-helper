"""Canonical Company change facts for the durable intake outbox.

This module deliberately knows nothing about Sheets, scheduling, or network
delivery.  It turns the small set of fields that can change a scrape into a
stable, auditable fact.  The SQLite repository records those facts in the
same transaction as a supported Company mutation.
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
from datetime import datetime, timezone

from .repository import RepositoryError, _url
from .cli import scraper_lock_name, writer_lock


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


class CompanyEventBridge:
    """Turn durable Company facts into one safe, narrow scan request.

    The bridge deliberately owns *only* its request file and its evidence
    directory.  It does not inspect, remove, or alter scrape locks, cycles, or
    checkpoints.  That makes a later withdrawal safe even when the request has
    already been admitted to an active cycle: the bridge records a cancellation
    instruction for the normal owner instead of trying to stop the cycle.

    Delivery is at-least-once.  An event is acknowledged only after the exact
    request (or cancellation instruction) has been atomically written and read
    back from disk.  A crash between those two operations is therefore a safe
    replay, rather than a second request.
    """

    def __init__(self, repository, state_directory, *, consumer=BRIDGE_CONSUMER,
                 now=None):
        if not isinstance(consumer, str) or not consumer.strip():
            raise ValueError("company-event bridge consumer is required")
        self.repository = repository
        self.root = Path(state_directory)
        self.consumer = consumer.strip()
        self._now = now or (lambda: datetime.now(timezone.utc))

    @property
    def request_path(self):
        return self.root / "next-scan.json"

    @property
    def evidence_directory(self):
        return self.root / "company-event-bridge"

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
        events = self.repository.pending_latest_company_events(self.consumer, limit=limit)
        latest = {}
        for event in events:
            self._validate_event(event)
            company_id = event["company_id"]
            current = latest.get(company_id)
            if current is None or event["revision"] > current["revision"]:
                latest[company_id] = event
        return [self.deliver(event) for event in sorted(
            latest.values(), key=lambda value: (value["company_id"], value["revision"])
        )]

    def deliver(self, event):
        """Durably deliver one Company event, returning a small audit receipt."""
        self._validate_event(event)
        kind = event["kind"]
        if kind == "company.eligible":
            result = self._deliver_eligible(event)
        else:
            result = self._deliver_cancellation(event)
        if result["state"] not in {
            "WAITING_FOR_SAFE_REQUEST_BOUNDARY", "SUPERSEDED_BY_DURABLE_REQUEST",
        }:
            self.repository.acknowledge_company_event(
                event["event_id"], self.consumer, source_revision=event["source_revision"],
            )
        return result

    def _deliver_eligible(self, event):
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
                request = self._request_for(event)
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

        request = self._request_for(event)
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

    def _request_for(self, event):
        return {
            "mode": "company-only",
            "request_id": "company-event:" + event["event_id"],
            "company_ids": [event["company_id"]],
            "source_revision": event["source_revision"],
            "enqueued_at": self._timestamp(),
            "start_last": [],
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
        if not isinstance(event.get("revision"), int) or event["revision"] < 1:
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

    def _write_atomic_json(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        encoded = (json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")
        descriptor, temporary = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
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
