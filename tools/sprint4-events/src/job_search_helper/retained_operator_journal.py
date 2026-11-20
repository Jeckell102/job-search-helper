"""Private write-ahead journal for the retained operator provider boundary.

All callers hold the inherited exclusive scraper lease. Build a binding from
freshly measured claims, validated runtime and the verified authorization
receipt. Prepare, claim once, call the provider, and freeze the checked
inventory using the returned process-local claim token. On recovery, reuse a
frozen inventory or leave a claimed request held. The caller must reverify
the current authorization and the returned provider identity where applicable.
After verified downstream settlement, record terminal evidence before exact
request consumption. Record verified consumption to open normal admission
and archive the exact terminal record for acknowledgement-loss recovery.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import stat
import tempfile

from .retained_operator_authorization import ACTION, EVENT_ACTION
from .retained_work_exception import _timestamp
from .retained_work_runner import _EVENT_ID


JOURNAL_NAME = "retained-operator-admission.json"
ARCHIVE_DIRECTORY = "retained-operator-admission-archive"
PREPARED = "PREPARED"
FETCH_CLAIMED = "FETCH_CLAIMED"
INVENTORY_FROZEN = "INVENTORY_FROZEN"
SETTLED = "SETTLED"
VERIFIED_ZERO = "VERIFIED_ZERO"
FETCH_OUTCOME = "FETCH_OUTCOME"

_SCHEMA = "retained-operator-admission-journal-v1"
_SHA256 = re.compile(r"[0-9a-f]{64}")
_CLAIMS_DIGESTS = {
    "request_sha256", "receipt_sha256", "company_row_sha256", "cycle_scope_sha256",
    "historical_work_sha256", "historical_manifest_sha256", "runtime_sha256",
    "workbook_controls_sha256",
}
_CLAIMS_FIELDS = _CLAIMS_DIGESTS | {
    "action", "version", "request_id", "company_id", "source_revision", "cycle_id", "expires_at",
}
_RUNTIME_DIGESTS = {"source_manifest_sha256", "config_sha256", "dependency_manifest_sha256"}
_AUTHORIZATION_FIELDS = {"authorization_digest", "claims_digest", "key_id", "expires_at"}
_RECORD_FIELDS = {
    "schema", "state", "binding", "fetch_claim_sha256", "inventory", "inventory_sha256", "record_sha256",
    "settlement_evidence", "settlement_evidence_sha256", "consumption",
}


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _digest(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _is_digest(value):
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _is_text(value):
    return isinstance(value, str) and bool(value.strip()) and value == value.strip()


def operator_journal_binding(claims, runtime, authorization):
    """Return the exact reservation identity from verified operator evidence."""
    if (not isinstance(claims, dict) or set(claims) != _CLAIMS_FIELDS
            or claims["action"] not in (ACTION, EVENT_ACTION) or type(claims["version"]) is not int
            or claims["version"] != 2
            or not all(_is_text(claims[key]) for key in (
                "request_id", "company_id", "source_revision", "cycle_id"))
            or not all(_is_digest(claims[key]) for key in _CLAIMS_DIGESTS)):
        raise ValueError("retained_operator_journal_claims_invalid")
    if claims["action"] == EVENT_ACTION:
        prefix = "company-event:"
        if not claims["request_id"].startswith(prefix) or not _EVENT_ID.fullmatch(
                claims["request_id"][len(prefix):]):
            raise ValueError("retained_operator_journal_claims_invalid")
    if not isinstance(runtime, dict) or runtime.get("state") not in (
            "NO_RELEASE", "COMPLETE", "ROLLED_BACK"):
        raise ValueError("retained_operator_journal_runtime_invalid")
    runtime_fields = _RUNTIME_DIGESTS | {"state"}
    if runtime["state"] != "NO_RELEASE":
        runtime_fields.add("release_id")
        if not _is_text(runtime.get("release_id")) or not runtime["release_id"].startswith("REL-"):
            raise ValueError("retained_operator_journal_runtime_invalid")
    if (set(runtime) != runtime_fields or not all(_is_digest(runtime[key]) for key in _RUNTIME_DIGESTS)
            or _digest(runtime) != claims["runtime_sha256"]):
        raise ValueError("retained_operator_journal_runtime_invalid")
    if (not isinstance(authorization, dict) or set(authorization) != _AUTHORIZATION_FIELDS
            or not _is_digest(authorization["authorization_digest"])
            or authorization["claims_digest"] != _digest(claims)
            or not _is_text(authorization["key_id"])
            or authorization["expires_at"] != claims["expires_at"]
            or _timestamp(claims["expires_at"]) != claims["expires_at"]):
        raise ValueError("retained_operator_journal_authorization_invalid")
    binding = {"claims": dict(claims), "runtime": dict(runtime),
               "authorization": dict(authorization)}
    return {**binding, "reservation_digest": _digest(binding)}


def _check_binding(binding):
    if not isinstance(binding, dict) or set(binding) != {
            "claims", "runtime", "authorization", "reservation_digest"}:
        raise ValueError("retained_operator_journal_binding_invalid")
    if operator_journal_binding(binding["claims"], binding["runtime"], binding["authorization"]) != binding:
        raise ValueError("retained_operator_journal_binding_invalid")


def _inventory_digest(inventory, binding):
    return provider_inventory_digest(inventory, event_scope=binding["claims"]["action"] == EVENT_ACTION)


def provider_inventory_digest(inventory, *, event_scope):
    statuses = {"complete", "partial"}
    if event_scope:
        from .ats import validate_outcome_failure
        statuses.update(("blocked", "failed", "unsupported"))
        failure = inventory.get("outcome_failure") if isinstance(inventory, dict) else None
        if failure is not None and (validate_outcome_failure(failure) != failure
                                    or inventory.get("status") == "complete"):
            raise ValueError("retained_event_journal_failure_invalid")
    if (not isinstance(inventory, dict) or inventory.get("status") not in statuses
            or not isinstance(inventory.get("jobs"), list)
            or not all(isinstance(job, dict) for job in inventory["jobs"])
            or not all(_is_text(inventory.get(key)) for key in ("ats", "source_url", "requested_url"))):
        raise ValueError("retained_operator_journal_inventory_invalid")
    encoded = _canonical(inventory)
    if json.loads(encoded) != inventory:
        raise ValueError("retained_operator_journal_inventory_invalid")
    return hashlib.sha256(encoded).hexdigest()


def _settlement_digest(evidence, binding, inventory_sha256):
    if not isinstance(evidence, dict) or not evidence:
        raise ValueError("retained_operator_journal_settlement_evidence_invalid")
    identity = {key: binding["claims"][key] for key in ("request_id", "company_id", "source_revision")}
    identity.update(reservation_digest=binding["reservation_digest"], inventory_sha256=inventory_sha256)
    if any(key in evidence and evidence[key] != value for key, value in identity.items()):
        raise ValueError("retained_operator_journal_settlement_evidence_binding_changed")
    encoded = _canonical(evidence)
    if json.loads(encoded) != evidence:
        raise ValueError("retained_operator_journal_settlement_evidence_invalid")
    return hashlib.sha256(encoded).hexdigest()


def _expected_consumption(binding, evidence):
    state = "FIRST_PASS_RELEASED_CONSUMED"
    if binding["claims"]["action"] == EVENT_ACTION:
        state = {VERIFIED_ZERO: "VERIFIED_ZERO_CONSUMED", FETCH_OUTCOME: "FETCH_OUTCOME_CONSUMED"}.get(
            evidence.get("state"), state,
        )
    return {"request_sha256": binding["claims"]["request_sha256"], "state": state}


def _validate_record(record):
    if not isinstance(record, dict) or set(record) != _RECORD_FIELDS or record["schema"] != _SCHEMA:
        raise ValueError("retained_operator_journal_corrupt")
    if record["record_sha256"] != _digest({key: value for key, value in record.items()
                                           if key != "record_sha256"}):
        raise ValueError("retained_operator_journal_corrupt")
    _check_binding(record["binding"])
    state = record["state"]
    claim = record["fetch_claim_sha256"]
    frozen = state in (INVENTORY_FROZEN, SETTLED)
    if (state == PREPARED and claim is not None
            or (state == FETCH_CLAIMED or frozen) and not _is_digest(claim)
            or state not in (PREPARED, FETCH_CLAIMED, INVENTORY_FROZEN, SETTLED)):
        raise ValueError("retained_operator_journal_corrupt")
    if frozen:
        if record["inventory_sha256"] != _inventory_digest(record["inventory"], record["binding"]):
            raise ValueError("retained_operator_journal_corrupt")
    elif record["inventory"] is not None or record["inventory_sha256"] is not None:
        raise ValueError("retained_operator_journal_corrupt")
    if state == SETTLED:
        if record["settlement_evidence_sha256"] != _settlement_digest(
                record["settlement_evidence"], record["binding"], record["inventory_sha256"]):
            raise ValueError("retained_operator_journal_corrupt")
        if record["consumption"] is not None and record["consumption"] != _expected_consumption(record["binding"], record["settlement_evidence"]):
            raise ValueError("retained_operator_journal_corrupt")
    elif any(record[key] is not None for key in (
            "settlement_evidence", "settlement_evidence_sha256", "consumption")):
        raise ValueError("retained_operator_journal_corrupt")


def _read_record(path):
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    except OSError as error:
        raise ValueError("retained_operator_journal_unreadable") from error
    try:
        with os.fdopen(descriptor, "rb") as handle:
            attrs = os.fstat(handle.fileno())
            if (not stat.S_ISREG(attrs.st_mode) or stat.S_IMODE(attrs.st_mode) != 0o600
                    or attrs.st_nlink != 1 or attrs.st_uid != os.geteuid()):
                raise ValueError("retained_operator_journal_unsafe")
            raw = handle.read()
        record = json.loads(raw)
        if _canonical(record) + b"\n" != raw:
            raise ValueError("retained_operator_journal_noncanonical")
        _validate_record(record)
        return record
    except (OSError, ValueError, TypeError, RecursionError) as error:
        raise ValueError("retained_operator_journal_corrupt") from error


def _sync_parent(path):
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_record(path, record):
    body = {key: value for key, value in record.items() if key != "record_sha256"}
    sealed = {**body, "record_sha256": _digest(body)}
    _validate_record(sealed)
    descriptor, temporary = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(_canonical(sealed) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _sync_parent(path)
    finally:
        if os.path.lexists(temporary):
            os.unlink(temporary)
    if _read_record(path) != sealed:
        raise ValueError("retained_operator_journal_readback_changed")
    return sealed


class RetainedOperatorJournal:
    """One admission at a time in the existing state directory under the scraper lease."""

    def __init__(self, state_directory):
        self.path = Path(state_directory) / JOURNAL_NAME
        self.archive_directory = self.path.parent / ARCHIVE_DIRECTORY

    def inspect(self):
        """Inspect the active slot without writes; independently rederive its binding before use."""
        return _read_record(self.path)

    def _archive_path(self, binding):
        return self.archive_directory / (
            binding["claims"]["request_sha256"] + "-" + binding["reservation_digest"] + ".json")

    def _archive_directory_exists(self):
        try:
            attrs = self.archive_directory.lstat()
        except FileNotFoundError:
            return False
        if (not stat.S_ISDIR(attrs.st_mode) or stat.S_IMODE(attrs.st_mode) != 0o700
                or attrs.st_uid != os.geteuid()):
            raise ValueError("retained_operator_journal_archive_directory_unsafe")
        return True

    def read_archived(self, binding):
        """Read an exact consumed terminal record by trusted request and reservation, without writes."""
        _check_binding(binding)
        if not self._archive_directory_exists():
            return None
        expected = self._archive_path(binding)
        request_sha256 = binding["claims"]["request_sha256"]
        # A new signature for the same exact request cannot open a second
        # reservation. Ignore temporary files from interrupted atomic writes.
        matches = [path for path in self.archive_directory.iterdir()
                   if path.name.startswith(request_sha256 + "-") and path.suffix == ".json"]
        if not matches:
            return None
        if matches != [expected]:
            raise ValueError("retained_operator_journal_archive_binding_changed")
        record = _read_record(expected)
        if record is None or record["binding"] != binding or record["consumption"] is None:
            raise ValueError("retained_operator_journal_archive_binding_changed")
        return record

    def read_archived_event(self, request_sha256, reservation_digest):
        """Reopen a consumed event using its exact content-addressed keys."""
        if not _is_digest(request_sha256) or not _is_digest(reservation_digest):
            raise ValueError("retained_event_archive_identity_invalid")
        if not self._archive_directory_exists():
            return None
        path = self.archive_directory / (request_sha256 + "-" + reservation_digest + ".json")
        record = _read_record(path)
        if record is None:
            return None
        binding = record["binding"]
        claims = binding["claims"]
        if (claims["action"] != EVENT_ACTION or claims["request_sha256"] != request_sha256
                or binding["reservation_digest"] != reservation_digest):
            raise ValueError("retained_event_archive_identity_changed")
        return self.read_archived(binding)

    def read_settled_event(self, request_sha256, reservation_digest):
        """Find only the selected settled active slot or its consumed archive."""
        archived = self.read_archived_event(request_sha256, reservation_digest)
        if archived is not None:
            return archived
        active = self.inspect()
        if active is None or active["state"] != SETTLED:
            return None
        binding = active["binding"]
        claims = binding["claims"]
        if (claims["action"], claims["request_sha256"], binding["reservation_digest"]) == (
                EVENT_ACTION, request_sha256, reservation_digest):
            return active
        return None

    def read(self, binding):
        """Read exact active or archived evidence, or None for a fresh request."""
        _check_binding(binding)
        active = self.inspect()
        archived = self.read_archived(binding)
        if active is None:
            return archived
        if active["binding"] == binding:
            if archived is not None and archived != active:
                raise ValueError("retained_operator_journal_archive_record_changed")
            return active
        if (active["binding"]["claims"]["request_sha256"] == binding["claims"]["request_sha256"]
                or (archived is None and active["consumption"] is None)):
            raise ValueError("retained_operator_journal_binding_changed")
        return archived

    def prepare(self, binding):
        """Durably create PREPARED once. An exact retry returns the current phase."""
        record = self.read(binding)
        if record is not None:
            _sync_parent(self.path)
            return record
        prior = self.inspect()
        if prior is not None:
            self.archive_completed(prior["binding"])
        return _write_record(self.path, {
            "schema": _SCHEMA, "state": PREPARED, "binding": binding,
            "fetch_claim_sha256": None, "inventory": None, "inventory_sha256": None,
            "settlement_evidence": None, "settlement_evidence_sha256": None, "consumption": None,
        })

    def claim_fetch(self, binding):
        """Persist and sync FETCH_CLAIMED before giving the sole caller a token."""
        record = self.read(binding)
        if record is None or record["state"] != PREPARED:
            raise ValueError("retained_operator_journal_fetch_already_claimed"
                             if record is not None else "retained_operator_journal_missing")
        claim = secrets.token_hex(32)
        _write_record(self.path, dict(record, state=FETCH_CLAIMED, fetch_claim_sha256=_digest(claim)))
        return claim

    def freeze_inventory(self, binding, claim, inventory):
        """Freeze inventory already checked against the approved provider identity."""
        record = self.read(binding)
        if (record is None or record["state"] == PREPARED or not _is_digest(claim)
                or not hmac.compare_digest(_digest(claim), record["fetch_claim_sha256"])):
            raise ValueError("retained_operator_journal_fetch_claim_invalid")
        inventory_sha256 = _inventory_digest(inventory, binding)
        if record["state"] in (INVENTORY_FROZEN, SETTLED):
            if record["inventory_sha256"] != inventory_sha256:
                raise ValueError("retained_operator_journal_inventory_changed")
            _sync_parent(self.path)
            return record
        return _write_record(self.path, dict(record, state=INVENTORY_FROZEN,
                                             inventory=inventory, inventory_sha256=inventory_sha256))

    def recover_inventory(self, binding):
        """Read only a frozen result. An ambiguous claim cannot authorize another fetch."""
        record = self.read(binding)
        if record is None or record["state"] == PREPARED:
            raise ValueError("retained_operator_journal_inventory_not_frozen")
        if record["state"] == FETCH_CLAIMED:
            raise ValueError("retained_operator_journal_fetch_ambiguous")
        return record["inventory"]

    def record_settlement(self, binding, *, inventory_sha256, evidence):
        """Freeze verified downstream evidence before consuming the exact request.

        The lease remains held. The caller independently validates the
        evidence from the downstream durable stores. An exact retry rereads
        the same terminal record; it may not replace an earlier receipt.
        """
        record = self.read(binding)
        if (record is None or record["state"] not in (INVENTORY_FROZEN, SETTLED)
                or record["inventory_sha256"] != inventory_sha256):
            raise ValueError("retained_operator_journal_settlement_binding_changed")
        evidence_sha256 = _settlement_digest(evidence, binding, inventory_sha256)
        if record["state"] == SETTLED:
            if record["settlement_evidence_sha256"] != evidence_sha256 or record["settlement_evidence"] != evidence:
                raise ValueError("retained_operator_journal_settlement_evidence_changed")
            _sync_parent(self.path)
            return record
        return _write_record(self.path, dict(record, state=SETTLED, settlement_evidence=evidence,
                                             settlement_evidence_sha256=evidence_sha256))

    def release_after_settlement(self, binding, *, inventory_sha256, consumption):
        """Record verified consumption, then archive and clear the active journal.

        Under the same lease, the caller independently verifies the archive,
        consumption receipt and absence of the original request before calling.
        The receipt must bind the exact request and FIRST PASS release.
        """
        record = self.read(binding)
        if (record is None or record["state"] != SETTLED
                or record["inventory_sha256"] != inventory_sha256
                or consumption != _expected_consumption(binding, record["settlement_evidence"])):
            raise ValueError("retained_operator_journal_consumption_binding_changed")
        if record["consumption"] is None:
            _write_record(self.path, dict(record, consumption=consumption))
        return self.archive_completed(binding)

    def archive_completed(self, binding):
        """Durably archive a completed+consumed record before clearing only its active slot.

        Repeating after an interrupted archive or unlink is safe under the
        lease. An unrelated active request is never overwritten or removed.
        """
        archived = self.read_archived(binding)
        active = self.inspect()
        if active is not None and active["binding"] != binding:
            if active["binding"]["claims"]["request_sha256"] == binding["claims"]["request_sha256"]:
                raise ValueError("retained_operator_journal_archive_binding_changed")
            active = None
        if active is not None and active["consumption"] is None:
            raise ValueError("retained_operator_journal_archive_requires_consumption")
        if archived is None:
            if active is None:
                raise ValueError("retained_operator_journal_archive_missing")
            if not self._archive_directory_exists():
                self.archive_directory.mkdir(mode=0o700)
            _sync_parent(self.archive_directory)
            archived = _write_record(self._archive_path(binding), active)
        elif active is not None and archived != active:
            raise ValueError("retained_operator_journal_archive_record_changed")
        _sync_parent(self._archive_path(binding))
        _sync_parent(self.archive_directory)
        if active is not None:
            self.path.unlink()
        _sync_parent(self.path)
        return archived


def assert_no_unfinished_operator_journal(state_directory):
    """Hold normal entry until a valid terminal record confirms exact consumption."""
    record = RetainedOperatorJournal(state_directory).inspect()
    if record is not None and record["consumption"] is None:
        raise ValueError("retained_operator_journal_holds_normal_lifecycle")
