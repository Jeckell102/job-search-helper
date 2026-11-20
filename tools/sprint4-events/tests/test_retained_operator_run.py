"""Composed operator admission against exact local stores and compact Sheets."""

import base64
from contextlib import closing, redirect_stdout
from datetime import datetime, timedelta, timezone
import io
from itertools import count
import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from job_search_helper import ats, cli, repository, retained_work_orchestrator
from job_search_helper.company_events import CompanyEventBridge, source_revision
from job_search_helper.engine import State
from job_search_helper.evidence_archives import EvidenceArchives
from job_search_helper.exact_cycle_planner import _exact_plan_digest
from job_search_helper.inbox import InventoryInbox
from job_search_helper.publication_receipts import record_fingerprints
from job_search_helper.repository import (
    GoogleRepository, MemoryRepository, RepositoryError, UncertainWriteError,
)
from job_search_helper.retained_dirty_provenance import retained_publication
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
    def __init__(self, root, monkeypatch, *, real_remote=False, company_event=False):
        self.root = root
        self.company_event = company_event
        self.request_id = REQUEST_ID
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
        if company_event:
            selected["Active Cycle ID"] = ""
            selected["Scan State"] = ""
            selected["Official Careers URL"] = "https://jobs.jobvite.com/samtec/old"
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
            "Scan Cycles": [{"Cycle ID": CYCLE_ID, "Cycle Status": "In Progress",
                             "Notes": json.dumps({"company_ids": ["COMP-OLD"]}) if company_event else ""}],
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
        if company_event:
            del cycle["companies"][COMPANY_ID]
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
        if company_event:
            with closing(self.local(write=True)) as local:
                updated = dict(selected, **{"Official Careers URL": BOARD})
                event = local.import_companies_with_events(
                    [(2, updated)], origin="sheets-reconciliation",
                )["company_events"][0]
                CompanyEventBridge(local, root).stage_manual_retained_event(
                    event["event_id"], company_id=COMPANY_ID, source_revision=event["source_revision"],
                    blocking_cycle_id=CYCLE_ID,
                )
                self.local_before = {tab: local.read(tab) for tab in local.schemas}
            selected["Official Careers URL"] = BOARD
            self.request = json.loads(self.queue_path.read_bytes())
            self.request_id = self.request["request_id"]
            self.request_receipt = root / "company-event-bridge" / "receipts" / (event["event_id"] + ".json")
        else:
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
            self.request_receipt = root / "operator-company-requests" / "receipts" / (
                digest({"request_id": REQUEST_ID}) + ".json"
            )
            write_json(self.request_receipt, {
                **authorization_scope, "request_sha256": digest(self.request), "state": "REQUEST_WRITTEN",
            })
        self.request_sha = digest(self.request)
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
        if not real_remote:
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

    def open_sheet(self, *, write, interactive, schemas, evidence_archives=True):
        assert not interactive and not evidence_archives
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

    def command(self, action, *, max_operations=100, company_event=None):
        args = [action, "--cycle-id", CYCLE_ID, "--company-id", COMPANY_ID, "--request-id", self.request_id,
                "--manifest-file", str(self.manifest_path)]
        if company_event is None:
            company_event = self.company_event
        if company_event:
            args.append("--company-event")
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


