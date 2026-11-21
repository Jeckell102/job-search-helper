"""Retain exact-v2 publication proof for the enrolled ordinary verification."""
from hashlib import sha256
import json
from pathlib import Path

from . import ordinary_verification_pending as pending, publication_receipts
from .runtime_mapping_facts import _fd_identities, _physical_identity, _store_identity


_TABLE = "ordinary_verification_publications"
_WORK_TABLES = ("inventories", "sync_plans", "exact_plan_local_state",
                "exact_remote_plans", "exact_sync_chunks")
_SCHEMA = "ordinary-rippling-verification-publication-v1"
_DIGESTS = {
    "plan_digest", "local_operations_digest", "local_records_digest",
    "planned_projection_digest", "projection_digest", "remote_records_digest",
    "receipt_id", "acknowledgement_id", "selected_fields_digest", "schedule_digest",
}


def _encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _decode(raw):
    value = json.loads(raw)
    if _encode(value) != raw:
        raise ValueError("Ordinary verification publication record is noncanonical.")
    return value


def _table_exists(connection):
    return connection.execute(
        "SELECT 1 FROM main.sqlite_master WHERE type='table' AND name=?", (_TABLE,),
    ).fetchone() is not None


def _row(connection, cycle_id, company_id):
    if not _table_exists(connection):
        return None
    row = connection.execute(
        "SELECT company,request_id,binding,proof_sha256,proof FROM main.ordinary_verification_publications "
        "WHERE cycle=?", (cycle_id,),
    ).fetchone()
    if row is not None and row[0] != company_id:
        raise ValueError("Ordinary verification publication has another Company owner.")
    return row


def has_bound_publication(inbox, cycle_id, company_id):
    from .inbox import InventoryInbox

    return isinstance(inbox, InventoryInbox) and _row(inbox.connection, cycle_id, company_id) is not None


def owns_receipt_scope(inbox, binding):
    """Keep legacy reconciliation fenced after an enrolled exact plan is removed."""
    return _receipt_owner(inbox, binding) is not None


def _receipt_owner(inbox, binding):
    connection = inbox.connection
    if not _table_exists(connection):
        return None
    request_id = binding.get("request_id")
    rows = connection.execute(
        "SELECT cycle,company FROM main.ordinary_verification_publications "
        "WHERE company=? AND (cycle=? OR request_id=?)",
        (binding.get("company_id"), request_id, request_id),
    ).fetchall()
    if len(rows) > 1:
        raise ValueError("Ordinary verification receipt has competing dispatch owners.")
    return rows[0] if rows else None


def _freeze_binding(stores, marker):
    owner = marker["owner"]
    return {**owner, "dispatch_sha256": marker["dispatch_sha256"], "inventory_sha256": marker["inventory_sha256"],
            "prepared_sha256": pending.digest(marker),
            "workbook_sha256": sha256(stores.jobs.spreadsheet_id.encode("utf-8")).hexdigest()}


def _live_binding(stores, cycle_id, company_id):
    cycle, stored = pending.read_prepared_inventory(stores, cycle_id, company_id)
    if stored[1]:
        raise ValueError("Ordinary verification publication needs its unblocked prepared inventory.")
    return _freeze_binding(stores, pending.read_marker(cycle, company_id))


def _binding_matches(row, binding):
    return row is not None and row[1:3] == (binding["request_id"], _encode(binding))


def _require_owned_leases(stores):
    directory = Path(stores.state.path).absolute().parent
    descriptors = _fd_identities()
    for name in ("scraper.lock", "writer.lock"):
        path = directory / name
        try:
            identity = _physical_identity(path)
        except (OSError, ValueError):
            raise ValueError("Ordinary verification publication requires its held scraper and writer leases.") from None
        for descriptor, opened_identity in descriptors.items():
            if opened_identity != identity:
                continue
            try:
                if Path(f"/proc/self/fd/{descriptor}").readlink() != path:
                    continue
                info = Path(f"/proc/self/fdinfo/{descriptor}").read_text().splitlines()
            except OSError:
                continue
            locks = (line.split() for line in info if line.startswith("lock:"))
            if any(fields[2:5] == ["FLOCK", "ADVISORY", "WRITE"] and fields[-2:] == ["0", "EOF"]
                   for fields in locks):
                break
        else:
            raise ValueError("Ordinary verification publication requires its held scraper and writer leases.")


