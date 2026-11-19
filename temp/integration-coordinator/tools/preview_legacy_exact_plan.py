#!/usr/bin/env python3
"""Read-only selected-row preview for one retained legacy exact plan.

This operator tool deliberately has no remote commit method and opens all
three local databases read-only. It is evidence for a later owner decision;
it never seals, migrates, publishes, acknowledges, blocks, or deletes work.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Mapping

from job_search_helper.exact_cycle_sync import (
    _chunks,
    _company_guard,
    _readback,
    _validate_chunkable,
)
from job_search_helper.publication_receipts import record_fingerprints


VERSION = "legacy-selected-row-preview-v1"
ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def _digest(value):
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


class ReadOnlyRemote:
    """Expose only the two narrow read APIs used by exact readback."""

    def __init__(self, remote):
        self._remote = remote
        self.schemas = remote.schemas

    def read_columns(self, tab, headers):
        return self._remote.read_columns(tab, headers)

    def read_rows(self, tab, row_numbers):
        return self._remote.read_rows(tab, row_numbers)


def preview_legacy_plan(*, cycle_id, company_id, cycle, payload, blocked,
                        plan, cursor, local, remote):
    """Preview exact remote equality without offering a mutation API."""
    if not isinstance(cycle_id, str) or not ID.fullmatch(cycle_id):
        raise ValueError("exact_cycle_id_invalid")
    if not isinstance(company_id, str) or not ID.fullmatch(company_id):
        raise ValueError("company_id_invalid")
    if (not isinstance(cycle, Mapping) or cycle.get("id") != cycle_id
            or cycle.get("status") in {"Complete", "Complete with exceptions"}):
        raise ValueError("exact_cycle_not_active")
    checkpoint = cycle.get("companies", {}).get(company_id)
    if (not isinstance(checkpoint, Mapping)
            or checkpoint.get("stage") != "inventory"
            or checkpoint.get("durable_inventory") is not True
            or checkpoint.get("locally_processed") is not True):
        raise ValueError("company_checkpoint_not_recoverable")
    if blocked is not False:
        raise ValueError("durable_inventory_blocked")
    if (not isinstance(payload, Mapping)
            or not isinstance(payload.get("jobs"), list)
            or not str(payload.get("requested_url") or "").strip()):
        raise ValueError("inventory_payload_invalid")
    if (not isinstance(plan, Mapping) or plan.get("exact_plan_version") == 2
            or set(plan) != {"operations", "final", "requested_url"}
            or not isinstance(plan.get("operations"), list)
            or not plan["operations"]
            or not isinstance(plan.get("final"), Mapping)
            or plan.get("requested_url") != payload.get("requested_url")):
        raise ValueError("legacy_plan_shape_invalid")
    operations = plan["operations"]
    if type(cursor) is not int or cursor != len(operations):
        raise ValueError("legacy_plan_local_cursor_not_complete")
    _validate_chunkable(operations)
    expected_full = record_fingerprints(operations)

    bounded_remote = ReadOnlyRemote(remote)
    controls = _company_guard(
        local, bounded_remote, company_id, payload["requested_url"])

    chunks = []
    all_match = True
    possible = 0
    for start, chunk in _chunks(operations, 0):
        expected = record_fingerprints(chunk)
        observed = _readback(bounded_remote, chunk)
        match = observed == expected
        all_match = all_match and match
        if not match:
            possible += len(chunk)
        chunks.append({
            "start": start,
            "count": len(chunk),
            "expected_records_digest": _digest(expected),
            "observed_records_digest": _digest(observed),
            "exact_match": match,
        })

    return {
        "version": VERSION,
        "read_only": True,
        "cycle_id": cycle_id,
        "company_id": company_id,
        "checkpoint_stage": checkpoint["stage"],
        "inventory_digest": _digest(payload),
        "plan_digest": _digest(plan),
        "cursor": cursor,
        "operation_count": len(operations),
        "expected_records_digest": _digest(expected_full),
        "current_controls_digest": _digest(controls),
        "chunks": chunks,
        "all_remote_rows_match": all_match,
        "possible_commit_operation_upper_bound": possible,
        "mutation_performed": False,
        "decision": ("REMOTE_MATCHES_LEGACY_PLAN"
                     if all_match else "REMOTE_DIFFERS_FROM_LEGACY_PLAN"),
    }


def _read_json_row(connection, query, parameters, label):
    row = connection.execute(query, parameters).fetchone()
    if row is None:
        raise ValueError(label + "_missing")
    try:
        return json.loads(row[0]), *row[1:]
    except (TypeError, ValueError) as exc:
        raise ValueError(label + "_invalid") from exc


def load_snapshot(state_database, inventory_database, cycle_id, company_id):
    state_uri = Path(state_database).resolve().as_uri() + "?mode=ro"
    inbox_uri = Path(inventory_database).resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(state_uri, uri=True) as state_db, \
            sqlite3.connect(inbox_uri, uri=True) as inbox_db:
        cycle, = _read_json_row(
            state_db, "SELECT data FROM cycles WHERE id=?", (cycle_id,), "cycle")
        payload, blocked = _read_json_row(
            inbox_db,
            "SELECT payload,blocked FROM inventories WHERE cycle=? AND company=?",
            (cycle_id, company_id), "inventory")
        plan, cursor = _read_json_row(
            inbox_db,
            "SELECT payload,cursor FROM sync_plans WHERE cycle=? AND company=?",
            (cycle_id, company_id), "plan")
    return cycle, payload, bool(blocked), plan, cursor


@contextmanager
def existing_exclusive_lock(path):
    """Share the writer's exclusion boundary without creating a lock file."""
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("writer_lock_busy") from exc
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--cycle-id", required=True)
    parser.add_argument("--company-id", required=True)
    args = parser.parse_args(argv)

    from job_search_helper.cli import (
        get_remote_repository,
        job_database_path,
        scraper_lock_name,
        state_path,
    )
    from job_search_helper.inbox import InventoryInbox
    from job_search_helper.runner import _load_environment
    from job_search_helper.sheet_profile import profile_schemas
    from job_search_helper.sqlite_repository import SQLiteRepository

    _load_environment()
    state_database = state_path()
    inventory_database = state_database.parent / "inventories.sqlite3"
    lock_path = state_database.parent / scraper_lock_name()
    if not lock_path.is_file():
        raise RuntimeError("existing_writer_lock_file_required")

    with existing_exclusive_lock(lock_path):
        cycle, payload, blocked, plan, cursor = load_snapshot(
            state_database, inventory_database, args.cycle_id, args.company_id)
        destination = InventoryInbox.destination_id(inventory_database)
        local = SQLiteRepository(job_database_path(), destination, readonly=True)
        try:
            schemas = profile_schemas(local.get_meta("sheets_profile"))
            remote = get_remote_repository(
                write=False, interactive=False, min_request_interval=1.1,
                schemas=schemas, evidence_archives=False)
            report = preview_legacy_plan(
                cycle_id=args.cycle_id, company_id=args.company_id,
                cycle=cycle, payload=payload, blocked=blocked, plan=plan,
                cursor=cursor, local=local, remote=remote)
        finally:
            local.close()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
