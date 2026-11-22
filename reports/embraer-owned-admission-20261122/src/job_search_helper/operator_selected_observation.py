"""Read-only ownership proof for one selected operator partial request.

This is deliberately an admission/readback helper.  It cannot queue, start,
resume, settle, publish, or deliver anything.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import re

from .company_events import canonical_company_fact, source_revision
from .engine import Engine, State
from .operator_company_request import SCHEMA, _digest
from .operator_partial_scope import AMPHENOL, require_operator_partial_scope
from .scan_request import _read_request, cycle_metadata, request_fingerprint
from .sqlite_repository import SQLiteRepository


COMPANY_ID = AMPHENOL.company_id
COMPANY_NAME = AMPHENOL.company_name
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_CYCLE_ID = re.compile(r"CYC-[0-9A-F]{12}\Z")
_FORBIDDEN_PROVENANCE = (
    "company_event", "repair_retry", "temporary_retry", "recovery_pause",
    "selected_retry_reservation_sha256",
)


def read_operator_selected_observation(repository, state, runtime_binding, *, request_sha256,
                                       settlement_recovery=False, scope=AMPHENOL):
    """Prove exactly one operator-selected request is still owned locally.

    A queued request returns ``state='QUEUED'``.  A request already moved to
    ``last-scan-request.json`` returns ``state='ADMITTED'`` only when its sole
    normal cycle and local Scan Cycles mirror retain the identical immutable
    operator provenance and runtime binding.  Every other condition is an
    explicit hold expressed as ``ValueError``.
    """
    require_operator_partial_scope(scope)
    root = _canonical_readers(repository, state)
    if not isinstance(request_sha256, str) or _SHA256.fullmatch(request_sha256) is None:
        raise ValueError("operator_selected_observation_request_sha256_invalid")
    if type(settlement_recovery) is not bool:
        raise ValueError("operator_selected_observation_settlement_recovery_invalid")

    request = _matching_request(root, request_sha256)
    receipt = _find_receipt(root, request, request_sha256)
    _validate_request(request, receipt, request_sha256, scope)
    company = _current_company(repository, request["operator_request"], scope)
    request_id = request["request_id"]
    cycles = [cycle for cycle in state.cycles() if cycle.get("start_request_id") == request_id]
    if len(cycles) > 1:
        raise ValueError("operator_selected_observation_cycle_ambiguous")
    if not cycles:
        if (root / "next-scan.json").is_file() and _same_json_file(root / "next-scan.json", request):
            return _result("QUEUED", request, request_sha256, receipt, company, scope)
        raise ValueError("operator_selected_observation_not_admitted")

    cycle = cycles[0]
    _validate_cycle(repository, cycle, request, runtime_binding, scope)
    mirrors = repository.matches("Scan Cycles", {"Cycle ID": cycle["id"]})
    if len(mirrors) != 1:
        raise ValueError("operator_selected_observation_mirror_ambiguous")
    mirror = mirrors[0][1]
    _validate_mirror(cycle, mirror, settlement_recovery=settlement_recovery, scope=scope)
    return _result("ADMITTED", request, request_sha256, receipt, company, scope, cycle=cycle, mirror=mirror)


def _canonical_readers(repository, state):
    if (not isinstance(repository, SQLiteRepository) or not repository.readonly
            or not isinstance(state, State) or not state.readonly):
        raise ValueError("operator_selected_observation_readonly_authority_required")
    if getattr(repository, "is_local", False) is not True or not state.path or state.path == ":memory:":
        raise ValueError("operator_selected_observation_local_authority_required")
    jobs = Path(repository.path)
    root = jobs.parent
    canonical_state = root / "state.db"
    if (not jobs.is_absolute() or not Path(state.path).is_absolute()
            or jobs != root / "jobs.sqlite3" or Path(state.path) != canonical_state
            or any(path.is_symlink() or not path.is_file() for path in (jobs, canonical_state))):
        raise ValueError("operator_selected_observation_canonical_stores_required")
    return root


def _find_receipt(root, request, request_sha256):
    directory = root / "operator-company-requests" / "receipts"
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("operator_selected_observation_receipt_missing")
    request_id = request.get("request_id") if isinstance(request, dict) else None
    path = directory / (_digest({"request_id": request_id}) + ".json")
    if path.is_symlink() or not path.is_file() or path.parent != directory:
        raise ValueError("operator_selected_observation_receipt_missing")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("operator_selected_observation_receipt_invalid") from exc
    if not isinstance(value, dict) or value.get("request_sha256") != request_sha256:
        raise ValueError("operator_selected_observation_receipt_invalid")
    return value


def _matching_request(root, request_sha256):
    """Use current queue or last request only; old requests are never replayed."""
    candidates = []
    for name in ("next-scan.json", "last-scan-request.json"):
        path = root / name
        if not path.exists():
            continue
        if path.is_symlink() or not path.is_file():
            raise ValueError("operator_selected_observation_request_unsafe")
        try:
            request, _company_ids = _read_request(path)
        except (OSError, ValueError, TypeError) as exc:
            raise ValueError("operator_selected_observation_request_invalid") from exc
        if _digest(request) == request_sha256:
            candidates.append((name, request))
    if len(candidates) != 1:
        raise ValueError("operator_selected_observation_request_ambiguous")
    return candidates[0][1]


def _validate_request(request, receipt, request_sha256, scope):
    operator = request.get("operator_request") if isinstance(request, dict) else None
    expected = {"schema": SCHEMA, "request_id": request.get("request_id") if isinstance(request, dict) else None,
                "company_id": scope.company_id,
                "source_revision": request.get("source_revision") if isinstance(request, dict) else None}
    if (not isinstance(request, dict) or request.get("mode") != "company-only"
            or request.get("company_ids") != [scope.company_id] or request.get("start_last") != []
            or operator != expected or any(request.get(key) is not None for key in (
                "company_event", "repair_retry", "temporary_retry"))
            or request_fingerprint(request, [scope.company_id]) is None):
        raise ValueError("operator_selected_observation_request_scope_invalid")
    if (set(receipt) != {"schema", "request_id", "company_id", "source_revision", "state", "request_sha256"}
            or any(receipt.get(key) != value for key, value in expected.items())
            or receipt.get("state") not in {"REQUEST_WRITTEN", "REQUEST_ALREADY_DURABLE"}
            or receipt.get("request_sha256") != request_sha256):
        raise ValueError("operator_selected_observation_receipt_invalid")


def _current_company(repository, operator, scope):
    rows = repository.matches("Companies", {"Company ID": scope.company_id})
    if len(rows) != 1:
        raise ValueError("operator_selected_observation_company_ambiguous")
    company = rows[0][1]
    fact = canonical_company_fact(company)
    if (company.get("Company") != scope.company_name or fact.get("eligible") is not True
            or str(company.get("Claimed By") or "").strip()
            or str(company.get("Claim Token") or "").strip()
            or source_revision(company) != operator["source_revision"]):
        raise ValueError("operator_selected_observation_company_not_current")
    return copy.deepcopy(company)


def _validate_cycle(repository, cycle, request, runtime_binding, scope):
    operator = request["operator_request"]
    if (not isinstance(cycle, dict) or not _CYCLE_ID.fullmatch(cycle.get("id", ""))
            or cycle.get("all") is not False or cycle.get("start_request_id") != request["request_id"]
            or cycle.get("operator_request") != operator
            or cycle.get("request_fingerprint") != request_fingerprint(request, [scope.company_id])
            or set(cycle.get("companies", {})) != {scope.company_id}
            or any(cycle.get(key) is not None for key in _FORBIDDEN_PROVENANCE)):
        raise ValueError("operator_selected_observation_cycle_scope_invalid")
    item = cycle["companies"][scope.company_id]
    if not isinstance(item, dict) or item.get("company") != scope.company_name:
        raise ValueError("operator_selected_observation_cycle_company_invalid")
    Engine.validate_cycle_runtime_binding(cycle, runtime_binding)


def _validate_mirror(cycle, mirror, *, settlement_recovery, scope):
    notes = cycle_metadata(mirror)
    transient = (settlement_recovery is True and cycle.get("status") == "In Progress"
                 and mirror.get("Cycle Status") == "Complete with exceptions")
    if ((mirror.get("Cycle Status") != cycle.get("status") and not transient) or notes.get("all") is not False
            or notes.get("company_ids") != [scope.company_id]
            or any(notes.get(key) != cycle.get(key) for key in (
                "start_request_id", "request_fingerprint", "operator_request", "runtime_binding"))
            or any(notes.get(key) is not None for key in _FORBIDDEN_PROVENANCE)):
        raise ValueError("operator_selected_observation_mirror_invalid")


def _same_json_file(path, expected):
    try:
        return json.loads(path.read_text(encoding="utf-8")) == expected
    except (OSError, ValueError):
        return False


def _result(state, request, request_sha256, receipt, company, scope, *, cycle=None, mirror=None):
    result = {
        "state": state, "request": copy.deepcopy(request), "request_sha256": request_sha256,
        "receipt": copy.deepcopy(receipt), "company": company,
        "company_id": scope.company_id, "source_revision": request["source_revision"],
        "request_fingerprint": request_fingerprint(request, [scope.company_id]),
    }
    if cycle is not None:
        result["cycle"] = copy.deepcopy(cycle)
        result["mirror"] = copy.deepcopy(mirror)
    return result
