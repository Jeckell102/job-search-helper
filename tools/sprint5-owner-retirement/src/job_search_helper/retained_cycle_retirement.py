"""Read-only proof for intentionally retiring one saved compact-workbook cycle."""
from __future__ import annotations

from contextlib import ExitStack, closing
import hashlib
import json
from pathlib import Path
import sqlite3
import stat

from .sheet_profile import COMPACT_PROFILE


VERSION = "owner-retired-cycle-v1"
_STORES = ("state.db", "jobs.sqlite3", "inventories.sqlite3")
_ACTIVE_INBOX_JOURNALS = (
    "exact_sync_chunks", "exact_plan_local_state", "exact_remote_plans",
    "exact_legacy_plan_migrations", "exact_legacy_delivery_evidence",
    "exact_selected_legacy_recoveries", "exact_control_before_prefix_recoveries",
)


def _digest(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()



def _checkpointed_inputs(*databases):
    facts = {}
    for database in databases:
        for suffix in ("", "-wal", "-journal"):
            file = database.with_name(database.name + suffix)
            try:
                info = file.lstat()
            except FileNotFoundError:
                if not suffix:
                    raise
                facts[file] = None
                continue
            if not stat.S_ISREG(info.st_mode) or (suffix and info.st_size):
                raise ValueError("Retirement verification requires checkpointed databases.")
            facts[file] = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    return facts


def _read_scoped(root, cycle_id):
    paths = tuple(root / name for name in _STORES)
    before = _checkpointed_inputs(*paths)
    with ExitStack() as stack:
        state, jobs, inbox = [
            stack.enter_context(closing(sqlite3.connect(
                path.as_uri() + "?mode=ro&immutable=1", uri=True,
            ))) for path in paths
        ]
        for db in (state, jobs, inbox):
            db.execute("PRAGMA query_only=ON")
        scoped = _original_rows(state, jobs, inbox, cycle_id, require_clean=True)
    if _checkpointed_inputs(*paths) != before:
        raise ValueError("Retirement inputs changed during readback.")
    return scoped


def _original_rows(state, jobs, inbox, cycle_id, *, require_clean):
    profile = jobs.execute("SELECT value FROM meta WHERE key='sheets_profile'").fetchone()
    destination = inbox.execute("SELECT id FROM destination").fetchall()
    local_destination = jobs.execute("SELECT value FROM meta WHERE key='spreadsheet_id'").fetchone()
    if profile != (COMPACT_PROFILE,) or len(destination) != 1 or destination[0] != local_destination:
        raise ValueError("Retirement requires the same compact local workbook in both stores.")
    saved = state.execute("SELECT data FROM cycles WHERE id=?", (cycle_id,)).fetchone()
    mirrors = jobs.execute(
        "SELECT row_id,data,policies FROM records WHERE tab='Scan Cycles' "
        "AND json_extract(data,'$.\"Cycle ID\"')=?", (cycle_id,),
    ).fetchall()
    if saved is None or len(mirrors) != 1:
        raise ValueError("Retirement requires one saved cycle and one exact mirror.")
    cycle = json.loads(saved[0])
    mirror = json.loads(mirrors[0][1])
    notes = json.loads(mirror["Notes"])
    if (cycle.get("id") != cycle_id or cycle.get("status") != "In Progress"
            or mirror.get("Cycle Status") != "In Progress"
            or not isinstance(cycle.get("companies"), dict)
            or sorted(cycle["companies"]) != sorted(notes.get("company_ids", []))
            or any(cycle.get(key) is not None for key in (
                "company_event", "repair_retry", "temporary_retry", "retained_work_exception",
                "selected_retry_reservation_sha256", "runtime_binding",
            ))):
        raise ValueError("The old cycle and its local mirror no longer agree.")
    inventories = inbox.execute(
        "SELECT company,payload,blocked FROM inventories WHERE cycle=? ORDER BY company", (cycle_id,),
    ).fetchall()
    plans = inbox.execute(
        "SELECT company,payload,cursor FROM sync_plans WHERE cycle=? ORDER BY company", (cycle_id,),
    ).fetchall()
    if not inventories or not {row[0] for row in plans} <= {row[0] for row in inventories} <= set(cycle["companies"]):
        raise ValueError("The selected cycle's saved work does not match its membership.")
    if require_clean and jobs.execute("SELECT 1 FROM dirty LIMIT 1").fetchone():
        raise ValueError("Local pending changes must settle before this retirement.")
    if require_clean and jobs.execute("SELECT 1 FROM delivery_attempts LIMIT 1").fetchone():
        raise ValueError("An unresolved delivery attempt requires reconciliation before retirement.")
    for table in _ACTIVE_INBOX_JOURNALS:
        if inbox.execute(f"SELECT 1 FROM {table} WHERE cycle=? LIMIT 1", (cycle_id,)).fetchone():
            raise ValueError(f"An unsettled Inbox journal requires separate reconciliation: {table}.")
    receipts = inbox.execute(
        "SELECT receipt_id,binding,records,schedule,state,acknowledgement_id,created_at,updated_at "
        "FROM publication_receipts "
        "WHERE json_extract(binding,'$.cycle_id')=? OR json_extract(binding,'$.request_id')=? "
        "ORDER BY receipt_id", (cycle_id, cycle_id),
    ).fetchall()
    verified_companies = {json.loads(receipt[1])["company_id"] for receipt in receipts
                          if receipt[4] == "SYNC_CONFIRMED" and receipt[5]}
    applications = jobs.execute(
        "SELECT * FROM exact_local_applications WHERE cycle=? ORDER BY company", (cycle_id,),
    ).fetchall()
    if (len(verified_companies) != len(receipts)
            or any(row[-1] != "VERIFIED" or row[2] not in verified_companies for row in applications)
            or verified_companies.intersection(row[0] for row in inventories)):
        raise ValueError("Previously committed work has an unresolved or overlapping receipt.")
    chunks = jobs.execute(
        "SELECT chunks.* FROM exact_local_apply_chunks chunks "
        "JOIN exact_local_applications applications USING(apply_id) "
        "WHERE applications.cycle=? ORDER BY chunks.apply_id,chunks.start_cursor", (cycle_id,),
    ).fetchall()
    if any(row[-1] != "VERIFIED" for row in chunks):
        raise ValueError("A saved exact local application is not verified.")
    return {
        "destination": destination[0][0], "state": saved[0], "mirror": mirrors[0],
        "inventories": inventories, "plans": plans,
        "receipts": receipts, "local_applications": applications, "local_chunks": chunks,
    }


def verify_retirement_archive(live_root, archive_root, cycle_id):
    """Match the exact raw saved work against an existing private verified backup."""
    roots = [Path(root).resolve(strict=True) for root in (live_root, archive_root)]
    if roots[0] == roots[1] or any(
        (roots[0] / name).samefile(roots[1] / name) for name in _STORES
    ):
        raise ValueError("Retirement archive must be a separate existing copy.")
    if not isinstance(cycle_id, str) or not cycle_id.strip() or cycle_id != cycle_id.strip():
        raise ValueError("Specify exactly one cycle to retire.")
    current, archived = [_read_scoped(root, cycle_id) for root in roots]
    if current != archived:
        changed = ", ".join(key for key in current if current[key] != archived[key])
        raise ValueError("Retirement archive differs from current saved scope: " + changed)
    return {
        "version": VERSION, "cycle_id": cycle_id, "status": "ARCHIVE_VERIFIED",
        "archive_scope_sha256": _digest(archived),
        "original_state_sha256": _digest(archived["state"]),
        "original_mirror_sha256": _digest(archived["mirror"]),
        "saved_inventory_count": len(archived["inventories"]),
        "saved_plan_count": len(archived["plans"]),
        "blocked_inventory_count": sum(bool(row[2]) for row in archived["inventories"]),
        "historical_confirmed_receipt_count": len(archived["receipts"]),
        "published": False, "retired": False,
    }
