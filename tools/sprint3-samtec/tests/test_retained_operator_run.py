"""Composed operator admission against exact local stores and compact Sheets."""

import base64
from contextlib import closing, redirect_stdout
from datetime import datetime, timedelta, timezone
import io
import json
import sqlite3
from unittest.mock import Mock

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from job_search_helper import ats, cli
from job_search_helper.company_events import source_revision
from job_search_helper.engine import State
from job_search_helper.inbox import InventoryInbox
from job_search_helper.repository import (
    GoogleRepository, MemoryRepository, RepositoryError, UncertainWriteError,
)
from job_search_helper.retained_operator_command import operator_command
from job_search_helper.retained_operator_journal import INVENTORY_FROZEN, SETTLED, RetainedOperatorJournal
from job_search_helper.retained_session_store import RetainedSessionStore
from job_search_helper.retained_work_exception import build_manifest, digest
from job_search_helper.selected_recovery_authorization import canonical
from job_search_helper.sheet_profile import COMPACT_PROFILE, COMPACT_SCHEMAS
from job_search_helper.sqlite_repository import SQLiteRepository
from sheets_fixture import RangeSheets


COMPANY_ID = "COMP-0739"
CYCLE_ID = "CYC-B639C6D864EC"
REQUEST_ID = "samtec-composed-fixture"
BOARD = "https://jobs.jobvite.com/samtec/search"
WORKBOOK = "disposable-operator-fixture"
DESCRIPTION = "Coordinate deployment and customer implementation. " + (
    "Work with the customer on production rollout and testing. " * 130
) + "Exact final description marker."


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


