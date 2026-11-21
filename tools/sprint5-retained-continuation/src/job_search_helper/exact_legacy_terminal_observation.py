"""Read-only confirmation for one completed, terminal legacy Company plan.

This intentionally does not migrate, replace, advance, acknowledge, publish,
or persist anything.  It is a narrow adapter for a blocked/unsupported
one-operation Companies plan whose compact-visible fields can be proven by an
exact Sheets readback.  A caller that wants a durable terminal disposition
must provide a separate, explicitly reviewed persistence boundary.
"""
from __future__ import annotations

import copy
import json
from typing import Mapping

from .exact_cycle_planner import _digest
from .repository import _equivalent
from .sheet_profile import COMPACT_PROFILE, LOCAL_ONLY_FIELDS, profile_schemas
from .sheets_sync import SheetsSynchronizer, _clean_observation_field


VERSION = "legacy-terminal-observation-v1"
OBSERVED_MATCH = "REMOTE_OBSERVED_MATCH"


def _required(value, label):
    value = str(value or "").strip()
    if not value:
        raise ValueError(f"terminal_observation_{label}_required")
    return value


def _final_identity(operation):
    identity = operation.get("identity")
    if not isinstance(identity, Mapping) or not identity:
        raise ValueError("terminal_observation_identity_invalid")
    final = copy.deepcopy(dict(identity))
    for name in ("on_insert", "values"):
        mapping = operation.get(name, {})
        if not isinstance(mapping, Mapping):
            raise ValueError("terminal_observation_mapping_invalid")
        for header in tuple(final):
            if header in mapping:
                final[header] = copy.deepcopy(mapping[header])
    return final


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def _rows(repository, table, row_id):
    tables = {row[0] for row in repository.db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    if table not in tables:
        return []
    columns = [row[1] for row in repository.db.execute(
        f"PRAGMA table_info({table})")]
    if not {"tab", "row_id"} <= set(columns):
        raise ValueError("terminal_observation_local_schema_invalid")
    return repository.db.execute(
        f"SELECT 1 FROM {table} WHERE tab=? AND row_id=? LIMIT 1",
        ("Companies", row_id)).fetchall()


def _reject_existing_exact_work(inbox, cycle_id, company_id):
    with inbox.lock:
        for table in ("exact_plan_local_state", "exact_remote_plans",
                      "exact_sync_chunks"):
            row = inbox.connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table,)).fetchone()
            if row and inbox.connection.execute(
                    f"SELECT 1 FROM {table} WHERE cycle=? AND company=? LIMIT 1",
                    (cycle_id, company_id)).fetchone():
                raise ValueError("terminal_observation_exact_work_exists")
        rows = inbox.connection.execute(
            "SELECT binding FROM publication_receipts").fetchall()
    for (encoded,) in rows:
        try:
            binding = json.loads(encoded)
        except (TypeError, ValueError) as error:
            raise ValueError("terminal_observation_receipt_invalid") from error
        # Receipts are per Company.  A receipt for another Company that merely
        # shares this historical cycle ID is unrelated evidence and must not
        # block this exact one-Company terminal scope.
        if binding.get("company_id") == company_id:
            raise ValueError("terminal_observation_receipt_exists")


