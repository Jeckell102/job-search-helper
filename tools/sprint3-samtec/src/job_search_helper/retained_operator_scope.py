"""Seal the local cycle evidence for an operator-only retained Company request."""
from collections.abc import Mapping
import json

from .retained_work_exception import _json_value, _receipt_records, _table_records, digest
from .scan_request import superseded_cycle_ids


FINISHED = frozenset(("Complete", "Complete with exceptions"))


def queued_membership_evidence(cycles, *, cycle_id, company_id, company_name):
    """Require the selected Company to have only its exact unstarted membership.

    The caller supplies the full State snapshot taken under scraper admission.
    Inventory, publication, Company controls and signature are separate checks.
    """
    by_id = {}
    for row in cycles:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            raise ValueError("retained_operator_cycle_identity_invalid")
        if not row["id"] or row["id"] in by_id:
            raise ValueError("retained_operator_cycle_identity_invalid")
        by_id[row["id"]] = row
    unfinished = {key: row for key, row in by_id.items() if row.get("status") not in FINISHED}
    superseded = superseded_cycle_ids(list(by_id.values()))
    if set(unfinished) - superseded != {cycle_id}:
        raise ValueError("retained_operator_effective_blocker_changed")
    membership = {}
    for key, row in unfinished.items():
        members = row.get("companies")
        if not isinstance(members, Mapping):
            raise ValueError("retained_operator_cycle_membership_invalid")
        if company_id in members:
            membership[key] = members[company_id]
    expected = {"company": company_name, "stage": "queued"}
    if membership != {cycle_id: expected}:
        raise ValueError("retained_operator_unstarted_membership_unverified")
    return {
        "cycle_id": cycle_id,
        "company_id": company_id,
        "cycles_sha256": digest([by_id[key] for key in sorted(by_id)]),
        "unfinished_cycle_ids": sorted(unfinished),
        "membership_sha256": digest(expected),
    }


def historical_work_evidence(inventory, jobs, cycle_scope):
    """Seal historical work and require absence of prior selected-company work.

    The connections must belong to the read-only snapshots protected by the
    caller's admission locks. This check also runs before recovery dispatch.
    """
    cycles = cycle_scope["unfinished_cycle_ids"]
    company = cycle_scope["company_id"]
    if not cycles or cycle_scope["cycle_id"] not in cycles or not company:
        raise ValueError("retained_operator_historical_scope_invalid")
    evidence = {
        "inventory": _protected_tables(inventory, cycles, company, required={"inventories", "sync_plans"}),
        "jobs": _protected_tables(jobs, cycles, company, required={"exact_local_applications"},
                                  created_during_publication={"retained_publications"}),
        "application_details": _application_details(jobs, cycles),
        "receipts": {cycle: _receipt_records(inventory, cycle) for cycle in cycles},
    }
    for raw, in inventory.execute("SELECT binding FROM publication_receipts"):
        try:
            binding = json.loads(raw)
        except (TypeError, ValueError) as error:
            raise ValueError("retained_operator_receipt_binding_invalid") from error
        if not isinstance(binding, dict) or not isinstance(binding.get("company_id"), str):
            raise ValueError("retained_operator_receipt_binding_invalid")
        if binding["company_id"] == company:
            raise ValueError("retained_operator_prior_company_receipt")
    return digest(evidence)


def _protected_tables(db, cycles, company, *, required, created_during_publication=()):
    evidence = {}
    for name, in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        quoted = '"' + name.replace('"', '""') + '"'
        columns = {row[1] for row in db.execute(f"PRAGMA table_info({quoted})")}
        if "cycle" not in columns:
            continue
        if "company" not in columns:
            raise ValueError("retained_operator_historical_table_unclassified")
        facts = {}
        for cycle in cycles:
            selected = db.execute(
                f"SELECT 1 FROM {quoted} WHERE cycle=? AND company=? LIMIT 1",
                (cycle, company),
            ).fetchone()
            if selected:
                raise ValueError("retained_operator_prior_company_work")
            facts[cycle] = _table_records(db, name, cycle)
        # First use can create the isolated publication ledger. Its rows for
        # this reservation have a private cycle, outside the historical seal.
        if name in created_during_publication and all(not fact["row_count"] for fact in facts.values()):
            continue
        evidence[name] = facts
    if not required <= evidence.keys():
        raise ValueError("retained_operator_historical_table_missing")
    return evidence


def _application_details(db, cycles):
    evidence = {}
    scope = ",".join("?" for _ in cycles)
    for name in ("exact_local_apply_chunks", "exact_local_acknowledgements"):
        rows = db.execute(
            f"SELECT detail.* FROM {name} AS detail "
            "JOIN exact_local_applications AS app ON app.apply_id=detail.apply_id "
            f"WHERE app.cycle IN ({scope})",
            cycles,
        )
        evidence[name] = sorted(digest([_json_value(value) for value in row]) for row in rows)
    return evidence