class OperatorFixture:
    def __init__(self, root, monkeypatch):
        self.root = root
        self.state_path = root / "state.db"
        self.jobs_path = root / "jobs.sqlite3"
        self.inbox_path = root / "inventories.sqlite3"
        self.queue_path = root / "next-scan.json"
        self.manifest_path = root / "manifest.json"
        self.approval_path = root / "approval.json"
        self.now = datetime.now(timezone.utc)
        self.runtime = {
            "state": "NO_RELEASE", "source_manifest_sha256": digest("fixture source"),
            "config_sha256": digest("fixture config"),
            "dependency_manifest_sha256": digest("fixture dependencies"),
        }
        selected = {
            "Company ID": COMPANY_ID, "Company": "Samtec", "Company Status": "Active",
            "Official Careers URL": BOARD, "ATS / Source": "Jobvite",
            "Active Cycle ID": CYCLE_ID, "Scan State": "Queued", "Notes": "Keep manual company note",
        }
        other = {
            "Company ID": "COMP-OLD", "Company": "Other", "Company Status": "Active",
            "Official Careers URL": "https://jobs.jobvite.com/other/search", "ATS / Source": "Jobvite",
            "Active Cycle ID": CYCLE_ID, "Scan State": "Inventory Ready",
        }
        self.historical_titles = ["Historical Other", "Previously open Samtec"]
        rows = {
            "Companies": [selected, other],
            "Job History": [
                {"Company": "Other", "Job Title": self.historical_titles[0], "Job Key": "HISTORICAL",
                 "Added to Opportunities?": "Yes", "Review Notes": "Keep reviewer notes",
                 "Official Job URL": "https://jobs.jobvite.com/other/job/old",
                 "Job Status": "Open and verified", "Salary / Range": "$140,000", "Source Hash": "old-source"},
                {"Company": "Samtec", "Job Title": self.historical_titles[1], "Job Key": "SAMTEC-UNSEEN",
                 "Added to Opportunities?": "No", "Review Notes": "Keep manual decision",
                 "Official Job URL": "https://jobs.jobvite.com/samtec/job/unseen",
                 "Job Status": "Open and verified", "Salary / Range": "$175,000",
                 "Consecutive Missing Scans": 2, "Source Hash": "unseen-source"},
            ],
            "Opportunities": [
                {"Company": "Other", "Job Title": self.historical_titles[0], "Opportunity ID": "OP-MANUAL",
                 "Application Status": "Applied", "Notes": "Keep application notes"}
            ],
            "Job Evidence": [
                {"Company": "Other", "Job Title": self.historical_titles[0], "Job Key": "HISTORICAL",
                 "Source Hash": "old-source", "Job Description": "Historical source evidence"}
            ],
            "Scan Cycles": [{"Cycle ID": CYCLE_ID, "Cycle Status": "In Progress"}],
        }
        with closing(SQLiteRepository(self.jobs_path, WORKBOOK, initialize=True)) as local:
            with local.transaction():
                local.set_meta("ready", "yes")
                local.set_meta("sheets_profile", COMPACT_PROFILE)
            local.ensure_columns("Opportunities", ["Opportunity ID"])
            import_source = MemoryRepository(rows, schemas=local.schemas)
            for tab in local.schemas:
                local.import_rows(tab, enumerate(import_source.read(tab), 2))
            self.local_before = {tab: local.read(tab) for tab in local.schemas}
            revision = source_revision(local.matches("Companies", {"Company ID": COMPANY_ID})[0][1])

        past_ids = [f"CYC-HIST-{number:02d}" for number in range(18)]
        cycle = {
            "id": CYCLE_ID, "status": "In Progress", "supersedes": past_ids,
            "companies": {
                COMPANY_ID: {"company": "Samtec", "stage": "queued"},
                "COMP-OLD": {"company": "Other", "stage": "inventory"},
            },
        }
        with closing(State(str(self.state_path))) as state:
            for key in past_ids:
                state.save_cycle({"id": key, "status": "In Progress", "companies": {}})
            state.save_cycle(cycle)
            assert len(state.cycles()) == 19
        with closing(InventoryInbox(self.inbox_path, WORKBOOK)) as inbox:
            inbox.save(CYCLE_ID, "COMP-OLD", {"inventory_status": "complete", "jobs": []})
            inbox.save_plan(CYCLE_ID, "COMP-OLD", [{"historical_fixture_plan": "leave intact"}])
        self.state_before = self.state_path.read_bytes()
        self.inbox_before = self.inbox_path.read_bytes()
        self.manifest = build_manifest(
            cycle, self.inbox_path, self.jobs_path, reason="fixture",
            created_at=self.now.isoformat(),
        )
        write_json(self.manifest_path, {"manifest": self.manifest})
        authorization_scope = {
            "schema": "operator-company-scan-request-v1", "request_id": REQUEST_ID,
            "company_id": COMPANY_ID, "source_revision": revision,
        }
        self.request = {
            "mode": "company-only", "request_id": REQUEST_ID, "company_ids": [COMPANY_ID],
            "source_revision": revision, "operator_request": authorization_scope,
            "start_last": [], "enqueued_at": self.now.isoformat(),
        }
        write_json(self.queue_path, self.request)
        self.request_sha = digest(self.request)
        self.request_receipt = root / "operator-company-requests" / "receipts" / (
            digest({"request_id": REQUEST_ID}) + ".json"
        )
        write_json(self.request_receipt, {
            **authorization_scope, "request_sha256": self.request_sha, "state": "REQUEST_WRITTEN",
        })
        self.request_receipt_before = self.request_receipt.read_bytes()

        self.service = RangeSheets({tab: rows[tab] for tab in COMPACT_SCHEMAS}, schemas=COMPACT_SCHEMAS)
        self.remote_before = {tab: self.remote().read(tab) for tab in COMPACT_SCHEMAS}
        self.open_local = Mock(side_effect=self.open_local_store)
        self.open_remote = Mock(side_effect=self.open_sheet)
        self.fetch = Mock(return_value=ats.Inventory(
            "complete",
            [
                {"title": "Implementation Manager", "posting_id": "42", "location": "Remote, United States",
                 "url": "https://jobs.jobvite.com/samtec/job/42", "description": DESCRIPTION, "ats": "Jobvite"},
                {"title": "Implementation Manager", "posting_id": "43", "location": "Singapore",
                 "url": "https://jobs.jobvite.com/samtec/job/43", "description": "Singapore only.", "ats": "Jobvite"},
            ],
            source_url=BOARD,
            ats="Jobvite",
        ))
        monkeypatch.setattr(cli, "get_repository", self.open_local)
        monkeypatch.setattr(cli, "get_remote_repository", self.open_remote)
        monkeypatch.setattr(ats, "fetch_inventory", self.fetch)
        self.key = Ed25519PrivateKey.generate()
        public_key = self.key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        monkeypatch.setenv("COMPANY_RETAINED_KEY_ID", "fixture-key")
        monkeypatch.setenv("COMPANY_RETAINED_ED25519_PUBLIC_KEY_BASE64", base64.b64encode(public_key).decode("ascii"))
        self.service.before_write = self.assert_publication_locks

    def local(self, *, write=False):
        return SQLiteRepository(self.jobs_path, WORKBOOK, readonly=not write)

    def remote(self):
        return GoogleRepository(self.service, WORKBOOK, schemas=COMPACT_SCHEMAS, min_request_interval=0)

    def open_local_store(self, *, write, interactive):
        assert not interactive
        if write:
            self.assert_held("scraper.lock", "writer.lock")
        return self.local(write=write)

    def open_sheet(self, *, write, interactive, schemas):
        assert not interactive
        assert schemas == COMPACT_SCHEMAS
        if write:
            self.assert_held("scraper.lock", "writer.lock")
        return self.remote()

    def assert_held(self, *locks):
        for name in locks:
            with pytest.raises(cli.WriterLockBusy), cli.writer_lock(self.root / name):
                pass

    def assert_publication_locks(self):
        self.assert_held("scraper.lock", "writer.lock", "retained-publication.lock")

    def command(self, action, *, max_operations=100):
        args = [action, "--cycle-id", CYCLE_ID, "--company-id", COMPANY_ID, "--request-id", REQUEST_ID,
                "--manifest-file", str(self.manifest_path)]
        if action == "preview":
            args.extend(["--expires-at", (self.now + timedelta(hours=1)).isoformat()])
        else:
            args.extend(["--approval-file", str(self.approval_path), "--max-operations", str(max_operations)])
        output = io.StringIO()
        with cli.writer_lock(self.root / "scraper.lock"), redirect_stdout(output):
            assert operator_command(args, (self.state_path, self.jobs_path, self.runtime)) == 0
        return json.loads(output.getvalue())

    def sign(self):
        claims = self.command("preview")["required_claims"]
        write_json(self.approval_path, {
            "payload": claims, "key_id": "fixture-key",
            "signature": base64.b64encode(self.key.sign(canonical(claims))).decode("ascii"),
        })
        return claims

    def assert_historical_records_unchanged(self):
        assert self.state_path.read_bytes() == self.state_before
        assert self.inbox_path.read_bytes() == self.inbox_before
        assert self.request_receipt.read_bytes() == self.request_receipt_before
        with closing(self.local()) as local:
            for tab in ("Companies", "Opportunities", "Scan Cycles"):
                assert local.read(tab) == self.local_before[tab]
            for tab in ("Job History", "Job Evidence"):
                existing = {row["Job Key"]: row for row in local.read(tab)}
                for row in self.local_before[tab]:
                    assert existing[row["Job Key"]] == row
        remote = self.remote()
        for tab in ("Companies", "Opportunities"):
            assert remote.read(tab) == self.remote_before[tab]
        existing = {row["Job Key"]: row for row in remote.read("Job History")}
        for row in self.remote_before["Job History"]:
            assert existing[row["Job Key"]] == row


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    return OperatorFixture(tmp_path, monkeypatch)


