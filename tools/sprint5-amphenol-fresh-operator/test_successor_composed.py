"""Compose both operator outcomes and the actual successor launch on local fixtures."""

from contextlib import closing, contextmanager, nullcontext
from hashlib import sha256
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import coding_tools
import host_server as host
from coordinator import Coordinator
from coordinator_inference import digest
from coordinator_store import task_state_digest
from job_search_helper import ats
from job_search_helper.acquiretm import SOURCE
from job_search_helper.cli import writer_lock
from job_search_helper.company_events import current_company_repair_snapshot
from job_search_helper.engine import State
from job_search_helper.inbox import InventoryInbox
from job_search_helper.operator_amphenol_settlement import execute_operator_amphenol
from job_search_helper.operator_company_request import _digest, queue_operator_company_request
from job_search_helper.sheet_profile import COMPACT_PROFILE
from job_search_helper.sqlite_repository import SQLiteRepository
from test_acquiretm import UpdatePanelPage
from test_ordinary_company_event_fetch import RUNTIME, workbook_reader


APP_SOURCE = Path("/tmp/jsh-operator-owned-bridge.xu59ooer")
COMPANY = {
    "Company ID": "COMP-0490", "Company": "Amphenol Aerospace", "Company Status": "Active",
    "ATS / Source": "AcquireTM", "Official Careers URL": SOURCE,
}
CHOICE = {"summary": "W1", "next_action": "listing_membership_change", "outcome": "phase_done"}


class InterruptedAfterPromotion(BaseException):
    """Stop after durable preparation and before the normal pilot command."""


def selection(record, request_sha256):
    return {
        "request_id": record["identity"]["request_id"],
        "request_sha256": request_sha256,
        "source_revision": record["identity"]["source_revision"],
    }


def enroll(fields):
    return host.recipe_enrollment_from_process_environment({
        "WRAPPER_AMPHENOL_OPERATOR_RECIPE_ENROLLMENT": json.dumps(fields),
    })


def prepare_local_root(tmp_path, monkeypatch):
    app = tmp_path / "application"
    app.mkdir()
    state, jobs = app / "state.db", app / "jobs.sqlite3"
    with (closing(State(state)), closing(InventoryInbox(app / "inventories.sqlite3", "sheet")),
          closing(SQLiteRepository(jobs, "sheet", initialize=True)) as repository):
        repository.set_meta("ready", "yes")
        repository.set_meta("sheets_profile", COMPACT_PROFILE)
        repository.ensure_columns("Opportunities", ["Opportunity ID"])
        repository.import_rows("Companies", [(2, COMPANY)])
    installed = tmp_path / "installed"
    for name in ("src/job_search_helper/acquiretm.py", "src/job_search_helper/ats.py",
                 "src/job_search_helper/company_sources.py", "tests/test_acquiretm.py"):
        dest = installed / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes((APP_SOURCE / name).read_bytes())
    assert sha256((installed / "src/job_search_helper/acquiretm.py").read_bytes()).hexdigest() == (
        "a95953afe2bc10138714f6b11af22572b17ab344bf61d78b834647895025aa61"
    )
    monkeypatch.setattr(host, "JOB_SEARCH_ROOT", installed)
    monkeypatch.setattr(coding_tools, "ROOT", installed)
    monkeypatch.setenv("SPREADSHEET_ID", "sheet")

    def company_snapshot(company_id):
        with closing(SQLiteRepository(jobs, "sheet", readonly=True)) as repository:
            return current_company_repair_snapshot(repository, company_id)

    @contextmanager
    def scope(_):
        with writer_lock(app / "scraper.lock"), writer_lock(app / "writer.lock"):
            yield app, jobs, InventoryInbox.destination_id(app / "inventories.sqlite3")

    monkeypatch.setattr(host, "current_company_repair_snapshot", company_snapshot)
    monkeypatch.setattr(host.OperatorAmphenolRecipeEnrollment, "owner_scope", scope)
    return app, state, jobs


