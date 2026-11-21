"""An archived old-cycle snapshot must match exact original saved scope."""
from contextlib import closing
import json
import shutil
import sqlite3

import pytest

from job_search_helper.engine import State
from job_search_helper.inbox import InventoryInbox
from job_search_helper.retained_cycle_retirement import verify_retirement_archive
from job_search_helper.sheet_profile import COMPACT_PROFILE
from job_search_helper.sqlite_repository import SQLiteRepository


CYCLE = "CYC-fixture-retirement"
COMPANY = "COMP-fixture-retirement"


@pytest.fixture
def stores(tmp_path):
    live, archive = tmp_path / "live", tmp_path / "archive"
    live.mkdir()
    archive.mkdir()
    state_file = live / "state.db"
    with closing(State(state_file)) as state:
        state.save_cycle({"id": CYCLE, "status": "In Progress",
                          "companies": {COMPANY: {"stage": "inventory"}}})
    jobs_file = live / "jobs.sqlite3"
    with closing(SQLiteRepository(jobs_file, "workbook", initialize=True)) as jobs:
        with jobs.transaction():
            jobs.set_meta("sheets_profile", COMPACT_PROFILE)
        jobs.import_rows("Scan Cycles", [(2, {"Cycle ID": CYCLE, "Cycle Status": "In Progress",
                                            "Notes": json.dumps({"company_ids": [COMPANY]})})])
    inventory_file = live / "inventories.sqlite3"
    with closing(InventoryInbox(inventory_file, "workbook")) as inbox:
        inbox.save(CYCLE, COMPANY, {"jobs": [], "inventory_status": "complete"})
        inbox.save_plan(CYCLE, COMPANY, {"operations": [{"tab": "Job History"}]})
        inbox.save("other-cycle", COMPANY, {"jobs": []})
    for file in (state_file, jobs_file, inventory_file):
        shutil.copyfile(file, archive / file.name)
    return live, archive


def test_archive_proof_changes_no_file_and_ignores_other_cycle_inventory(stores):
    live, archive = stores
    with closing(sqlite3.connect(live / "inventories.sqlite3")) as db, db:
        db.execute("UPDATE inventories SET payload='{}' WHERE cycle='other-cycle'")
    originals = {p: p.read_bytes() for root in stores for p in root.iterdir()}
    result = verify_retirement_archive(live, archive, CYCLE)
    assert result == verify_retirement_archive(live, archive, CYCLE)
    assert result["saved_inventory_count"] == result["saved_plan_count"] == 1
    assert result["status"] == "ARCHIVE_VERIFIED"
    assert result["published"] is False and result["retired"] is False
    assert {p: p.read_bytes() for p in originals} == originals


@pytest.mark.parametrize("table", ["inventories", "sync_plans"])
def test_archive_refuses_byte_distinct_original_payload(stores, table):
    live, archive = stores
    with closing(sqlite3.connect(live / "inventories.sqlite3")) as db, db:
        db.execute(f"UPDATE {table} SET payload=payload || ' ' WHERE cycle=?", (CYCLE,))
    with pytest.raises(ValueError, match="differs from current saved scope"):
        verify_retirement_archive(live, archive, CYCLE)


def test_archive_refuses_dirty_local_state(stores):
    live, archive = stores
    with closing(sqlite3.connect(live / "jobs.sqlite3")) as db, db:
        row_id = db.execute("SELECT row_id FROM records WHERE tab='Scan Cycles'").fetchone()[0]
        db.execute("INSERT INTO dirty VALUES ('Scan Cycles',?,'Notes')", (row_id,))
    with pytest.raises(ValueError, match="Local pending changes"):
        verify_retirement_archive(live, archive, CYCLE)


def test_archive_refuses_same_directory_or_alias(stores):
    live, archive = stores
    with pytest.raises(ValueError, match="separate existing copy"):
        verify_retirement_archive(live, live, CYCLE)
    name = "state.db"
    (archive / name).unlink()
    (archive / name).hardlink_to(live / name)
    with pytest.raises(ValueError, match="separate existing copy"):
        verify_retirement_archive(live, archive, CYCLE)



def test_retirement_holds_legacy_remote_intent_before_archive_comparison(stores):
    live, archive = stores
    with closing(InventoryInbox(live / "inventories.sqlite3", "workbook")) as inbox:
        intent = inbox.begin_exact_chunk(CYCLE, COMPANY, 0, 1, "a" * 64)
        assert intent["state"] == "PENDING"
    with pytest.raises(ValueError, match="exact_sync_chunks"):
        verify_retirement_archive(live, archive, CYCLE)


