"""Crash-durable handoff from an admitted integration release to one retry.

The release controller calls :class:`RepairRetryBridge` only after a reviewed
release is active.  The bridge first saves an immutable intent, then offers a
company-only request to the normal scraper boundary.  A crash between those
steps is recoverable by redelivering the same release receipt; a different
pending scan is never overwritten.

This module does not install code, start the scraper, or publish jobs.  Those
remain separate receipts and owners.  It establishes the F2 identity and
precedence boundary used by those existing components.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path


REPAIR_RETRY_SCHEMA = "repair-retry-request-v1"
RELEASE_BINDING_SCHEMA = "integration-release-binding-v1"
_DIGEST_FIELDS = (
    "source_manifest_sha256", "dependency_manifest_sha256", "config_sha256",
)


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def _text(value, name, *, maximum=256):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise ValueError(f"Repair retry requires bounded {name}")
    return value.strip()


def _digest(value):
    value = _text(value, "SHA-256", maximum=64)
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("Repair retry requires lowercase SHA-256 bindings")
    return value


def canonical_release_binding(value):
    """Validate the complete installed version used by a future attempt."""
    if not isinstance(value, dict) or set(value) != {
            "schema", "release_id", *_DIGEST_FIELDS}:
        raise ValueError("Repair retry release binding has unsupported fields")
    if value.get("schema") != RELEASE_BINDING_SCHEMA:
        raise ValueError("Repair retry release binding schema is unsupported")
    result = {
        "schema": RELEASE_BINDING_SCHEMA,
        "release_id": _text(value.get("release_id"), "release ID"),
    }
    result.update({name: _digest(value.get(name)) for name in _DIGEST_FIELDS})
    return result


def canonical_retry_binding(value):
    """Validate one immutable release-to-retry identity."""
    required = {
        "schema", "attempt_id", "failed_request_id", "company_id",
        "source_revision", "release", "activated_at",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("Repair retry binding has unsupported fields")
    if value.get("schema") != REPAIR_RETRY_SCHEMA:
        raise ValueError("Repair retry binding schema is unsupported")
    result = {
        "schema": REPAIR_RETRY_SCHEMA,
        "failed_request_id": _text(value.get("failed_request_id"), "failed request ID"),
        "company_id": _text(value.get("company_id"), "Company ID"),
        "source_revision": _text(value.get("source_revision"), "source revision"),
        "release": canonical_release_binding(value.get("release")),
        "activated_at": _timestamp(value.get("activated_at")),
    }
    expected = retry_attempt_id(result)
    if value.get("attempt_id") != expected:
        raise ValueError("Repair retry attempt ID does not match its immutable binding")
    result["attempt_id"] = expected
    return result


def retry_attempt_id(binding_without_attempt):
    """Derive a fresh attempt identity from source, failure and full release."""
    immutable = {key: binding_without_attempt[key] for key in (
        "schema", "failed_request_id", "company_id", "source_revision",
        "release", "activated_at",
    )}
    return "RTRY-" + hashlib.sha256(_canonical(immutable).encode("utf-8")).hexdigest()[:24]


def retry_request(binding, *, enqueued_at):
    binding = canonical_retry_binding(binding)
    return {
        "mode": "company-only",
        "request_id": "company-retry:" + binding["attempt_id"],
        "company_ids": [binding["company_id"]],
        "source_revision": binding["source_revision"],
        "enqueued_at": _timestamp(enqueued_at),
        "start_last": [],
        "repair_retry": binding,
    }


def validate_retry_request(request, company_ids):
    """Return canonical retry provenance or raise before scope admission."""
    binding = canonical_retry_binding(request.get("repair_retry"))
    expected_request_id = "company-retry:" + binding["attempt_id"]
    if (company_ids != [binding["company_id"]]
            or request.get("request_id") != expected_request_id
            or request.get("source_revision") != binding["source_revision"]
            or request.get("request_id") == binding["failed_request_id"]):
        raise ValueError("Repair retry request is not bound to its company, source, and fresh attempt")
    return binding


class RepairRetryBridge:
    """Persist release intent before offering it to the single scan boundary."""

    def __init__(self, database, *, current_source_revision, now=None):
        self.database = Path(database)
        self.root = self.database.parent / "repair-retry"
        self.intent_directory = self.root / "intents"
        self.receipt_directory = self.root / "receipts"
        self.request_path = self.database.parent / "next-scan.json"
        self.current_source_revision = current_source_revision
        self.now = now or (lambda: datetime.now(timezone.utc))
        for directory in (self.intent_directory, self.receipt_directory):
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)

    def deliver(self, binding):
        canonical = canonical_retry_binding(binding)
        current = self.current_source_revision(canonical["company_id"])
        if current != canonical["source_revision"]:
            self._receipt(canonical, "STALE_COMPANY_REVISION")
            return {"attempt_id": canonical["attempt_id"],
                    "state": "STALE_COMPANY_REVISION"}

        intent_path = self.intent_directory / (canonical["attempt_id"] + ".json")
        existing_intent = self._read_json(intent_path)
        if existing_intent is None:
            self._write_atomic_json(intent_path, canonical)
        elif existing_intent != canonical:
            raise RuntimeError("Repair retry intent conflicts with its immutable attempt ID")

        # The immutable activation time is also the queue-age origin.  Using
        # it makes crash recovery reproduce byte-for-byte identical requests.
        request = retry_request(canonical, enqueued_at=canonical["activated_at"])
        existing = self._read_json(self.request_path)
        if existing is not None:
            if existing == request:
                state = "REQUEST_ALREADY_DURABLE"
            else:
                state = "WAITING_SAFE_REQUEST_BOUNDARY"
            self._receipt(canonical, state, request=request)
            return {"attempt_id": canonical["attempt_id"], "state": state}

        self._write_atomic_json(self.request_path, request)
        if self._read_json(self.request_path) != request:
            raise RuntimeError("Repair retry durable request readback failed")
        self._receipt(canonical, "REQUEST_WRITTEN", request=request)
        return {"attempt_id": canonical["attempt_id"], "state": "REQUEST_WRITTEN"}

    def pending_intents(self):
        return [self._read_json(path) for path in sorted(self.intent_directory.glob("RTRY-*.json"))]

    def _receipt(self, binding, state, *, request=None):
        identity = {
            "schema": REPAIR_RETRY_SCHEMA,
            "attempt_id": binding["attempt_id"],
            "company_id": binding["company_id"],
            "source_revision": binding["source_revision"],
            "release_id": binding["release"]["release_id"],
        }
        entry = {
            "state": state,
            "recorded_at": self._timestamp(),
        }
        if request is not None:
            entry["request_sha256"] = hashlib.sha256(
                _canonical(request).encode("utf-8")).hexdigest()
        path = self.receipt_directory / (binding["attempt_id"] + ".json")
        prior = self._read_json(path)
        if prior is None:
            value = {**identity, "state": state, "history": [entry]}
        else:
            if {key: prior.get(key) for key in identity} != identity:
                raise RuntimeError("Repair retry receipt conflicts with immutable attempt identity")
            history = prior.get("history")
            if not isinstance(history, list):
                raise RuntimeError("Repair retry receipt history is invalid")
            value = {**identity, "state": state, "history": [*history, entry]}
        self._write_atomic_json(path, value)

    def _timestamp(self):
        return _timestamp(self.now())

    @staticmethod
    def _read_json(path):
        if not path.exists():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"Cannot safely read {path.name}") from exc
        if not isinstance(value, dict):
            raise RuntimeError(f"Expected object JSON in {path.name}")
        return value

    @staticmethod
    def _write_atomic_json(path, value):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = path.with_name(path.name + ".new")
        payload = (_canonical(value) + "\n").encode("utf-8")
        with temporary.open("wb") as handle:
            os.chmod(temporary, 0o600)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _timestamp(value):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("Repair retry timestamp must be ISO-8601") from exc
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("Repair retry timestamp must include a timezone")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