def bind_publication(stores, cycle_id, company_id):
    """Bind the durable prepared inventory before the enrolled exact plan freezes."""
    inbox = stores.inbox
    with inbox.lock:
        _require_owned_leases(stores)
        binding = _live_binding(stores, cycle_id, company_id)
        with inbox.connection:
            inbox.connection.execute("BEGIN IMMEDIATE")
            row = _row(inbox.connection, cycle_id, company_id)
            if row is not None:
                if not _binding_matches(row, binding) or row[3:] != (None, None):
                    raise ValueError("Ordinary verification publication binding already owns other evidence.")
                return binding
            inventory = inbox.get(cycle_id, company_id)
            if (inbox.plan(cycle_id, company_id) is not None or inventory is None or inventory[1]
                    or pending.digest(inventory[0]) != binding["inventory_sha256"]):
                raise ValueError("Bind ordinary verification publication before freezing any plan.")
            inbox.connection.execute(
                "CREATE TABLE IF NOT EXISTS main.ordinary_verification_publications ("
                "cycle TEXT PRIMARY KEY, company TEXT NOT NULL, request_id TEXT NOT NULL UNIQUE, "
                "binding TEXT NOT NULL, proof_sha256 TEXT, proof TEXT, "
                "CHECK ((proof_sha256 IS NULL) = (proof IS NULL)))",
            )
            inbox.connection.execute(
                "INSERT INTO main.ordinary_verification_publications VALUES (?,?,?,?,NULL,NULL)",
                (cycle_id, company_id, binding["request_id"], _encode(binding)),
            )
        return binding


def _require_exact_plan(plan, binding):
    from .exact_cycle_planner import _exact_plan_digest

    if (not isinstance(plan, dict) or plan.get("exact_plan_version") != 2
            or plan.get("cycle_id") != binding["cycle_id"] or plan.get("company_id") != binding["company_id"]
            or plan.get("inventory_payload_digest") != binding["inventory_sha256"]
            or plan.get("plan_digest") != _exact_plan_digest(plan)
            or any(key in plan for key in ("ordinary_company_event", "selected_retry_receipt_binding",
                                           "retained_membership_only", pending.MARKER))
            or any(not isinstance(plan.get(key), dict) or pending.MARKER in plan[key]
                   for key in ("final", "local_finalization", "final_projection"))):
        raise ValueError("Ordinary verification publication requires its exact private-field-free v2 plan.")


def require_bound_plan(stores, cycle_id, company_id, plan):
    binding = _live_binding(stores, cycle_id, company_id)
    row = _row(stores.inbox.connection, cycle_id, company_id)
    if not _binding_matches(row, binding) or row[3:] != (None, None):
        raise ValueError("Ordinary verification publication has no exact pending binding.")
    saved = stores.inbox.plan(cycle_id, company_id)
    if saved is None or saved[0] != plan:
        raise ValueError("Ordinary verification publication plan changed before finalization.")
    _require_exact_plan(plan, binding)
    return binding


