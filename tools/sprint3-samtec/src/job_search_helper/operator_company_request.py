"""Durable, explicit operator requests for one normal company-only scan."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import tempfile

from .company_events import canonical_company_fact, source_revision
from .cli import scraper_lock_name, writer_lock
from .scan_request import _enqueued_at


SCHEMA = "operator-company-scan-request-v1"
_REQUEST_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{2,127}\Z")


def _digest(value):
    return sha256(json.dumps(value, separators=(",", ":"), sort_keys=True).encode()).hexdigest()


def _read(path):
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("operator_company_request_json_unreadable") from exc
    if not isinstance(value, dict):
        raise ValueError("operator_company_request_json_invalid")
    return value


def _write_atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    encoded = (json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n").encode()
    fd, temporary = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        directory_fd = os.open(path.parent, directory_flags)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def queue_operator_company_request(repository, state_directory, company_id, request_id, *, now=None):
    """Queue exactly one eligible Company without starting or widening a scan.

    The caller supplies an opaque, stable request ID. Repeating the same ID is
    a readback-verified no-op; a different outstanding request is never
    replaced. The receipt permanently binds the ID to the original request.
    """
    company_id = str(company_id or "").strip()
    request_id = str(request_id or "").strip()
    if not company_id or not _REQUEST_ID.fullmatch(request_id):
        raise ValueError("operator_company_request_identity_invalid")
    matches = repository.matches("Companies", {"Company ID": company_id})
    if len(matches) != 1:
        raise ValueError("operator_company_request_company_missing_or_ambiguous")
    company = dict(matches[0][1])
    fact = canonical_company_fact(company)
    if not fact["eligible"]:
        raise ValueError("operator_company_request_company_ineligible")
    if str(company.get("Claimed By", "")).strip() or str(company.get("Claim Token", "")).strip():
        raise ValueError("operator_company_request_company_claimed")
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        raise ValueError("operator_company_request_clock_timezone_required")
    root = Path(state_directory).resolve()
    identity = {"schema": SCHEMA, "request_id": request_id, "company_id": company_id,
                "source_revision": source_revision(company)}
    request = {
        "mode": "company-only", "request_id": request_id,
        "company_ids": [company_id], "source_revision": identity["source_revision"],
        "enqueued_at": clock.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "start_last": [], "operator_request": identity,
    }
    request_path = root / "next-scan.json"
    receipt_path = root / "operator-company-requests" / "receipts" / (_digest({"request_id": request_id}) + ".json")
    with writer_lock(root / scraper_lock_name()):
        current = _read(request_path)
        prior = _read(receipt_path)
        if prior is not None:
            prior_digest = prior.get("request_sha256")
            if (any(prior.get(key) != value for key, value in identity.items())
                    or prior.get("state") not in {"REQUEST_WRITTEN", "REQUEST_ALREADY_DURABLE"}
                    or not isinstance(prior_digest, str) or not re.fullmatch("[0-9a-f]{64}", prior_digest)):
                raise ValueError("operator_company_request_receipt_collision")
            if current is None or current.get("request_id") != request_id:
                return {"state": "REQUEST_PREVIOUSLY_RESERVED", "request_id": request_id,
                        "company_id": company_id, "source_revision": identity["source_revision"]}
        if current is not None and current.get("request_id") != request_id:
            return {"state": "WAITING_FOR_SAFE_REQUEST_BOUNDARY", "request_id": request_id,
                    "company_id": company_id}
        if current is None:
            _write_atomic(request_path, request)
            if _digest(_read(request_path)) != _digest(request):
                raise RuntimeError("operator_company_request_readback_changed")
            state = "REQUEST_WRITTEN"
        else:
            _enqueued_at(current)
            request["enqueued_at"] = current["enqueued_at"]
            if current != request or (prior is not None and prior_digest != _digest(current)):
                raise ValueError("operator_company_request_receipt_collision")
            state = "REQUEST_ALREADY_DURABLE"
        if prior is None:
            _write_atomic(receipt_path, {**identity, "state": state, "request_sha256": _digest(request)})
    return {"state": state, "request_id": request_id, "company_id": company_id,
            "source_revision": request["source_revision"]}
