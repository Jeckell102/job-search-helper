"""Disposable proof that ATS Corporation's public partial is a durable owned outcome."""

from contextlib import closing
import json
from unittest.mock import Mock

import pytest

from collections import Counter
from hashlib import sha256
from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.cli import PROJECT_ROOT, writer_lock
from job_search_helper.engine import State
from job_search_helper.inbox import InventoryInbox
from job_search_helper.integration_release import source_tree_digest
from job_search_helper.operator_amphenol_settlement import execute_operator_partial
from job_search_helper.operator_company_request import _digest, queue_operator_company_request
from job_search_helper.operator_embraer_settlement import read_operator_partial_source
from job_search_helper.operator_partial_scope import ATS_CORPORATION, CROWN
from job_search_helper.repository import GoogleRepository
from job_search_helper.sheet_profile import COMPACT_PROFILE, COMPACT_SCHEMAS
from job_search_helper.sqlite_repository import SQLiteRepository
from sheets_fixture import RangeSheets


HOST = 'https://jobs.atsautomation.com'
PATHS = ('/job/Buyer/10001/', '/PA/job/Integration-Engineer/10002/', '/Comecer/job/Designer/10003/')


def anchors(paths):
    return ''.join(f'<a class="jobTitle-link" href="{path}">Role</a>' for path in paths)


class ATSBoard:
    def __init__(self, body, status=200):
        self.body = body.encode()
        self.status = status
        self.calls = Counter()

    def get(self, url):
        assert url == ATS_CORPORATION.board_url
        self.calls[url] += 1
        return HTTPResponse(self.status, self.body)