def settle_distinct_request(app, state, jobs, request_id, monkeypatch):
    with closing(SQLiteRepository(jobs, "sheet")) as repository:
        queued = queue_operator_company_request(repository, app, COMPANY["Company ID"], request_id)
    assert queued["state"] == "REQUEST_WRITTEN"
    request_sha256 = _digest(json.loads((app / "next-scan.json").read_bytes()))
    page = UpdatePanelPage("delayed")
    details = Mock(side_effect=AssertionError("The typed partial must not query detail pages"))
    browser = SimpleNamespace(
        new_context=lambda: SimpleNamespace(new_page=lambda: page, request=details),
        close=lambda: None,
    )
    playwright = SimpleNamespace(chromium=SimpleNamespace(launch=lambda **_: browser))
    workbook = workbook_reader(COMPANY, SOURCE)
    with monkeypatch.context() as observing:
        observing.setitem(sys.modules, "playwright.sync_api",
                          SimpleNamespace(sync_playwright=lambda: nullcontext(playwright)))
        observing.setattr("job_search_helper.acquiretm.time.monotonic_ns", lambda: page.clock_ns)
        with writer_lock(app / "scraper.lock"):
            result = execute_operator_amphenol((state, jobs, RUNTIME), request_sha256=request_sha256,
                                               fetcher=ats.fetch_inventory, remote_reader=workbook)
    assert result["state"] == "FETCH_REPAIR_QUALIFIED"
    assert not (app / "next-scan.json").exists()
    details.assert_not_called()
    workbook.assert_called_once()
    assert workbook.return_value.service.batches == []
    return result["outcome"], request_sha256


def coordinator_for(base, selected):
    def never_dispatch(*args, **kwargs):
        pytest.fail("The integration fixture does not dispatch inference")

    return Coordinator(
        base, model=never_dispatch, company_revision_resolver=lambda _: selected.source_revision,
        repair_profile_selector=selected.profile,
    )


def retain_completed_predecessor(app, coordinator, enrollment, old_id, old_outcome):
    """Seed one locally finalized response using actual durable inference APIs."""
    store = coordinator.store
    assert store.claim_pilot(old_id)["id"] == old_id
    store.update(old_id, phase="inspect", baseline_passed=True)
    prepared = enrollment._read(app, coordinator, old_outcome, task_id=old_id)
    assert prepared is not None
    session = store.start_inference_session(old_id, max_calls=1)
    assert session is not None
    reserved = store.reserve_inference(
        old_id, phase="inspect", prompt_digest=digest(prepared["messages"]),
        tools_digest=digest(prepared["tools"]), prompt_tokens=1000, output_tokens=500, max_calls=1,
        expected_control_generation=store.control_generation(), session_id=session["inference_session_id"],
    )
    assert reserved is not None
    request_id = reserved["request_id"]
    store.bind_inference_control(request_id, {
        "request_id": request_id, "request_fingerprint": "a" * 64, "owner_generation": "b" * 64,
    })
    response = {
        "message": {"tool_calls": [{"type": "function", "function": {
            "name": "worker_checkpoint", "arguments": CHOICE,
        }}]},
        "usage": {"prompt_eval_count": 900, "eval_count": 100, "done_reason": "stop"},
    }
    receipt = store.finalize_inference(request_id, response, record_owned_recipe_choice=True)["receipt"]
    assert receipt["status"] == "COMPLETED" and receipt["accepted_recipe_choice"] == CHOICE
    store.end_inference_session(old_id, session["inference_session_id"])
    store.stop_pilot()
    old = store.update(old_id, status="PAUSED_ERROR", stop_requested=False)
    assert old["calls"] == old["sessions"] == 1 and store.pilot_task() is None
    assert store.unresolved_inferences() == []
    return old


def tables_before(store, old_id, old_outcome):
    with store.connect() as db:
        return (
            db.execute("SELECT state FROM tasks WHERE id=?", (old_id,)).fetchall(),
            db.execute("SELECT * FROM inference_receipts WHERE task=?", (old_id,)).fetchall(),
            db.execute("SELECT * FROM receipts WHERE task=?", (old_id,)).fetchall(),
            db.execute("SELECT * FROM scrape_outcome_delivery_receipts WHERE outcome_id=?", (old_outcome,)).fetchall(),
            db.execute("SELECT * FROM repair_intake WHERE task_id=?", (old_id,)).fetchall(),
        )


