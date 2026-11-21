"""Offline tests for the narrow terminal legacy observation adapter."""
from __future__ import annotations

import copy
from pathlib import Path
import tempfile
import unittest

from job_search_helper.exact_legacy_terminal_observation import (
    OBSERVED_MATCH, build_terminal_observation_binding, observe_terminal_plan,
)
from job_search_helper.inbox import InventoryInbox
from job_search_helper.repository import GoogleRepository, MemoryRepository, SCHEMAS
from job_search_helper.sheet_profile import COMPACT_PROFILE, COMPACT_SCHEMAS
from job_search_helper.sqlite_repository import SQLiteRepository
from sheets_fixture import RangeSheets


CYCLE = "CYC-TERMINAL"
COMPANY = "COMP-TERMINAL"
URL = "https://jobs.example.test/terminal"


class FixedState:
    def __init__(self, cycle):
        self._cycle = copy.deepcopy(cycle)

    def cycle(self, cycle_id):
        return copy.deepcopy(self._cycle) if cycle_id == CYCLE else None


class NoCommitRemote(GoogleRepository):
    def commit(self, operations):  # pragma: no cover - assertion is the test
        raise AssertionError("terminal observation must never commit")


class TerminalObservationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.local = SQLiteRepository(
            Path(self.temporary.name) / "jobs.sqlite3", "fixture", initialize=True)
        self.addCleanup(self.local.close)
        self.local.ensure_columns("Opportunities", ["Opportunity ID"])
        with self.local.transaction():
            self.local.set_meta("ready", "yes")
            self.local.set_meta("sheets_profile", COMPACT_PROFILE)
        self.row = {
            "Company ID": COMPANY, "Company": "Terminal Fixture",
            "Company Status": "Blocked", "Official Careers URL": URL,
            "Blocked Reason": "Provider requires manual access",
            "Automatic Retry?": "No", "Last Scan Result": "Unsupported",
            "Next Action": "Keep held",
            "Scan State": "Blocked", "Active Cycle ID": CYCLE,
            "Coverage Status": "Blocked", "Record Updated": "now",
        }
        full = MemoryRepository({"Companies": [self.row]}, schemas=self.local.schemas)
        for tab in SCHEMAS:
            self.local.import_rows(tab, enumerate(full.read(tab), 2))
        self.inbox = InventoryInbox(Path(self.temporary.name) / "inbox.sqlite3", "fixture")
        self.addCleanup(self.inbox.close)
        self.payload = {"inventory_status": "blocked", "jobs": [], "requested_url": URL}
        self.plan = {"operations": [{
            "tab": "Companies", "identity": {"Company ID": COMPANY},
            "values": {
                "Blocked Reason": self.row["Blocked Reason"],
                "Automatic Retry?": self.row["Automatic Retry?"],
                "Last Scan Result": self.row["Last Scan Result"],
                "Next Action": self.row["Next Action"],
                "Scan State": self.row["Scan State"],
                "Active Cycle ID": self.row["Active Cycle ID"],
                "Coverage Status": self.row["Coverage Status"],
                "Record Updated": self.row["Record Updated"],
            }, "on_insert": {}, "expected": {}, "append_notes": {},
            "append_if_missing": False,
        }], "final": {"stage": "blocked"}, "requested_url": URL}
        self.inbox.save(CYCLE, COMPANY, self.payload)
        self.inbox.block(CYCLE, COMPANY)
        self.inbox.save_plan(CYCLE, COMPANY, self.plan)
        self.inbox.advance(CYCLE, {COMPANY: 1})
        self.state = FixedState({"id": CYCLE, "companies": {
            COMPANY: {"stage": "blocked"},
        }})
        # Compact remote contains visible fields only.  This is an offline
        # RangeSheets fixture, not a remote call.
        remote_row = {key: value for key, value in self.row.items()
                      if key in COMPACT_SCHEMAS["Companies"]}
        self.service = RangeSheets({"Companies": [remote_row]}, schemas=COMPACT_SCHEMAS)
        self.remote = NoCommitRemote(self.service, "fixture", schemas=COMPACT_SCHEMAS,
                                     min_request_interval=0)

    def binding(self):
        return build_terminal_observation_binding(
            self.state, self.inbox, self.local, cycle_id=CYCLE, company_id=COMPANY)

    def test_local_only_baseline_drift_is_pinned_and_exact_readback_never_commits(self):
        row_id, current = self.local.matches("Companies", {"Company ID": COMPANY})[0]
        baseline = self.local.baseline("Companies", row_id)
        # Deliberately stale only in compact-excluded fields.  Visible fields
        # retain their original baseline equality requirement.
        baseline["Active Cycle ID"] = "old-cycle"
        baseline["Record Updated"] = "old-time"
        with self.local.transaction():
            self.local._baseline("Companies", row_id, baseline)
        before = (self.local.path.read_bytes(),
                  Path(self.inbox.path).read_bytes(), self.service.request_bytes)
        binding = self.binding()
        self.assertEqual(binding["local_evidence"]["local_only_fields"], [
            "Active Cycle ID", "Coverage Status", "Record Updated", "Scan State"])
        result = observe_terminal_plan(
            self.state, self.inbox, self.local, self.remote,
            cycle_id=CYCLE, company_id=COMPANY, binding=binding)
        self.assertEqual(result["state"], OBSERVED_MATCH)
        self.assertEqual(self.service.request_bytes, before[2])
        self.assertEqual((self.local.path.read_bytes(), Path(self.inbox.path).read_bytes()),
                         before[:2])
        self.assertGreater(len(self.service.get_calls), 0)

    def test_visible_baseline_change_holds_before_any_remote_read(self):
        row_id, _current = self.local.matches("Companies", {"Company ID": COMPANY})[0]
        baseline = self.local.baseline("Companies", row_id)
        baseline["Next Action"] = "other visible value"
        with self.local.transaction():
            self.local._baseline("Companies", row_id, baseline)
        with self.assertRaisesRegex(ValueError, "visible_baseline_unverifiable"):
            self.binding()
        self.assertEqual(self.service.get_calls, [])
        self.assertEqual(self.service.request_bytes, 0)

    def test_local_only_current_change_or_dirty_mark_holds_before_remote_read(self):
        row_id, current = self.local.matches("Companies", {"Company ID": COMPANY})[0]
        current["Scan State"] = "Queued"
        self.local.import_rows("Companies", [(row_id, current)])
        with self.assertRaisesRegex(ValueError, "local_value_changed"):
            self.binding()
        current["Scan State"] = "Blocked"
        self.local.import_rows("Companies", [(row_id, current)])
        # The normal local-only pruning policy makes this impossible through
        # mark_dirty; inject the stale row to prove this adapter still refuses
        # it rather than treating its local-only status as a broad exception.
        with self.local.transaction():
            self.local.db.execute("INSERT INTO dirty VALUES (?,?,?)",
                                  ("Companies", row_id, "Scan State"))
        with self.assertRaisesRegex(ValueError, "dirty_field_present"):
            self.binding()
        self.assertEqual(self.service.get_calls, [])

    def test_wrong_terminal_shape_and_existing_receipt_hold(self):
        altered = copy.deepcopy(self.plan)
        altered["operations"].append(copy.deepcopy(altered["operations"][0]))
        with self.inbox.lock, self.inbox.connection:
            self.inbox.connection.execute(
                "UPDATE sync_plans SET payload=? WHERE cycle=? AND company=?",
                (__import__("json").dumps(altered), CYCLE, COMPANY))
        with self.assertRaisesRegex(ValueError, "plan_not_completed_one_op"):
            self.binding()
        with self.inbox.lock, self.inbox.connection:
            self.inbox.connection.execute(
                "UPDATE sync_plans SET payload=? WHERE cycle=? AND company=?",
                (__import__("json").dumps(self.plan), CYCLE, COMPANY))
            self.inbox.connection.execute(
                "INSERT INTO publication_receipts VALUES (?,?,?,?,?,?,?,?)",
                ("fake", '{"company_id":"' + COMPANY + '"}', "{}", "{}",
                 "SYNC_CONFIRMED", None, "now", "now"))
        with self.assertRaisesRegex(ValueError, "receipt_exists"):
            self.binding()

    def test_remote_mismatch_creates_no_receipt_or_write(self):
        self.service.set_cell("Companies", 1, "Next Action", "not held")
        binding = self.binding()
        before = (self.local.path.read_bytes(), Path(self.inbox.path).read_bytes())
        with self.assertRaisesRegex(ValueError, "readback differs"):
            observe_terminal_plan(self.state, self.inbox, self.local, self.remote,
                                  cycle_id=CYCLE, company_id=COMPANY, binding=binding)
        self.assertEqual((self.local.path.read_bytes(), Path(self.inbox.path).read_bytes()), before)
        self.assertEqual(self.service.request_bytes, 0)


if __name__ == "__main__":
    unittest.main()
