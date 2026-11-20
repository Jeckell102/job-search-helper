from __future__ import annotations

import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from job_search_helper.exact_cycle_planner import _digest, _exact_plan_digest
from job_search_helper.exact_local_plan import commit_exact_local_plan
from job_search_helper.publication_receipts import record_fingerprints
from job_search_helper.repository import GoogleRepository, MemoryRepository, SCHEMAS
from job_search_helper.repository import UncertainWriteError
from job_search_helper.retained_dirty_provenance import (
    REMOTE_PENDING, reserve_dirty_provenance, retained_publication,
)
from job_search_helper.retained_session_store import RetainedSessionStore
from job_search_helper.retained_work_publication import publish_retained_reservation
import job_search_helper.retained_work_publication as retained_publication_module
from job_search_helper.cli import WriterLockBusy, scraper_lock_name, writer_lock
from job_search_helper.sheet_profile import COMPACT_PROFILE, COMPACT_SCHEMAS
from job_search_helper.sqlite_repository import SQLiteRepository
from sheets_fixture import RangeSheets


def company(identifier="COMP-NEW"):
    return {"Company ID": identifier, "Company": "Fixture", "Company Status": "Active",
            "Official Careers URL": "https://jobs.example.test/fixture", "Scan State": "Queued",
            "Claimed By": "", "Claim Token": "", "Automatic Retry?": "",
            "Last Checked": "", "Next Action": ""}


def plan(*, include_selected_job=False):
    local = [{"tab": "Companies", "identity": {"Company ID": "COMP-NEW"},
              "expected": {"Scan State": "Queued"},
              "values": {"Scan State": "Complete", "Last Checked": "2026-11-19",
                         "Next Action": "Inventory saved"}}]
    remote = [{"tab": "Companies", "identity": {"Company ID": "COMP-NEW"},
               "expected": {"Last Checked": "", "Next Action": ""}, "on_insert": {},
               "values": {"Last Checked": "2026-11-19", "Next Action": "Inventory saved"},
               "append_notes": {}, "append_if_missing": False}]
    result = {"exact_plan_version": 2, "cycle_id": "CYC-NEW", "company_id": "COMP-NEW",
              "inventory_payload_digest": _digest({"jobs": []}), "publication_profile": COMPACT_PROFILE,
              "requested_url": "https://jobs.example.test/fixture",
              "control_evidence_version": 1,
              "control_evidence": {
                  "company_id": "COMP-NEW",
                  "requested_url": "https://jobs.example.test/fixture",
                  "official_careers_url": "https://jobs.example.test/fixture",
                  "company_status": "Active", "claimed_by": "", "claim_token": "",
              },
              "publication_schema": {"Companies": ["Company ID", "Last Checked", "Next Action"]},
              "local_operations": local, "remote_projection": remote,
              "final": {"stage": "complete"}, "final_projection": {"stage": "complete"}}
    if include_selected_job:
        job = {
            "Job Key": "JOB-SELECTED", "Source Hash": "SOURCE-SELECTED",
            "Company": "Fixture COMP-NEW",
            "Job Title": "Field Applications Engineer",
            "Added to Opportunities?": "Pending",
            "Official Job URL": "https://jobs.example.test/selected",
            "Job Status": "Open", "Review Status": "Needs Review",
            "Last Checked": "2026-11-19",
        }
        evidence = {
            "Job Key": job["Job Key"], "Source Hash": job["Source Hash"],
            "Company": job["Company"], "Job Title": job["Job Title"],
            "Official Job URL": job["Official Job URL"],
            "Captured At": "2026-11-19",
            "Job Description": "Field applications support and systems integration.",
        }
        result["local_operations"].extend((
            {"tab": "Job Evidence",
             "identity": {"Job Key": job["Job Key"],
                          "Source Hash": job["Source Hash"]},
             "append_if_missing": True, "on_insert": evidence},
            {"tab": "Job History", "identity": {"Job Key": job["Job Key"]},
             "append_if_missing": True, "on_insert": job},
        ))
        published = {
            "Company", "Job Title", "Added to Opportunities?",
            "Rejection Reason", "Requisition ID", "Official Job URL", "Location",
            "First Seen", "Last Checked", "Job Status", "Job Key", "Review Notes",
            "Material Change Summary", "Last Evaluated", "Review Status", "Fit Level",
            "Salary / Range", "Work Arrangement",
        }
        result["remote_projection"].append({
            "tab": "Job History", "identity": {"Job Key": job["Job Key"]},
            "append_if_missing": True,
            "on_insert": {key: value for key, value in job.items() if key in published},
            "values": {}, "expected": {}, "append_notes": {},
        })
        result["publication_schema"]["Job History"] = sorted(published)
    result["control_evidence_digest"] = _digest(result["control_evidence"])
    result["publication_schema_digest"] = _digest(result["publication_schema"])
    result["local_operations_digest"] = _digest(local)
    result["local_expected_records"] = record_fingerprints(local)
    result["local_expected_records_digest"] = _digest(result["local_expected_records"])
    result["remote_projection_digest"] = _digest(remote)
    result["remote_records"] = record_fingerprints(remote)
    result["remote_records_digest"] = _digest(result["remote_records"])
    result["local_finalization_digest"] = _digest({"operations": local, "final": result["final"]})
    result["final_projection_digest"] = _digest(result["final_projection"])
    result["plan_digest"] = _exact_plan_digest(result)
    return result


