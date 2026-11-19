import copy
import base64
from contextlib import nullcontext
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from job_search_helper.inbox import InventoryInbox
from job_search_helper.repository import SCHEMAS
from job_search_helper.selected_recovery_authorization import (
    Ed25519AuthorizationVerifier, TestAuthorizationVerifier, canonical,
    verify_authorization, verify_cancellation_authorization,
)
from job_search_helper.selected_recovery_runner import (
    _build_readonly, _default_lock, apply_selected_recovery,
    cancel_selected_recovery,
    preview_selected_recovery,
)
from job_search_helper.engine import State
from job_search_helper.exact_cycle_sync import publish_exact_cycle, _company_guard
from job_search_helper.exact_legacy_migration_runner import (
    adopt_retained_legacy_migration, preview_retained_legacy_migration,
)
from job_search_helper.repository import MemoryRepository
from job_search_helper.sheet_profile import COMPACT_SCHEMAS
from job_search_helper.sqlite_repository import SQLiteRepository


CYCLE = "CYC-B639C6D864EC"
COMPANY = "COMP-0054"
URL = "https://jobs.example.test/board"
EXPIRY = "2030-01-01T00:00:00+00:00"


def operation(tab, identity, values, expected=None):
    return {"tab": tab, "identity": identity, "values": values,
            "on_insert": {}, "expected": expected or {}, "append_notes": {},
            "append_if_missing": False}


class RecordingCompactRemote(MemoryRepository):
    def __init__(self):
        super().__init__({
            "Companies": [{"Company ID": COMPANY, "Company": COMPANY,
                           "Company Status": "Active", "Official Careers URL": URL,
                           "Last Checked": "old"}],
            "Job History": [{"Job Key": "job-1", "Company": COMPANY,
                             "Official Job URL": "https://jobs.example.test/1",
                             "Review Status": "Human Reviewed", "Last Checked": "old"}],
        }, schemas=COMPACT_SCHEMAS)
        self.spreadsheet_id = "fixture"
        self.commits = []

    def commit(self, operations):
        self.commits.append(copy.deepcopy(operations))
        return super().commit(operations)


