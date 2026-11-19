import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from job_search_helper.exact_legacy_migration import (
    build_legacy_v2_plan, preview_legacy_migration_binding,
)
from job_search_helper.exact_local_plan import (
    _resolved_row_scope, _row_scope, commit_exact_local_plan, exact_local_plan,
)
from job_search_helper.repository import MemoryRepository, SCHEMAS
from job_search_helper.exact_cycle_planner import (
    _digest, _validate_existing_exact_plan_v2,
)
from job_search_helper.sqlite_repository import SQLiteRepository
from job_search_helper.publication_receipts import record_fingerprints
from job_search_helper.inbox import InventoryInbox
from job_search_helper.exact_cycle_sync import _fallback_receipt
from job_search_helper.exact_legacy_migration_runner import (
    adopt_retained_legacy_migration, preview_retained_legacy_migration,
)


URL = "https://boards.example.test/davidson"


class CompactMemoryRepository(MemoryRepository):
    spreadsheet_id = "fixture"

    def get_meta(self, key):
        return "compact-v1" if key == "sheets_profile" else None

    def matches(self, tab, identity):
        return [(number, copy.deepcopy(row))
                for number, row in enumerate(self.read(tab), start=2)
                if all(str(row.get(key, "")) == str(value)
                       for key, value in identity.items())]


def controls():
    return {
        "company_id": "COMP-0035", "requested_url": URL,
        "official_careers_url": URL, "company_status": "Active",
        "claimed_by": "", "claim_token": "",
    }


def binding(repo, legacy, payload, cursor):
    return preview_legacy_migration_binding(
        repo, cycle_id="CYC-B639C6D864EC", company_id="COMP-0035",
        payload=payload, legacy_plan=legacy, cursor=cursor,
        controls=controls())


def fixture(*, unrelated_drift=False, cursor=3):
    schemas = copy.deepcopy(SCHEMAS)
    schemas["Opportunities"].append("Opportunity ID")
    repo = CompactMemoryRepository({
        "Companies": [{
            "Company ID": "COMP-0035", "Company": "Davidson",
            "Company Status": "Active", "Official Careers URL": URL,
            "Last Checked": "now",
        }],
        "Job Evidence": [{
            "Job Key": "job-1", "Source Hash": "hash-1",
            "Job Description": "evidence",
        }],
        "Job History": [{
            "Job Key": "job-1", "Company": "Davidson",
            "Official Job URL": "https://jobs.example.test/1",
            "Last Checked": "changed" if unrelated_drift else "now",
            "Review Status": "Human Reviewed", "Decision": "Keep",
        }],
    }, schemas=schemas)
    operations = [{
        "tab": "Companies", "identity": {"Company ID": "COMP-0035"},
        "values": {"Last Checked": "now"}, "on_insert": {},
        "expected": {}, "append_notes": {}, "append_if_missing": False,
    }, {
        "tab": "Job Evidence",
        "identity": {"Job Key": "job-1", "Source Hash": "hash-1"},
        "values": {"Job Description": "evidence"}, "on_insert": {},
        "expected": {}, "append_notes": {}, "append_if_missing": False,
    }, {
        "tab": "Job History", "identity": {"Job Key": "job-1"},
        "values": {"Company": "Davidson",
                   "Official Job URL": "https://jobs.example.test/1",
                   "Last Checked": "now", "Review Status": "Pending",
                   "Decision": "Old"},
        "on_insert": {}, "expected": {}, "append_notes": {},
        "append_if_missing": False,
    }]
    legacy = {"operations": operations, "final": {"stage": "complete"},
              "requested_url": URL}
    payload = {"inventory_status": "complete", "jobs": [],
               "requested_url": URL}
    return repo, legacy, payload, cursor


