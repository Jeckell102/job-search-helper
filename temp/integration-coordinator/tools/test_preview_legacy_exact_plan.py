import copy
import unittest

from job_search_helper.repository import MemoryRepository, SCHEMAS
from job_search_helper.repository import RepositoryError

from preview_legacy_exact_plan import preview_legacy_plan


URL = "https://boards.example.test/davidson"


class Remote(MemoryRepository):
    def __init__(self, last_checked):
        rows = {
            "Companies": [{
                "Company ID": "COMP-0035", "Company": "Davidson",
                "Company Status": "Active", "Official Careers URL": URL,
            }],
            "Job History": [{
                "Job Key": "job-1", "Company": "Davidson",
                "Official Job URL": "https://jobs.example.test/1",
                "Last Checked": last_checked,
            }],
        }
        super().__init__(rows, schemas=copy.deepcopy(SCHEMAS))
        self.commit_calls = []

    def commit(self, operations):
        self.commit_calls.append(copy.deepcopy(operations))
        raise AssertionError("preview must never commit")


class ControlProfileLimitedRemote(Remote):
    def read_columns(self, tab, headers):
        if tab == "Companies":
            raise RepositoryError("Companies: missing required headers: Scan State")
        return super().read_columns(tab, headers)


def fixture(cursor=1):
    local = MemoryRepository({"Companies": [{
        "Company ID": "COMP-0035", "Company": "Davidson",
        "Company Status": "Active", "Official Careers URL": URL,
        "Claimed By": "", "Claim Token": "", "Scan State": "Queued",
        "Automatic Retry?": "Yes",
    }]}, schemas=copy.deepcopy(SCHEMAS))
    cycle = {
        "id": "CYC-B639C6D864EC", "status": "In Progress",
        "companies": {"COMP-0035": {
            "stage": "inventory", "durable_inventory": True,
            "locally_processed": True,
        }},
    }
    payload = {"inventory_status": "complete", "jobs": [],
               "requested_url": URL}
    operation = {
        "tab": "Job History", "identity": {"Job Key": "job-1"},
        "values": {"Last Checked": "after"}, "append_if_missing": False,
        "on_insert": {}, "expected": {"Last Checked": "before"},
        "append_notes": {},
    }
    plan = {"operations": [operation], "final": {"stage": "complete"},
            "requested_url": URL}
    return local, cycle, payload, plan, cursor


class PreviewTests(unittest.TestCase):
    def test_exact_match_is_read_only(self):
        local, cycle, payload, plan, cursor = fixture()
        remote = Remote("after")
        report = preview_legacy_plan(
            cycle_id=cycle["id"], company_id="COMP-0035", cycle=cycle,
            payload=payload, blocked=False, plan=plan, cursor=cursor,
            local=local, remote=remote)
        self.assertTrue(report["all_remote_rows_match"])
        self.assertEqual(report["possible_commit_operation_upper_bound"], 0)
        self.assertFalse(report["mutation_performed"])
        self.assertEqual(remote.commit_calls, [])

    def test_mismatch_reports_upper_bound_without_commit(self):
        local, cycle, payload, plan, cursor = fixture()
        remote = Remote("before")
        report = preview_legacy_plan(
            cycle_id=cycle["id"], company_id="COMP-0035", cycle=cycle,
            payload=payload, blocked=False, plan=plan, cursor=cursor,
            local=local, remote=remote)
        self.assertFalse(report["all_remote_rows_match"])
        self.assertEqual(report["possible_commit_operation_upper_bound"], 1)
        self.assertEqual(remote.commit_calls, [])

    def test_incomplete_local_cursor_refuses_before_remote_access(self):
        local, cycle, payload, plan, _cursor = fixture(cursor=0)
        remote = Remote("after")
        with self.assertRaisesRegex(ValueError, "local_cursor_not_complete"):
            preview_legacy_plan(
                cycle_id=cycle["id"], company_id="COMP-0035", cycle=cycle,
                payload=payload, blocked=False, plan=plan, cursor=0,
                local=local, remote=remote)
        self.assertEqual(remote.commit_calls, [])

    def test_blocked_inventory_refuses_before_remote_access(self):
        local, cycle, payload, plan, cursor = fixture()
        remote = Remote("after")
        with self.assertRaisesRegex(ValueError, "durable_inventory_blocked"):
            preview_legacy_plan(
                cycle_id=cycle["id"], company_id="COMP-0035", cycle=cycle,
                payload=payload, blocked=True, plan=plan, cursor=cursor,
                local=local, remote=remote)
        self.assertEqual(remote.commit_calls, [])

    def test_historical_full_schema_is_required_before_remote_access(self):
        local, cycle, payload, plan, cursor = fixture()
        remote = Remote("after")
        remote.schemas = {"Companies": copy.deepcopy(SCHEMAS["Companies"]),
                          "Job History": ["Job Key"]}
        with self.assertRaisesRegex(ValueError, "field_not_in_full_schema"):
            preview_legacy_plan(
                cycle_id=cycle["id"], company_id="COMP-0035", cycle=cycle,
                payload=payload, blocked=False, plan=plan, cursor=cursor,
                local=local, remote=remote)
        self.assertEqual(remote.commit_calls, [])

    def test_unavailable_legacy_tab_is_a_read_only_profile_hold(self):
        local, cycle, payload, plan, cursor = fixture()
        remote = Remote("after")
        remote.schemas.pop("Job History")
        report = preview_legacy_plan(
            cycle_id=cycle["id"], company_id="COMP-0035", cycle=cycle,
            payload=payload, blocked=False, plan=plan, cursor=cursor,
            local=local, remote=remote)
        self.assertEqual(report["decision"], "REMOTE_PROFILE_INCOMPATIBLE")
        self.assertIn("Job History", report["reason"])
        self.assertFalse(report["mutation_performed"])
        self.assertEqual(remote.commit_calls, [])

    def test_unavailable_company_controls_are_a_read_only_profile_hold(self):
        local, cycle, payload, plan, cursor = fixture()
        remote = ControlProfileLimitedRemote("after")
        report = preview_legacy_plan(
            cycle_id=cycle["id"], company_id="COMP-0035", cycle=cycle,
            payload=payload, blocked=False, plan=plan, cursor=cursor,
            local=local, remote=remote)
        self.assertEqual(report["decision"], "REMOTE_PROFILE_INCOMPATIBLE")
        self.assertIn("Scan State", report["reason"])
        self.assertIsNone(report["current_controls_digest"])
        self.assertFalse(report["mutation_performed"])
        self.assertEqual(remote.commit_calls, [])


if __name__ == "__main__":
    unittest.main()