def test_retirement_control_record_preserves_original_state_and_all_data(stores, monkeypatch):
    from job_search_helper.retained_cycle_retirement_control import retire_saved_cycle

    monkeypatch.setenv("JOB_STORAGE_BACKEND", "sqlite")
    live, archive = stores
    proof = verify_retirement_archive(live, archive, CYCLE)
    with closing(sqlite3.connect(live / "state.db")) as db:
        before = db.execute("SELECT * FROM cycles").fetchall()
    inventory_bytes = (live / "inventories.sqlite3").read_bytes()
    jobs_bytes = (live / "jobs.sqlite3").read_bytes()
    scope = {"archive_scope_sha256": proof["archive_scope_sha256"],
             "reason": "Owner is retiring unfinished and archived work"}
    with pytest.raises(ValueError, match="differs from the reviewed"):
        retire_saved_cycle(live, archive, CYCLE, **dict(scope, archive_scope_sha256="a" * 64))
    retired = retire_saved_cycle(live, archive, CYCLE, **scope)
    assert retired["state"] == "RETIRED_UNPUBLISHED"
    assert retired["published"] is False
    assert retire_saved_cycle(live, archive, CYCLE, **scope) == retired
    with pytest.raises(ValueError, match="authority changed"):
        retire_saved_cycle(live, archive, CYCLE, **dict(scope, reason="different scope"))
    with closing(sqlite3.connect(live / "state.db")) as db:
        assert db.execute("SELECT * FROM cycles").fetchall() == before
        assert db.execute("SELECT COUNT(*) FROM retained_cycle_retirements").fetchone() == (1,)
    assert (live / "inventories.sqlite3").read_bytes() == inventory_bytes
    assert (live / "jobs.sqlite3").read_bytes() == jobs_bytes


def test_retirement_waits_for_review_writeback_owner(stores, monkeypatch):
    from job_search_helper.cli import WriterLockBusy, writer_lock
    from job_search_helper.retained_cycle_retirement_control import retire_saved_cycle

    monkeypatch.setenv("JOB_STORAGE_BACKEND", "sqlite")
    live, archive = stores
    proof = verify_retirement_archive(live, archive, CYCLE)
    with writer_lock(live / "review-writeback.lock"), pytest.raises(WriterLockBusy):
        retire_saved_cycle(live, archive, CYCLE, archive_scope_sha256=proof["archive_scope_sha256"],
                           reason="Owner ends the unfinished attempt")
    with closing(sqlite3.connect(live / "state.db")) as db:
        assert db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='retained_cycle_retirements'"
        ).fetchone() is None



def test_retirement_reader_verifies_originals_and_rejects_replay(stores, monkeypatch):
    from job_search_helper.retained_cycle_retirement_control import (
        assert_cycle_not_retired, retire_saved_cycle, verified_retired_cycle_ids,
    )

    monkeypatch.setenv("JOB_STORAGE_BACKEND", "sqlite")
    live, archive = stores
    proof = verify_retirement_archive(live, archive, CYCLE)
    with closing(State(live / "state.db", readonly=True)) as state:
        assert verified_retired_cycle_ids(state) == set()
        assert_cycle_not_retired(state, CYCLE)
    retire_saved_cycle(live, archive, CYCLE, archive_scope_sha256=proof["archive_scope_sha256"],
                       reason="Owner elects to start again later")
    with (closing(State(live / "state.db", readonly=True)) as state,
          closing(sqlite3.connect(live / "state.db")) as writer):
        writer.execute("PRAGMA journal_mode=WAL")
        with writer:
            writer.execute("INSERT INTO cycles VALUES ('later-cycle','{}')")
        assert verified_retired_cycle_ids(state) == {CYCLE}
        with pytest.raises(ValueError, match="saved scrape was retired"):
            assert_cycle_not_retired(state, CYCLE)
        assert_cycle_not_retired(state, "later-cycle")
        with closing(sqlite3.connect(archive / "inventories.sqlite3")) as copied, copied:
            copied.execute("UPDATE inventories SET payload=payload || ' ' WHERE cycle=?", (CYCLE,))
        with pytest.raises(ValueError, match="archive no longer matches"):
            verified_retired_cycle_ids(state)
        with pytest.raises(ValueError, match="saved scrape was retired"):
            assert_cycle_not_retired(state, CYCLE)