def test_existing_selected_salary_and_manual_edit_remain_protected(fixture):
    inventory = fixture.fetch.return_value
    posting = inventory.jobs[0]
    inventory.jobs[:] = [posting]
    provider_observed_at = []

    def fetch_inventory(*_args):
        provider_observed_at.append(datetime.now(timezone.utc))
        return inventory

    fixture.fetch.side_effect = fetch_inventory
    assert "compensation" not in posting
    job_key = "comp-0739:jobvite:42"
    estimate = "$120,000–$140,000 estimated"
    prior = {
        "Job Key": job_key, "Company": "Samtec", "Requisition ID": "42", "Job Title": posting["title"],
        "Official Job URL": posting["url"], "Location": "Remote",
        "Job Status": "Open and verified", "Added to Opportunities?": "Manual Review",
        "Review Status": "Manual Review", "Review Notes": "Reviewer supplied salary estimate",
        "Salary / Range": estimate,
    }
    with closing(fixture.local(write=True)) as local:
        local.import_rows("Job History", [(4, prior)])
    for header, value in prior.items():
        fixture.service.set_cell("Job History", 3, header, value)
    fixture.sign()
    fixture.service.lose_response = True
    with pytest.raises(UncertainWriteError):
        fixture.command("execute")

    journal = RetainedOperatorJournal(fixture.root).inspect()
    reservation = journal["binding"]["reservation_digest"]
    provider_entered_at, = provider_observed_at
    frozen_inventory = journal["inventory"]
    started_at = datetime.fromisoformat(frozen_inventory["fetch_started_at"])
    completed_at = datetime.fromisoformat(frozen_inventory["fetched_at"])
    assert fixture.now <= started_at <= provider_entered_at <= completed_at <= datetime.now(timezone.utc)
    with closing(RetainedSessionStore(fixture.root / "retained-sessions.sqlite3")) as sessions:
        pending = sessions.load(reservation)
    local_operation, = (operation for operation in pending["plan"]["local_operations"]
                        if operation["tab"] == "Job History")
    remote_operation, = pending["plan"]["remote_projection"]
    for operation in (local_operation, remote_operation):
        assert operation["expected"]["Location"] == prior["Location"]
        assert operation["expected"]["Salary / Range"] == estimate
        assert "Salary / Range" not in operation.get("values", {})
        assert operation["expected"]["Added to Opportunities?"] == "Manual Review"
        assert "Added to Opportunities?" not in operation.get("values", {})

    remote = fixture.remote()
    row = remote.read_row("Job History", 4)
    assert row["Location"] == posting["location"]
    assert row["Salary / Range"] == estimate
    assert row["Review Notes"] == prior["Review Notes"]
    fixture.service.set_cell("Job History", 3, "Added to Opportunities?", "Yes")
    with pytest.raises(ValueError, match="remote guard differs from the frozen projection"):
        fixture.command("execute")
    with closing(RetainedSessionStore(fixture.root / "retained-sessions.sqlite3")) as sessions:
        assert sessions.load(reservation)["chunks"] == pending["chunks"]
    assert fixture.remote().read_row("Job History", 4)["Added to Opportunities?"] == "Yes"
    with closing(fixture.local()) as local:
        assert local.db.execute("SELECT count(*) FROM exact_local_acknowledgements").fetchone() == (0,)
    assert fixture.queue_path.exists()
    assert len(fixture.service.batches) == 1

    fixture.service.set_cell("Job History", 3, "Added to Opportunities?", "Manual Review")
    result = fixture.command("execute")
    assert result["state"] == "SYNC_CONFIRMED"
    archived = RetainedOperatorJournal(fixture.root).read_archived(journal["binding"])
    assert archived["inventory"]["fetch_started_at"] == frozen_inventory["fetch_started_at"]
    assert result["inventory_sha256"] == archived["inventory_sha256"] == digest(frozen_inventory)
    fixture.fetch.assert_called_once_with("Jobvite", BOARD, COMPANY_ID, "Samtec")
    assert len(fixture.service.batches) == 1
    with closing(fixture.local()) as local:
        final = local.matches("Job History", {"Job Key": job_key})[0][1]
        assert final["Salary / Range"] == estimate
        assert final["Added to Opportunities?"] == "Manual Review"
        assert final["Review Notes"] == prior["Review Notes"]
    row = fixture.remote().read_row("Job History", 4)
    assert row["Salary / Range"] == estimate
    assert row["Added to Opportunities?"] == "Manual Review"
    fixture.assert_historical_records_unchanged()