def require_plan_freeze_authority(inbox, local, cycle_id, company_id, *, stores=None, state=None):
    """Prove enrolled ownership before freezing a generic-looking v2 plan."""
    bound = has_bound_publication(inbox, cycle_id, company_id)
    cycle = state.cycle(cycle_id) if state is not None else None
    item = (cycle.get("companies") or {}).get(company_id, {}) if isinstance(cycle, dict) else {}
    marked = isinstance(item, dict) and pending.MARKER in item
    if not bound and not marked and stores is None:
        return None
    if (not bound or not isinstance(stores, pending.VerificationStores) or stores.inbox is not inbox
            or (state is not None and (not marked or stores.state is not state))):
        raise ValueError("Enrolled ordinary verification publication requires its original dispatch authority.")
    _require_owned_leases(stores)
    from .sqlite_repository import SQLiteRepository

    if (not isinstance(local, SQLiteRepository) or local.readonly
            or local.spreadsheet_id != stores.jobs.spreadsheet_id):
        raise ValueError("Ordinary verification publication requires the descriptor-proven writable Jobs store.")
    try:
        original_jobs = _store_identity(stores.jobs, stores.jobs.db)
        writer_jobs = _store_identity(local, local.db)
    except (OSError, ValueError) as exc:
        raise ValueError("Ordinary verification publication requires the descriptor-proven writable Jobs store.") from exc
    if writer_jobs != original_jobs:
        raise ValueError("Ordinary verification publication requires the descriptor-proven writable Jobs store.")
    binding = _live_binding(stores, cycle_id, company_id)
    row = _row(inbox.connection, cycle_id, company_id)
    if not _binding_matches(row, binding) or row[3:] != (None, None):
        raise ValueError("Ordinary verification publication has no exact pending binding.")
    return binding


def require_write_authority(inbox, local, cycle_id, company_id, plan_digest, *,
                            stores=None, state=None, payload=None):
    """Validate exact enrolled authority at a selected write boundary."""
    binding = require_plan_freeze_authority(
        inbox, local, cycle_id, company_id, stores=stores, state=state)
    if binding is None:
        return None
    saved = inbox.plan(cycle_id, company_id)
    plan = saved[0] if saved is not None else None
    _require_exact_plan(plan, binding)
    if (plan["plan_digest"] != plan_digest
            or (payload is not None and pending.digest(payload) != binding["inventory_sha256"])):
        raise ValueError("Ordinary verification publication write does not match its exact plan and inventory.")
    return plan


def require_receipt_authority(inbox, receipt, stores):
    owner = _receipt_owner(inbox, receipt["binding"])
    if owner is None and stores is None:
        return
    if owner is None or not isinstance(stores, pending.VerificationStores):
        raise ValueError("Enrolled ordinary verification receipt requires its original dispatch authority.")
    from .exact_cycle_receipt import derive_receipt
    from .exact_cycle_sync import _fallback_receipt

    cycle_id, company_id = owner
    saved = inbox.plan(cycle_id, company_id)
    plan = require_write_authority(
        inbox, stores.jobs, cycle_id, company_id, saved[0].get("plan_digest") if saved else None, stores=stores)
    cycle = stores.state.cycle(cycle_id)
    payload = inbox.get(cycle_id, company_id)[0]
    expected = (derive_receipt(cycle, company_id, payload, plan, receipt["timestamp"]),
                _fallback_receipt(cycle, company_id, plan, payload))
    fields = ("binding", "records", "schedule")
    if not any(all(item[key] == receipt[key] for key in fields) for item in expected):
        raise ValueError("Enrolled ordinary verification receipt differs from its exact plan.")


