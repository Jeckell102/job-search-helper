from contextlib import contextmanager
import fcntl
import json
import os
import sqlite3
from pathlib import Path

import pytest

from job_search_helper import ats, ordinary_verification_pending as pending, runner
from job_search_helper.cli import WriterLockBusy, writer_lock
from job_search_helper.engine import Engine
from job_search_helper.ordinary_verification_worker import OrdinaryVerificationHandoff
from job_search_helper.repository import RepositoryError
from job_search_helper.sqlite_repository import SQLiteRepository

from test_ordinary_verification_pending import COMPANY, COMPANY_ID, CYCLE_ID, OBSERVATION, attempt


RUNTIME = {"state": "NO_RELEASE", "source_manifest_sha256": "a" * 64,
           "config_sha256": "b" * 64, "dependency_manifest_sha256": "c" * 64}


@pytest.fixture
def local_worker(monkeypatch, attempt):
    from job_search_helper import ordinary_verification_worker

    stores, _, admission, _ = attempt
    cycle = stores.state.cycle(CYCLE_ID)
    cycle["runtime_binding"] = RUNTIME
    stores.state.save_cycle(cycle)
    monkeypatch.setattr(ordinary_verification_worker, "qualification_for_snapshot",
                        lambda snapshot: {"matrix_digest": admission["matrix_digest"]})
    frozen = cycle["companies"][COMPANY_ID]["installed_source_configuration"]
    monkeypatch.setattr(ordinary_verification_worker, "_resolve_authoritative_installed_source_configuration",
                        lambda repo, company_id: frozen)
    scopes = []

    @contextmanager
    def open_stores():
        scopes.append("opened")
        try:
            yield stores
        finally:
            scopes.append("closed")

    handoff = OrdinaryVerificationHandoff(CYCLE_ID, open_stores)
    return stores, handoff, scopes


def mismatch():
    return ats.Inventory("partial", reason="stale controlled board", ats="Rippling",
                         rippling_tenant_mismatch=ats.validate_rippling_tenant_mismatch(OBSERVATION))


def test_same_ordinary_fetch_and_saves_only_sealed_exact_inventory(local_worker):
    stores, handoff, scopes = local_worker
    seen = []

    def fetch(*args):
        assert scopes == ["opened", "closed"]
        seen.append(args)
        return mismatch()

    engine = Engine(stores.jobs, stores.state, inbox=stores.inbox, fetcher=fetch, runtime_binding=RUNTIME)
    original = engine.resume_local(CYCLE_ID, verification_handoff=handoff)
    assert seen == [("Rippling", COMPANY["Official Careers URL"], COMPANY_ID, "Forterra")]
    assert scopes == ["opened", "closed", "opened", "closed"]
    assert original["attempted_company_ids"] == [COMPANY_ID]
    assert original["run_counts"]["pending"] == 1
    assert pending.verifier_payload(stores, CYCLE_ID, COMPANY_ID)["observation"] == OBSERVATION
    assert stores.inbox.plan(CYCLE_ID, COMPANY_ID) is None
    assert stores.jobs.scrape_outcomes() == []
    retry = engine.resume_local(CYCLE_ID, verification_handoff=handoff)
    assert retry["attempted_company_ids"] == [] and len(seen) == 1
    with pytest.raises(RepositoryError, match="exact continuation"):
        engine.resume_local(CYCLE_ID, sync_only=True)