def test_publisher_entry_stop_leaves_verified_local_commit_and_resumes_once(fixture, monkeypatch):
    claims = fixture.sign()
    envelope = json.loads(fixture.approval_path.read_bytes())
    fixture.key.public_key().verify(base64.b64decode(envelope["signature"]), canonical(claims))

    publisher = Mock(side_effect=InterruptedError("fixture stopped at publisher entry"))
    with monkeypatch.context() as stop:
        stop.setattr(retained_work_orchestrator, "_publish_retained_reservation", publisher)
        with pytest.raises(InterruptedError, match="stopped at publisher entry"):
            fixture.command("execute", max_operations=3)
    publisher.assert_called_once()
    fixture.fetch.assert_called_once_with("Jobvite", BOARD, COMPANY_ID, "Samtec")
    assert not fixture.service.batches
    assert json.loads(fixture.queue_path.read_bytes()) == fixture.request

    frozen = RetainedOperatorJournal(fixture.root).inspect()
    assert frozen["state"] == INVENTORY_FROZEN
    binding = frozen["binding"]
    reservation = binding["reservation_digest"]
    assert binding["claims"] == claims
    assert binding["authorization"]["claims_digest"] == digest(claims)
    assert binding["runtime"] == fixture.runtime
    assert claims["request_sha256"] == fixture.request_sha
    assert claims["source_revision"] == fixture.request["source_revision"]

    def read_session():
        with closing(RetainedSessionStore(fixture.root / "retained-sessions.sqlite3")) as store:
            return store.load(reservation)

    local_only = read_session()
    plan = local_only["plan"]
    assert local_only["state"] == "RESERVED"
    assert local_only["chunks"] == [] and local_only["remote_cursor"] == 0
    assert all(local_only[field] is None for field in ("receipt_id", "intent_id", "acknowledgement_id"))
    assert (local_only["request_id"], local_only["company_id"], local_only["source_revision"]) == (
        REQUEST_ID, COMPANY_ID, claims["source_revision"],
    )
    assert local_only["exception_cycle_id"] == CYCLE_ID
    assert local_only["cycle_id"] != CYCLE_ID
    assert plan["runtime_binding_sha256"] == claims["runtime_sha256"]
    assert _exact_plan_digest(plan) == local_only["plan_digest"]

    def read_local_chunks(local, apply_id):
        return local.db.execute(
            "SELECT start_cursor,operation_count,operations_digest,expected_records,"
            "expected_records_digest,state,applied_at,verified_at FROM exact_local_apply_chunks "
            "WHERE apply_id=? ORDER BY start_cursor", (apply_id,),
        ).fetchall()

    with closing(fixture.local()) as local:
        parent, = local.db.execute(
            "SELECT apply_id,cycle,company,plan_digest,state FROM exact_local_applications"
        ).fetchall()
        apply_id = parent[0]
        assert parent[1:] == (local_only["cycle_id"], COMPANY_ID, local_only["plan_digest"], "VERIFIED")
        provenance = retained_publication(local, reservation)
        assert provenance["state"] == "LOCAL_VERIFIED"
        assert provenance["local_apply_id"] == apply_id
        assert provenance["plan_digest"] == local_only["plan_digest"]
        assert provenance["source_revision"] == claims["source_revision"]
        assert provenance["cells_digest"]
        assert all(provenance[field] is None for field in ("receipt_id", "intent_id", "acknowledgement_id"))
        assert local.db.execute("SELECT count(*) FROM exact_local_acknowledgements").fetchone() == (0,)
        chunks = read_local_chunks(local, apply_id)
        operations = plan["local_operations"]
        guard_only = plan.get("record_fingerprint_version", 1) == 2
        assert len(operations) == 4
        assert [(chunk[0], chunk[1]) for chunk in chunks] == [(0, 3), (3, 1)]
        verified_records = {}
        for cursor, count, operation_sha, records, records_sha, state, applied, verified in chunks:
            assert state == "VERIFIED" and applied and verified
            selected = operations[cursor:cursor + count]
            assert operation_sha == digest(selected)
            rows = {}
            for operation in selected:
                tab = operation["tab"]
                (_, row), = local.matches(tab, operation["identity"])
                rows.setdefault(tab, []).append(row)
            observed = record_fingerprints(selected, rows, include_guard_only=guard_only)
            assert observed == json.loads(records)
            assert records_sha == digest(observed)
            verified_records.update(observed)
        assert verified_records == plan["local_expected_records"]
        assert digest(verified_records) == plan["local_expected_records_digest"]
    assert fixture.remote().read("Job History") == fixture.remote_before["Job History"]

    mutation = Mock(side_effect=AssertionError("verified local operations were reapplied"))
    with monkeypatch.context() as forbid_reapply:
        forbid_reapply.setattr(SQLiteRepository, "_commit_in_transaction", mutation)
        fixture.service.lose_response = True
        with pytest.raises(UncertainWriteError):
            fixture.command("execute", max_operations=100)
        pending = read_session()
        assert pending["state"] == "SYNC_PENDING"
        dispatch, = pending["chunks"]
        assert (dispatch["start_cursor"], dispatch["operation_count"], dispatch["state"]) == (0, 2, "CLAIMED")
        assert pending["receipt_id"] and pending["intent_id"] and pending["acknowledgement_id"] is None
        assert len(fixture.service.batches) == 1
        assert fixture.queue_path.exists()

        result = fixture.command("execute", max_operations=1)
    mutation.assert_not_called()

    confirmed = read_session()
    assert result["state"] == confirmed["state"] == "SYNC_CONFIRMED"
    assert result["reservation_digest"] == reservation
    assert result["inventory_sha256"] == frozen["inventory_sha256"]
    assert result["plan_digest"] == confirmed["plan_digest"] == local_only["plan_digest"]
    assert result["projection_digest"] == confirmed["projection_digest"] == local_only["projection_digest"]
    for field in ("receipt_id", "intent_id"):
        assert result[field] == confirmed[field] == pending[field]
    confirmed_dispatch, = confirmed["chunks"]
    assert confirmed_dispatch["claim_id"] == dispatch["claim_id"]
    assert confirmed_dispatch["state"] == "CONFIRMED" and confirmed_dispatch["readback_digest"]
    assert result["acknowledgement_id"] == confirmed["acknowledgement_id"]
    with closing(fixture.local()) as local:
        assert read_local_chunks(local, apply_id) == chunks
        assert local.db.execute(
            "SELECT apply_id,receipt_id,acknowledgement_id FROM exact_local_acknowledgements"
        ).fetchall() == [(apply_id, confirmed["receipt_id"], result["acknowledgement_id"])]
        assert local.db.execute("SELECT count(*) FROM dirty").fetchone() == (0,)
    remote_rows = fixture.remote().read("Job History")
    assert record_fingerprints(
        plan["remote_projection"], {"Job History": remote_rows}, include_guard_only=guard_only,
    ) == plan["remote_records"]
    assert not fixture.queue_path.exists()
    fixture.fetch.assert_called_once_with("Jobvite", BOARD, COMPANY_ID, "Samtec")
    assert len(fixture.service.batches) == 1
    fixture.assert_historical_records_unchanged()