def _validate_proof(inbox, local, evidence, binding):
    from .exact_cycle_sync import _remote_intent_id

    if (set(evidence) != _DIGESTS | {"schema", "owner", "receipt_binding", "apply_id", "intent_id", "final_stage"}
            or evidence["schema"] != _SCHEMA or evidence["owner"] != binding
            or evidence["final_stage"] not in {"complete", "partial"}
            or any(not pending._is_digest(evidence[key]) for key in _DIGESTS)):
        raise ValueError("Ordinary verification publication proof is malformed.")
    cycle_id, company_id = binding["cycle_id"], binding["company_id"]
    receipt_binding = evidence["receipt_binding"]
    # The exact-v2 fallback receipt owns the cycle ID and may use an
    # inventory-based source. The marker separately owns the real source.
    if (not isinstance(receipt_binding, dict) or set(receipt_binding) != {
        "request_id", "company_id", "source_revision", "release_id"}
            or receipt_binding["request_id"] != cycle_id or receipt_binding["company_id"] != company_id
            or receipt_binding["source_revision"] not in {
                binding["source_revision"], "frozen-inventory:" + binding["inventory_sha256"]}
            or evidence["intent_id"] != _remote_intent_id(
                cycle_id, company_id, evidence["plan_digest"], evidence["projection_digest"])):
        raise ValueError("Ordinary verification receipt identity differs from the enrolled source and inventory.")
    receipt = publication_receipts.receipt(inbox.connection, receipt_binding)
    if (receipt is None or receipt["binding"] != receipt_binding or receipt["receipt_id"] != evidence["receipt_id"]
            or receipt["state"] != publication_receipts.SYNC_CONFIRMED
            or receipt["acknowledgement_id"] != evidence["acknowledgement_id"]
            or pending.digest(receipt["records"]) != evidence["remote_records_digest"]
            or pending.digest(receipt["schedule"]) != evidence["schedule_digest"]):
        raise ValueError("Ordinary verification publication lacks its confirmed receipt.")
    local_state = local.db.execute(
        "SELECT inventory_payload_digest,local_operations_digest,remote_projection_digest "
        "FROM main.exact_local_applications WHERE apply_id=? AND cycle=? AND company=?",
        (evidence["apply_id"], cycle_id, company_id),
    ).fetchone()
    if local_state != (binding["inventory_sha256"], evidence["local_operations_digest"],
                       evidence["planned_projection_digest"]):
        raise ValueError("Ordinary verification publication lacks its exact Jobs application.")
    ack = inbox._require_exact_local_acknowledgement(
        local, cycle_id, company_id, evidence["plan_digest"], evidence["receipt_id"],
        evidence["acknowledgement_id"], expected_apply_id=evidence["apply_id"],
    )
    if ack["selected_fields_digest"] != evidence["selected_fields_digest"]:
        raise ValueError("Ordinary verification publication lacks its exact Jobs selected-fields acknowledgement.")