def test_old_outcome_blocks_enrollment_and_provider(local_worker):
    stores, handoff, _ = local_worker
    cycle = stores.state.cycle(CYCLE_ID)
    company = cycle["companies"][COMPANY_ID]
    writer = SQLiteRepository(stores.jobs.path, "fixture-workbook")
    try:
        writer.record_scrape_outcome({
            "company_id": COMPANY_ID, "cycle_id": CYCLE_ID,
            "request_id": cycle["start_request_id"],
            "source_revision": company["outcome_source_revision"],
            "source_current": True, "inventory_status": "incomplete", "storage_status": "confirmed",
            "failure": {"category": "unknown"},
        })
    finally:
        writer.close()

    def should_not_fetch(*_):
        pytest.fail("the exact prior outcome owns this attempt")

    engine = Engine(stores.jobs, stores.state, inbox=stores.inbox, fetcher=should_not_fetch, runtime_binding=RUNTIME)
    with pytest.raises(RepositoryError, match="already has an immutable outcome"):
        engine.resume_local(CYCLE_ID, verification_handoff=handoff)
    assert pending.read_marker(stores.state.cycle(CYCLE_ID), COMPANY_ID) is None
    assert stores.inbox.get(CYCLE_ID, COMPANY_ID) is None


def test_pending_prevents_generic_lifecycle_before_repository_construction(local_worker):
    stores, handoff, _ = local_worker
    handoff.assignment()
    with pytest.raises(ValueError, match="exact owned continuation"):
        runner._assert_no_pending_ordinary_verification(Path(stores.state.path))