@pytest.mark.parametrize("cut_after_prepare", [False, True])
def test_fresh_exact_operator_successor_uses_existing_launch_once(tmp_path, monkeypatch, cut_after_prepare):
    app, state, jobs = prepare_local_root(tmp_path, monkeypatch)
    base = tmp_path / "coordinator"
    predecessor, old_digest = settle_distinct_request(app, state, jobs, "operator-amphenol-fixture-old", monkeypatch)
    old = enroll(selection(predecessor, old_digest))
    first_coordinator = coordinator_for(base, old)
    first_coordinator.store.set_queue_enabled(False)
    first_coordinator.store.set_autopilot_enabled(False)
    first = old.catch_up(first_coordinator)
    assert first["state"] == "RECIPE_PILOT_QUEUED", first
    old_id = first["task_id"]
    old_task = retain_completed_predecessor(app, first_coordinator, old, old_id, predecessor["outcome_id"])

    fresh, new_digest = settle_distinct_request(app, state, jobs, "operator-amphenol-fixture-fresh", monkeypatch)
    assert fresh["outcome_id"] != predecessor["outcome_id"]
    assert fresh["identity"]["source_revision"] == predecessor["identity"]["source_revision"]
    assert fresh["failure_fingerprint"] == predecessor["failure_fingerprint"]
    ordinary = enroll(selection(fresh, new_digest))
    plain_coordinator = coordinator_for(base, ordinary)
    assert ordinary.catch_up(plain_coordinator) == {"state": "HELD_RECIPE_OWNER"}
    store = plain_coordinator.store
    [prior] = store.held_repair_intake()
    assert prior["outcome_id"] == predecessor["outcome_id"] and prior["task_id"] == old_id
    assert set(prior["evidence_outcome_ids"]) == {predecessor["outcome_id"], fresh["outcome_id"]}
    assert len(store.all()) == 1

    receipts_query = (
        "SELECT consumer,outcome_id,record_sha256,receipt,receipt_sha256 "
        "FROM scrape_outcome_delivery_receipts ORDER BY outcome_id"
    )
    with closing(SQLiteRepository(jobs, "sheet", readonly=True)) as reader, store.connect() as receiver:
        original_pairs = reader.db.execute(receipts_query).fetchall()
        assert len(original_pairs) == 2 and receiver.execute(receipts_query).fetchall() == original_pairs
        assert reader.db.execute("SELECT count(*) FROM scrape_outcome_deliveries").fetchone() == (2,)
    old_bytes = tables_before(store, old_id, predecessor["outcome_id"])
    exact_selection = {
        **selection(fresh, new_digest),
        "predecessor_outcome_id": predecessor["outcome_id"],
        "predecessor_repair_key": prior["repair_key"],
        "predecessor_task_id": old_id,
        "predecessor_task_state_sha256": task_state_digest(old_task),
        "failure_fingerprint": fresh["failure_fingerprint"],
    }
    successor = enroll(exact_selection)
    coordinator = coordinator_for(base, successor)
    commands = []
    real_command = coordinator.command

    def observe_command(data):
        commands.append(data["action"])
        reply = real_command(data)
        if cut_after_prepare and data["action"] == "prepare-held-repair":
            assert reply.get("ok") and reply.get("id") != old_id
            assert reply["state"]["status"] == "PAUSED"
            raise InterruptedAfterPromotion()
        return reply

    monkeypatch.setattr(coordinator, "command", observe_command)
    if cut_after_prepare:
        with pytest.raises(InterruptedAfterPromotion):
            successor.catch_up(coordinator)
        assert commands == ["prepare-held-repair"]
    else:
        launched = successor.catch_up(coordinator)
        assert launched["state"] == "RECIPE_PILOT_QUEUED", launched
        assert commands == ["prepare-held-repair", "pilot-start"]

    durable = coordinator.store
    [new_owner] = [item for item in durable.held_repair_intake() if item["outcome_id"] == fresh["outcome_id"]]
    assert new_owner["status"] == "PROMOTED_PAUSED"
    assert new_owner["repair_key"] != prior["repair_key"]
    assert new_owner["evidence_outcome_ids"] == [fresh["outcome_id"]]
    new_id = new_owner["task_id"]
    assert new_id != old_id
    task = durable.get(new_id)
    assert task["max_sessions"] == 1 and task["isolated_workspace"] is True
    assert task["repair_provenance"]["outcome_id"] == fresh["outcome_id"]
    assert task["status"] == ("PAUSED" if cut_after_prepare else "QUEUED")
    assert durable.pilot_task() == (None if cut_after_prepare else new_id)
    assert durable.inference_receipts(new_id) == []
    assert tables_before(durable, old_id, predecessor["outcome_id"]) == old_bytes

    restarted = coordinator_for(base, successor)
    replay_commands = []
    restarted_command = restarted.command

    def observe_restarted(data):
        replay_commands.append(data["action"])
        return restarted_command(data)

    monkeypatch.setattr(restarted, "command", observe_restarted)
    replay = successor.catch_up(restarted)
    assert replay == {"state": "HELD_RECIPE_BOUNDARY"}
    assert replay_commands == []
    assert restarted.store.get(new_id) == task
    assert restarted.store.pilot_task() == (None if cut_after_prepare else new_id)
    assert len(restarted.store.all()) == 2
    assert restarted.store.inference_receipts(new_id) == []
    assert tables_before(restarted.store, old_id, predecessor["outcome_id"]) == old_bytes
    with closing(SQLiteRepository(jobs, "sheet", readonly=True)) as reader, restarted.store.connect() as receiver:
        assert reader.db.execute(receipts_query).fetchall() == original_pairs
        assert receiver.execute(receipts_query).fetchall() == original_pairs
    print(f"cut_after_prepare={cut_after_prepare} replay={replay['state']} "
          f"successor_status={task['status']} calls={commands} replay_calls={replay_commands}")