def test_compact_preview_signs_exact_membership_without_mutating_stores(fixture):
    before = fixture.jobs_path.read_bytes()
    claims = fixture.sign()
    assert (claims["company_id"], claims["cycle_id"], claims["request_id"]) == (COMPANY_ID, CYCLE_ID, REQUEST_ID)
    assert claims["request_sha256"] == fixture.request_sha
    assert claims["runtime_sha256"] == digest(fixture.runtime)
    assert fixture.jobs_path.read_bytes() == before
    assert not fixture.service.batches
    assert RetainedOperatorJournal(fixture.root).inspect() is None
    fixture.fetch.assert_not_called()
    fixture.assert_historical_records_unchanged()


def test_compact_execute_refuses_missing_destination_tab_before_fetch(fixture):
    fixture.sign()
    fixture.service.sheets[:] = [
        sheet for sheet in fixture.service.sheets if sheet["properties"]["title"] != "Job History"
    ]
    with pytest.raises(RepositoryError, match="Missing tab: Job History"):
        fixture.command("execute")

    fixture.fetch.assert_not_called()
    assert not fixture.service.batches
    assert RetainedOperatorJournal(fixture.root).inspect() is None
    assert not (fixture.root / "retained-sessions.sqlite3").exists()
    assert fixture.queue_path.exists()