@pytest.mark.parametrize("replace_scraper_lock", [False, True])
def test_enrolled_runner_keeps_named_scraper_flock_and_releases_writer_for_provider(
    local_worker, monkeypatch, tmp_path, replace_scraper_lock,
):
    import release_admission_bootstrap

    stores, _, _ = local_worker
    owner_directory = tmp_path / "ordinary-owner"
    owner_directory.mkdir(mode=0o700)
    database = owner_directory / "state.db"
    jobs_path = owner_directory / "jobs.sqlite3"
    inventory_path = owner_directory / "inventories.sqlite3"
    monkeypatch.setenv("JOB_STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("STATE_DB_FILE", str(database))
    monkeypatch.setenv("JOB_DB_FILE", str(jobs_path))
    monkeypatch.setenv("SPREADSHEET_ID", "fixture-workbook")
    measured = release_admission_bootstrap._validate_runtime(runner.PROJECT_ROOT, owner_directory)
    original = stores.state.cycle(CYCLE_ID)
    original["runtime_binding"] = measured
    stores.state.save_cycle(original)
    for connection, destination in ((stores.state.connection, database),
                                    (stores.jobs.db, jobs_path),
                                    (stores.inbox.connection, inventory_path)):
        copied = sqlite3.connect(destination)
        try:
            connection.backup(copied)
        finally:
            copied.close()
        destination.chmod(0o600)
    writer_path = database.with_name("writer.lock")
    scraper_path = database.with_name("scraper.lock")
    monkeypatch.setattr(runner, "load_title_blacklist", lambda: None)
    monkeypatch.setattr(runner, "load_title_review_list", lambda: None)
    calls = []

    def fetch(*args):
        with pytest.raises(WriterLockBusy):
            with writer_lock(scraper_path):
                pass
        with writer_lock(writer_path):
            calls.append(args)
            if replace_scraper_lock:
                scraper_path.rename(scraper_path.with_suffix(".previous"))
                scraper_path.touch(mode=0o600)
        return mismatch()

    monkeypatch.setattr(ats, "fetch_inventory", fetch)
    lock = os.open(scraper_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for _ in range(1 if replace_scraper_lock else 2):
            fd = os.dup(lock)
            monkeypatch.setenv("JSH_SCRAPER_ADMISSION_FD", str(fd))
            monkeypatch.setenv("JSH_SCRAPER_ADMISSION_PATH", str(scraper_path))
            monkeypatch.setenv("JSH_SCRAPER_RUNTIME_BINDING", json.dumps(measured))
            options = dict(resume=True, resume_cycle_id=CYCLE_ID,
                           capture_ordinary_verification=True,
                           browser_fallback=False, fetch_workers=1)
            if replace_scraper_lock:
                with pytest.raises(RuntimeError, match="lock identity changed"):
                    runner.run_start(**options)
            else:
                assert runner.run_start(**options) == 0
    finally:
        os.close(lock)
    assert len(calls) == 1
    with pending.open_verification_stores(database, jobs_path, inventory_path, "fixture-workbook") as owned:
        if replace_scraper_lock:
            assert pending.read_marker(owned.state.cycle(CYCLE_ID), COMPANY_ID)["state"] == "ARMED"
            assert owned.inbox.get(CYCLE_ID, COMPANY_ID) is None
        else:
            assert pending.verifier_payload(owned, CYCLE_ID, COMPANY_ID)["observation"] == OBSERVATION
        assert owned.jobs.scrape_outcomes() == []
        assert owned.inbox.plan(CYCLE_ID, COMPANY_ID) is None
    assert not database.with_name("scraper-performance.json").exists()


def test_qualification_change_during_fetch_leaves_armed_without_inventory(local_worker, monkeypatch):
    from job_search_helper import ordinary_verification_worker

    stores, handoff, _ = local_worker

    def fetch(*_):
        monkeypatch.setattr(ordinary_verification_worker, "qualification_for_snapshot", lambda snapshot: None)
        return mismatch()

    engine = Engine(stores.jobs, stores.state, inbox=stores.inbox, fetcher=fetch, runtime_binding=RUNTIME)
    with pytest.raises(RepositoryError, match="requires a reviewed source qualification"):
        engine.resume_local(CYCLE_ID, verification_handoff=handoff)
    assert pending.read_marker(stores.state.cycle(CYCLE_ID), COMPANY_ID)["state"] == "ARMED"
    assert stores.inbox.get(CYCLE_ID, COMPANY_ID) is None


@pytest.mark.parametrize("when", ["provider", "replay"])
def test_foreign_claim_blocks_save_and_replay(local_worker, when):
    stores, handoff, _ = local_worker

    def claim():
        writer = SQLiteRepository(stores.jobs.path, "fixture-workbook")
        try:
            writer.import_rows("Companies", [(2, {**COMPANY, "Claimed By": "fixture-other-owner"})])
        finally:
            writer.close()

    def fetch(*args):
        if when == "provider":
            claim()
        return mismatch()

    engine = Engine(stores.jobs, stores.state, inbox=stores.inbox, fetcher=fetch, runtime_binding=RUNTIME)
    if when == "replay":
        engine.resume_local(CYCLE_ID, verification_handoff=handoff)
        claim()
    with pytest.raises(RepositoryError, match="held or has a foreign claim"):
        engine.resume_local(CYCLE_ID, verification_handoff=handoff)
    marker = pending.read_marker(stores.state.cycle(CYCLE_ID), COMPANY_ID)
    if when == "provider":
        assert marker["state"] == "ARMED"
        assert stores.inbox.get(CYCLE_ID, COMPANY_ID) is None
    else:
        assert marker["state"] == "PREPARED"
        assert stores.inbox.get(CYCLE_ID, COMPANY_ID) is not None


def test_enrolled_browser_progress_stays_in_memory(local_worker):
    stores, handoff, _ = local_worker
    emitted = []

    class Fetcher:
        def fetch_with_progress(self, *args, progress_factory):
            progress = progress_factory("https://ats.rippling.com/stale-tenant/jobs")
            progress.save_listing({"queue": [], "visited": [], "complete": True})
            emitted.append(progress.listing("ignored"))
            return mismatch()

    engine = Engine(stores.jobs, stores.state, inbox=stores.inbox,
                    fetcher=Fetcher(), runtime_binding=RUNTIME)
    engine.resume_local(CYCLE_ID, verification_handoff=handoff)
    assert emitted[0]["complete"] is True
    assert stores.inbox.connection.execute("SELECT count(*) FROM main.browser_progress").fetchone() == (0,)


def test_armed_marker_blocks_interrupted_cycle_pause_before_opening_repository(local_worker, monkeypatch):
    stores, handoff, _ = local_worker
    handoff.assignment()
    monkeypatch.setenv("JOB_STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("JOB_DB_FILE", str(stores.jobs.path))
    monkeypatch.setattr(runner, "get_repository",
                        lambda **_: pytest.fail("repository constructed before marker guard"))
    with pytest.raises(ValueError, match="exact owned continuation"):
        runner.pause_interrupted_cycle(CYCLE_ID, "fixture", database=Path(stores.state.path))
    engine = Engine(stores.jobs, stores.state, runtime_binding=RUNTIME)
    with pytest.raises(ValueError, match="exact owned continuation"):
        engine.assess_interrupted_cycle_recovery(CYCLE_ID)


def test_real_bootstrap_exec_reaches_qualification_gate_without_provider(local_worker, monkeypatch, tmp_path):
    import subprocess
    import sys

    import release_admission_bootstrap

    stores, _, _ = local_worker
    owner_directory = tmp_path / "launcher-owner"
    owner_directory.mkdir(mode=0o700)
    database = owner_directory / "state.db"
    jobs_path = owner_directory / "jobs.sqlite3"
    inbox_path = owner_directory / "inventories.sqlite3"
    monkeypatch.setenv("JOB_STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("STATE_DB_FILE", str(database))
    monkeypatch.setenv("JOB_DB_FILE", str(jobs_path))
    monkeypatch.setenv("SPREADSHEET_ID", "fixture-workbook")
    measured = release_admission_bootstrap._validate_runtime(runner.PROJECT_ROOT, owner_directory)
    cycle = stores.state.cycle(CYCLE_ID)
    cycle["runtime_binding"] = measured
    stores.state.save_cycle(cycle)
    for connection, destination in ((stores.state.connection, database),
                                    (stores.jobs.db, jobs_path),
                                    (stores.inbox.connection, inbox_path)):
        copied = sqlite3.connect(destination)
        try:
            connection.backup(copied)
        finally:
            copied.close()
        destination.chmod(0o600)
    launched = subprocess.run(
        [sys.executable, "-I", "-S", str(runner.PROJECT_ROOT / "release_admission_bootstrap.py"),
         "start", "--resume", "--resume-cycle-id", CYCLE_ID, "--capture-ordinary-verification",
         "--no-browser-fallback", "--fetch-workers", "1"],
        cwd=runner.PROJECT_ROOT, capture_output=True, text=True, timeout=8,
    )
    assert launched.returncode == 1
    assert "requires a reviewed source qualification" in launched.stderr
    assert "Ordinary verification inventory" not in launched.stdout
    with pending.open_verification_stores(database, jobs_path, inbox_path, "fixture-workbook") as owned:
        assert pending.read_marker(owned.state.cycle(CYCLE_ID), COMPANY_ID) is None
        assert owned.inbox.get(CYCLE_ID, COMPANY_ID) is None
        assert owned.jobs.scrape_outcomes() == []


def test_continuing_named_lock_proof_refuses_bootstrap_alias(monkeypatch, tmp_path):
    monkeypatch.setenv("JOB_STORAGE_BACKEND", "sqlite")
    database = tmp_path / "state.db"
    nominal = tmp_path / "scraper.lock"
    target = tmp_path / "other.lock"
    nominal.symlink_to(target)
    locked = os.open(target, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(locked, fcntl.LOCK_EX | fcntl.LOCK_NB)
        monkeypatch.setenv("JSH_SCRAPER_ADMISSION_FD", str(locked))
        monkeypatch.setenv("JSH_SCRAPER_ADMISSION_PATH", str(target))
        monkeypatch.setenv("JSH_SCRAPER_RUNTIME_BINDING", json.dumps(RUNTIME))
        with pytest.raises(RuntimeError, match="does not own the expected lock"):
            with runner._scraper_admission(database, require_inherited=True, with_lock_proof=True):
                pytest.fail("an alias may not own the named capture")
    finally:
        os.close(locked)
