"""Immutable, offline adapter check for the five retained terminal plans."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import stat
import sys
import threading


CYCLE = "CYC-B639C6D864EC"
COMPANIES = ("COMP-0002", "COMP-0008", "COMP-0016", "COMP-0040", "COMP-0045")


def snapshot(paths):
    result = {}
    for path in paths:
        for suffix in ("", "-wal", "-journal"):
            item = path.with_name(path.name + suffix)
            try:
                facts = item.lstat()
            except FileNotFoundError:
                if not suffix:
                    raise
                result[str(item)] = None
                continue
            if not stat.S_ISREG(facts.st_mode) or (suffix and facts.st_size):
                raise RuntimeError("busy_or_nonregular_store")
            result[str(item)] = (facts.st_dev, facts.st_ino, facts.st_mode,
                                 facts.st_size, facts.st_mtime_ns, facts.st_ctime_ns)
    return result


def immutable(path):
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
    db.execute("PRAGMA query_only=ON")
    return db


class FrozenState:
    def __init__(self, cycle):
        self._cycle = cycle
    def cycle(self, cycle_id):
        return self._cycle if cycle_id == CYCLE else None


class FrozenInbox:
    def __init__(self, connection):
        self.connection, self.lock = connection, threading.RLock()
    def get(self, cycle, company):
        row = self.connection.execute(
            "SELECT payload,blocked FROM inventories WHERE cycle=? AND company=?",
            (cycle, company)).fetchone()
        return (json.loads(row[0]), bool(row[1])) if row else None
    def plan(self, cycle, company):
        row = self.connection.execute(
            "SELECT payload,cursor FROM sync_plans WHERE cycle=? AND company=?",
            (cycle, company)).fetchone()
        return (json.loads(row[0]), row[1]) if row else None


class OfflineRemote:
    """Only the two read methods used by readback_exact_scope are present."""
    def __init__(self, spreadsheet_id, row):
        self.spreadsheet_id, self.row = spreadsheet_id, dict(row)
        self.reads = 0
    def read_columns(self, tab, headers):
        if tab != "Companies":
            raise AssertionError("unexpected_tab")
        self.reads += 1
        return [(2, {header: self.row.get(header, "") for header in headers})]
    def read_row(self, tab, row_id):
        if tab != "Companies" or row_id != 2:
            raise AssertionError("unexpected_row")
        self.reads += 1
        return dict(self.row)
    def commit(self, _operations):
        raise AssertionError("remote_commit_forbidden")


def main():
    root = Path(sys.argv[1]).resolve(strict=True)
    paths = [root / name for name in ("state.db", "jobs.sqlite3", "inventories.sqlite3")]
    before = snapshot(paths)
    # Imports follow the candidate source first.  No installed production
    # module is altered or imported as an application entry point.
    from job_search_helper.exact_legacy_terminal_observation import (
        build_terminal_observation_binding, observe_terminal_plan,
    )
    from job_search_helper.sheet_profile import COMPACT_PROFILE, profile_schemas
    from job_search_helper.sqlite_repository import SQLiteRepository

    state_db, jobs_db, inbox_db = (immutable(path) for path in paths)
    try:
        cycle_row = state_db.execute("SELECT data FROM cycles WHERE id=?", (CYCLE,)).fetchone()
        if cycle_row is None:
            raise RuntimeError("cycle_missing")
        state = FrozenState(json.loads(cycle_row[0]))
        inbox = FrozenInbox(inbox_db)
        destination = inbox_db.execute("SELECT id FROM destination").fetchone()[0]
        local = SQLiteRepository(paths[1], destination, readonly=True, immutable=True)
        try:
            results = []
            schemas = profile_schemas(COMPACT_PROFILE)
            for company in COMPANIES:
                binding = build_terminal_observation_binding(
                    state, inbox, local, cycle_id=CYCLE, company_id=company)
                projection = binding["remote_projection"]
                # A disposable remote starts with only the compact fields
                # frozen into the original plan.  This proves readback routing,
                # not actual Sheets state.
                remote = OfflineRemote(destination, projection["values"] | projection["identity"])
                receipt = observe_terminal_plan(
                    state, inbox, local, remote, cycle_id=CYCLE,
                    company_id=company, binding=binding)
                results.append({
                    "company_id": company,
                    "checkpoint_stage": binding["checkpoint_stage"],
                    "remote_visible_field_count": len(projection["values"]),
                    "local_only_field_count": len(binding["local_evidence"]["local_only_fields"]),
                    "local_only_baseline_digest": binding["local_evidence"]["local_only_snapshot_digest"],
                    "remote_projection_digest": binding["remote_projection_digest"],
                    "receipt_state": receipt["state"],
                    "offline_read_calls": remote.reads,
                })
        finally:
            local.close()
    finally:
        state_db.close(); jobs_db.close(); inbox_db.close()
    after = snapshot(paths)
    if after != before:
        raise RuntimeError("store_identity_changed")
    print(json.dumps({
        "cycle_id": CYCLE, "case_count": len(results), "cases": results,
        "stores_unchanged": True, "transport": "disposable_expected_value_only",
        "network": "not_constructed", "remote_commit": "forbidden",
    }, sort_keys=True))


if __name__ == "__main__":
    main()
