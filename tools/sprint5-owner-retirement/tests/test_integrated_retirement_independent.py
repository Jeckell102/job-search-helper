"""Integrated retirement ownership checks with real disposable SQLite stores."""
from contextlib import closing
import json
import shutil
import sqlite3

import pytest

from job_search_helper.engine import Engine, State
from job_search_helper.exact_cycle_sync import publish_exact_cycle
from job_search_helper.exact_legacy_migration_runner import adopt_retained_legacy_migration
from job_search_helper.inbox import InventoryInbox
from job_search_helper.retained_cycle_retirement import verify_retirement_archive
from job_search_helper.retained_cycle_retirement_control import retire_saved_cycle
from job_search_helper.runner import _readonly_named_exact_preflight, active_inbox_cycles
from job_search_helper.scan_request import (
    company_only_queue_status, request_fingerprint, requested_scan,
)
from job_search_helper.sqlite_repository import SQLiteRepository
from test_retained_cycle_retirement import COMPANY, CYCLE, stores


NEW = "COMP-fresh"
OTHER = "CYC-other-held"
CLOCK = "2026-11-21T10:00:00Z"


def queue(directory, company=NEW, name="REQ-fresh"):
    request = {"mode": "company-only", "request_id": name, "company_ids": [company],
               "source_revision": "fixture-revision", "enqueued_at": CLOCK, "start_last": []}
    path = directory / "next-scan.json"
    path.write_text(json.dumps(request))
    return path, request


def retire(stores, monkeypatch):
    current, archive = stores
    monkeypatch.setenv("JOB_STORAGE_BACKEND", "sqlite")
    proof = verify_retirement_archive(current, archive, CYCLE)
    marker = retire_saved_cycle(current, archive, CYCLE, archive_scope_sha256=proof["archive_scope_sha256"],
                                reason="Fixture owner retirement")
    assert marker["state"] == "RETIRED_UNPUBLISHED"
    return marker


def scoped(current):
    with closing(sqlite3.connect(current / "state.db")) as state, \
         closing(sqlite3.connect(current / "jobs.sqlite3")) as jobs, \
         closing(sqlite3.connect(current / "inventories.sqlite3")) as inbox:
        return (
            state.execute("SELECT data FROM cycles WHERE id=?", (CYCLE,)).fetchall(),
            jobs.execute("SELECT row_id,data,policies FROM records WHERE tab='Scan Cycles' "
                         "AND json_extract(data, '$.\"Cycle ID\"')=?", (CYCLE,)).fetchall(),
            inbox.execute("SELECT * FROM inventories WHERE cycle=?", (CYCLE,)).fetchall(),
            inbox.execute("SELECT * FROM sync_plans WHERE cycle=?", (CYCLE,)).fetchall(),
            inbox.execute("SELECT * FROM publication_receipts").fetchall(),
        )


def old_routes_hold(engine, inbox, state_path):
    state = engine.state

    def denied(*args, **kwargs):
        raise AssertionError("unexpected publisher or provider callback")

    for operation in [
        lambda: engine.resume(CYCLE, retry_blocked=True),
        lambda: engine.resume_parallel(CYCLE, retry_blocked=True),
        lambda: _readonly_named_exact_preflight(state_path, state_path.parent / "absent-inbox", CYCLE, [COMPANY]),
        lambda: publish_exact_cycle(inbox, CYCLE, object(), company_ids=[COMPANY], state=state,
                                    company_guard=denied, synchronizer=object()),
        lambda: adopt_retained_legacy_migration(state_path.parent / "absent-inbox",
                                                state_path.parent / "absent-jobs",
                                                CYCLE, COMPANY, {"binding": {}, "delivery_evidence": {}}),
    ]:
        with pytest.raises(ValueError, match="was retired"):
            operation()


def test_real_marker_enables_one_fresh_company_and_never_replays_old_work(stores, monkeypatch):
    current, archive = stores
    original = scoped(current)
    archived = {file: file.read_bytes() for file in archive.iterdir()}
    retire(stores, monkeypatch)
    path, request = queue(current)
    old_queue = path.read_bytes()
    with closing(State(current / "state.db")) as state, \
         closing(SQLiteRepository(current / "jobs.sqlite3", "workbook", require_ready=False)) as jobs, \
         closing(InventoryInbox(current / "inventories.sqlite3", "workbook")) as inbox:
        jobs.import_rows("Companies", [(2, {"Company ID": NEW, "Company": "Fixture Company", "Company Status": "Active"})])
        engine = Engine(jobs, state, inbox=inbox)
        assert company_only_queue_status(engine, state, current / "state.db")["state"] == "READY_FOR_START"
        assert active_inbox_cycles(inbox, state) == ["other-cycle"]
        old_routes_hold(engine, inbox, current / "state.db")
        assert scoped(current) == original and path.read_bytes() == old_queue

        state.save_cycle({"id": OTHER, "status": "In Progress", "companies": {}, "started_at": CLOCK,
                          "all": False})
        jobs.import_rows("Scan Cycles", [(3, {"Cycle ID": OTHER, "Cycle Status": "In Progress"})])
        held = company_only_queue_status(engine, state, current / "state.db")
        assert held["blocking_cycle_ids"] == [OTHER]
        with pytest.raises(ValueError, match=OTHER):
            requested_scan(engine, state, current / "state.db")
        assert path.read_bytes() == old_queue
        other = state.cycle(OTHER)
        other["status"] = "Complete"
        state.save_cycle(other)
        jobs.import_rows("Scan Cycles", [(3, {"Cycle ID": OTHER, "Cycle Status": "Complete"})])

        fresh = requested_scan(engine, state, current / "state.db")
        assert fresh != CYCLE and set(state.cycle(fresh)["companies"]) == {NEW}
        assert state.cycle(fresh)["start_request_id"] == request["request_id"]
        assert (current / "last-scan-request.json").read_bytes() == old_queue
        assert not path.exists()
        assert scoped(current) == original
        assert {file: file.read_bytes() for file in archive.iterdir()} == archived

        # Proof drift holds new admission while the recorded retirement still guards old execution.
        path, _ = queue(current, name="REQ-after-archive-drift")
        protected_queue = path.read_bytes()
        with closing(sqlite3.connect(archive / "inventories.sqlite3")) as db, db:
            db.execute("UPDATE sync_plans SET payload=payload || ' ' WHERE cycle=?", (CYCLE,))
        with pytest.raises(ValueError, match="archive no longer matches"):
            requested_scan(engine, state, current / "state.db")
        old_routes_hold(engine, inbox, current / "state.db")
        assert path.read_bytes() == protected_queue and scoped(current) == original


def test_exact_old_queued_request_cannot_reenter_retired_ownership(stores, monkeypatch):
    current, archive = stores
    path, request = queue(current, COMPANY, "REQ-original")
    with closing(State(current / "state.db")) as state:
        saved = state.cycle(CYCLE)
        saved.update(start_request_id=request["request_id"], started_at=CLOCK, all=False,
                     request_fingerprint=request_fingerprint(request, [COMPANY]))
        state.save_cycle(saved)
    shutil.copyfile(current / "state.db", archive / "state.db")
    retire(stores, monkeypatch)
    original = scoped(current)
    original_queue = path.read_bytes()
    with closing(State(current / "state.db")) as state, \
         closing(SQLiteRepository(current / "jobs.sqlite3", "workbook", require_ready=False)) as jobs:
        engine = Engine(jobs, state)
        with pytest.raises(ValueError, match="was retired"):
            requested_scan(engine, state, current / "state.db")
    assert path.read_bytes() == original_queue and scoped(current) == original