class RetainedWorkPublicationTests(unittest.TestCase):
    def setUp(self):
        self._set_up_fixture()

    def _set_up_fixture(self, *, include_selected_job=False):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.local = SQLiteRepository(Path(self.temp.name) / "jobs.sqlite3", "fixture", initialize=True)
        self.addCleanup(self.local.close)
        with self.local.transaction():
            self.local.set_meta("ready", "yes"); self.local.set_meta("sheets_profile", COMPACT_PROFILE)
        rows = {"Companies": [company(), company("COMP-OTHER")]}
        source = MemoryRepository(rows, schemas=self.local.schemas)
        for tab in SCHEMAS:
            self.local.import_rows(tab, enumerate(source.read(tab), 2))
        self.service = RangeSheets(rows, schemas=COMPACT_SCHEMAS)
        self.remote = GoogleRepository(self.service, "fixture", schemas=COMPACT_SCHEMAS, min_request_interval=0)
        self.store = RetainedSessionStore(Path(self.temp.name) / "retained.sqlite3")
        self.addCleanup(self.store.close)
        self.reservation = "reservation"
        self.plan = plan(include_selected_job=include_selected_job)
        with self.local.transaction():
            self.local.db.execute("""CREATE TABLE retained_intake_holds (
                reservation_digest TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE,
                event_id TEXT NOT NULL UNIQUE, company_id TEXT NOT NULL,
                manifest_digest TEXT NOT NULL, start_binding_digest TEXT NOT NULL,
                state TEXT NOT NULL CHECK(state='FROZEN'))""")
            self.local.db.execute("INSERT INTO retained_intake_holds VALUES (?,?,?,?,?,?,?)",
                (self.reservation, "REQ", "EVT", "COMP-NEW", "manifest", "binding", "FROZEN"))
        reserve_dirty_provenance(self.local, reservation_digest=self.reservation, request_id="REQ",
            event_id="EVT", exception_cycle_id="CYC-OLD", cycle_id="CYC-NEW", company_id="COMP-NEW",
            source_revision="SRC-1", manifest_digest="manifest", start_binding_digest="binding", plan=self.plan)
        commit_exact_local_plan(self.local, "CYC-NEW", "COMP-NEW", self.plan,
                                reservation_digest=self.reservation)
        self.store.freeze(self.reservation, admission={"request_id": "REQ", "event_id": "EVT",
            "exception_cycle_id": "CYC-OLD", "cycle_id": "CYC-NEW", "company_id": "COMP-NEW",
            "source_revision": "SRC-1", "manifest_digest": "manifest", "start_binding_digest": "binding"},
            inventory={"jobs": []}, plan=self.plan)

    def test_nonempty_first_pass_release_contains_only_frozen_job_and_evidence(self):
        self._set_up_fixture(include_selected_job=True)
        result = publish_retained_reservation(
            self.reservation, self.store, self.local, self.remote)
        evidence = result["first_pass"]
        self.assertEqual([("JOB-SELECTED", "SOURCE-SELECTED")], [
            (item["job_key"], item["source_hash"])
            for item in evidence["selected_jobs"]])
        self.assertEqual(1, sum(evidence["counts"].values()))
        release = Path(evidence["output_dir"])
        self.assertTrue((release / "first-pass.jsonl").is_file())
        self.assertTrue((release / "summary.json").is_file())
        self.assertEqual("FIRST_PASS_RELEASED", result["state"])

    def test_lost_response_recovers_by_readback_without_second_commit(self):
        self.service.lose_response = True
        with self.assertRaises(UncertainWriteError):
            publish_retained_reservation(self.reservation, self.store, self.local, self.remote)
        self.assertEqual("CLAIMED", self.store.load(self.reservation)["chunks"][0]["state"])
        batches = len(self.service.batches)
        result = publish_retained_reservation(self.reservation, self.store, self.local, self.remote)
        self.assertEqual("FIRST_PASS_RELEASED", result["state"])
        self.assertEqual("SYNC_CONFIRMED", result["session_state"])
        self.assertEqual(batches, len(self.service.batches))
        self.assertEqual(result, publish_retained_reservation(
            self.reservation, self.store, self.local, self.remote))
        self.assertEqual("", self.remote.read_columns("Companies", ["Company ID"])[1][1].get("Last Checked", ""))

    def test_no_commit_keeps_claimed_and_unrelated_row_untouched(self):
        def fail_before_write():
            raise RuntimeError("no write")
        self.service.before_write = fail_before_write
        with self.assertRaisesRegex(UncertainWriteError, "No successful write"):
            publish_retained_reservation(self.reservation, self.store, self.local, self.remote)
        self.assertEqual("CLAIMED", self.store.load(self.reservation)["chunks"][0]["state"])
        rows = self.remote.read_columns("Companies", ["Company ID", "Last Checked"])
        other = [row for _number, row in rows if row.get("Company ID") == "COMP-OTHER"][0]
        self.assertEqual("", other.get("Last Checked", ""))

    def test_post_ack_crash_recovers_ledger_without_remote_replay(self):
        real_acknowledge = retained_publication_module._acknowledge_selected_dirty

        def acknowledge_then_crash(*args, **kwargs):
            real_acknowledge(*args, **kwargs)
            raise OSError("injected post-ack crash")

        with patch.object(retained_publication_module, "_acknowledge_selected_dirty",
                          side_effect=acknowledge_then_crash):
            with self.assertRaisesRegex(OSError, "post-ack crash"):
                publish_retained_reservation(
                    self.reservation, self.store, self.local, self.remote)
        self.assertEqual("SYNC_CONFIRMED", self.store.load(self.reservation)["state"])
        self.assertEqual("REMOTE_PENDING", self.local.db.execute(
            "SELECT state FROM retained_publications WHERE reservation_digest=?",
            (self.reservation,)).fetchone()[0])
        batches = len(self.service.batches)
        recovered = publish_retained_reservation(
            self.reservation, self.store, self.local, self.remote)
        self.assertEqual("FIRST_PASS_RELEASED", recovered["state"])
        self.assertEqual(batches, len(self.service.batches))

    def test_retained_publication_shares_the_normal_scraper_lock(self):
        lock = Path(self.store.path).parent / scraper_lock_name()
        with writer_lock(lock):
            with self.assertRaises(WriterLockBusy):
                publish_retained_reservation(
                    self.reservation, self.store, self.local, self.remote)
        self.assertEqual([], self.service.batches)

    def test_retained_publication_never_creates_normal_state_or_inbox(self):
        root = Path(self.store.path).parent
        state_path, inbox_path = root / "state.db", root / "inventories.sqlite3"
        self.assertFalse(state_path.exists())
        self.assertFalse(inbox_path.exists())
        result = publish_retained_reservation(
            self.reservation, self.store, self.local, self.remote)
        self.assertEqual("FIRST_PASS_RELEASED", result["state"])
        self.assertFalse(state_path.exists())
        self.assertFalse(inbox_path.exists())

    def test_local_dirty_value_tamper_blocks_before_remote_write(self):
        """A changed sealed value cannot be published under the old receipt."""
        self.local.commit([{
            "tab": "Companies", "identity": {"Company ID": "COMP-NEW"},
            "values": {"Last Checked": "tampered-after-plan"},
        }])
        with self.assertRaisesRegex(
                ValueError, "Complete local readback differs from the frozen plan"):
            publish_retained_reservation(
                self.reservation, self.store, self.local, self.remote)
        self.assertEqual([], self.service.batches)

    def test_company_control_change_after_claim_blocks_remote_write(self):
        """The write-boundary Company reread rejects a newly claimed company."""
        real_claim = self.store.claim_chunk

        def claim_then_change_controls(*args, **kwargs):
            claim = real_claim(*args, **kwargs)
            self.local.commit([{
                "tab": "Companies", "identity": {"Company ID": "COMP-NEW"},
                "expected": {"Claimed By": ""},
                "values": {"Claimed By": "manual-operator"},
            }])
            return claim

        with patch.object(self.store, "claim_chunk",
                          side_effect=claim_then_change_controls):
            with self.assertRaisesRegex(ValueError, "local_company_claimed"):
                publish_retained_reservation(
                    self.reservation, self.store, self.local, self.remote)
        self.assertEqual([], self.service.batches)
        self.assertEqual("CLAIMED", self.store.load(
            self.reservation)["chunks"][0]["state"])

    def test_crash_after_remote_confirmation_recovers_without_second_commit(self):
        with patch(
                "job_search_helper.retained_work_publication._acknowledge_selected_dirty",
                side_effect=RuntimeError("injected post-confirmation crash")):
            with self.assertRaisesRegex(RuntimeError, "post-confirmation crash"):
                publish_retained_reservation(
                    self.reservation, self.store, self.local, self.remote)
        self.assertEqual("SYNC_CONFIRMED", self.store.load(
            self.reservation)["state"])
        self.assertEqual(REMOTE_PENDING, retained_publication(
            self.local, self.reservation)["state"])
        self.assertGreater(self.local.db.execute(
            "SELECT count(*) FROM dirty").fetchone()[0], 0)
        batches = len(self.service.batches)
        result = publish_retained_reservation(
            self.reservation, self.store, self.local, self.remote)
        self.assertEqual("FIRST_PASS_RELEASED", result["state"])
        self.assertEqual(batches, len(self.service.batches))
        self.assertEqual(1, self.local.db.execute(
            "SELECT count(*) FROM exact_local_acknowledgements").fetchone()[0])
        self.assertEqual("FIRST_PASS_RELEASED", retained_publication(
            self.local, self.reservation)["state"])

    def test_crash_after_local_ack_recovers_provenance_without_second_commit(self):
        with patch(
                "job_search_helper.retained_work_publication.confirm_remote_from_session",
                side_effect=RuntimeError("injected post-ack crash")):
            with self.assertRaisesRegex(RuntimeError, "post-ack crash"):
                publish_retained_reservation(
                    self.reservation, self.store, self.local, self.remote)
        self.assertEqual("SYNC_CONFIRMED", self.store.load(
            self.reservation)["state"])
        self.assertEqual(REMOTE_PENDING, retained_publication(
            self.local, self.reservation)["state"])
        self.assertEqual(0, self.local.db.execute(
            "SELECT count(*) FROM dirty").fetchone()[0])
        self.assertEqual(1, self.local.db.execute(
            "SELECT count(*) FROM exact_local_acknowledgements").fetchone()[0])
        batches = len(self.service.batches)
        result = publish_retained_reservation(
            self.reservation, self.store, self.local, self.remote)
        self.assertEqual("FIRST_PASS_RELEASED", result["state"])
        self.assertEqual(batches, len(self.service.batches))