@pytest.mark.parametrize(
    ("posting_ids", "tamper_readback"),
    [(("42",), False), (("42", "43"), False), (("42",), True), (("43",), False)],
    ids=["eligible-only", "mixed-screening", "changed-readback", "all-screened"],
)
def test_compact_operator_lost_ack_readback_and_terminal_replay(fixture, posting_ids, tamper_readback):
    fixture.fetch.return_value.jobs[:] = [
        posting for posting in fixture.fetch.return_value.jobs if posting["posting_id"] in posting_ids
    ]
    fixture.sign()
    fixture.service.lose_response = True
    with pytest.raises(UncertainWriteError):
        fixture.command("execute")

    fixture.fetch.assert_called_once_with("Jobvite", BOARD, COMPANY_ID, "Samtec")
    frozen = RetainedOperatorJournal(fixture.root).inspect()
    assert frozen["state"] == INVENTORY_FROZEN
    reservation = frozen["binding"]["reservation_digest"]
    with closing(RetainedSessionStore(fixture.root / "retained-sessions.sqlite3")) as sessions:
        pending = sessions.load(reservation)
    assert pending["state"] == "SYNC_PENDING"
    assert [chunk["state"] for chunk in pending["chunks"]] == ["CLAIMED"]
    plan = pending["plan"]
    assert plan["retained_membership_only"] is True
    assert plan["runtime_binding_sha256"] == digest(fixture.runtime)
    assert {operation["tab"] for operation in plan["local_operations"]} == {"Job History", "Job Evidence"}
    expected_ids = set(posting_ids)
    assert [operation["tab"] for operation in plan["remote_projection"]] == ["Job History"] * len(expected_ids)

    assert json.loads(fixture.queue_path.read_bytes()) == fixture.request
    assert len(fixture.service.batches) == 1
    rows = {row["Requisition ID"]: row for row in fixture.remote().read("Job History")
            if row["Job Title"] not in fixture.historical_titles}
    assert set(rows) == expected_ids
    assert {(row["Company"], row["Job Title"]) for row in rows.values()} == {("Samtec", "Implementation Manager")}
    if "42" in rows:
        assert rows["42"]["Added to Opportunities?"] == "Pending"
    if "43" in rows:
        assert rows["43"]["Added to Opportunities?"] == "No"
        assert "outside the U.S." in rows["43"]["Rejection Reason"]
    representative_id = posting_ids[0]
    job_key = rows[representative_id]["Job Key"]
    fixture.assert_historical_records_unchanged()
    reads_before_recovery = len(fixture.service.get_calls)

    if tamper_readback:
        row_number, = (number for number, row in fixture.remote().read_columns("Job History", ["Job Key"])
                       if row["Job Key"] == job_key)
        fixture.service.set_cell("Job History", row_number - 1, "Location", "Changed after lost acknowledgement")
        with pytest.raises(ValueError, match="remote readback differs from the frozen projection"):
            fixture.command("execute")
        with closing(RetainedSessionStore(fixture.root / "retained-sessions.sqlite3")) as sessions:
            assert sessions.load(reservation)["chunks"] == pending["chunks"]
        assert fixture.queue_path.exists()
        assert len(fixture.service.batches) == 1
        fixture.fetch.assert_called_once()
        fixture.service.set_cell("Job History", row_number - 1, "Location", rows["42"]["Location"])

    result = fixture.command("execute", max_operations=1)
    assert result["state"] == "SYNC_CONFIRMED"
    assert result["reservation_digest"] == reservation
    assert result["plan_digest"] == plan["plan_digest"]
    assert result["projection_digest"] == plan["remote_projection_digest"]
    assert result["inventory_sha256"] == frozen["inventory_sha256"]
    assert len(fixture.service.get_calls) > reads_before_recovery
    assert len(fixture.service.batches) == 1
    with closing(RetainedSessionStore(fixture.root / "retained-sessions.sqlite3")) as sessions:
        final = sessions.load(reservation)
    assert final["state"] == "SYNC_CONFIRMED"
    assert [chunk["state"] for chunk in final["chunks"]] == ["CONFIRMED"]

    with closing(fixture.local()) as local:
        assert local.db.execute(
            "SELECT company,plan_digest,state FROM exact_local_applications"
        ).fetchall() == [(COMPANY_ID, result["plan_digest"], "VERIFIED")]
        assert local.db.execute(
            "SELECT receipt_id,acknowledgement_id FROM exact_local_acknowledgements"
        ).fetchall() == [(result["receipt_id"], result["acknowledgement_id"])]
        assert local.db.execute("SELECT count(*) FROM dirty").fetchone() == (0,)
        history = local.matches("Job History", {"Job Key": job_key})[0][1]
        evidence = local.matches("Job Evidence", {"Job Key": job_key, "Source Hash": history["Source Hash"]})
        assert len(evidence) == 1
        assert evidence[0][1]["Job Description"] == (DESCRIPTION if representative_id == "42" else "Singapore only.")
        queue, = local.db.execute(
            "SELECT queue_evidence FROM retained_publications WHERE reservation_digest=?", (reservation,)
        ).fetchone()
        queue_evidence = json.loads(queue)
        assert digest(queue_evidence) == result["first_pass_evidence_sha256"]
        assert {item["job_key"] for item in queue_evidence["selected_jobs"]} == {
            row["Job Key"] for row in rows.values()
        }
        first_pass = fixture.root.joinpath(queue_evidence["output_dir"], "first-pass.jsonl")
        second_pass = fixture.root.joinpath(queue_evidence["output_dir"], "second-pass.jsonl")
        review_keys = {json.loads(line)["job_key"] for path in (first_pass, second_pass)
                       for line in path.read_text(encoding="utf-8").splitlines()}
        assert review_keys == ({rows["42"]["Job Key"]} if "42" in rows else set())

    journal = RetainedOperatorJournal(fixture.root)
    assert journal.inspect() is None
    archived_journal = journal.read_archived(frozen["binding"])
    assert archived_journal["state"] == SETTLED
    assert archived_journal["consumption"] == result["consumption"]
    assert not fixture.queue_path.exists()
    archive = fixture.root / "company-event-bridge" / "consumed-requests" / (fixture.request_sha + ".json")
    assert json.loads(archive.read_bytes()) == fixture.request
    archived_bytes = archive.read_bytes()

    replacement = {"request_id": "new-unrelated-request", "mode": "company-only", "company_ids": ["COMP-OLD"]}
    write_json(fixture.queue_path, replacement)
    replacement_bytes = fixture.queue_path.read_bytes()
    fixture.open_remote.reset_mock()
    fixture.open_local.reset_mock()
    fixture.fetch.reset_mock()
    assert fixture.command("execute") == result
    assert fixture.command("execute") == result
    fixture.open_remote.assert_not_called()
    fixture.fetch.assert_not_called()
    assert fixture.open_local.call_count == 2
    assert all(call.kwargs == {"write": False, "interactive": False} for call in fixture.open_local.call_args_list)
    assert len(fixture.service.batches) == 1
    if tamper_readback:
        first_pass.write_bytes(first_pass.read_bytes() + b"changed fixture release\n")
        with pytest.raises(ValueError, match="retained_first_pass_release_file_changed"):
            fixture.command("execute")
        fixture.open_remote.assert_not_called()
        fixture.fetch.assert_not_called()
        assert fixture.open_local.call_args.kwargs == {"write": False, "interactive": False}
    assert archive.read_bytes() == archived_bytes
    assert fixture.queue_path.read_bytes() == replacement_bytes
    fixture.assert_historical_records_unchanged()