def test_two_new_postings_can_start_with_one_operation_per_chunk(fixture):
    fixture.sign()
    result = fixture.command("execute", max_operations=1)
    assert result["state"] == "SYNC_CONFIRMED"
    reservation = result["reservation_digest"]
    with closing(RetainedSessionStore(fixture.root / "retained-sessions.sqlite3")) as store:
        session = store.load(reservation)
    assert [(chunk["start_cursor"], chunk["operation_count"], chunk["state"])
            for chunk in session["chunks"]] == [(0, 1, "CONFIRMED"), (1, 1, "CONFIRMED")]

    operations = session["plan"]["local_operations"]
    assert len(operations) == 4
    assert {operation["tab"] for operation in operations} == {"Job History", "Job Evidence"}
    with closing(fixture.local()) as local:
        assert local.db.execute(
            "SELECT start_cursor,operation_count,state FROM exact_local_apply_chunks ORDER BY start_cursor"
        ).fetchall() == [(cursor, 1, "VERIFIED") for cursor in range(4)]
        assert local.db.execute(
            "SELECT start_cursor,operation_count FROM retained_dirty_chunks "
            "WHERE reservation_digest=? ORDER BY start_cursor", (reservation,),
        ).fetchall() == [(cursor, 1) for cursor in range(4)]
        dirty_targets = local.db.execute(
            "SELECT DISTINCT start_cursor,tab,identity FROM retained_dirty_cells "
            "WHERE reservation_digest=? ORDER BY start_cursor", (reservation,),
        ).fetchall()
        assert [(cursor, tab, json.loads(identity)) for cursor, tab, identity in dirty_targets] == [
            (cursor, operation["tab"], operation["identity"])
            for cursor, operation in enumerate(operations) if operation["tab"] == "Job History"
        ]
        assert local.db.execute("SELECT count(*) FROM dirty").fetchone() == (0,)

    fixture.fetch.assert_called_once_with("Jobvite", BOARD, COMPANY_ID, "Samtec")
    assert len(fixture.service.batches) == 2
    assert not fixture.queue_path.exists()
    fixture.assert_historical_records_unchanged()


def test_real_remote_factory_uses_compact_main_workbook_with_archives_configured(tmp_path, monkeypatch):
    fixture = OperatorFixture(tmp_path, monkeypatch, real_remote=True)
    registry = fixture.root / "evidence-archives.json"
    archive_id = "disposable-archive-never-opened"
    write_json(registry, {"version": 1, "spreadsheet_id": WORKBOOK,
                          "archives": [{"spreadsheet_id": archive_id, "reserved_bytes": 0}]})
    registry_bytes = registry.read_bytes()
    monkeypatch.setenv("SPREADSHEET_ID", WORKBOOK)
    monkeypatch.setenv("EVIDENCE_ARCHIVES_FILE", str(registry))
    # Advance only the repository's clock between fake calls to avoid quota waits.
    monkeypatch.setattr(repository, "time", SimpleNamespace(monotonic=count(step=3).__next__))

    serviced_workbooks = []

    def checked(method):
        def call(*, spreadsheetId, **kwargs):
            serviced_workbooks.append(spreadsheetId)
            assert spreadsheetId == WORKBOOK
            return method(spreadsheetId=spreadsheetId, **kwargs)
        return call

    def values():
        fixture_values = fixture.service.values()
        return SimpleNamespace(get=checked(fixture_values.get), batchGet=checked(fixture_values.batchGet))

    sheets = SimpleNamespace(get=checked(fixture.service.get),
                             batchUpdate=checked(fixture.service.batchUpdate), values=values)

    def open_service(*, write, interactive):
        assert not interactive
        if write:
            fixture.assert_held("scraper.lock", "writer.lock")
        return SimpleNamespace(spreadsheets=lambda: sheets)

    authorize = Mock(side_effect=open_service)
    monkeypatch.setattr(cli, "authorize", authorize)
    legacy_default = cli.get_remote_repository(schemas=COMPACT_SCHEMAS)
    assert isinstance(legacy_default, EvidenceArchives)
    assert legacy_default.schemas != COMPACT_SCHEMAS
    assert not serviced_workbooks

    claims = fixture.sign()
    assert claims["company_id"] == COMPANY_ID
    assert registry.read_bytes() == registry_bytes

    # The operator preview ignores the archive registry even if it is unavailable.
    registry.unlink()
    assert fixture.command("preview")["required_claims"] == claims
    assert not registry.exists()
    registry.write_bytes(registry_bytes)

    # Actual main-workbook header validation continues to fail closed.
    original_sheets = fixture.service.sheets[:]
    fixture.service.sheets[:] = [
        sheet for sheet in original_sheets if sheet["properties"]["title"] != "Job History"
    ]
    with pytest.raises(RepositoryError, match="Missing tab: Job History"):
        fixture.command("execute")
    fixture.fetch.assert_not_called()
    assert not fixture.service.batches
    assert RetainedOperatorJournal(fixture.root).inspect() is None
    fixture.service.sheets[:] = original_sheets

    result = fixture.command("execute")
    assert result["state"] == "SYNC_CONFIRMED"
    assert result["source_revision"] == claims["source_revision"]
    fixture.fetch.assert_called_once_with("Jobvite", BOARD, COMPANY_ID, "Samtec")
    assert [call.kwargs for call in authorize.call_args_list if call.kwargs["write"]] == [
        {"write": True, "interactive": False}
    ]
    assert serviced_workbooks and set(serviced_workbooks) == {WORKBOOK}
    assert len(fixture.service.batches) == 1
    assert fixture.service.batches[0]["spreadsheetId"] == WORKBOOK
    assert registry.read_bytes() == registry_bytes
    with closing(fixture.local()) as local:
        key = "comp-0739:jobvite:42"
        (_, history), = local.matches("Job History", {"Job Key": key})
        (_, evidence), = local.matches("Job Evidence", {"Job Key": key, "Source Hash": history["Source Hash"]})
        assert evidence["Job Description"] == DESCRIPTION
    assert not fixture.queue_path.exists()
    fixture.assert_historical_records_unchanged()


