"""Read-only signed-scope measurement for the retained operator route."""
from contextlib import closing
from pathlib import Path
import sqlite3
from types import SimpleNamespace

from .exact_cycle_sync import _company_guard
from .company_sources import repair_source
from .retained_operator_authorization import (
    operator_membership_claims, verify_operator_membership_authorization,
)
from .retained_operator_scope import historical_work_evidence, queued_membership_evidence
from .retained_work_exception import (
    _assert_disjoint_identity, _endpoint, _name, _provider_identity, digest, revalidate_manifest,
)
from .retained_work_runner import _trusted_snapshot
from .scan_request import _unfinished_cycle_ids


def verify_operator_source_identity(manifest, scope, company, fact, *, inventory=None):
    """Check other-company aliases and match the returned source to the known board."""
    company_id = scope["company_id"]
    other_members = {
        "cycle_membership": [value for value in manifest["cycle_membership"] if value != company_id],
        "cycle_company_identities": [
            value for value in manifest["cycle_company_identities"] if value.get("company_id") != company_id
        ],
    }
    ats, source, _ = repair_source(company.get("ATS / Source", ""), company["Official Careers URL"],
                                   company_id, company["Company"])
    expected_provider = _provider_identity(ats, source)
    source_endpoint = _endpoint(source)
    if inventory is not None:
        returned_provider = _provider_identity(inventory["ats"], inventory["source_url"])
        if not expected_provider or returned_provider != expected_provider:
            raise ValueError("retained_operator_returned_source_changed")
        source_endpoint = _endpoint(inventory["source_url"])
    _assert_disjoint_identity(
        other_members, company_id, _name(company["Company"]), fact["official_careers_url"],
        source_endpoint=source_endpoint, provider_identity=expected_provider,
    )


def measure_operator_membership(local, remote, state, state_directory, manifest, runtime, *, expires_at):
    """Measure one current operator request while its caller holds admission."""
    root = Path(state_directory).resolve()
    if not state.readonly or not local.readonly or Path(state.path).resolve() != root / "state.db":
        raise ValueError("retained_operator_readonly_state_required")
    if Path(local.path).resolve() != root / "jobs.sqlite3":
        raise ValueError("retained_operator_repository_identity_changed")
    snapshot, company, cycle = _trusted_snapshot(local, state, root, manifest)
    request = snapshot["request"]
    if not request.get("operator_request") or request.get("company_event") is not None:
        raise ValueError("retained_operator_request_changed")
    scope = queued_membership_evidence(
        state.cycles(), cycle_id=manifest["cycle_id"], company_id=request["company_ids"][0],
        company_name=company["Company"],
    )
    if company.get("Active Cycle ID") != scope["cycle_id"]:
        raise ValueError("retained_operator_historical_owner_changed")
    verify_operator_source_identity(manifest, scope, company, snapshot["company_fact"])
    revalidate_manifest(manifest, cycle, root / "inventories.sqlite3", root / "jobs.sqlite3")
    with closing(sqlite3.connect((root / "inventories.sqlite3").as_uri() + "?mode=ro", uri=True)) as inventory:
        with closing(sqlite3.connect((root / "jobs.sqlite3").as_uri() + "?mode=ro", uri=True)) as jobs:
            historical = historical_work_evidence(inventory, jobs, scope)
    workbook_blockers = _unfinished_cycle_ids(SimpleNamespace(repo=remote), state, include_remote=True)
    if workbook_blockers != {scope["cycle_id"]}:
        raise ValueError("retained_operator_workbook_blockers_changed")
    controls = _company_guard(local, remote, scope["company_id"], company["Official Careers URL"])
    if not getattr(remote, "schemas", None):
        raise ValueError("retained_operator_workbook_schema_missing")
    workbook = {"controls": controls, "schemas_sha256": digest(remote.schemas)}
    return operator_membership_claims(
        snapshot, scope, historical_work_digest=historical, runtime=runtime,
        workbook_controls=workbook, expires_at=expires_at,
    )


def verify_current_operator_membership(local, remote, state, state_directory, manifest, runtime,
                                       *, approval, verifier, now=None):
    """Recompute the exact approval scope before admitting any fetch."""
    payload = approval.get("payload") if isinstance(approval, dict) else None
    if not isinstance(payload, dict) or not payload.get("expires_at"):
        raise ValueError("retained_operator_authorization_missing")
    claims = measure_operator_membership(
        local, remote, state, state_directory, manifest, runtime, expires_at=payload["expires_at"],
    )
    return verify_operator_membership_authorization(approval, claims, verifier, now=now)
