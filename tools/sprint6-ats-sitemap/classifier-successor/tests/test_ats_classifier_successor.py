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


def test_fresh_classifier_successor_preserves_terminal_parent(tmp_path, monkeypatch):
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
            "src/job_search_helper/ats_job_path.py",
        }
        assert read_operator_partial_source(reader, outcome, "a" * 64, scope=ATS_CORPORATION) is None
        assert read_operator_partial_source(reader, outcome, request_sha, scope=CROWN) is None
        assert state.cycle(result["cycle_id"])["companies"][ATS_CORPORATION.company_id]["stage"] == "partial"
        assert reader.scrape_outcomes(company_id=ATS_CORPORATION.company_id) == [outcome]
        assert reader.matches("Companies", {"Company ID": other["Company ID"]}) == other_before
        assert inbox.connection.execute("SELECT count(*) FROM inventories").fetchone() == (0,)
        assert inbox.connection.execute("SELECT count(*) FROM publication_receipts").fetchone() == (0,)

    import shutil
    import coding_tools
    import embraer_operator_pilot
    from ats_operator_pilot import ATSOperatorEnrollment, ENV
    from ats_parser_assignment import EDIT_ANCHOR, TARGET
    from coordinator import Coordinator
    from coordinator_baseline import binding, files
    from coordinator_store import Store, OUTCOME_DELIVERY_CONSUMER, task_state_digest

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

    predecessor = outcome
    store = Store(receiver)
    prior_receipt = store.ingest_scrape_outcome_delivery_v1(OUTCOME_DELIVERY_CONSUMER, predecessor)
    repair_key, = [item['repair_key'] for item in store.held_repair_intake()]
    parent_id = "WRAP-1234567890"
    parent = {
        "id": parent_id, "status": "PAUSED_TEST_FAILURE", "phase": "verify",
        "stop_requested": False, "calls": 1, "sessions": 1, "tokens": 1478,
        "held_repair_key": repair_key,
        "integration": {"work_order": "successfactors-ats-sitemap-parser-v1"},
    }
    serialized_parent = json.dumps(parent)
    prior_request = ("prior-inference", parent_id, "COMPLETED", "{}")
    with store.connect() as con:
        con.execute("INSERT INTO tasks VALUES (?,?)", (parent_id, serialized_parent))
        con.execute("UPDATE repair_intake SET task_id=?,status='PROMOTED_PAUSED' WHERE repair_key=?", (parent_id,repair_key))
        con.execute("INSERT INTO inference_receipts VALUES (?,?,?,?)", prior_request)
    store.set_queue_enabled(False)

    second_id = "operator-ats-fixture-next"
    with closing(SQLiteRepository(jobs_path, "sheet")) as repository:
        queue_operator_company_request(repository, tmp_path, ATS_CORPORATION.company_id, second_id)
    second_sha = _digest(json.loads(queued.read_text()))
    with writer_lock(tmp_path / "scraper.lock"):
        fresh = execute_operator_partial(
            (state_path, jobs_path, runtime), request_sha256=second_sha,
            fetcher=fetch, remote_reader=remote, scope=ATS_CORPORATION,
        )
    assert fresh["state"] == "FETCH_REPAIR_QUALIFIED", fresh
    outcome = fresh["outcome"]
    assert outcome["outcome_id"] != predecessor["outcome_id"]
    assert outcome["failure_fingerprint"] == predecessor["failure_fingerprint"]
    enrollment = ATSOperatorEnrollment.from_process_environment({ENV: json.dumps({
        "request_id": second_id, "source_revision": proof["source_revision"],
        "request_sha256": second_sha, "baseline_sha256": baseline_sha, "source_files": proof["source_files"],
        "successor": {
            "outcome_id": outcome["outcome_id"], "predecessor_outcome_id": predecessor["outcome_id"],
            "predecessor_repair_key": repair_key, "predecessor_task_id": parent_id,
            "predecessor_task_state_sha256": task_state_digest(parent),
            "failure_fingerprint": predecessor["failure_fingerprint"],
        },
    })})

    calls = []
    new = """def classify_job_path(path: str) -> str:
    match = re.fullmatch(r"/(?:(?:PA|Comecer)/)?job/[^/]+/([0-9]{4,24})/", path)
    if match is None:
        raise ValueError("Unexpected ATS posting path")
    return match.group(1)"""

    def model(history, schemas, limit):
        assert [schema["function"]["name"] for schema in schemas] == ["code_edit"]
        packet = json.loads(history[-1]["content"])
        assert packet["old"] == EDIT_ANCHOR and packet["path"] == TARGET
        calls.append(1)
        return {
            "id": "fixture-single-edit",
            "message": {"tool_calls": [{"function": {"name": "code_edit", "arguments": {
                "path": TARGET, "sha256": pinned[TARGET], "old": EDIT_ANCHOR, "new": new,
            }}}]},
            "usage": {"prompt_eval_count": 800, "eval_count": 200, "done_reason": "tool_calls"},
        }

    coordinator = Coordinator(
        receiver, model=model, repair_profile_selector=enrollment.profile,
        company_revision_resolver=lambda cid: proof["source_revision"] if cid == ATS_CORPORATION.company_id else None,
        owned_parser_reader=lambda state: enrollment.approved_edit_owner(coordinator, state),
    )
    admitted = enrollment.catch_up(coordinator)
    assert admitted.get("task_id") is not None, admitted
    task_id = admitted["task_id"]
    assert coordinator.store.pilot_task() == task_id != parent_id
    assert coordinator.store.get(task_id)["held_repair_key"] == store._operator_successor_repair_key(repair_key)
    assert enrollment.catch_up(coordinator)["task_id"] == task_id
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
    assert new in (receiver / task_id / "repo" / TARGET).read_text()
    assert store.get(parent_id) == parent
    assert store.ingest_scrape_outcome_delivery_v1(OUTCOME_DELIVERY_CONSUMER, predecessor) == prior_receipt
    with store.connect() as con:
        assert con.execute("SELECT * FROM inference_receipts WHERE task=?", (parent_id,)).fetchall() == [prior_request]
    assert sheets.request_bytes == 0
    assert not store.queue_enabled()
    assert not store.campaign_enabled()