class LegacyMigrationTests(unittest.TestCase):
    def sqlite_fixture(self, temporary):
        repo = SQLiteRepository(
            Path(temporary) / "jobs.sqlite3", "fixture", initialize=True)
        repo.ensure_columns("Opportunities", ["Opportunity ID"])
        rows = {
            "Companies": [{
                "Company ID": "COMP-0035", "Company": "Davidson",
                "Company Status": "Active", "Official Careers URL": URL,
                "Last Checked": "now",
            }],
            "Job Evidence": [{
                "Job Key": "job-1", "Source Hash": "hash-1",
                "Job Description": "evidence",
            }],
            "Job History": [{
                "Job Key": "job-1", "Company": "Davidson",
                "Official Job URL": "https://jobs.example.test/1",
                "Last Checked": "now", "Review Status": "Human Reviewed",
                "Decision": "Keep",
            }],
        }
        for tab in SCHEMAS:
            repo.import_rows(tab, enumerate(rows.get(tab, []), 2))
        with repo.transaction():
            repo.set_meta("ready", "yes")
            repo.set_meta("sheets_profile", "compact-v1")
        return repo

    def test_protected_drift_becomes_guards_and_local_only_tab_is_projected_out(self):
        repo, legacy, payload, cursor = fixture()
        plan, report = build_legacy_v2_plan(
            repo, cycle_id="CYC-B639C6D864EC", company_id="COMP-0035",
            payload=payload, legacy_plan=legacy, cursor=cursor,
            controls=controls(), binding=binding(repo, legacy, payload, cursor))
        self.assertEqual(report["legacy_operation_count"], 3)
        self.assertEqual(report["remote_operation_count"], 2)
        self.assertEqual(report["local_only_operation_count"], 1)
        self.assertEqual(report["protected_conflict_count"], 1)
        history = next(item for item in plan["local_operations"]
                       if item["tab"] == "Job History")
        self.assertNotIn("Review Status", history["values"])
        self.assertNotIn("Decision", history["values"])
        self.assertEqual(history["expected"]["Review Status"], "Human Reviewed")
        self.assertEqual(history["expected"]["Decision"], "Keep")
        remote = next(item for item in plan["remote_projection"]
                      if item["tab"] == "Job History")
        self.assertNotIn("Review Status", remote["values"])
        self.assertEqual(remote["expected"]["Review Status"], "Human Reviewed")
        scope = _row_scope(plan)
        history_scope = next(item for item in scope if item["tab"] == "Job History")
        self.assertEqual(history_scope["guards"]["Review Status"], "Human Reviewed")
        self.assertEqual(history_scope["guards"]["Decision"], "Keep")
        self.assertEqual([item["tab"] for item in plan["remote_projection"]],
                         ["Job History", "Companies"])
        self.assertIs(_validate_existing_exact_plan_v2(
            plan, payload, repo, "CYC-B639C6D864EC", "COMP-0035",
            plan["control_evidence_digest"]), plan)
        receipt = _fallback_receipt({
            "id": "CYC-B639C6D864EC", "started_at": "start",
            "companies": {"COMP-0035": {}},
        }, "COMP-0035", plan, payload)
        self.assertEqual(receipt["records"], plan["remote_records"])
        self.assertFalse(report["mutation_performed"])

    def test_nonprotected_local_drift_refuses(self):
        repo, legacy, payload, cursor = fixture(unrelated_drift=True)
        with self.assertRaisesRegex(ValueError, "nonprotected_drift"):
            build_legacy_v2_plan(
                repo, cycle_id="CYC-B639C6D864EC", company_id="COMP-0035",
                payload=payload, legacy_plan=legacy, cursor=cursor,
                controls=controls(), binding=binding(repo, legacy, payload, cursor))

    def test_incomplete_cursor_refuses(self):
        repo, legacy, payload, _cursor = fixture(cursor=2)
        with self.assertRaisesRegex(ValueError, "cursor_not_complete"):
            build_legacy_v2_plan(
                repo, cycle_id="CYC-B639C6D864EC", company_id="COMP-0035",
                payload=payload, legacy_plan=legacy, cursor=2,
                controls=controls(), binding=binding(repo, legacy, payload, 2))

    def test_control_identity_mismatch_refuses(self):
        repo, legacy, payload, cursor = fixture()
        bad = controls(); bad["company_id"] = "OTHER"
        with self.assertRaisesRegex(ValueError, "control_evidence_identity_mismatch"):
            build_legacy_v2_plan(
                repo, cycle_id="CYC-B639C6D864EC", company_id="COMP-0035",
                payload=payload, legacy_plan=legacy, cursor=cursor, controls=bad,
                binding=binding(repo, legacy, payload, cursor))

    def test_exact_retained_binding_is_required(self):
        repo, legacy, payload, cursor = fixture()
        exact = binding(repo, legacy, payload, cursor)
        for key, value in (("cycle_id", "CYC-OTHER"),
                           ("company_id", "COMP-OTHER"),
                           ("legacy_plan_digest", "0" * 64),
                           ("inventory_payload_digest", "1" * 64),
                           ("legacy_operation_count", 99),
                           ("original_local_cursor", 2)):
            changed = copy.deepcopy(exact); changed[key] = value
            with self.assertRaisesRegex(ValueError, "binding_mismatch"):
                build_legacy_v2_plan(
                    repo, cycle_id="CYC-B639C6D864EC", company_id="COMP-0035",
                    payload=payload, legacy_plan=legacy, cursor=cursor,
                    controls=controls(), binding=changed)

    def test_migration_metadata_requires_the_exact_protected_field_set(self):
        repo, legacy, payload, cursor = fixture()
        plan, _report = build_legacy_v2_plan(
            repo, cycle_id="CYC-B639C6D864EC", company_id="COMP-0035",
            payload=payload, legacy_plan=legacy, cursor=cursor,
            controls=controls(), binding=binding(repo, legacy, payload, cursor))
        for protected in ([], ["Review Status"],
                          ["Decision", "Review Status", "Review Status"]):
            altered = copy.deepcopy(plan)
            altered["legacy_migration"]["protected_fields"] = protected
            with self.assertRaisesRegex(ValueError, "migration guards are invalid"):
                _row_scope(altered)

    def test_changed_protected_guard_refuses_scope_verification(self):
        repo, legacy, payload, cursor = fixture()
        plan, _report = build_legacy_v2_plan(
            repo, cycle_id="CYC-B639C6D864EC", company_id="COMP-0035",
            payload=payload, legacy_plan=legacy, cursor=cursor,
            controls=controls(), binding=binding(repo, legacy, payload, cursor))
        repo.commit([{
            "tab": "Job History", "identity": {"Job Key": "job-1"},
            "values": {"Decision": "Reject"}, "on_insert": {},
            "expected": {}, "append_notes": {}, "append_if_missing": False,
        }])
        with self.assertRaisesRegex(ValueError, "guard changed before verification"):
            _resolved_row_scope(repo, plan)

    def test_verified_restart_refuses_changed_protected_guard(self):
        memory, legacy, payload, cursor = fixture()
        plan, _report = build_legacy_v2_plan(
            memory, cycle_id="CYC-B639C6D864EC", company_id="COMP-0035",
            payload=payload, legacy_plan=legacy, cursor=cursor,
            controls=controls(), binding=binding(memory, legacy, payload, cursor))
        with tempfile.TemporaryDirectory() as temporary:
            repo = SQLiteRepository(
                Path(temporary) / "jobs.sqlite3", "fixture", initialize=True)
            self.addCleanup(repo.close)
            rows = {
                "Companies": [{
                    "Company ID": "COMP-0035", "Company": "Davidson",
                    "Company Status": "Active", "Official Careers URL": URL,
                    "Last Checked": "now",
                }],
                "Job Evidence": [{
                    "Job Key": "job-1", "Source Hash": "hash-1",
                    "Job Description": "evidence",
                }],
                "Job History": [{
                    "Job Key": "job-1", "Company": "Davidson",
                    "Official Job URL": "https://jobs.example.test/1",
                    "Last Checked": "now", "Review Status": "Human Reviewed",
                    "Decision": "Keep",
                }],
            }
            for tab in SCHEMAS:
                repo.import_rows(tab, enumerate(rows.get(tab, []), 2))
            with repo.transaction():
                repo.set_meta("ready", "yes")
                repo.set_meta("sheets_profile", "compact-v1")
            commit_exact_local_plan(
                repo, "CYC-B639C6D864EC", "COMP-0035", plan)
            self.assertIsNotNone(exact_local_plan(
                repo, "CYC-B639C6D864EC", "COMP-0035"))
            repo.commit([{
                "tab": "Job History", "identity": {"Job Key": "job-1"},
                "values": {"Decision": "Reject"}, "on_insert": {},
                "expected": {}, "append_notes": {}, "append_if_missing": False,
            }])
            with self.assertRaisesRegex(ValueError, "guard changed after verification"):
                exact_local_plan(repo, "CYC-B639C6D864EC", "COMP-0035")

    def test_remote_receipt_includes_guard_only_review_decisions(self):
        operation = {
            "tab": "Job History", "identity": {"Job Key": "job-1"},
            "values": {"Last Checked": "now"}, "on_insert": {},
            "expected": {"Review Status": "Human Reviewed", "Decision": "Keep"},
            "append_notes": {}, "append_if_missing": False,
        }
        planned = record_fingerprints([operation], include_guard_only=True)
        matching = record_fingerprints([operation], {"Job History": [{
            "Job Key": "job-1", "Last Checked": "now",
            "Review Status": "Human Reviewed", "Decision": "Keep",
        }]}, include_guard_only=True)
        changed = record_fingerprints([operation], {"Job History": [{
            "Job Key": "job-1", "Last Checked": "now",
            "Review Status": "Changed", "Decision": "Reject",
        }]}, include_guard_only=True)
        self.assertEqual(matching, planned)
        self.assertNotEqual(changed, planned)
        self.assertEqual(
            record_fingerprints([operation]),
            record_fingerprints([operation], {"Job History": [{
                "Job Key": "job-1", "Last Checked": "now",
                "Review Status": "Changed", "Decision": "Reject",
            }]}))

    def test_durable_adoption_reuses_completed_local_work_without_replay(self):
        _memory, legacy, payload, cursor = fixture()
        with tempfile.TemporaryDirectory() as temporary:
            repo = self.sqlite_fixture(temporary)
            self.addCleanup(repo.close)
            approved = preview_legacy_migration_binding(
                repo, cycle_id="CYC-B639C6D864EC", company_id="COMP-0035",
                payload=payload, legacy_plan=legacy, cursor=cursor,
                controls=controls())
            plan, _report = build_legacy_v2_plan(
                repo, cycle_id="CYC-B639C6D864EC", company_id="COMP-0035",
                payload=payload, legacy_plan=legacy, cursor=cursor,
                controls=controls(), binding=approved)
            for operation in plan["remote_projection"]:
                row_id = repo.matches(operation["tab"], operation["identity"])[0][0]
                fields = set(operation.get("values", {}))
                fields.update(operation.get("on_insert", {}))
                fields.update(operation.get("append_notes", {}))
                repo.mark_dirty(operation["tab"], row_id, fields)
            inbox = InventoryInbox(Path(temporary) / "inbox.sqlite3", "fixture")
            self.addCleanup(inbox.close)
            inbox.save("CYC-B639C6D864EC", "COMP-0035", payload)
            inbox.save_plan("CYC-B639C6D864EC", "COMP-0035", legacy)
            with inbox.lock, inbox.connection:
                inbox.connection.execute(
                    "UPDATE sync_plans SET cursor=? WHERE cycle=? AND company=?",
                    (cursor, "CYC-B639C6D864EC", "COMP-0035"))
            begun = inbox.begin_exact_legacy_migration(
                "CYC-B639C6D864EC", "COMP-0035", plan, approved,
                timestamp="2026-11-19T20:00:00Z")
            self.assertEqual(begun["state"], "FROZEN")
            with self.assertRaisesRegex(ValueError, "cannot be cleaned up"):
                inbox.acknowledge("CYC-B639C6D864EC", "COMP-0035")
            with self.assertRaisesRegex(ValueError, "cannot be discarded"):
                inbox.discard_plan("CYC-B639C6D864EC", "COMP-0035")
            with self.assertRaisesRegex(ValueError, "inventory state is immutable"):
                inbox.block("CYC-B639C6D864EC", "COMP-0035")
            with patch.object(repo, "_commit_in_transaction",
                              side_effect=AssertionError("legacy work must not replay")):
                adopted = repo.adopt_verified_legacy_local_plan(
                    "CYC-B639C6D864EC", "COMP-0035", plan,
                    timestamp_value="2026-11-19T20:00:01Z")
            self.assertFalse(adopted["recovered"])
            local_done = inbox.mark_exact_legacy_local_complete(
                "CYC-B639C6D864EC", "COMP-0035", plan, repo,
                timestamp="2026-11-19T20:00:02Z")
            self.assertEqual(local_done["state"], "LOCAL_COMPLETE")
            frozen = inbox.freeze_exact_legacy_successor(
                "CYC-B639C6D864EC", "COMP-0035", plan, repo,
                timestamp="2026-11-19T20:00:03Z")
            self.assertEqual(frozen["state"], "REMOTE_PLAN_FROZEN")
            stored, stored_cursor = inbox.plan("CYC-B639C6D864EC", "COMP-0035")
            self.assertEqual(stored["plan_digest"], plan["plan_digest"])
            self.assertEqual(stored_cursor, len(plan["local_operations"]))
            self.assertEqual(inbox.exact_local_state(
                "CYC-B639C6D864EC", "COMP-0035")["state"], "LOCAL_VERIFIED")
            self.assertEqual(inbox.connection.execute(
                "SELECT COUNT(*) FROM publication_receipts").fetchone()[0], 0)
            self.assertEqual(inbox.connection.execute(
                "SELECT COUNT(*) FROM exact_remote_plans").fetchone()[0], 0)
            migration = inbox.exact_legacy_migration_state(
                "CYC-B639C6D864EC", "COMP-0035")
            self.assertEqual(migration["state"], "REMOTE_PLAN_FROZEN")
            self.assertEqual(migration["legacy_plan_digest"], _digest(legacy))
            self.assertTrue(repo.adopt_verified_legacy_local_plan(
                "CYC-B639C6D864EC", "COMP-0035", plan,
                timestamp_value="2026-11-19T20:00:04Z")["recovered"])
            self.assertTrue(inbox.freeze_exact_legacy_successor(
                "CYC-B639C6D864EC", "COMP-0035", plan, repo,
                timestamp="2026-11-19T20:00:05Z")["recovered"])
            self.assertFalse(inbox.begin_exact_legacy_migration(
                "CYC-B639C6D864EC", "COMP-0035", plan, approved,
                timestamp="2026-11-19T20:00:06Z")["created"])

    def test_durable_adoption_holds_if_full_snapshot_changes(self):
        _memory, legacy, payload, cursor = fixture()
        with tempfile.TemporaryDirectory() as temporary:
            repo = self.sqlite_fixture(temporary)
            self.addCleanup(repo.close)
            approved = preview_legacy_migration_binding(
                repo, cycle_id="CYC-B639C6D864EC", company_id="COMP-0035",
                payload=payload, legacy_plan=legacy, cursor=cursor,
                controls=controls())
            plan, _report = build_legacy_v2_plan(
                repo, cycle_id="CYC-B639C6D864EC", company_id="COMP-0035",
                payload=payload, legacy_plan=legacy, cursor=cursor,
                controls=controls(), binding=approved)
            repo.commit([{
                "tab": "Job History", "identity": {"Job Key": "job-1"},
                "values": {"Review Notes": "changed after approval"},
            }])
            with self.assertRaisesRegex(ValueError, "snapshot changed"):
                repo.adopt_verified_legacy_local_plan(
                    "CYC-B639C6D864EC", "COMP-0035", plan,
                    timestamp_value="2026-11-19T20:00:01Z")
            self.assertIsNone(exact_local_plan(
                repo, "CYC-B639C6D864EC", "COMP-0035"))

    def test_public_adoption_retry_after_successor_freeze_is_a_noop(self):
        _memory, legacy, payload, cursor = fixture()
        with tempfile.TemporaryDirectory() as temporary:
            local_path = Path(temporary) / "jobs.sqlite3"
            inbox_path = Path(temporary) / "inbox.sqlite3"
            repo = self.sqlite_fixture(temporary)
            approved = preview_legacy_migration_binding(
                repo, cycle_id="CYC-B639C6D864EC", company_id="COMP-0035",
                payload=payload, legacy_plan=legacy, cursor=cursor,
                controls=controls())
            plan, _report = build_legacy_v2_plan(
                repo, cycle_id="CYC-B639C6D864EC", company_id="COMP-0035",
                payload=payload, legacy_plan=legacy, cursor=cursor,
                controls=controls(), binding=approved)
            for operation in plan["remote_projection"]:
                row_id = repo.matches(operation["tab"], operation["identity"])[0][0]
                fields = set(operation.get("values", {}))
                fields.update(operation.get("on_insert", {}))
                fields.update(operation.get("append_notes", {}))
                repo.mark_dirty(operation["tab"], row_id, fields)
            repo.close()
            inbox = InventoryInbox(inbox_path, "fixture")
            inbox.save("CYC-B639C6D864EC", "COMP-0035", payload)
            inbox.save_plan("CYC-B639C6D864EC", "COMP-0035", legacy)
            with inbox.lock, inbox.connection:
                inbox.connection.execute(
                    "UPDATE sync_plans SET cursor=? WHERE cycle=? AND company=?",
                    (cursor, "CYC-B639C6D864EC", "COMP-0035"))
            inbox.close()
            preview = preview_retained_legacy_migration(
                inbox_path, local_path, "CYC-B639C6D864EC", "COMP-0035")
            with patch.object(SQLiteRepository, "_commit_in_transaction",
                              side_effect=AssertionError("legacy work must not replay")):
                first = adopt_retained_legacy_migration(
                    inbox_path, local_path, "CYC-B639C6D864EC", "COMP-0035",
                    preview["binding"])
                retry = adopt_retained_legacy_migration(
                    inbox_path, local_path, "CYC-B639C6D864EC", "COMP-0035",
                    preview["binding"])
            self.assertEqual(first["successor_state"], "REMOTE_PLAN_FROZEN")
            self.assertEqual(retry["successor_state"], "REMOTE_PLAN_FROZEN")
            verify = InventoryInbox(inbox_path, "fixture")
            self.addCleanup(verify.close)
            self.assertEqual(verify.connection.execute(
                "SELECT COUNT(*) FROM publication_receipts").fetchone()[0], 0)

    def test_public_preview_is_byte_for_byte_read_only(self):
        _memory, legacy, payload, cursor = fixture()
        with tempfile.TemporaryDirectory() as temporary:
            local_path = Path(temporary) / "jobs.sqlite3"
            inbox_path = Path(temporary) / "inbox.sqlite3"
            repo = self.sqlite_fixture(temporary)
            repo.close()
            inbox = InventoryInbox(inbox_path, "fixture")
            inbox.save("CYC-B639C6D864EC", "COMP-0035", payload)
            inbox.save_plan("CYC-B639C6D864EC", "COMP-0035", legacy)
            with inbox.lock, inbox.connection:
                inbox.connection.execute(
                    "UPDATE sync_plans SET cursor=? WHERE cycle=? AND company=?",
                    (cursor, "CYC-B639C6D864EC", "COMP-0035"))
            inbox.close()
            before = (local_path.read_bytes(), inbox_path.read_bytes())
            preview = preview_retained_legacy_migration(
                inbox_path, local_path, "CYC-B639C6D864EC", "COMP-0035")
            after = (local_path.read_bytes(), inbox_path.read_bytes())
            self.assertFalse(preview["mutation_performed"])
            self.assertEqual(after, before)

    def test_durable_adoption_recovers_each_cross_database_boundary(self):
        _memory, legacy, payload, cursor = fixture()
        with tempfile.TemporaryDirectory() as temporary:
            local_path = Path(temporary) / "jobs.sqlite3"
            inbox_path = Path(temporary) / "inbox.sqlite3"
            repo = self.sqlite_fixture(temporary)
            approved = preview_legacy_migration_binding(
                repo, cycle_id="CYC-B639C6D864EC", company_id="COMP-0035",
                payload=payload, legacy_plan=legacy, cursor=cursor,
                controls=controls())
            plan, _report = build_legacy_v2_plan(
                repo, cycle_id="CYC-B639C6D864EC", company_id="COMP-0035",
                payload=payload, legacy_plan=legacy, cursor=cursor,
                controls=controls(), binding=approved)
            for operation in plan["remote_projection"]:
                row_id = repo.matches(operation["tab"], operation["identity"])[0][0]
                fields = set(operation.get("values", {}))
                fields.update(operation.get("on_insert", {}))
                fields.update(operation.get("append_notes", {}))
                repo.mark_dirty(operation["tab"], row_id, fields)
            inbox = InventoryInbox(inbox_path, "fixture")
            inbox.save("CYC-B639C6D864EC", "COMP-0035", payload)
            inbox.save_plan("CYC-B639C6D864EC", "COMP-0035", legacy)
            with inbox.lock, inbox.connection:
                inbox.connection.execute(
                    "UPDATE sync_plans SET cursor=? WHERE cycle=? AND company=?",
                    (cursor, "CYC-B639C6D864EC", "COMP-0035"))
            inbox.begin_exact_legacy_migration(
                "CYC-B639C6D864EC", "COMP-0035", plan, approved,
                timestamp="2026-11-19T20:00:00Z")
            inbox.close()
            inbox = InventoryInbox(inbox_path, "fixture")
            with patch.object(repo, "_commit_in_transaction",
                              side_effect=AssertionError("legacy work must not replay")):
                repo.adopt_verified_legacy_local_plan(
                    "CYC-B639C6D864EC", "COMP-0035", plan,
                    timestamp_value="2026-11-19T20:00:01Z")
            repo.close()
            repo = SQLiteRepository(local_path, "fixture")
            inbox.mark_exact_legacy_local_complete(
                "CYC-B639C6D864EC", "COMP-0035", plan, repo,
                timestamp="2026-11-19T20:00:02Z")
            inbox.close()
            inbox = InventoryInbox(inbox_path, "fixture")
            inbox.freeze_exact_legacy_successor(
                "CYC-B639C6D864EC", "COMP-0035", plan, repo,
                timestamp="2026-11-19T20:00:03Z")
            self.assertEqual(inbox.exact_legacy_migration_state(
                "CYC-B639C6D864EC", "COMP-0035")["state"],
                "REMOTE_PLAN_FROZEN")
            self.assertEqual(inbox.connection.execute(
                "SELECT COUNT(*) FROM publication_receipts").fetchone()[0], 0)
            repo.close(); inbox.close()


if __name__ == "__main__":
    unittest.main()
