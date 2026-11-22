"""Disposable proof that Crown's public partial is a durable owned outcome."""

from contextlib import closing
import json
from unittest.mock import Mock

import pytest

from crown_inventory_regression import CrownBoard
from job_search_helper.ats import fetch_inventory
from job_search_helper.cli import PROJECT_ROOT, writer_lock
from job_search_helper.engine import State
from job_search_helper.inbox import InventoryInbox
from job_search_helper.integration_release import source_tree_digest
from job_search_helper.operator_amphenol_settlement import execute_operator_partial
from job_search_helper.operator_company_request import _digest, queue_operator_company_request
from job_search_helper.operator_embraer_settlement import read_operator_partial_source
from job_search_helper.operator_partial_scope import CROWN, EMBRAER
from job_search_helper.repository import GoogleRepository
from job_search_helper.sheet_profile import COMPACT_PROFILE, COMPACT_SCHEMAS
from job_search_helper.sqlite_repository import SQLiteRepository
from sheets_fixture import RangeSheets


def test_exact_partial_settles_once_without_job_publication(tmp_path, monkeypatch):
    state_path = tmp_path / "state.db"
    jobs_path = tmp_path / "jobs.sqlite3"
    inbox_path = tmp_path / "inventories.sqlite3"
    company = {
        "Company ID": CROWN.company_id,
        "Company": CROWN.company_name,
        "Company Status": "Active",
        "Official Careers URL": CROWN.careers_url,
        "ATS / Source": CROWN.provider,
    }
    other = {**company, "Company ID": "COMP-9999", "Company": "Other"}
    monkeypatch.setenv("SPREADSHEET_ID", "sheet")
    with (
        closing(State(str(state_path))),
        closing(InventoryInbox(inbox_path, "sheet")),
        closing(SQLiteRepository(jobs_path, "sheet", initialize=True)) as writer,
    ):
        writer.set_meta("ready", "yes")
        writer.set_meta("sheets_profile", COMPACT_PROFILE)
        writer.ensure_columns("Opportunities", ["Opportunity ID"])
        writer.import_rows("Companies", [(2, company), (3, other)])
        with pytest.raises(ValueError, match="operator_crown_request_identity_invalid"):
            queue_operator_company_request(writer, tmp_path, other["Company ID"], "operator-crown-wrong")
        assert not (tmp_path / "next-scan.json").exists()
        queue_operator_company_request(writer, tmp_path, CROWN.company_id, "operator-crown-fixture")
        other_before = writer.matches("Companies", {"Company ID": other["Company ID"]})

    queued = tmp_path / "next-scan.json"
    request_sha = _digest(json.loads(queued.read_text()))
    runtime = {
        "state": "NO_RELEASE",
        "source_manifest_sha256": source_tree_digest(PROJECT_ROOT),
        "config_sha256": "b" * 64,
        "dependency_manifest_sha256": "c" * 64,
    }
    sheets = RangeSheets({"Companies": [company]}, schemas=COMPACT_SCHEMAS)
    remote = Mock(return_value=GoogleRepository(
        sheets, "sheet", schemas=COMPACT_SCHEMAS, min_request_interval=0,
    ))
    board = CrownBoard()

    def fetch(provider, source, company_id, name):
        return fetch_inventory(provider, source, company_id, name, discovery_transport=board)

    from job_search_helper.operator_selected_observation import _validate_request

    unqualified = json.loads(queued.read_text())
    unqualified["request_id"] = "operator-plain"
    unqualified["operator_request"]["request_id"] = "operator-plain"
    with pytest.raises(ValueError, match="operator_selected_observation_request_scope_invalid"):
        _validate_request(unqualified, {}, request_sha, CROWN)

    def settle(fetcher, remote_reader):
        with writer_lock(tmp_path / "scraper.lock"):
            return execute_operator_partial(
                (state_path, jobs_path, runtime), request_sha256=request_sha,
                fetcher=fetcher, remote_reader=remote_reader, scope=CROWN,
            )

    result = settle(fetch, remote)
    assert result["state"] == "FETCH_REPAIR_QUALIFIED", result
    assert not queued.exists()
    assert dict(board.calls) == {CROWN.board_url: 1}
    assert sheets.request_bytes == 0
    remote.assert_called_once()
    no_replay = Mock(side_effect=AssertionError("Repeat would perform work"))
    assert settle(no_replay, no_replay) == result
    no_replay.assert_not_called()

    outcome = result["outcome"]
    assert outcome["repair_category"] == "pagination_regression"
    with (
        closing(SQLiteRepository(jobs_path, "sheet", readonly=True)) as reader,
        closing(InventoryInbox(inbox_path, "sheet", readonly=True)) as inbox,
        closing(State(str(state_path), readonly=True)) as state,
    ):
        proof = read_operator_partial_source(reader, outcome, request_sha, scope=CROWN)
        assert proof["evidence_code"] == CROWN.failure_code
        assert proof["settlement_sha256"] == result["settlement_sha256"]
        assert set(proof["source_files"]) == {
            "src/job_search_helper/successfactors.py", "src/job_search_helper/ats.py",
        }
        assert read_operator_partial_source(reader, outcome, "a" * 64, scope=CROWN) is None
        assert read_operator_partial_source(reader, outcome, request_sha, scope=EMBRAER) is None
        assert state.cycle(result["cycle_id"])["companies"][CROWN.company_id]["stage"] == "partial"
        assert reader.scrape_outcomes(company_id=CROWN.company_id) == [outcome]
        assert reader.matches("Companies", {"Company ID": other["Company ID"]}) == other_before
        assert inbox.connection.execute("SELECT count(*) FROM inventories").fetchone() == (0,)
        assert inbox.connection.execute("SELECT count(*) FROM publication_receipts").fetchone() == (0,)

    import shutil

    tools = PROJECT_ROOT / "dev/wrapper-coder/tools"
    monkeypatch.syspath_prepend(str(tools))
    monkeypatch.setenv("JOB_STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("STATE_DB_FILE", str(state_path))
    monkeypatch.setenv("JOB_DB_FILE", str(jobs_path))
    import coding_tools
    from coordinator import Coordinator
    from coordinator_baseline import binding, files
    from crown_operator_pilot import ENV, CrownOperatorEnrollment
    from read_crown_enrollment import build_enrollment

    wrapper_base = tmp_path / "wrapper"
    monkeypatch.setattr(coding_tools, "BASE", wrapper_base)
    monkeypatch.setattr(coding_tools, "ROOT", wrapper_base / "repo")
    assignment = files(PROJECT_ROOT)
    baseline_sha = binding(assignment)["digest"]
    baseline = wrapper_base / "pilot-bases" / f"crown-{baseline_sha}"
    for name in assignment:
        target = baseline / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PROJECT_ROOT / name, target)

    with closing(SQLiteRepository(jobs_path, "sheet", readonly=True)) as reader:
        value = build_enrollment(reader, tmp_path, PROJECT_ROOT, baseline, baseline_sha, "operator-crown-fixture")
        assert value["request_sha256"] == request_sha
        with pytest.raises(ValueError, match="assignment baseline differs"):
            build_enrollment(reader, tmp_path, PROJECT_ROOT, baseline, "a" * 64, "operator-crown-fixture")
    enrollment = CrownOperatorEnrollment.from_process_environment({ENV: json.dumps(value)})

    def coordinator():
        return Coordinator(
            tmp_path / "receiver", model=no_replay, repair_profile_selector=enrollment.profile,
            company_revision_resolver=lambda cid: proof["source_revision"] if cid == CROWN.company_id else None,
        )

    first = coordinator()
    first.store.set_queue_enabled(False)
    handoff = enrollment.catch_up(first)
    assert handoff["state"] == "CROWN_PILOT_QUEUED", handoff
    assert first.store.pilot_task() == handoff["task_id"]
    task = first.store.get(handoff["task_id"])
    assert task["status"] == "QUEUED"
    assert task["integration"]["source_targets"] == ["src/job_search_helper/successfactors.py"]
    assert task["repair_provenance"]["outcome_id"] == outcome["outcome_id"]
    assert task["max_sessions"] == 4

    restarted = coordinator()
    assert enrollment.catch_up(restarted) == {**handoff, "state": "CROWN_PILOT_ALREADY_PREPARED"}
    assert len(restarted.store.all()) == 1
    assert not restarted.store.queue_enabled()
    assert not restarted.store.campaign_enabled()
    assert not restarted.store.autopilot_enabled()
    assert not restarted.store.unresolved_inferences()
    no_replay.assert_not_called()