def test_exact_partial_settles_once_without_job_publication(tmp_path, monkeypatch):
    state_path = tmp_path / "state.db"
    jobs_path = tmp_path / "jobs.sqlite3"
    inbox_path = tmp_path / "inventories.sqlite3"
    company = {
        "Company ID": ATS_CORPORATION.company_id,
        "Company": ATS_CORPORATION.company_name,
        "Company Status": "Active",
        "Official Careers URL": ATS_CORPORATION.careers_url,
        "ATS / Source": ATS_CORPORATION.provider,
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
        with pytest.raises(ValueError, match="operator_ats_request_identity_invalid"):
            queue_operator_company_request(writer, tmp_path, other["Company ID"], "operator-ats-wrong")
        assert not (tmp_path / "next-scan.json").exists()
        queue_operator_company_request(writer, tmp_path, ATS_CORPORATION.company_id, "operator-ats-fixture")
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
    valid = anchors(PATHS + PATHS)
    board = ATSBoard(valid)
    for markup, status in [
        ("", 200),
        (valid, 403),
        (valid + anchors(('/Other/job/Outside/10004/',)), 200),
        (valid + anchors(('https://other.invalid/job/Outside/10004/',)), 200),
        (valid + anchors(('/job/Other-slug/10001/',)), 200),
        (valid + 'Results <strong>1-3</strong> of <strong>3</strong>', 200),
        (valid + 'Results <b>1-3</b> of <b>3</b> Results <b>1-3</b> of <b>5</b>', 200),
    ]:
        unqualified = fetch_inventory(ATS_CORPORATION.provider, ATS_CORPORATION.careers_url,
                                      ATS_CORPORATION.company_id, ATS_CORPORATION.company_name,
                                      discovery_transport=ATSBoard(markup, status))
        assert unqualified.outcome_failure is None
    wrong = fetch_inventory(ATS_CORPORATION.provider, ATS_CORPORATION.board_url, 'COMP-9999', 'Other',
                            discovery_transport=ATSBoard(valid))
    assert wrong.outcome_failure is None

    def fetch(provider, source, company_id, name):
        inventory = fetch_inventory(provider, source, company_id, name, discovery_transport=board)
        url_set = '\n'.join(sorted(HOST + path for path in PATHS))
        assert inventory.outcome_failure == {
            'schema': 'outcome-failure-v1', 'category': 'pagination_regression',
            'evidence_code': ATS_CORPORATION.failure_code,
            'evidence': {'company_id': ATS_CORPORATION.company_id, 'board': ATS_CORPORATION.board_url,
                         'listing_count': len(PATHS), 'listing_sha256': sha256(url_set.encode()).hexdigest()},
        }
        return inventory

    from job_search_helper.operator_selected_observation import _validate_request

    unqualified = json.loads(queued.read_text())
    unqualified["request_id"] = "operator-plain"
    unqualified["operator_request"]["request_id"] = "operator-plain"
    with pytest.raises(ValueError, match="operator_selected_observation_request_scope_invalid"):
        _validate_request(unqualified, {}, request_sha, ATS_CORPORATION)

    def settle(fetcher, remote_reader):
        with writer_lock(tmp_path / "scraper.lock"):
            return execute_operator_partial(
                (state_path, jobs_path, runtime), request_sha256=request_sha,
                fetcher=fetcher, remote_reader=remote_reader, scope=ATS_CORPORATION,
            )

    result = settle(fetch, remote)
    assert result["state"] == "FETCH_REPAIR_QUALIFIED", result
    assert not queued.exists()
    assert dict(board.calls) == {ATS_CORPORATION.board_url: 1}
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
        proof = read_operator_partial_source(reader, outcome, request_sha, scope=ATS_CORPORATION)
        assert proof["evidence_code"] == ATS_CORPORATION.failure_code
        assert proof["settlement_sha256"] == result["settlement_sha256"]
        assert set(proof["source_files"]) == {
            "src/job_search_helper/successfactors.py", "src/job_search_helper/ats.py",
            "src/job_search_helper/successfactors_sitemap.py", "src/job_search_helper/ats_sitemap_parser.py",
        }
        assert read_operator_partial_source(reader, outcome, "a" * 64, scope=ATS_CORPORATION) is None
        assert read_operator_partial_source(reader, outcome, request_sha, scope=CROWN) is None
        assert state.cycle(result["cycle_id"])["companies"][ATS_CORPORATION.company_id]["stage"] == "partial"
        assert reader.scrape_outcomes(company_id=ATS_CORPORATION.company_id) == [outcome]
        assert reader.matches("Companies", {"Company ID": other["Company ID"]}) == other_before
        assert inbox.connection.execute("SELECT count(*) FROM inventories").fetchone() == (0,)
        assert inbox.connection.execute("SELECT count(*) FROM publication_receipts").fetchone() == (0,)

    # Rehearse the exact host progression with one synthetic model response.
    import shutil

    import coding_tools
    import embraer_operator_pilot
    from ats_operator_pilot import ATSOperatorEnrollment
    from ats_parser_assignment import TARGET
    from coordinator import Coordinator
    from coordinator_baseline import binding, files

    base = tmp_path / "wrapper"
    receiver = base / "tasks"
    monkeypatch.setattr(embraer_operator_pilot, "__file__",
                        str(PROJECT_ROOT / "dev/wrapper-coder/tools/embraer_operator_pilot.py"))
    monkeypatch.setattr(coding_tools, "BASE", base)
    monkeypatch.setattr(coding_tools, "ROOT", base / "repo")
    monkeypatch.setenv("JOB_STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("STATE_DB_FILE", str(state_path))
    monkeypatch.setenv("JOB_DB_FILE", str(jobs_path))
    pinned = files(PROJECT_ROOT)
    baseline_sha = binding(pinned)["digest"]
    baseline = base / "pilot-bases" / f"{ATS_CORPORATION.slug}-{baseline_sha}"
    for relative in pinned:
        target = baseline / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PROJECT_ROOT / relative, target)
    pins = proof["source_files"]
    enrollment = ATSOperatorEnrollment(
        outcome["identity"]["request_id"], proof["source_revision"], request_sha,
        pins["src/job_search_helper/successfactors.py"], pins["src/job_search_helper/ats.py"],
        baseline_sha, input_pins=pins,
    )
    before = (baseline / TARGET).read_text()
    calls = []

    def model(history, schemas, limit):
        assert [schema["function"]["name"] for schema in schemas] == ["code_edit"]
        assert len(history) == 2
        assert 256 <= limit <= 1600
        calls.append(1)
        return {
            "id": "fixture-single-edit",
            "message": {"tool_calls": [{"function": {"name": "code_edit", "arguments": {
                "path": TARGET, "sha256": pinned[TARGET], "old": before,
                "new": before.replace("PARSER_READY = False", "PARSER_READY = True"),
            }}}]},
            "usage": {"prompt_eval_count": 800, "eval_count": 200, "done_reason": "tool_calls"},
        }

    coordinator = Coordinator(
        receiver, model=model, repair_profile_selector=enrollment.profile,
        company_revision_resolver=lambda cid: proof["source_revision"] if cid == ATS_CORPORATION.company_id else None,
        owned_parser_reader=lambda state: enrollment.approved_edit_owner(coordinator, state),
    )
    coordinator.store.set_queue_enabled(False)
    admitted = enrollment.catch_up(coordinator)
    assert admitted.get("task_id") is not None, admitted
    assert coordinator.store.pilot_task() == admitted["task_id"]
    task_id = admitted["task_id"]
    monkeypatch.setattr(coordinator, "tests", lambda state: False)
    for phase in ("baseline", "inspect", "implement"):
        assert coordinator.store.get(task_id)["phase"] == phase
        assert coordinator.store.claim_pilot(task_id)
        coordinator.step(task_id)
    current = coordinator.store.get(task_id)
    assert current["phase"] == "verify", current["reason"]
    assert current["calls"] == current["sessions"] == len(calls) == 1
    edits = [receipt for receipt in coordinator.store.receipts(task_id) if receipt["name"] == "code_edit"]
    assert len(edits) == 1 and edits[0]["arguments"]["path"] == TARGET
    assert (receiver / task_id / "repo" / TARGET).read_text().count("PARSER_READY = True") == 1
    assert not coordinator.store.queue_enabled()
    assert not coordinator.store.campaign_enabled()
    no_replay.assert_not_called()