class SelectedRecoveryIntegrationTests(unittest.TestCase):
    def fixture(self, root, *, fully_settled=False):
        local_path = Path(root) / "jobs.sqlite3"
        inbox_path = Path(root) / "inventories.sqlite3"
        repo = SQLiteRepository(local_path, "fixture", initialize=True)
        self.addCleanup(repo.close)
        repo.ensure_columns("Opportunities", ["Opportunity ID"])
        rows = {
            "Companies": [{"Company ID": COMPANY, "Company": COMPANY,
                           "Company Status": "Active", "Official Careers URL": URL,
                           "Last Checked": "old"}],
            "Job History": [{"Job Key": "job-1", "Company": COMPANY,
                             "Official Job URL": "https://jobs.example.test/1",
                             "Source Hash": "source-1", "Review Status": "Human Reviewed",
                             "Decision": "Keep", "Last Checked": "old"}],
        }
        for tab in SCHEMAS:
            repo.import_rows(tab, enumerate(rows.get(tab, []), 2))
        with repo.transaction():
            repo.set_meta("ready", "yes"); repo.set_meta("sheets_profile", "compact-v1")
        repo.commit([operation("Companies", {"Company ID": COMPANY},
                               {"Last Checked": "new"}, {"Last Checked": "old"})])
        legacy = {"operations": [
            operation("Companies", {"Company ID": COMPANY}, {"Last Checked": "new"},
                      {"Last Checked": "old"}),
            operation("Job History", {"Job Key": "job-1"}, {
                "Company": COMPANY, "Source Hash": "source-1", "Last Checked": "new"},
                      {"Last Checked": "old", "Added to Opportunities?": "",
                       "Source Hash": "source-1"}),
        ], "final": {"stage": "complete"}, "requested_url": URL}
        if fully_settled:
            legacy["operations"] = legacy["operations"][:1]
        inbox = InventoryInbox(inbox_path, "fixture")
        self.addCleanup(inbox.close)
        inbox.save(CYCLE, COMPANY, {"inventory_status": "complete", "jobs": [], "requested_url": URL})
        with inbox.connection:
            inbox.connection.execute("INSERT INTO sync_plans VALUES (?,?,?,?)",
                                   (CYCLE, COMPANY, json.dumps(legacy), 1))
        return str(inbox_path), str(local_path)

    def test_fully_settled_one_of_one_prefix_freezes_without_replay(self):
        with tempfile.TemporaryDirectory() as root:
            inbox_path, local_path = self.fixture(root, fully_settled=True)
            preview = preview_selected_recovery(
                inbox_path, local_path, CYCLE, COMPANY, expires_at=EXPIRY)
            self.assertEqual((preview["verified_prefix_cursor"],
                              preview["remaining_operation_count"]), (1, 0))
            verifier, envelope = self.authorization(preview)
            result = apply_selected_recovery(
                inbox_path, local_path, CYCLE, COMPANY, envelope, verifier,
                lock_factory=nullcontext, allow_test_verifier=True)
            self.assertEqual(result["state"], "V2_PLAN_FROZEN")
            self.assertFalse(result["receipt_created"])
            self.assertFalse(result["remote_write_performed"])
            self.assertEqual(self.journal_rows(inbox_path), [("V2_PLAN_FROZEN",)])

    def authorization(self, preview):
        verifier = TestAuthorizationVerifier()
        return verifier, verifier.issue(preview["authorization_claims"])

    def frozen_selected(self, root):
        inbox_path, local_path = self.fixture(root, fully_settled=True)
        preview = preview_selected_recovery(
            inbox_path, local_path, CYCLE, COMPANY, expires_at=EXPIRY)
        verifier, envelope = self.authorization(preview)
        with patch(
                "job_search_helper.selected_recovery_runner.adopt_verified_legacy_prefix",
                side_effect=ValueError("not pending publication")):
            with self.assertRaisesRegex(ValueError, "not pending publication"):
                apply_selected_recovery(
                    inbox_path, local_path, CYCLE, COMPANY, envelope, verifier,
                    lock_factory=nullcontext, allow_test_verifier=True)
        return inbox_path, local_path, verifier, envelope

    def test_frozen_selected_cancel_archives_full_evidence_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as root:
            inbox_path, local_path, verifier, envelope = self.frozen_selected(root)
            before_plan = sqlite3.connect(inbox_path).execute(
                "SELECT payload,cursor FROM sync_plans WHERE cycle=? AND company=?",
                (CYCLE, COMPANY)).fetchone()
            first = cancel_selected_recovery(
                inbox_path, local_path, CYCLE, COMPANY, envelope, verifier,
                lock_factory=nullcontext, allow_test_verifier=True)
            self.assertEqual((first["state"], first["recovered"]),
                             ("CANCELLED", False))
            with sqlite3.connect(inbox_path) as db:
                self.assertEqual(db.execute(
                    "SELECT count(*) FROM exact_selected_legacy_recoveries").fetchone()[0], 0)
                archived = json.loads(db.execute(
                    "SELECT evidence FROM exact_selected_legacy_recovery_archive "
                    "WHERE cycle=? AND company=?", (CYCLE, COMPANY)).fetchone()[0])
                self.assertEqual(db.execute(
                    "SELECT payload,cursor FROM sync_plans WHERE cycle=? AND company=?",
                    (CYCLE, COMPANY)).fetchone(), before_plan)
                self.assertIsNotNone(db.execute(
                    "SELECT 1 FROM inventories WHERE cycle=? AND company=?",
                    (CYCLE, COMPANY)).fetchone())
            self.assertEqual(archived["version"], "selected-recovery-cancellation-v1")
            self.assertEqual(archived["selected_recovery"]["state"], "FROZEN")
            self.assertEqual(archived["cancellation"]["reason"],
                             "full_legacy_observation_handoff")
            second = cancel_selected_recovery(
                inbox_path, local_path, CYCLE, COMPANY, envelope, verifier,
                lock_factory=nullcontext, allow_test_verifier=True)
            self.assertEqual((second["state"], second["recovered"]),
                             ("CANCELLED", True))

    def test_frozen_selected_cancel_refuses_any_local_application(self):
        with tempfile.TemporaryDirectory() as root:
            inbox_path, local_path, verifier, envelope = self.frozen_selected(root)
            local = SQLiteRepository(local_path, "fixture", initialize=False)
            self.addCleanup(local.close)
            frozen = InventoryInbox.sealed_selected_legacy_recovery(
                inbox_path, CYCLE, COMPANY)
            plan = frozen["candidate"]
            with local.transaction():
                local.db.execute(
                    "INSERT INTO exact_local_applications VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    ("apply-conflict", CYCLE, COMPANY, plan["plan_digest"],
                     plan["inventory_payload_digest"],
                     plan["local_operations_digest"],
                     plan["remote_projection_digest"], "[]",
                     "2026-11-19T00:00:00Z", None, "APPLYING"))
            with self.assertRaisesRegex(ValueError, "conflicts with local work"):
                cancel_selected_recovery(
                    inbox_path, local_path, CYCLE, COMPANY, envelope, verifier,
                    lock_factory=nullcontext, allow_test_verifier=True)
            self.assertEqual(self.journal_rows(inbox_path), [("FROZEN",)])

    def test_ordinary_migration_refuses_parallel_selected_journal(self):
        with tempfile.TemporaryDirectory() as root:
            inbox_path, local_path, _verifier, _envelope = self.frozen_selected(root)
            approved = preview_retained_legacy_migration(
                inbox_path, local_path, CYCLE, COMPANY)
            self.assertEqual(approved["delivery_evidence"]["delivery_mode"],
                             "observation_only")
            with self.assertRaisesRegex(ValueError, "conflicts with selected recovery"):
                adopt_retained_legacy_migration(
                    inbox_path, local_path, CYCLE, COMPANY, approved)
            with sqlite3.connect(inbox_path) as db:
                self.assertEqual(db.execute(
                    "SELECT count(*) FROM exact_legacy_plan_migrations").fetchone()[0], 0)
                self.assertEqual(db.execute(
                    "SELECT count(*) FROM exact_selected_legacy_recoveries").fetchone()[0], 1)

    def test_cancelled_full_prefix_hands_off_to_observation_only_migration(self):
        with tempfile.TemporaryDirectory() as root:
            inbox_path, local_path, verifier, envelope = self.frozen_selected(root)
            cancel_selected_recovery(
                inbox_path, local_path, CYCLE, COMPANY, envelope, verifier,
                lock_factory=nullcontext, allow_test_verifier=True)
            approved = preview_retained_legacy_migration(
                inbox_path, local_path, CYCLE, COMPANY)
            result = adopt_retained_legacy_migration(
                inbox_path, local_path, CYCLE, COMPANY, approved)
            self.assertEqual(result["delivery_mode"], "observation_only")
            self.assertEqual(result["successor_state"], "REMOTE_PLAN_FROZEN")
            self.assertFalse(result["receipt_created"])
            self.assertFalse(result["remote_write_performed"])
            with sqlite3.connect(inbox_path) as db:
                self.assertEqual(db.execute(
                    "SELECT count(*) FROM exact_selected_legacy_recoveries").fetchone()[0], 0)
                self.assertEqual(db.execute(
                    "SELECT count(*) FROM exact_selected_legacy_recovery_archive").fetchone()[0], 1)
                self.assertEqual(db.execute(
                    "SELECT count(*) FROM publication_receipts").fetchone()[0], 0)
                self.assertEqual(db.execute(
                    "SELECT state FROM exact_legacy_plan_migrations "
                    "WHERE cycle=? AND company=?", (CYCLE, COMPANY)).fetchone(),
                    ("REMOTE_PLAN_FROZEN",))
                self.assertEqual(db.execute(
                    "SELECT delivery_mode,state FROM exact_legacy_delivery_evidence "
                    "WHERE cycle=? AND company=?", (CYCLE, COMPANY)).fetchone(),
                    ("observation_only", "BOUND"))

    def journal_rows(self, inbox_path):
        with sqlite3.connect(inbox_path) as db:
            return db.execute("SELECT state FROM exact_selected_legacy_recoveries").fetchall()

    def prepared_publisher(self, root):
        inbox_path, local_path = self.fixture(root)
        preview = preview_selected_recovery(
            inbox_path, local_path, CYCLE, COMPANY, expires_at=EXPIRY)
        verifier, envelope = self.authorization(preview)
        apply_selected_recovery(
            inbox_path, local_path, CYCLE, COMPANY, envelope, verifier,
            lock_factory=nullcontext, allow_test_verifier=True)
        inbox = InventoryInbox(inbox_path, "fixture")
        local = SQLiteRepository(local_path, "fixture", initialize=False)
        state = State(Path(root) / "state.db")
        remote = RecordingCompactRemote()
        self.addCleanup(inbox.close)
        self.addCleanup(local.close)
        self.addCleanup(state.close)
        state.save_cycle({
            "id": CYCLE, "start_request_id": "start-original-scan",
            "started_at": "2026-11-19T00:00:00+00:00", "status": "In Progress",
            "companies": {COMPANY: {
                "stage": "inventory", "durable_inventory": True,
                "locally_processed": True,
            }},
        })
        guard = lambda company_id, requested_url: _company_guard(
            local, remote, company_id, requested_url)
        return inbox, local, state, remote, guard

    def test_preview_is_read_only_and_has_exact_claims(self):
        with tempfile.TemporaryDirectory() as root:
            inbox_path, local_path = self.fixture(root)
            with sqlite3.connect(inbox_path) as db:
                before = db.execute("SELECT name FROM sqlite_master ORDER BY name").fetchall()
            preview = preview_selected_recovery(inbox_path, local_path, CYCLE, COMPANY,
                                                expires_at=EXPIRY)
            with sqlite3.connect(inbox_path) as db:
                after = db.execute("SELECT name FROM sqlite_master ORDER BY name").fetchall()
                receipts = db.execute("SELECT count(*) FROM publication_receipts").fetchone()[0]
            self.assertEqual(before, after)
            self.assertEqual(receipts, 0)
            self.assertFalse(preview["mutation_performed"])
            self.assertEqual(preview["authorization_claims"]["company_id"], COMPANY)
            self.assertEqual(preview["authorization_claims"]["action"],
                             "selected-legacy-local-adopt-v1")

    def test_default_apply_lock_is_the_normal_sqlite_scraper_lock(self):
        marker = object()
        with tempfile.TemporaryDirectory() as root, \
                patch("job_search_helper.cli.scraper_lock_name",
                      return_value="scraper.lock"), \
                patch("job_search_helper.cli.writer_lock",
                      return_value=marker) as acquire:
            result = _default_lock(Path(root) / "jobs.sqlite3")
        self.assertIs(result, marker)
        acquire.assert_called_once_with(Path(root).resolve() / "scraper.lock")

    def test_forged_wrong_scope_is_rejected_before_journal_write(self):
        with tempfile.TemporaryDirectory() as root:
            inbox_path, local_path = self.fixture(root)
            preview = preview_selected_recovery(inbox_path, local_path, CYCLE, COMPANY,
                                                expires_at=EXPIRY)
            verifier, envelope = self.authorization(preview)
            forged = copy.deepcopy(envelope); forged["payload"]["company_id"] = "COMP-OTHER"
            with self.assertRaisesRegex(ValueError, "scope_mismatch"):
                apply_selected_recovery(inbox_path, local_path, CYCLE, COMPANY, forged, verifier,
                                        lock_factory=nullcontext, allow_test_verifier=True)
            with sqlite3.connect(inbox_path) as db:
                self.assertEqual(db.execute(
                    "SELECT count(*) FROM exact_selected_legacy_recoveries").fetchone()[0], 0)

    def test_expired_and_test_verifier_are_rejected_without_explicit_test_gate(self):
        with tempfile.TemporaryDirectory() as root:
            inbox_path, local_path = self.fixture(root)
            preview = preview_selected_recovery(inbox_path, local_path, CYCLE, COMPANY,
                                                expires_at=EXPIRY)
            verifier, envelope = self.authorization(preview)
            with self.assertRaisesRegex(ValueError, "test_verifier_forbidden"):
                verify_authorization(envelope, preview["authorization_claims"], verifier)
            expired = copy.deepcopy(preview["authorization_claims"])
            expired["expires_at"] = "2000-01-01T00:00:00+00:00"
            with self.assertRaisesRegex(ValueError, "expired"):
                verify_authorization(verifier.issue(expired), expired, verifier,
                                     allow_test_verifier=True)
            cancelled = verify_cancellation_authorization(
                verifier.issue(expired), expired, verifier,
                allow_test_verifier=True)
            self.assertEqual(cancelled["expires_at"], expired["expires_at"])

    def test_current_inbox_begin_freezes_only_matching_signed_source(self):
        with tempfile.TemporaryDirectory() as root:
            inbox_path, local_path = self.fixture(root)
            (_destination, _payload, _legacy, _cursor, _legacy_state,
             _binding, plan, _report) = _build_readonly(
                 inbox_path, local_path, CYCLE, COMPANY)
            verifier = TestAuthorizationVerifier()
            from job_search_helper.selected_recovery_authorization import required_claims
            claims = required_claims(
                cycle_id=CYCLE, company_id=COMPANY, plan=plan,
                recovery=plan["selected_legacy_recovery"], expires_at=EXPIRY)
            authorization = verify_authorization(
                verifier.issue(claims), claims, verifier,
                allow_test_verifier=True)
            inbox = InventoryInbox(inbox_path, "fixture")
            self.addCleanup(inbox.close)
            created = inbox.begin_selected_legacy_recovery(
                CYCLE, COMPANY, plan, authorization,
                timestamp="2026-11-19T00:00:00Z")
            self.assertEqual(created["state"], "FROZEN")
            state = inbox.selected_legacy_recovery_state(CYCLE, COMPANY)
            self.assertEqual(state["authorization_digest"], authorization["authorization_digest"])
            self.assertEqual(state["successor_plan_digest"], plan["plan_digest"])
            self.assertIsNone(inbox.exact_local_state(CYCLE, COMPANY))
            self.assertIsNone(inbox.exact_remote_state(CYCLE, COMPANY))

    def test_current_inbox_promotes_only_verified_successor_without_receipt(self):
        with tempfile.TemporaryDirectory() as root:
            inbox_path, local_path = self.fixture(root)
            (_destination, _payload, _legacy, _cursor, _legacy_state,
             _binding, plan, _report) = _build_readonly(
                 inbox_path, local_path, CYCLE, COMPANY)
            verifier = TestAuthorizationVerifier()
            from job_search_helper.selected_recovery_authorization import required_claims
            from job_search_helper.exact_local_plan import (
                adopt_verified_legacy_prefix, commit_exact_local_plan)
            claims = required_claims(
                cycle_id=CYCLE, company_id=COMPANY, plan=plan,
                recovery=plan["selected_legacy_recovery"], expires_at=EXPIRY)
            authorization = verify_authorization(
                verifier.issue(claims), claims, verifier,
                allow_test_verifier=True)
            inbox = InventoryInbox(inbox_path, "fixture")
            local = SQLiteRepository(local_path, "fixture", initialize=False)
            self.addCleanup(inbox.close); self.addCleanup(local.close)
            inbox.begin_selected_legacy_recovery(
                CYCLE, COMPANY, plan, authorization,
                timestamp="2026-11-19T00:00:00Z")
            adopt_verified_legacy_prefix(
                local, CYCLE, COMPANY, plan,
                timestamp_value="2026-11-19T00:00:01Z")
            inbox.mark_selected_legacy_prefix_verified(
                CYCLE, COMPANY, plan, local,
                timestamp="2026-11-19T00:00:02Z")
            commit_exact_local_plan(local, CYCLE, COMPANY, plan)
            inbox.mark_selected_legacy_local_verified(
                CYCLE, COMPANY, plan, local,
                timestamp="2026-11-19T00:00:03Z")
            frozen = inbox.freeze_selected_legacy_successor(
                CYCLE, COMPANY, plan, local,
                timestamp="2026-11-19T00:00:04Z")
            self.assertEqual(frozen["state"], "V2_PLAN_FROZEN")
            self.assertEqual(inbox.require_selected_legacy_publication(
                CYCLE, COMPANY, plan)["state"], "V2_PLAN_FROZEN")
            from datetime import datetime, timezone
            with self.assertRaisesRegex(ValueError, "expired"):
                inbox.require_selected_legacy_publication(
                    CYCLE, COMPANY, plan,
                    now=datetime(2031, 1, 1, tzinfo=timezone.utc))
            with self.assertRaisesRegex(ValueError, "Selected legacy recovery cannot be cleaned"):
                inbox.acknowledge(CYCLE, COMPANY, local=local)
            stored, cursor = inbox.plan(CYCLE, COMPANY)
            self.assertEqual((stored["plan_digest"], cursor),
                             (plan["plan_digest"], len(plan["local_operations"])))
            self.assertEqual(inbox.exact_local_state(CYCLE, COMPANY)["state"],
                             "LOCAL_VERIFIED")
            self.assertIsNone(inbox.exact_remote_state(CYCLE, COMPANY))
            self.assertEqual(inbox.connection.execute(
                "SELECT count(*) FROM publication_receipts").fetchone()[0], 0)

    def test_selected_successor_uses_the_ordinary_exact_v2_publisher(self):
        """The selected gate authorizes the real exact-v2 release path only."""
        with tempfile.TemporaryDirectory() as root:
            inbox_path, local_path = self.fixture(root)
            preview = preview_selected_recovery(inbox_path, local_path, CYCLE, COMPANY,
                                                expires_at=EXPIRY)
            verifier, envelope = self.authorization(preview)
            applied = apply_selected_recovery(
                inbox_path, local_path, CYCLE, COMPANY, envelope, verifier,
                lock_factory=nullcontext, allow_test_verifier=True)
            self.assertEqual(applied["state"], "V2_PLAN_FROZEN")

            inbox = InventoryInbox(inbox_path, "fixture")
            local = SQLiteRepository(local_path, "fixture", initialize=False)
            state = State(Path(root) / "state.sqlite3")
            self.addCleanup(inbox.close); self.addCleanup(local.close); self.addCleanup(state.close)
            state.save_cycle({"id": CYCLE, "started_at": "2026-11-19T00:00:00Z",
                              "status": "In Progress", "companies": {COMPANY: {
                                  "stage": "inventory", "durable_inventory": True,
                                  "locally_processed": True,
                              }}})
            remote = MemoryRepository({
                "Companies": [{"Company ID": COMPANY, "Company": COMPANY,
                               "Company Status": "Active", "Official Careers URL": URL,
                               "Last Checked": "old"}],
                "Job History": [{"Job Key": "job-1", "Company": COMPANY,
                                 "Official Job URL": "https://jobs.example.test/1",
                                 "Last Checked": "old"}],
            }, schemas=COMPACT_SCHEMAS)
            remote.spreadsheet_id = "fixture"
            plan, _cursor = inbox.plan(CYCLE, COMPANY)
            from job_search_helper.exact_local_plan import exact_local_plan
            from job_search_helper.sheets_sync import SheetsSynchronizer
            preview_sync = SheetsSynchronizer(local, remote)
            normalized = preview_sync._normalize_exact_scope(
                exact_local_plan(local, CYCLE, COMPANY)["row_scope"])
            rebuilt = [preview_sync._plan_exact_row(item, operation)["operation"]
                       for item, operation in zip(normalized, plan["remote_projection"])]
            self.assertEqual(rebuilt, plan["remote_projection"])
            report = publish_exact_cycle(
                inbox, CYCLE, remote, state=state, company_ids=[COMPANY], local=local,
                company_guard=lambda company_id, requested_url: _company_guard(
                    local, remote, company_id, requested_url))
            self.assertEqual(report["confirmed"], [COMPANY], report)
            # Terminal acknowledgement archives the selected authorization
            # evidence rather than leaving a live promotion record behind.
            self.assertIsNone(inbox.selected_legacy_recovery_state(CYCLE, COMPANY))
            self.assertEqual(inbox.connection.execute(
                "SELECT count(*) FROM exact_selected_legacy_recovery_archive "
                "WHERE cycle=? AND company=?", (CYCLE, COMPANY)).fetchone()[0], 1)
            self.assertEqual(inbox.connection.execute(
                "SELECT count(*) FROM publication_receipts").fetchone()[0], 1)

    def test_external_ed25519_signature_binds_the_full_claim_set(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        with tempfile.TemporaryDirectory() as root:
            inbox_path, local_path = self.fixture(root)
            preview = preview_selected_recovery(inbox_path, local_path, CYCLE, COMPANY,
                                                expires_at=EXPIRY)
            private = Ed25519PrivateKey.generate()
            payload = preview["authorization_claims"]
            envelope = {"key_id": "independent-review",
                        "payload": payload,
                        "signature": base64.b64encode(private.sign(canonical(payload))).decode("ascii")}
            public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
            verified = verify_authorization(
                envelope, payload, Ed25519AuthorizationVerifier({"independent-review": public}))
            self.assertEqual(verified["key_id"], "independent-review")
            changed = copy.deepcopy(payload); changed["company_id"] = "COMP-UNSELECTED"
            with self.assertRaisesRegex(ValueError, "scope_mismatch"):
                verify_authorization(envelope, changed,
                                     Ed25519AuthorizationVerifier({"independent-review": public}))

    def test_apply_is_local_only_and_idempotently_freezes_future_remote_plan(self):
        with tempfile.TemporaryDirectory() as root:
            inbox_path, local_path = self.fixture(root)
            preview = preview_selected_recovery(inbox_path, local_path, CYCLE, COMPANY,
                                                expires_at=EXPIRY)
            verifier, envelope = self.authorization(preview)
            result = apply_selected_recovery(inbox_path, local_path, CYCLE, COMPANY, envelope, verifier,
                                             lock_factory=nullcontext, allow_test_verifier=True)
            self.assertEqual(result["state"], "V2_PLAN_FROZEN")
            self.assertFalse(result["receipt_created"])
            self.assertFalse(result["remote_write_performed"])
            self.assertEqual(self.journal_rows(inbox_path), [("V2_PLAN_FROZEN",)])
            # This specifically proves the public apply entry point uses the
            # current inbox promotion, rather than the obsolete standalone
            # journal which could report a terminal-looking state without
            # installing a normal exact-v2 successor.
            with sqlite3.connect(inbox_path) as db:
                stored_payload, stored_cursor = db.execute(
                    "SELECT payload,cursor FROM sync_plans WHERE cycle=? AND company=?",
                    (CYCLE, COMPANY)).fetchone()
                local_state = db.execute(
                    "SELECT state FROM exact_plan_local_state WHERE cycle=? AND company=?",
                    (CYCLE, COMPANY)).fetchone()
            stored_plan = json.loads(stored_payload)
            self.assertEqual(stored_plan["plan_digest"], result["plan_digest"])
            self.assertIn("local_operations", stored_plan)
            self.assertEqual(stored_cursor, len(stored_plan["local_operations"]))
            self.assertEqual(local_state, ("LOCAL_VERIFIED",))
            again = apply_selected_recovery(inbox_path, local_path, CYCLE, COMPANY, envelope, verifier,
                                            lock_factory=nullcontext, allow_test_verifier=True)
            self.assertEqual(again["state"], "V2_PLAN_FROZEN")
            with sqlite3.connect(inbox_path) as db:
                self.assertEqual(db.execute("SELECT count(*) FROM publication_receipts").fetchone()[0], 0)
                self.assertEqual(db.execute("SELECT count(*) FROM exact_remote_plans").fetchone()[0], 0)

    def test_crash_after_local_completion_resumes_from_frozen_signed_candidate(self):
        with tempfile.TemporaryDirectory() as root:
            inbox_path, local_path = self.fixture(root)
            preview = preview_selected_recovery(inbox_path, local_path, CYCLE, COMPANY,
                                                expires_at=EXPIRY)
            verifier, envelope = self.authorization(preview)
            from job_search_helper.exact_local_plan import commit_exact_local_plan as actual_commit
            def crash_after_commit(*args, **kwargs):
                actual_commit(*args, **kwargs)
                raise RuntimeError("injected_crash_after_local_completion")
            with patch("job_search_helper.selected_recovery_runner.commit_exact_local_plan",
                       side_effect=crash_after_commit):
                with self.assertRaisesRegex(RuntimeError, "injected_crash"):
                    apply_selected_recovery(inbox_path, local_path, CYCLE, COMPANY, envelope, verifier,
                                            lock_factory=nullcontext, allow_test_verifier=True)
            self.assertEqual(self.journal_rows(inbox_path), [("PREFIX_VERIFIED",)])
            # The second invocation must use the immutable frozen candidate,
            # not rebuild against its now-changed local snapshot.
            resumed = apply_selected_recovery(inbox_path, local_path, CYCLE, COMPANY, envelope, verifier,
                                              lock_factory=nullcontext, allow_test_verifier=True)
            self.assertEqual(resumed["state"], "V2_PLAN_FROZEN")
            self.assertTrue(resumed["recovered"])
            self.assertEqual(self.journal_rows(inbox_path), [("V2_PLAN_FROZEN",)])
            changed = copy.deepcopy(envelope)
            changed["payload"]["successor_plan_digest"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "scope_mismatch"):
                apply_selected_recovery(inbox_path, local_path, CYCLE, COMPANY, changed, verifier,
                                        lock_factory=nullcontext, allow_test_verifier=True)

    def test_real_exact_v2_publication_binds_cycle_receipt_and_archives_cleanup(self):
        with tempfile.TemporaryDirectory() as root:
            inbox, local, state, remote, guard = self.prepared_publisher(root)

            report = publish_exact_cycle(
                inbox, CYCLE, remote, company_ids=[COMPANY], state=state,
                company_guard=guard, local=local)

            self.assertEqual(report["confirmed"], [COMPANY])
            self.assertEqual(len(remote.commits), 1)
            binding, receipt_state = inbox.connection.execute(
                "SELECT binding,state FROM publication_receipts").fetchone()
            self.assertEqual(json.loads(binding)["request_id"], CYCLE)
            self.assertEqual(receipt_state, "SYNC_CONFIRMED")
            self.assertEqual(inbox.connection.execute(
                "SELECT count(*) FROM exact_selected_legacy_recoveries").fetchone()[0], 0)
            self.assertEqual(inbox.connection.execute(
                "SELECT count(*) FROM exact_selected_legacy_recovery_archive").fetchone()[0], 1)
            self.assertEqual(inbox.connection.execute(
                "SELECT count(*) FROM exact_remote_plans").fetchone()[0], 0)
            self.assertEqual(inbox.pending(CYCLE, include_blocked=True), [])
            self.assertEqual(state.cycle(CYCLE)["companies"][COMPANY]["stage"], "complete")
            history = local.matches("Job History", {"Job Key": "job-1"})[0][1]
            self.assertEqual((history["Review Status"], history["Decision"]),
                             ("Human Reviewed", "Keep"))

    def test_restart_between_remote_intent_freeze_and_selected_marker_never_replays(self):
        with tempfile.TemporaryDirectory() as root:
            inbox, local, state, remote, guard = self.prepared_publisher(root)
            with patch.object(
                    inbox, "mark_selected_legacy_remote_plan_frozen",
                    side_effect=RuntimeError("injected_after_remote_intent_freeze")):
                first = publish_exact_cycle(
                    inbox, CYCLE, remote, company_ids=[COMPANY], state=state,
                    company_guard=guard, local=local)

            self.assertEqual(first["held"], [{"company_id": COMPANY,
                                               "reason": "RuntimeError"}])
            self.assertEqual(remote.commits, [])
            self.assertEqual(inbox.selected_legacy_recovery_state(
                CYCLE, COMPANY)["state"], "V2_PLAN_FROZEN")
            self.assertIsNotNone(inbox.exact_remote_state(CYCLE, COMPANY))
            commits_before_retry = len(remote.commits)

            second = publish_exact_cycle(
                inbox, CYCLE, remote, company_ids=[COMPANY], state=state,
                company_guard=guard, local=local)

            self.assertEqual(second["confirmed"], [COMPANY])
            self.assertEqual(len(remote.commits), commits_before_retry + 1)
            third = publish_exact_cycle(
                inbox, CYCLE, remote, company_ids=[COMPANY], state=state,
                company_guard=guard, local=local)
            self.assertEqual(third["held"], [{"company_id": COMPANY,
                                               "reason": "durable_inventory_missing"}])
            self.assertEqual(len(remote.commits), commits_before_retry + 1)

    def test_expired_selected_gate_refuses_before_receipt_or_remote_intent(self):
        with tempfile.TemporaryDirectory() as root:
            inbox, local, state, remote, guard = self.prepared_publisher(root)
            with inbox.connection:
                inbox.connection.execute(
                    "UPDATE exact_selected_legacy_recoveries "
                    "SET authorization_expires_at='2000-01-01T00:00:00+00:00' "
                    "WHERE cycle=? AND company=?", (CYCLE, COMPANY))

            report = publish_exact_cycle(
                inbox, CYCLE, remote, company_ids=[COMPANY], state=state,
                company_guard=guard, local=local)

            self.assertEqual(report["held"], [{"company_id": COMPANY,
                                                "reason": "selected_recovery_authorization_expired"}])
            self.assertEqual(remote.commits, [])
            self.assertEqual(inbox.connection.execute(
                "SELECT count(*) FROM publication_receipts").fetchone()[0], 0)
            self.assertEqual(inbox.connection.execute(
                "SELECT count(*) FROM exact_remote_plans").fetchone()[0], 0)
            self.assertEqual(inbox.selected_legacy_recovery_state(
                CYCLE, COMPANY)["state"], "V2_PLAN_FROZEN")

if __name__ == "__main__":
    unittest.main()