def test_signed_disjoint_event_publishes_and_replays_exactly(tmp_path, monkeypatch):
    from job_search_helper.retained_operator_authorization import EVENT_ACTION

    fixture = OperatorFixture(tmp_path, monkeypatch, company_event=True)
    claims = fixture.sign()
    assert claims["action"] == EVENT_ACTION
    assert claims["request_sha256"] == fixture.request_sha
    assert claims["receipt_sha256"] == digest(json.loads(fixture.request_receipt.read_bytes()))
    with pytest.raises(ValueError, match="retained_operator_authorization_action_invalid"):
        fixture.command("execute", company_event=False)
    fixture.fetch.assert_not_called()
    result = fixture.command("execute")
    assert result["state"] == "SYNC_CONFIRMED"
    assert result["request_id"] == fixture.request_id
    assert result["company_id"] == COMPANY_ID
    assert len(result["acknowledgement_id"]) == 64
    with closing(fixture.local()) as local:
        outcome, = local.scrape_outcomes()
    assert outcome["outcome_id"] == result["outcome_id"]
    assert outcome["outcome"] == "COMPLETE"
    assert outcome["identity"]["request_id"] == fixture.request_id
    assert outcome["identity"]["retained_reservation_sha256"] == result["reservation_digest"]
    journal = RetainedOperatorJournal(tmp_path)
    archived = journal.read_archived_event(fixture.request_sha, result["reservation_digest"])
    assert archived["settlement_evidence"]["acknowledgement_id"] == result["acknowledgement_id"]
    assert journal.read_archived_event(fixture.request_sha, "0" * 64) is None
    fixture.fetch.assert_called_once()
    fixture.assert_historical_records_unchanged()
    fixture.open_local.reset_mock()
    fixture.open_remote.reset_mock()
    assert fixture.command("execute") == result
    fixture.fetch.assert_called_once()
    fixture.open_remote.assert_not_called()
    assert all(not call.kwargs["write"] for call in fixture.open_local.call_args_list)


def test_stage_event_cli_requires_exact_request_with_no_remote_access(tmp_path, monkeypatch):
    fixture = OperatorFixture(tmp_path, monkeypatch, company_event=True)
    args = [
        "stage-event", "--company-event", "--cycle-id", CYCLE_ID,
        "--company-id", COMPANY_ID, "--request-id", fixture.request_id,
        "--manifest-file", str(fixture.manifest_path),
        "--source-revision", fixture.request["source_revision"],
    ]
    pending = fixture.queue_path.read_bytes()
    output = io.StringIO()
    with cli.writer_lock(tmp_path / "scraper.lock"), redirect_stdout(output):
        assert operator_command(args, (fixture.state_path, fixture.jobs_path, fixture.runtime)) == 0
    assert json.loads(output.getvalue())["state"] == "MANUAL_RETAINED_STAGED"
    assert fixture.queue_path.read_bytes() == pending
    fixture.fetch.assert_not_called()
    fixture.open_remote.assert_not_called()


def test_typed_failed_event_fetch_settles_without_retry_or_publication(tmp_path, monkeypatch):
    fixture = OperatorFixture(tmp_path, monkeypatch, company_event=True)
    fixture.sign()
    failure = ats.outcome_failure("temporary_transport", "retryable_http_status")
    fixture.fetch.return_value = ats.Inventory(
        "failed", source_url=BOARD, ats="Jobvite",
        browser_fallback_allowed=False, outcome_failure=failure,
    )
    result = fixture.command("execute")
    assert result["state"] == "FETCH_OUTCOME"
    assert result["outcome"]["outcome"] == "TEMPORARY"
    assert result["consumption"]["state"] == "FETCH_OUTCOME_CONSUMED"
    assert fixture.command("execute") == result
    fixture.fetch.assert_called_once()
    record = RetainedOperatorJournal(tmp_path).read_archived_event(fixture.request_sha, result["reservation_digest"])
    assert record["state"] == SETTLED
    assert record["inventory"]["outcome_failure"] == failure
    assert record["inventory"]["status"] == "failed"
    assert not fixture.queue_path.exists()
    assert all(not call.kwargs["write"] for call in fixture.open_remote.call_args_list)
    assert not (tmp_path / "retained-sessions.sqlite3").exists()
    fixture.assert_historical_records_unchanged()


def test_staged_event_blocks_normal_start_and_sync_before_any_factory(tmp_path, monkeypatch):
    from contextlib import nullcontext
    from job_search_helper import runner, sync_cli

    fixture = OperatorFixture(tmp_path, monkeypatch, company_event=True)
    queued = fixture.queue_path.read_bytes()
    normal_setup = Mock(side_effect=AssertionError("An ordinary process opened a guarded factory"))
    monkeypatch.setattr(runner, "state_path", lambda: fixture.state_path)
    monkeypatch.setattr(runner, "_load_environment", lambda: None)
    monkeypatch.setattr(runner, "_scraper_admission", lambda *_args, **_kwargs: nullcontext(fixture.runtime))
    monkeypatch.setattr(runner, "get_repository", normal_setup)
    monkeypatch.setattr(sync_cli, "state_path", lambda: fixture.state_path)
    monkeypatch.setattr(sync_cli, "job_database_path", lambda: fixture.jobs_path)
    monkeypatch.setattr(sync_cli, "_load_environment", lambda: None)
    monkeypatch.setattr(sync_cli, "SQLiteRepository", normal_setup)
    monkeypatch.setattr(sync_cli, "get_remote_repository", normal_setup)
    with pytest.raises(ValueError, match="retained_runner_manual_event_holds_normal_lifecycle"):
        runner.run_start()
    with pytest.raises(ValueError, match="retained_runner_manual_event_holds_normal_lifecycle"):
        runner.run_start(sync_only=True, sync_cycle_id=CYCLE_ID, sync_company_ids=[COMPANY_ID])
    assert sync_cli.main(["once"]) == 1
    assert sync_cli.main(["watch"]) == 1
    normal_setup.assert_not_called()
    fixture.fetch.assert_not_called()
    assert fixture.queue_path.read_bytes() == queued