def archive_before_cleanup(stores, cycle_id, company_id, binding):
    """Freeze terminal proof inside the same Inbox transaction as cleanup."""
    from .exact_cycle_sync import _checkpoint_matches_final, _fallback_receipt

    inbox, local = stores.inbox, stores.jobs
    db = inbox.connection
    if not db.in_transaction:
        raise ValueError("Ordinary verification publication archive requires the Inbox cleanup transaction.")
    _require_owned_leases(stores)
    cycle = stores.state.cycle(cycle_id)
    marker = pending.read_marker(cycle, company_id)
    saved = inbox.plan(cycle_id, company_id)
    inventory = inbox.get(cycle_id, company_id)
    row = _row(db, cycle_id, company_id)
    if (marker is None or marker["state"] != "PREPARED" or _freeze_binding(stores, marker) != binding
            or not _binding_matches(row, binding) or row[3:] != (None, None)
            or saved is None or inventory is None or inventory[1]
            or pending.digest(inventory[0]) != binding["inventory_sha256"]):
        raise ValueError("Ordinary verification publication evidence changed before cleanup.")
    plan, cursor = saved
    _require_exact_plan(plan, binding)
    if not _checkpoint_matches_final(cycle["companies"][company_id], plan):
        raise ValueError("Ordinary verification State is not finalized for publication cleanup.")
    local_state = inbox.exact_local_state(cycle_id, company_id)
    remote = inbox.exact_remote_state(cycle_id, company_id)
    if (cursor != len(plan["local_operations"])
            or local_state is None or local_state["state"] != "LOCAL_VERIFIED"
            or local_state["plan_digest"] != plan["plan_digest"]
            or local_state["local_operations_digest"] != plan["local_operations_digest"]
            or local_state["local_records_digest"] != plan["local_expected_records_digest"]
            or local_state["remote_projection_digest"] != plan["remote_projection_digest"]
            or remote is None or remote["state"] != "LOCAL_ACKNOWLEDGED"
            or remote["local_plan_digest"] != plan["plan_digest"] or remote["delivery_mode"] != "write_once"
            or not isinstance(remote["projection"], list) or not remote["projection"]
            or remote["remote_cursor"] != len(remote["projection"])
            or remote["projection_digest"] != pending.digest(remote["projection"])):
        raise ValueError("Ordinary verification publication lacks terminal exact plan and application evidence.")
    expected = _fallback_receipt(cycle, company_id, plan, inventory[0])
    acknowledgement = inbox._require_exact_local_acknowledgement(
        local, cycle_id, company_id, plan["plan_digest"], remote["receipt_id"], remote["acknowledgement_id"],
        expected_apply_id=local_state["local_apply_id"],
    )
    evidence = {
        "schema": _SCHEMA, "owner": binding, "receipt_binding": expected["binding"],
        "plan_digest": plan["plan_digest"], "local_operations_digest": plan["local_operations_digest"],
        "local_records_digest": local_state["local_records_digest"], "apply_id": acknowledgement["apply_id"],
        "planned_projection_digest": plan["remote_projection_digest"], "projection_digest": remote["projection_digest"],
        "remote_records_digest": pending.digest(expected["records"]), "schedule_digest": pending.digest(expected["schedule"]),
        "receipt_id": remote["receipt_id"], "acknowledgement_id": remote["acknowledgement_id"],
        "intent_id": remote["intent_id"], "selected_fields_digest": acknowledgement["selected_fields_digest"],
        "final_stage": plan["final"]["stage"],
    }
    _validate_proof(inbox, local, evidence, binding)
    count = db.execute(
        "UPDATE main.ordinary_verification_publications SET proof_sha256=?,proof=? "
        "WHERE cycle=? AND company=? AND binding=? AND proof IS NULL AND proof_sha256 IS NULL",
        (pending.digest(evidence), _encode(evidence), cycle_id, company_id, _encode(binding)),
    ).rowcount
    if count != 1:
        raise ValueError("Ordinary verification publication proof changed before cleanup.")


def read_publication_proof(stores, cycle_id, company_id):
    """Read the exact retained proof after cleanup without contacting Sheets."""
    inbox = stores.inbox
    with inbox.lock:
        cycle = stores.state.cycle(cycle_id)
        marker = pending.read_marker(cycle, company_id)
        if marker is None or marker["state"] != "PREPARED":
            raise ValueError("Ordinary verification publication requires its prepared marker.")
        pending._check_stores(stores, marker["owner"])
        binding = _freeze_binding(stores, marker)
        row = _row(inbox.connection, cycle_id, company_id)
        if row is None:
            return None
        if not _binding_matches(row, binding):
            raise ValueError("Ordinary verification publication belongs to another dispatch.")
        if row[3:] == (None, None):
            return None
        evidence = _decode(row[4])
        if not isinstance(evidence, dict) or pending.digest(evidence) != row[3]:
            raise ValueError("Ordinary verification publication proof digest differs.")
        if any(inbox.connection.execute(
            f"SELECT 1 FROM main.{table} WHERE cycle=? AND company=?", (cycle_id, company_id),
        ).fetchone() is not None for table in _WORK_TABLES):
            raise ValueError("Ordinary verification publication cleanup is incomplete.")
        if cycle["companies"][company_id]["stage"] != evidence.get("final_stage"):
            raise ValueError("Ordinary verification final State differs from the publication proof.")
        _validate_proof(inbox, stores.jobs, evidence, binding)
        refreshed = stores.state.cycle(cycle_id)
        if (pending.read_marker(refreshed, company_id) != marker
                or refreshed["companies"][company_id]["stage"] != evidence["final_stage"]
                or _row(inbox.connection, cycle_id, company_id) != row):
            raise ValueError("Ordinary verification publication proof changed during readback.")
        pending._check_stores(stores, marker["owner"])
        return evidence
