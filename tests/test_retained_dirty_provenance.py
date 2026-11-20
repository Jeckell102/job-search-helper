"""Offline proof for reservation-bound exceptional dirty provenance."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import job_search_helper.retained_first_pass as retained_first_pass_module
from job_search_helper.exact_cycle_planner import _digest, _exact_plan_digest
from job_search_helper.exact_local_plan import commit_exact_local_plan
from job_search_helper.exact_cycle_sync import publish_exact_cycle
from job_search_helper.publication_receipts import record_fingerprints
from job_search_helper.repository import SCHEMAS
from job_search_helper.retained_dirty_provenance import (
    FIRST_PASS_RELEASED, LOCAL_VERIFIED, REMOTE_CONFIRMED, REMOTE_PENDING,
    RESERVED,
    bind_remote_intent, confirm_remote_from_authorities,
    reserve_dirty_provenance, retained_publication,
    verify_dirty_provenance,
)
from job_search_helper.sqlite_repository import SQLiteRepository
from job_search_helper.inbox import InventoryInbox
from job_search_helper.sheets_sync import SheetsSynchronizer
from job_search_helper.repository import RepositoryError
from job_search_helper.retained_first_pass import release_retained_first_pass


def company(company_id="COMP-NEW"):
    return {
        "Company ID": company_id,
        "Company": "Fixture " + company_id,
        "Company Status": "Active",
        "Official Careers URL": "https://jobs.example.test/" + company_id,
        "Scan State": "Queued",
        "Active Cycle ID": "",
        "Last Checked": "",
        "Next Action": "",
    }


def sealed_plan():
    local = [{
        "tab": "Companies",
        "identity": {"Company ID": "COMP-NEW"},
        "values": {
            "Scan State": "Complete",
            "Active Cycle ID": "CYC-NEW",
            "Last Checked": "2026-11-19",
            "Next Action": "Inventory saved",
        },
        "expected": {"Scan State": "Queued"},
    }]
    remote = [{
        "tab": "Companies",
        "identity": {"Company ID": "COMP-NEW"},
        "values": {
            "Last Checked": "2026-11-19",
            "Next Action": "Inventory saved",
        },
        "append_if_missing": False,
        "on_insert": {},
        "expected": {},
        "append_notes": {},
    }]
    plan = {
        "exact_plan_version": 2,
        "cycle_id": "CYC-NEW",
        "company_id": "COMP-NEW",
        "inventory_payload_digest": _digest({"inventory": "fixture"}),
        "publication_profile": "compact-v1",
        "publication_schema": {
            "Companies": ["Company ID", "Last Checked", "Next Action"]},
        "local_operations": local,
        "remote_projection": remote,
        "final": {"stage": "complete"},
        "final_projection": {"stage": "complete"},
    }
    plan["publication_schema_digest"] = _digest(plan["publication_schema"])
    plan["local_operations_digest"] = _digest(local)
    plan["local_expected_records"] = record_fingerprints(local)
    plan["local_expected_records_digest"] = _digest(
        plan["local_expected_records"])
    plan["remote_projection_digest"] = _digest(remote)
    plan["remote_records"] = record_fingerprints(remote)
    plan["remote_records_digest"] = _digest(plan["remote_records"])
    plan["local_finalization_digest"] = _digest({
        "operations": local, "final": plan["final"]})
    plan["final_projection_digest"] = _digest(plan["final_projection"])
    plan["plan_digest"] = _exact_plan_digest(plan)
    return plan


class RetainedDirtyProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.repository = SQLiteRepository(
            Path(self.temporary.name) / "jobs.sqlite3", "fixture", initialize=True)
        self.addCleanup(self.repository.close)
        self.inbox = InventoryInbox(
            Path(self.temporary.name) / "inbox.sqlite3", "fixture")
        self.addCleanup(self.inbox.close)
        for tab in SCHEMAS:
            rows = [company(), company("COMP-OTHER")] if tab == "Companies" else []
            self.repository.import_rows(tab, enumerate(rows, 2))
        with self.repository.transaction():
            self.repository.set_meta("ready", "yes")
            self.repository.set_meta("sheets_profile", "compact-v1")
        self.plan = sealed_plan()

    def freeze_remote_intent(self):
        records = record_fingerprints(self.plan["remote_projection"])
        with self.inbox.lock, self.inbox.connection:
            self.inbox.connection.execute(
                "INSERT INTO publication_receipts VALUES (?,?,?,?,?,?,?,?)",
                ("REC-1", json.dumps({
                    "request_id": "CYC-NEW", "company_id": "COMP-NEW"}),
                 json.dumps(records, sort_keys=True), "{}", "LOCAL_COMMITTED", None,
                 "2026-11-19T00:00:00Z", "2026-11-19T00:00:00Z"))
            self.inbox.connection.execute(
                "INSERT INTO sync_plans VALUES (?,?,?,?)",
                ("CYC-NEW", "COMP-NEW", json.dumps(self.plan, sort_keys=True),
                 len(self.plan["local_operations"])))
            self.inbox.connection.execute(
                "INSERT INTO exact_plan_local_state VALUES (?,?,?,?,?,?,?,?,?,?)",
                ("CYC-NEW", "COMP-NEW", self.plan["plan_digest"],
                 self.plan["local_operations_digest"],
                 self.plan["remote_projection_digest"], "LOCAL_VERIFIED",
                 retained_publication(self.repository, "reservation-digest")["local_apply_id"],
                 self.plan["local_expected_records_digest"],
                 "2026-11-19T00:00:00Z", "2026-11-19T00:00:00Z"))
            self.inbox.connection.execute(
                "INSERT INTO exact_remote_plans("
                "cycle,company,local_plan_digest,projection,projection_digest,"
                "receipt_id,intent_id,remote_cursor,state,first_attempt_claimed,"
                "attempted_at,acknowledgement_id,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,0,'FROZEN',0,NULL,NULL,?,?)",
                ("CYC-NEW", "COMP-NEW", self.plan["plan_digest"],
                 json.dumps(self.plan["remote_projection"], sort_keys=True,
                            separators=(",", ":")),
                 self.plan["remote_projection_digest"], "REC-1", "INTENT-1",
                 "2026-11-19T00:00:00Z", "2026-11-19T00:00:00Z"))

    def add_selected_job_to_plan(self):
        job = {
            "Job Key": "JOB-SELECTED", "Source Hash": "SOURCE-SELECTED",
            "Company": "Fixture COMP-NEW",
            "Job Title": "Field Applications Engineer",
            "Added to Opportunities?": "Pending",
            "Official Job URL": "https://jobs.example.test/selected",
            "Job Status": "Open", "Review Status": "Needs Review",
            "Last Checked": "2026-11-19",
        }
        local = {
            "tab": "Job History", "identity": {"Job Key": "JOB-SELECTED"},
            "append_if_missing": True, "on_insert": job,
        }
        publishable = set([
            "Company", "Job Title", "Added to Opportunities?",
            "Rejection Reason", "Requisition ID", "Official Job URL",
            "Location", "First Seen", "Last Checked", "Job Status", "Job Key",
            "Review Notes", "Material Change Summary", "Last Evaluated",
            "Review Status", "Fit Level", "Salary / Range", "Work Arrangement",
        ])
        remote_insert = {key: value for key, value in job.items()
                         if key in publishable}
        remote = {
            "tab": "Job History", "identity": {"Job Key": "JOB-SELECTED"},
            "append_if_missing": True, "on_insert": remote_insert,
            "values": {}, "expected": {}, "append_notes": {},
        }
        self.plan["local_operations"].append(local)
        self.plan["remote_projection"].append(remote)
        self.plan["publication_schema"]["Job History"] = sorted(publishable)
        self.plan["publication_schema_digest"] = _digest(
            self.plan["publication_schema"])
        self.plan["local_operations_digest"] = _digest(
            self.plan["local_operations"])
        self.plan["local_expected_records"] = record_fingerprints(
            self.plan["local_operations"])
        self.plan["local_expected_records_digest"] = _digest(
            self.plan["local_expected_records"])
        self.plan["remote_projection_digest"] = _digest(
            self.plan["remote_projection"])
        self.plan["remote_records"] = record_fingerprints(
            self.plan["remote_projection"])
        self.plan["remote_records_digest"] = _digest(
            self.plan["remote_records"])
        self.plan["local_finalization_digest"] = _digest({
            "operations": self.plan["local_operations"],
            "final": self.plan["final"],
        })
        self.plan["plan_digest"] = _exact_plan_digest(self.plan)

    def confirm_remote_authorities(self, acknowledgement="ACK-1"):
        application = retained_publication(
            self.repository, "reservation-digest")
        with self.repository.transaction():
            self.repository.db.execute("DELETE FROM dirty")
            self.repository.db.execute(
                "INSERT INTO exact_local_acknowledgements VALUES (?,?,?,?,?)",
                (application["local_apply_id"], "REC-1", acknowledgement,
                 "selected-fields-digest", "2026-11-19T00:00:00Z"))
        with self.inbox.lock, self.inbox.connection:
            self.inbox.connection.execute(
                "UPDATE publication_receipts SET state='SYNC_CONFIRMED',"
                "acknowledgement_id=? WHERE receipt_id='REC-1'",
                (acknowledgement,))
            self.inbox.connection.execute(
                "UPDATE exact_remote_plans SET state='SYNC_CONFIRMED',"
                "acknowledgement_id=? WHERE cycle='CYC-NEW' AND company='COMP-NEW'",
                (acknowledgement,))

    def reserve(self):
        with self.repository.transaction():
            self.repository.db.execute("""CREATE TABLE IF NOT EXISTS retained_intake_holds (
                reservation_digest TEXT PRIMARY KEY, request_id TEXT NOT NULL,
                event_id TEXT NOT NULL, company_id TEXT NOT NULL,
                manifest_digest TEXT NOT NULL, start_binding_digest TEXT NOT NULL,
                state TEXT NOT NULL)""")
            self.repository.db.execute(
                "INSERT OR IGNORE INTO retained_intake_holds VALUES (?,?,?,?,?,?,?)",
                ("reservation-digest", "REQ-NEW", "CEV-NEW", "COMP-NEW",
                 "manifest-digest", "start-binding-digest", "FROZEN"))
        return reserve_dirty_provenance(
            self.repository,
            reservation_digest="reservation-digest",
            request_id="REQ-NEW",
            event_id="CEV-NEW",
            exception_cycle_id="CYC-HISTORICAL",
            cycle_id="CYC-NEW",
            company_id="COMP-NEW",
            source_revision="source-revision",
            manifest_digest="manifest-digest",
            start_binding_digest="start-binding-digest",
            plan=self.plan,
        )

    def dirty(self):
        return list(self.repository.db.execute(
            "SELECT tab,row_id,header FROM dirty ORDER BY tab,row_id,header"))

    def test_clean_reservation_and_local_commit_seal_exact_dirty_cells(self):
        self.assertEqual(self.reserve()["state"], RESERVED)
        self.assertEqual(self.repository.db.execute(
            "SELECT count(*) FROM retained_intake_holds").fetchone()[0], 0)
        result = commit_exact_local_plan(
            self.repository, "CYC-NEW", "COMP-NEW", self.plan,
            reservation_digest="reservation-digest")
        self.assertEqual(result["retained_provenance"]["state"], LOCAL_VERIFIED)
        publication = retained_publication(
            self.repository, "reservation-digest")
        self.assertEqual(publication["state"], LOCAL_VERIFIED)
        self.assertEqual(publication["plan_digest"], self.plan["plan_digest"])
        self.assertEqual({header for _tab, _row, header in self.dirty()},
                         {"Last Checked", "Next Action"})
        cells = self.repository.db.execute(
            "SELECT tab,row_id,header FROM retained_dirty_cells "
            "WHERE reservation_digest=? ORDER BY tab,row_id,header",
            ("reservation-digest",)).fetchall()
        self.assertEqual(cells, self.dirty())
        self.assertEqual(self.reserve()["state"], LOCAL_VERIFIED)

    def test_preexisting_dirty_cell_blocks_reservation_without_parent(self):
        self.repository.commit([{
            "tab": "Companies",
            "identity": {"Company ID": "COMP-OTHER"},
            "values": {"Next Action": "unrelated"},
        }])
        with self.assertRaisesRegex(ValueError, "preexisting"):
            self.reserve()
        count = self.repository.db.execute(
            "SELECT count(*) FROM retained_publications").fetchone()[0]
        self.assertEqual(count, 0)

    def test_local_failure_rolls_back_cells_and_chunk_evidence(self):
        self.reserve()
        with patch.object(self.repository, "_commit_in_transaction",
                          side_effect=OSError("disk failure")):
            with self.assertRaisesRegex(OSError, "disk failure"):
                commit_exact_local_plan(
                    self.repository, "CYC-NEW", "COMP-NEW", self.plan,
                    reservation_digest="reservation-digest")
        self.assertEqual(self.dirty(), [])
        self.assertEqual(self.repository.db.execute(
            "SELECT count(*) FROM retained_dirty_cells").fetchone()[0], 0)
        self.assertEqual(self.repository.db.execute(
            "SELECT count(*) FROM retained_dirty_chunks").fetchone()[0], 0)
        self.assertEqual(retained_publication(
            self.repository, "reservation-digest")["state"], RESERVED)

    def test_unrelated_dirty_change_after_verification_blocks_reread(self):
        self.reserve()
        commit_exact_local_plan(
            self.repository, "CYC-NEW", "COMP-NEW", self.plan,
            reservation_digest="reservation-digest")
        self.repository.commit([{
            "tab": "Companies",
            "identity": {"Company ID": "COMP-OTHER"},
            "values": {"Next Action": "foreign mutation"},
        }])
        with self.assertRaisesRegex(ValueError, "dirty_set_changed"):
            verify_dirty_provenance(
                self.repository, "reservation-digest", self.plan)

    def test_local_only_chunk_is_journaled_without_inventing_remote_cells(self):
        evidence = {
            "tab": "Job Evidence",
            "identity": {"Job Key": "JOB-1", "Source Hash": "HASH-1"},
            "append_if_missing": True,
            "on_insert": {
                "Job Key": "JOB-1", "Source Hash": "HASH-1",
                "Company": "Fixture COMP-NEW", "Job Title": "Role",
                "Official Job URL": "https://jobs.example.test/role",
                "Captured At": "2026-11-19", "Job Description": "Evidence",
            },
        }
        self.plan["local_operations"].insert(0, evidence)
        self.plan["local_operations_digest"] = _digest(
            self.plan["local_operations"])
        self.plan["local_expected_records"] = record_fingerprints(
            self.plan["local_operations"])
        self.plan["local_expected_records_digest"] = _digest(
            self.plan["local_expected_records"])
        self.plan["local_finalization_digest"] = _digest({
            "operations": self.plan["local_operations"],
            "final": self.plan["final"],
        })
        self.plan["plan_digest"] = _exact_plan_digest(self.plan)
        self.reserve()
        commit_exact_local_plan(
            self.repository, "CYC-NEW", "COMP-NEW", self.plan,
            max_operations=1, reservation_digest="reservation-digest")
        chunks = self.repository.db.execute(
            "SELECT start_cursor,operation_count FROM retained_dirty_chunks "
            "WHERE reservation_digest=? ORDER BY start_cursor",
            ("reservation-digest",)).fetchall()
        self.assertEqual(chunks, [(0, 1), (1, 1)])
        self.assertEqual({tab for tab, _row, _header in self.dirty()},
                         {"Companies"})

    def test_changed_reservation_binding_is_refused(self):
        first = self.reserve()
        altered = copy.deepcopy(self.plan)
        altered["final"]["stage"] = "partial"
        altered["local_finalization_digest"] = _digest({
            "operations": altered["local_operations"], "final": altered["final"]})
        altered["plan_digest"] = _exact_plan_digest(altered)
        with self.assertRaisesRegex(ValueError, "reservation_changed"):
            reserve_dirty_provenance(
                self.repository,
                reservation_digest="reservation-digest",
                request_id="REQ-NEW",
                event_id="CEV-NEW",
                exception_cycle_id="CYC-HISTORICAL",
                cycle_id="CYC-NEW",
                company_id="COMP-NEW",
                source_revision="source-revision",
                manifest_digest="manifest-digest",
                start_binding_digest="start-binding-digest",
                plan=altered,
            )
        self.assertEqual(first["plan_digest"], self.plan["plan_digest"])

    def test_dirty_clear_crash_recovers_from_durable_remote_authorities(self):
        self.reserve()
        commit_exact_local_plan(
            self.repository, "CYC-NEW", "COMP-NEW", self.plan,
            reservation_digest="reservation-digest")
        self.freeze_remote_intent()
        bound = bind_remote_intent(
            self.repository, "reservation-digest", self.plan, inbox=self.inbox)
        self.assertEqual(bound["state"], REMOTE_PENDING)
        self.confirm_remote_authorities()
        # Simulate a restart after exact acknowledgement cleared dirty cells
        # but before this ledger recorded REMOTE_CONFIRMED.
        self.assertEqual(self.reserve()["state"], REMOTE_PENDING)
        self.assertEqual(bind_remote_intent(
            self.repository, "reservation-digest", self.plan,
            inbox=self.inbox)["state"], REMOTE_PENDING)
        confirmed = confirm_remote_from_authorities(
            self.repository, "reservation-digest", self.plan, inbox=self.inbox)
        self.assertEqual(confirmed["state"], REMOTE_CONFIRMED)
        self.assertEqual(self.reserve()["state"], REMOTE_CONFIRMED)

    def test_fabricated_local_ack_cannot_confirm_without_inbox_readback(self):
        self.reserve()
        commit_exact_local_plan(
            self.repository, "CYC-NEW", "COMP-NEW", self.plan,
            reservation_digest="reservation-digest")
        self.freeze_remote_intent()
        bind_remote_intent(
            self.repository, "reservation-digest", self.plan, inbox=self.inbox)
        application = retained_publication(
            self.repository, "reservation-digest")
        with self.repository.transaction():
            self.repository.db.execute("DELETE FROM dirty")
            self.repository.db.execute(
                "INSERT INTO exact_local_acknowledgements VALUES (?,?,?,?,?)",
                (application["local_apply_id"], "REC-1", "FORGED-ACK",
                 "selected-fields-digest", "2026-11-19T00:00:00Z"))
        with self.assertRaisesRegex(ValueError, "confirmation_mismatch"):
            confirm_remote_from_authorities(
                self.repository, "reservation-digest", self.plan,
                inbox=self.inbox)
        self.assertEqual(retained_publication(
            self.repository, "reservation-digest")["state"], REMOTE_PENDING)

    def test_generic_sheets_paths_refuse_active_retained_hold(self):
        self.reserve()

        class NoRemoteAccess:
            spreadsheet_id = "fixture"

            def __getattr__(self, name):
                raise AssertionError("generic remote access is forbidden: " + name)

        synchronizer = SheetsSynchronizer(self.repository, NoRemoteAccess())
        with self.assertRaisesRegex(RepositoryError, "dedicated exact publisher"):
            synchronizer.merge_remote("Companies", [])
        with self.assertRaisesRegex(RepositoryError, "dedicated exact publisher"):
            synchronizer._operations()
        with self.assertRaisesRegex(RepositoryError, "dedicated exact publisher"):
            synchronizer.pull()
        with self.assertRaisesRegex(RepositoryError, "dedicated exact publisher"):
            synchronizer.publish_batch()

    def test_generic_sheets_paths_refuse_frozen_preplan_intake_hold(self):
        with self.repository.transaction():
            self.repository.db.execute("""CREATE TABLE retained_intake_holds (
                reservation_digest TEXT PRIMARY KEY, request_id TEXT NOT NULL,
                event_id TEXT NOT NULL, company_id TEXT NOT NULL,
                manifest_digest TEXT NOT NULL, start_binding_digest TEXT NOT NULL,
                state TEXT NOT NULL)""")
            self.repository.db.execute(
                "INSERT INTO retained_intake_holds VALUES (?,?,?,?,?,?,?)",
                ("reservation", "request", "event", "COMP-NEW", "manifest",
                 "binding", "FROZEN"))

        class NoRemoteAccess:
            spreadsheet_id = "fixture"

            def __getattr__(self, name):
                raise AssertionError("generic remote access is forbidden: " + name)

        synchronizer = SheetsSynchronizer(self.repository, NoRemoteAccess())
        with self.assertRaisesRegex(RepositoryError, "Retained intake hold"):
            synchronizer.pull()

    def test_generic_sheets_paths_hold_every_pre_release_state(self):
        class NoRemoteAccess:
            spreadsheet_id = "fixture"

            def __getattr__(self, name):
                raise AssertionError("generic remote access is forbidden: " + name)

        synchronizer = SheetsSynchronizer(self.repository, NoRemoteAccess())
        for state in (RESERVED, LOCAL_VERIFIED, REMOTE_PENDING,
                      REMOTE_CONFIRMED):
            with self.subTest(state=state):
                self.reserve()
                with self.repository.transaction():
                    self.repository.db.execute(
                        "UPDATE retained_publications SET state=? "
                        "WHERE reservation_digest=?", (state, "reservation-digest"))
                with self.assertRaisesRegex(RepositoryError,
                                            "dedicated exact publisher"):
                    synchronizer.pull()

    def test_ordinary_exact_confirmation_paths_refuse_retained_hold(self):
        self.reserve()

        class NoRemoteAccess:
            spreadsheet_id = "fixture"

            def __getattr__(self, name):
                raise AssertionError("generic remote access is forbidden: " + name)

        synchronizer = SheetsSynchronizer(self.repository, NoRemoteAccess())
        arguments = dict(inbox=self.inbox, cycle_id="CYC-NEW",
                         company_id="COMP-NEW", plan_digest="plan",
                         receipt_id="receipt", intent_id="intent")
        with self.assertRaisesRegex(RepositoryError, "dedicated exact publisher"):
            synchronizer.confirm_exact_scope(**arguments)
        with self.assertRaisesRegex(RepositoryError, "dedicated exact publisher"):
            synchronizer.confirm_and_acknowledge_exact_scope(**arguments)

    def test_ordinary_exact_cycle_publisher_rejects_retained_cycle(self):
        class RetainedState:
            def cycle(self, cycle_id):
                return {
                    "id": cycle_id,
                    "status": "In Progress",
                    "companies": {"COMP-NEW": {}},
                    "retained_work_exception": {
                        "reservation_digest": "reservation-digest"},
                }

        with self.assertRaisesRegex(ValueError, "dedicated reservation-bound"):
            publish_exact_cycle(
                self.inbox, "CYC-NEW", object(),
                company_ids=["COMP-NEW"], state=RetainedState(),
                company_guard=lambda *_: {}, local=self.repository)

    def test_first_pass_release_requires_remote_confirmation_and_is_restart_safe(self):
        self.reserve()
        commit_exact_local_plan(
            self.repository, "CYC-NEW", "COMP-NEW", self.plan,
            reservation_digest="reservation-digest")
        output = Path(self.temporary.name) / "retained-first-pass"
        with self.assertRaisesRegex(ValueError, "remote_confirmation_required"):
            release_retained_first_pass(
                self.repository, "reservation-digest", self.plan, output)
        self.freeze_remote_intent()
        bind_remote_intent(
            self.repository, "reservation-digest", self.plan, inbox=self.inbox)
        self.confirm_remote_authorities()
        confirm_remote_from_authorities(
            self.repository, "reservation-digest", self.plan, inbox=self.inbox)
        first = release_retained_first_pass(
            self.repository, "reservation-digest", self.plan, output)
        self.assertEqual(first["selected_jobs"], [])
        self.assertEqual(first["counts"], {
            "first_pass": 0, "second_pass": 0, "deterministic_filtered": 0})
        destination = Path(first["output_dir"])
        self.assertTrue((destination / "first-pass.jsonl").is_file())
        self.assertEqual(retained_publication(
            self.repository, "reservation-digest")["state"],
                         "FIRST_PASS_RELEASED")
        self.assertEqual(release_retained_first_pass(
            self.repository, "reservation-digest", self.plan, output), first)

    def test_first_pass_release_contains_only_selected_delivered_job(self):
        self.add_selected_job_to_plan()
        unrelated = {
            "Job Key": "JOB-FOREIGN", "Source Hash": "SOURCE-FOREIGN",
            "Company": "Other", "Job Title": "Field Engineer",
            "Added to Opportunities?": "Pending",
            "Official Job URL": "https://jobs.example.test/foreign",
            "Job Status": "Open", "Review Status": "Needs Review",
        }
        self.repository.import_rows("Job History", [(2, unrelated)])
        self.reserve()
        commit_exact_local_plan(
            self.repository, "CYC-NEW", "COMP-NEW", self.plan,
            reservation_digest="reservation-digest")
        self.freeze_remote_intent()
        bind_remote_intent(
            self.repository, "reservation-digest", self.plan, inbox=self.inbox)
        self.confirm_remote_authorities()
        confirm_remote_from_authorities(
            self.repository, "reservation-digest", self.plan, inbox=self.inbox)
        output = Path(self.temporary.name) / "selected-first-pass"
        evidence = release_retained_first_pass(
            self.repository, "reservation-digest", self.plan, output)
        self.assertEqual([(item["job_key"], item["source_hash"])
                          for item in evidence["selected_jobs"]],
                         [("JOB-SELECTED", "SOURCE-SELECTED")])
        first_pass = [json.loads(line) for line in
                      (Path(evidence["output_dir"]) / "first-pass.jsonl")
                      .read_text().splitlines()]
        self.assertEqual([item["job_key"] for item in first_pass],
                         ["JOB-SELECTED"])

    def test_first_pass_never_bulk_reads_shared_job_evidence(self):
        self.add_selected_job_to_plan()
        evidence = {
            "Job Key": "JOB-SELECTED", "Source Hash": "SOURCE-SELECTED",
            "Company": "Fixture COMP-NEW",
            "Job Title": "Field Applications Engineer",
            "Official Job URL": "https://jobs.example.test/selected",
            "Captured At": "2026-11-19",
            "Job Description": "Field applications support",
        }
        foreign = dict(evidence, **{
            "Job Key": "JOB-FOREIGN", "Source Hash": "SOURCE-FOREIGN",
            "Job Description": "foreign evidence must not be read",
        })
        self.repository.import_rows("Job Evidence", [(2, evidence), (3, foreign)])
        self.reserve()
        commit_exact_local_plan(
            self.repository, "CYC-NEW", "COMP-NEW", self.plan,
            reservation_digest="reservation-digest")
        self.freeze_remote_intent()
        bind_remote_intent(
            self.repository, "reservation-digest", self.plan, inbox=self.inbox)
        self.confirm_remote_authorities()
        confirm_remote_from_authorities(
            self.repository, "reservation-digest", self.plan, inbox=self.inbox)
        original_read_columns = self.repository.read_columns

        def selected_only(tab, headers):
            if tab == "Job Evidence":
                raise AssertionError("retained first pass bulk-read Job Evidence")
            return original_read_columns(tab, headers)

        with patch.object(self.repository, "read_columns", side_effect=selected_only):
            result = release_retained_first_pass(
                self.repository, "reservation-digest", self.plan,
                Path(self.temporary.name) / "selected-only-evidence")
        self.assertEqual(result["selected_jobs"], [{
            "row_id": 1, "job_key": "JOB-SELECTED",
            "source_hash": "SOURCE-SELECTED"}])

    def test_first_pass_crash_then_coherent_file_tamper_is_refused(self):
        self.add_selected_job_to_plan()
        self.reserve()
        commit_exact_local_plan(
            self.repository, "CYC-NEW", "COMP-NEW", self.plan,
            reservation_digest="reservation-digest")
        self.freeze_remote_intent()
        bind_remote_intent(
            self.repository, "reservation-digest", self.plan, inbox=self.inbox)
        self.confirm_remote_authorities()
        confirm_remote_from_authorities(
            self.repository, "reservation-digest", self.plan, inbox=self.inbox)
        output = Path(self.temporary.name) / "crash-first-pass"
        with patch.object(self.repository, "transaction",
                          side_effect=OSError("injected DB checkpoint failure")):
            with self.assertRaisesRegex(OSError, "checkpoint failure"):
                release_retained_first_pass(
                    self.repository, "reservation-digest", self.plan, output)
        self.assertEqual(retained_publication(
            self.repository, "reservation-digest")["state"], REMOTE_CONFIRMED)
        destinations = [path for path in output.iterdir()
                        if path.name.startswith("retained-")]
        self.assertEqual(len(destinations), 1)
        destination = destinations[0]

        # Rewrite the queue and all self-reported hashes coherently.  Retry
        # must still compare against a fresh authoritative queue derivation.
        first_path = destination / "first-pass.jsonl"
        first_path.write_text(json.dumps({
            "job_key": "JOB-FOREIGN", "source_hash": "SOURCE-FOREIGN"}) + "\n")
        first_hash = __import__("hashlib").sha256(first_path.read_bytes()).hexdigest()
        summary_path = destination / "summary.json"
        summary = json.loads(summary_path.read_text())
        summary["file_sha256"]["first-pass.jsonl"] = first_hash
        summary_path.write_text(json.dumps(
            summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        summary_hash = __import__("hashlib").sha256(
            summary_path.read_bytes()).hexdigest()
        release_path = destination / "release.json"
        release = json.loads(release_path.read_text())
        release["file_sha256"]["first-pass.jsonl"] = first_hash
        release["file_sha256"]["summary.json"] = summary_hash
        release["evidence_digest"] = _digest({
            key: value for key, value in release.items()
            if key != "evidence_digest"})
        release_path.write_text(json.dumps(
            release, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        with self.assertRaisesRegex(ValueError, "existing_release_changed"):
            release_retained_first_pass(
                self.repository, "reservation-digest", self.plan, output)
        self.assertEqual(retained_publication(
            self.repository, "reservation-digest")["state"], REMOTE_CONFIRMED)

    def test_first_pass_clean_post_file_crash_converges_without_rewrite(self):
        self.reserve()
        commit_exact_local_plan(
            self.repository, "CYC-NEW", "COMP-NEW", self.plan,
            reservation_digest="reservation-digest")
        self.freeze_remote_intent()
        bind_remote_intent(
            self.repository, "reservation-digest", self.plan, inbox=self.inbox)
        self.confirm_remote_authorities()
        confirm_remote_from_authorities(
            self.repository, "reservation-digest", self.plan, inbox=self.inbox)
        output = Path(self.temporary.name) / "clean-crash-first-pass"
        with patch.object(self.repository, "transaction",
                          side_effect=OSError("injected DB checkpoint failure")):
            with self.assertRaisesRegex(OSError, "checkpoint failure"):
                release_retained_first_pass(
                    self.repository, "reservation-digest", self.plan, output)
        recovered = release_retained_first_pass(
            self.repository, "reservation-digest", self.plan, output)
        self.assertEqual(recovered["selected_jobs"], [])
        self.assertEqual(retained_publication(
            self.repository, "reservation-digest")["state"],
                         "FIRST_PASS_RELEASED")

    def test_first_pass_refuses_evidence_change_during_file_publication(self):
        self.add_selected_job_to_plan()
        evidence = {
            "Job Key": "JOB-SELECTED", "Source Hash": "SOURCE-SELECTED",
            "Company": "Fixture COMP-NEW",
            "Job Title": "Field Applications Engineer",
            "Official Job URL": "https://jobs.example.test/selected",
            "Captured At": "2026-11-19",
            "Job Description": "Field applications support",
        }
        self.repository.import_rows("Job Evidence", [(2, evidence)])
        self.reserve()
        commit_exact_local_plan(
            self.repository, "CYC-NEW", "COMP-NEW", self.plan,
            reservation_digest="reservation-digest")
        self.freeze_remote_intent()
        bind_remote_intent(
            self.repository, "reservation-digest", self.plan, inbox=self.inbox)
        self.confirm_remote_authorities()
        confirm_remote_from_authorities(
            self.repository, "reservation-digest", self.plan, inbox=self.inbox)
        output = Path(self.temporary.name) / "evidence-race-first-pass"
        real_write = retained_first_pass_module._write_release

        def write_then_change_evidence(destination, result, release_evidence):
            written = real_write(destination, result, release_evidence)
            changed = dict(evidence)
            changed["Job Description"] = "Navy systems integration support"
            self.repository.import_rows("Job Evidence", [(2, changed)])
            return written

        with patch.object(retained_first_pass_module, "_write_release",
                          side_effect=write_then_change_evidence):
            with self.assertRaisesRegex(ValueError, "source_changed"):
                release_retained_first_pass(
                    self.repository, "reservation-digest", self.plan, output)
        self.assertEqual(retained_publication(
            self.repository, "reservation-digest")["state"], REMOTE_CONFIRMED)


if __name__ == "__main__":
    unittest.main()