def test_confirmed_event_recovers_after_newer_company_source_without_network(tmp_path, monkeypatch):
    fixture = OperatorFixture(tmp_path, monkeypatch, company_event=True)
    fixture.sign()
    with monkeypatch.context() as stop:
        stop.setattr(RetainedOperatorJournal, "record_settlement",
                     Mock(side_effect=InterruptedError("stop after confirmed receipt")))
        with pytest.raises(InterruptedError, match="stop after confirmed receipt"):
            fixture.command("execute")
    assert RetainedOperatorJournal(tmp_path).inspect()["state"] == INVENTORY_FROZEN
    with closing(fixture.local(write=True)) as local:
        row = local.matches("Companies", {"Company ID": COMPANY_ID})[0][1]
        row["Official Careers URL"] = "https://jobs.jobvite.com/samtec/new"
        newer = local.import_companies_with_events(
            [(2, row)], origin="sheets-reconciliation",
        )["company_events"][0]
    fixture.open_remote.reset_mock()
    fixture.open_local.reset_mock()
    result = fixture.command("execute")
    assert result["state"] == "SYNC_CONFIRMED"
    fixture.fetch.assert_called_once()
    fixture.open_remote.assert_not_called()
    assert sum(call.kwargs["write"] for call in fixture.open_local.call_args_list) == 1
    assert not fixture.queue_path.exists()
    with closing(fixture.local()) as local:
        outcome, = local.scrape_outcomes()
        assert outcome["outcome_id"] == result["outcome_id"]
        assert outcome["outcome"] == "STALE_OR_PAUSED"
        assert local.db.execute(
            "SELECT event_id FROM company_event_outbox WHERE event_id=?", (newer["event_id"],),
        ).fetchone() == (newer["event_id"],)


def test_event_outcome_crash_keeps_request_owned_until_exact_replay(tmp_path, monkeypatch):
    from job_search_helper.retained_work_runner import assert_normal_lifecycle_not_held

    fixture = OperatorFixture(tmp_path, monkeypatch, company_event=True)
    fixture.sign()
    with monkeypatch.context() as stop:
        stop.setattr(SQLiteRepository, "record_retained_event_outcome",
                     Mock(side_effect=InterruptedError("stop before durable outcome")))
        with pytest.raises(InterruptedError, match="stop before durable outcome"):
            fixture.command("execute")
    record = RetainedOperatorJournal(tmp_path).inspect()
    assert record["state"] == SETTLED
    assert record["consumption"] is None
    assert fixture.queue_path.exists()
    with pytest.raises(ValueError, match="retained_runner_manual_event_holds_normal_lifecycle"):
        assert_normal_lifecycle_not_held(tmp_path, fixture.jobs_path)
    with closing(fixture.local()) as local:
        assert local.scrape_outcomes() == []
    fixture.open_remote.reset_mock()
    result = fixture.command("execute")
    assert result["state"] == "SYNC_CONFIRMED"
    assert RetainedOperatorJournal(tmp_path).inspect() is None
    fixture.open_remote.assert_not_called()
    fixture.fetch.assert_called_once()
    with closing(fixture.local()) as local:
        outcome, = local.scrape_outcomes()
        assert outcome["outcome_id"] == result["outcome_id"]
    assert fixture.command("execute") == result


def test_selected_signed_event_delivers_exact_receipt(tmp_path, monkeypatch):
    from job_search_helper.outcomes import COMPLETE
    from job_search_helper.scrape_outcome_delivery import CONSUMER, SCHEMA, OutcomeDelivery

    fixture = OperatorFixture(tmp_path, monkeypatch, company_event=True)
    fixture.sign()
    result = fixture.command("execute")
    selected = result["outcome_id"]

    def receipt(outcome):
        assert outcome["outcome"] == COMPLETE
        return {"schema": SCHEMA, "consumer": CONSUMER, "outcome_id": selected,
                "record_sha256": digest(outcome), "disposition": "ACCEPTED",
                "sink_receipt_id": "fixture:exact", "sink_status": "RECORDED_NO_REPAIR"}

    with closing(fixture.local(write=True)) as local:
        sink = Mock()
        sink.ingest_immutable.side_effect = receipt
        other = local.record_scrape_outcome({
            "request_id": "other", "company_id": "COMP-OLD", "source_revision": "fixture",
            "source_current": True, "inventory_status": "complete",
        })["outcome"]
        delivery = OutcomeDelivery(local, sink)
        assert delivery.drain(outcome_id=selected) == [{"outcome_id": selected, "disposition": "ACCEPTED"}]
        assert delivery.drain(outcome_id=selected) == []
        sink.ingest_immutable.assert_called_once()
        assert local.pending_scrape_outcomes(CONSUMER) == [other]