def _operation_scope(repository, operation, company_id):
    if (not isinstance(operation, Mapping)
            or operation.get("tab") != "Companies"
            or _final_identity(operation) != {"Company ID": company_id}):
        raise ValueError("terminal_observation_operation_shape_invalid")
    # Retained v1 updates omitted this optional flag.  Omission means the
    # historic non-insert default; an explicit truthy/non-boolean value is not
    # a safe terminal observation target.
    append_if_missing = operation.get("append_if_missing", False)
    if type(append_if_missing) is not bool or append_if_missing:
        raise ValueError("terminal_observation_operation_shape_invalid")
    for name in ("on_insert", "append_notes"):
        if operation.get(name, {}) != {}:
            raise ValueError("terminal_observation_operation_not_update_only")
    values = operation.get("values")
    expected = operation.get("expected", {})
    if (not isinstance(values, Mapping) or not values
            or not isinstance(expected, Mapping)):
        raise ValueError("terminal_observation_operation_mapping_invalid")
    if repository.get_meta("sheets_profile") != COMPACT_PROFILE:
        raise ValueError("terminal_observation_compact_profile_required")
    publication = profile_schemas(COMPACT_PROFILE)
    headers = set(publication["Companies"])
    local_only = set(LOCAL_ONLY_FIELDS["Companies"])
    if set(values) - headers - local_only:
        raise ValueError("terminal_observation_unknown_or_unpublished_field")
    remote_values = {header: copy.deepcopy(value) for header, value in values.items()
                     if header in headers}
    local_values = {header: copy.deepcopy(value) for header, value in values.items()
                    if header in local_only}
    if not remote_values:
        raise ValueError("terminal_observation_visible_projection_missing")
    # The frozen compact projection must not carry a local-only expected guard.
    if set(expected) - headers:
        raise ValueError("terminal_observation_local_only_expected_guard")
    return remote_values, local_values, {
        "tab": "Companies", "identity": {"Company ID": company_id},
        "values": remote_values, "on_insert": {},
        "append_if_missing": False,
        "expected": copy.deepcopy(dict(expected)), "append_notes": {},
    }


def _local_evidence(repository, company_id, operation, remote_values, local_values):
    matches = repository.matches("Companies", {"Company ID": company_id})
    if len(matches) != 1:
        raise ValueError("terminal_observation_company_missing_or_ambiguous")
    row_id, current = matches[0]
    baseline = repository.baseline("Companies", row_id)
    if not isinstance(baseline, Mapping):
        raise ValueError("terminal_observation_company_baseline_missing")
    dirty = {header for (header,) in repository.db.execute(
        "SELECT header FROM dirty WHERE tab=? AND row_id=?",
        ("Companies", row_id))}
    if set(operation["values"]) & dirty:
        raise ValueError("terminal_observation_dirty_field_present")
    for table, label in (("conflicts", "conflict"),
                         ("manual_choices", "manual_choice"),
                         ("delivery_attempts", "delivery_attempt")):
        if _rows(repository, table, row_id):
            raise ValueError(f"terminal_observation_{label}_present")
    for header, value in operation["values"].items():
        if not _equivalent(header, current.get(header, ""), value):
            raise ValueError("terminal_observation_local_value_changed")
    for header in remote_values:
        if not _clean_observation_field(header, baseline, current, operation):
            raise ValueError("terminal_observation_visible_baseline_unverifiable")
    local_snapshot = []
    for header in sorted(local_values):
        present = header in baseline
        local_snapshot.append({
            "header": header,
            "current_digest": _digest(current.get(header, "")),
            "baseline_value_digest": _digest({
                "present": present,
                "value": copy.deepcopy(baseline[header]) if present else None,
            }),
        })
    return row_id, {"version": 1, "row_id": row_id,
                    "visible_fields": sorted(remote_values),
                    "local_only_fields": sorted(local_values),
                    "local_only_snapshot": local_snapshot,
                    "local_only_snapshot_digest": _digest(local_snapshot)}