def test_retained_complete_stays_immutable_but_is_held_if_source_changes_before_delivery(tmp_path, monkeypatch):
    from job_search_helper.scrape_outcome_delivery import OutcomeDelivery

    fixture = OperatorFixture(tmp_path, monkeypatch, company_event=True)
    fixture.sign()
    result = fixture.command("execute")
    with closing(fixture.local(write=True)) as local:
        row = local.matches("Companies", {"Company ID": COMPANY_ID})[0][1]
        row["Official Careers URL"] = "https://jobs.jobvite.com/samtec/new"
        local.import_companies_with_events([(2, row)], origin="sheets-reconciliation")
        sink = Mock()
        assert OutcomeDelivery(local, sink).drain(outcome_id=result["outcome_id"]) == [
            {"outcome_id": result["outcome_id"], "disposition": "HELD_STALE_RETAINED_SOURCE"}
        ]
        sink.ingest_immutable.assert_not_called()
        assert local.db.execute("SELECT COUNT(*) FROM scrape_outcome_delivery_attempts").fetchone()[0] == 0
    assert fixture.command("execute") == result


@pytest.mark.parametrize("zero_evidence", [None, "samtec_jobvite_explicit_zero"])
def test_staged_event_distinguishes_verified_zero_from_ambiguous_empty(tmp_path, monkeypatch, zero_evidence):
    fixture = OperatorFixture(tmp_path, monkeypatch, company_event=True)
    fixture.sign()
    fixture.fetch.return_value = ats.Inventory(
        "complete", source_url=BOARD, ats="Jobvite",
        browser_fallback_allowed=False, verified_zero=zero_evidence,
    )
    if zero_evidence is None:
        with pytest.raises(ValueError, match="retained_event_zero_openings_not_verified"):
            fixture.command("execute")
        assert fixture.queue_path.exists()
        assert RetainedOperatorJournal(tmp_path).inspect()["state"] == INVENTORY_FROZEN
        with closing(fixture.local()) as local:
            assert local.scrape_outcomes() == []
    else:
        result = fixture.command("execute")
        assert result["state"] == "VERIFIED_ZERO"
        assert result["consumption"]["state"] == "VERIFIED_ZERO_CONSUMED"
        assert "receipt_id" not in result
        assert not fixture.queue_path.exists()
        fixture.open_remote.reset_mock()
        assert fixture.command("execute") == result
        fixture.open_remote.assert_not_called()
        with closing(fixture.local()) as local:
            outcome, = local.scrape_outcomes()
            assert outcome["outcome_id"] == result["outcome_id"]
            assert outcome["outcome"] == "COMPLETE"
    fixture.fetch.assert_called_once()
    assert not (tmp_path / "retained-sessions.sqlite3").exists()
    assert not (tmp_path / "retained-first-pass").exists()
    assert all(not call.kwargs["write"] for call in fixture.open_remote.call_args_list)
    fixture.assert_historical_records_unchanged()


def test_expired_event_reopens_only_exact_claim_and_never_dispatches_suffix(tmp_path, monkeypatch):
    from job_search_helper import retained_operator_authorization, selected_recovery_authorization

    fixture = OperatorFixture(tmp_path, monkeypatch, company_event=True)
    fixture.sign()
    fixture.service.lose_response = True
    with pytest.raises(UncertainWriteError):
        fixture.command("execute", max_operations=1)
    record = RetainedOperatorJournal(tmp_path).inspect()
    binding = record["binding"]
    reservation = binding["reservation_digest"]
    with closing(RetainedSessionStore(tmp_path / "retained-sessions.sqlite3")) as store:
        prior = store.load(reservation)["chunks"]
    assert len(prior) == 1 and prior[0]["state"] == "CLAIMED"
    original = fixture.approval_path.read_bytes()
    expiry = selected_recovery_authorization._expiry

    def late(value, _now):
        return expiry(value, fixture.now + timedelta(hours=2))

    monkeypatch.setattr(selected_recovery_authorization, "_expiry", late)
    monkeypatch.setattr(retained_operator_authorization, "_expiry", late)
    envelope = json.loads(original)
    envelope["signature"] = base64.b64encode(bytes(64)).decode("ascii")
    write_json(fixture.approval_path, envelope)
    fixture.open_remote.reset_mock()
    fixture.open_local.reset_mock()
    with pytest.raises(ValueError, match="selected_recovery_authorization_signature_invalid"):
        fixture.command("execute")
    fixture.open_remote.assert_not_called()
    fixture.approval_path.write_bytes(original)
    result = fixture.command("execute")
    assert result["state"] == "HELD_UNCLAIMED_SUFFIX"
    assert result["unclaimed_operations"] == 1
    assert result["claim_id"] == prior[0]["claim_id"]
    assert len(fixture.service.batches) == 1
    assert all(not call.kwargs["write"] for call in fixture.open_remote.call_args_list)
    assert all(not call.kwargs["write"] for call in fixture.open_local.call_args_list)
    assert fixture.queue_path.exists()
    fixture.open_remote.reset_mock()
    assert fixture.command("execute") == result
    fixture.open_remote.assert_not_called()
    fixture.fetch.assert_called_once()


def test_public_outcome_cannot_claim_staged_event_with_a_fabricated_ordinary_cycle(tmp_path, monkeypatch):
    fixture = OperatorFixture(tmp_path, monkeypatch, company_event=True)
    fixture.sign()
    with closing(fixture.local(write=True)) as local:
        with pytest.raises(RepositoryError, match="Company-event outcomes require a sealed event writer"):
            local.record_scrape_outcome({
                "request_id": fixture.request_id, "company_id": COMPANY_ID,
                "company_event_id": fixture.request["company_event"]["event_id"],
                "source_revision": fixture.request["source_revision"], "cycle_id": "CYC-FABRICATED",
                "inventory_status": "complete", "source_current": True,
            })
        assert local.scrape_outcomes() == []
    fixture.fetch.assert_not_called()
    result = fixture.command("execute")
    with closing(fixture.local()) as local:
        outcome, = local.scrape_outcomes()
        assert outcome["outcome_id"] == result["outcome_id"]
    fixture.fetch.assert_called_once()


def test_expiry_during_publication_stops_before_next_claim(tmp_path, monkeypatch):
    from job_search_helper import retained_operator_authorization, selected_recovery_authorization

    fixture = OperatorFixture(tmp_path, monkeypatch, company_event=True)
    fixture.sign()
    expiry = selected_recovery_authorization._expiry

    def expires_after_first_batch(value, now):
        after_first_batch = fixture.now + timedelta(hours=2) if fixture.service.batches else now
        return expiry(value, after_first_batch)

    monkeypatch.setattr(selected_recovery_authorization, "_expiry", expires_after_first_batch)
    monkeypatch.setattr(retained_operator_authorization, "_expiry", expires_after_first_batch)
    with pytest.raises(ValueError, match="selected_recovery_authorization_expired"):
        fixture.command("execute", max_operations=1)
    outcome = fixture.command("execute", max_operations=100)
    assert outcome["state"] == "HELD_UNCLAIMED_SUFFIX"
    assert outcome["unclaimed_operations"] == 1
    assert len(fixture.service.batches) == 1
    fixture.fetch.assert_called_once()
    with closing(RetainedSessionStore(tmp_path / "retained-sessions.sqlite3")) as sessions:
        saved = sessions.load(outcome["reservation_digest"])
    assert [claim["state"] for claim in saved["chunks"]] == ["CONFIRMED"]


@pytest.mark.parametrize(("failure", "classification"), [
    (ats.outcome_failure("access_denied", "human_verification"), "BLOCKED"),
    (None, "UNKNOWN_CAPABILITY_HOLD"),
])
def test_failed_event_dispositions_do_not_write_partial_jobs(tmp_path, monkeypatch, failure, classification):
    fixture = OperatorFixture(tmp_path, monkeypatch, company_event=True)
    fixture.sign()
    postings = fixture.fetch.return_value.jobs
    fixture.fetch.return_value = ats.Inventory(
        "partial", postings, source_url=BOARD, ats="Jobvite",
        browser_fallback_allowed=False, outcome_failure=failure,
    )
    result = fixture.command("execute")
    assert result["outcome"]["outcome"] == classification
    archived = RetainedOperatorJournal(tmp_path).read_archived_event(
        fixture.request_sha, result["reservation_digest"],
    )
    assert archived["inventory"]["jobs"] == postings
    with closing(fixture.local()) as local:
        assert local.read("Job History") == fixture.local_before["Job History"]
        assert local.read("Job Evidence") == fixture.local_before["Job Evidence"]
    assert not fixture.service.batches
    assert not (tmp_path / "retained-first-pass").exists()


def test_failure_outcome_is_sealed_before_outbox_retry_and_source_change(tmp_path, monkeypatch):
    from job_search_helper.scrape_outcome_delivery import OutcomeDelivery

    fixture = OperatorFixture(tmp_path, monkeypatch, company_event=True)
    fixture.sign()
    fixture.fetch.return_value = ats.Inventory(
        "failed", source_url=BOARD, ats="Jobvite", browser_fallback_allowed=False,
        outcome_failure=ats.outcome_failure("temporary_transport", "retryable_http_status"),
    )
    with monkeypatch.context() as stop:
        stop.setattr(SQLiteRepository, "record_retained_event_outcome",
                     Mock(side_effect=InterruptedError("shutdown before outcome write")))
        with pytest.raises(InterruptedError, match="shutdown before outcome write"):
            fixture.command("execute")
    assert fixture.queue_path.exists()
    with closing(fixture.local(write=True)) as local:
        row = local.matches("Companies", {"Company ID": COMPANY_ID})[0][1]
        row["Official Careers URL"] = "https://jobs.jobvite.com/samtec/new"
        local.import_companies_with_events([(2, row)], origin="sheets-reconciliation")
    fixture.open_remote.reset_mock()
    result = fixture.command("execute")
    assert result["outcome"]["outcome"] == "TEMPORARY"
    with closing(fixture.local(write=True)) as local:
        sink = Mock()
        assert OutcomeDelivery(local, sink).drain(outcome_id=result["outcome_id"]) == [
            {"outcome_id": result["outcome_id"], "disposition": "HELD_STALE_RETAINED_SOURCE"}
        ]
        sink.ingest_immutable.assert_not_called()
    fixture.open_remote.assert_not_called()
    fixture.fetch.assert_called_once()