def build_terminal_observation_binding(state, inbox, repository, *, cycle_id,
                                       company_id):
    """Return a non-persistent binding for one exact terminal observation."""
    cycle_id = _required(cycle_id, "cycle_id")
    company_id = _required(company_id, "company_id")
    cycle = state.cycle(cycle_id)
    if not isinstance(cycle, Mapping) or cycle.get("id") != cycle_id:
        raise ValueError("terminal_observation_cycle_missing")
    checkpoint = cycle.get("companies", {}).get(company_id)
    if (not isinstance(checkpoint, Mapping)
            or checkpoint.get("stage") not in {"blocked", "unsupported"}):
        raise ValueError("terminal_observation_checkpoint_not_terminal")
    saved = inbox.get(cycle_id, company_id)
    if saved is None or saved[1] is not True or not isinstance(saved[0], Mapping):
        raise ValueError("terminal_observation_inbox_not_blocked")
    payload, _blocked = saved
    planned = inbox.plan(cycle_id, company_id)
    if planned is None:
        raise ValueError("terminal_observation_frozen_plan_missing")
    plan, cursor = planned
    if (not isinstance(plan, Mapping) or set(plan) != {"operations", "final", "requested_url"}
            or not isinstance(plan.get("operations"), list)
            or len(plan["operations"]) != 1 or type(cursor) is not int
            or cursor != 1):
        raise ValueError("terminal_observation_plan_not_completed_one_op")
    if plan.get("requested_url") != payload.get("requested_url"):
        raise ValueError("terminal_observation_plan_payload_mismatch")
    _reject_existing_exact_work(inbox, cycle_id, company_id)
    operation = copy.deepcopy(plan["operations"][0])
    remote_values, local_values, projection = _operation_scope(
        repository, operation, company_id)
    row_id, local = _local_evidence(
        repository, company_id, operation, remote_values, local_values)
    binding = {
        "version": VERSION, "cycle_id": cycle_id, "company_id": company_id,
        "checkpoint_stage": checkpoint["stage"],
        "inventory_payload_digest": _digest(payload),
        "legacy_plan_digest": _digest(plan), "completed_cursor": cursor,
        "publication_profile": COMPACT_PROFILE,
        "publication_schema_digest": _digest({
            "Companies": list(profile_schemas(COMPACT_PROFILE)["Companies"])}),
        "operation_identity_digest": _digest(_final_identity(operation)),
        "remote_projection": projection,
        "remote_projection_digest": _digest([projection]),
        "local_evidence": local,
    }
    binding["binding_digest"] = _digest(binding)
    return binding


def _row_scope(binding):
    projection = binding["remote_projection"]
    local = binding["local_evidence"]
    return [{"tab": "Companies", "row_id": local["row_id"],
             "identity": copy.deepcopy(projection["identity"]),
             "fields": sorted(projection["values"]),
             "append_if_missing": False, "guards": {},
             "expected": copy.deepcopy(projection["expected"])}]


def observe_terminal_plan(state, inbox, repository, remote, *, cycle_id,
                          company_id, binding):
    """Read exact remote compact fields and return a non-persistent receipt.

    The binding is rederived before the remote read.  This function deliberately
    never receives an Inbox write API and never invokes a commit-capable
    SheetsSynchronizer method.
    """
    current = build_terminal_observation_binding(
        state, inbox, repository, cycle_id=cycle_id, company_id=company_id)
    if not isinstance(binding, Mapping) or dict(binding) != current:
        raise ValueError("terminal_observation_binding_changed")
    synchronizer = SheetsSynchronizer(repository, remote)
    exact = synchronizer.plan_exact_scope(
        _row_scope(current), [current["remote_projection"]],
        delivery_mode="observation_only")
    receipt_id = _digest({"kind": VERSION, "binding": current["binding_digest"]})
    intent_id = _digest({"kind": "terminal-observation", "receipt_id": receipt_id})
    readback = synchronizer.readback_exact_scope(
        exact, receipt_id=receipt_id, intent_id=intent_id,
        intent_projection_digest=exact["projection_digest"])
    return {"version": VERSION, "state": OBSERVED_MATCH,
            "binding": copy.deepcopy(current), "receipt_id": receipt_id,
            "intent_id": intent_id, "readback": readback,
            "receipt_digest": _digest({
                "version": VERSION, "state": OBSERVED_MATCH,
                "binding_digest": current["binding_digest"],
                "receipt_id": receipt_id, "intent_id": intent_id,
                "acknowledgement_id": readback["acknowledgement_id"],
            })}
