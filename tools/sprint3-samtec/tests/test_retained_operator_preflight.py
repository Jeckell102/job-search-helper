import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from job_search_helper.company_events import source_revision
from job_search_helper.engine import State
from job_search_helper.retained_operator_preflight import measure_operator_membership, verify_operator_source_identity
from job_search_helper.retained_work_exception import build_manifest, digest


class SnapshotRepository:
    is_local = True
    readonly = True
    schemas = {"Companies": ["Company ID", "Company Status", "Official Careers URL"]}

    def __init__(self, path, company):
        self.path = path
        self.company = company
        self.remote_blocker = None

    def matches(self, tab, identity):
        assert tab == "Companies" and identity == {"Company ID": "COMP-0739"}
        return [(2, dict(self.company))]

    def read_columns(self, tab, headers):
        if tab == "Companies":
            return [(2, {key: self.company.get(key, "") for key in headers})]
        assert tab == "Scan Cycles"
        if self.remote_blocker is None:
            return []
        return [(2, {"Cycle ID": self.remote_blocker, "Cycle Status": "In Progress"})]


class RetainedOperatorPreflightTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        cycle = {"id": "CYC-OLD", "status": "In Progress", "companies": {
            "COMP-0739": {"company": "Samtec", "stage": "queued"},
            "COMP-OLD": {"company": "Other", "stage": "inventory"},
        }}
        with sqlite3.connect(self.root / "inventories.sqlite3") as inventory:
            inventory.executescript("""
                CREATE TABLE destination (id);
                INSERT INTO destination VALUES ('workbook');
                CREATE TABLE inventories (cycle, company, payload);
                CREATE TABLE sync_plans (cycle, company, payload);
                CREATE TABLE publication_receipts (receipt_id, binding);
                INSERT INTO inventories VALUES ('CYC-OLD','COMP-OLD','{}');
                INSERT INTO sync_plans VALUES ('CYC-OLD','COMP-OLD','{}');
            """)
        with sqlite3.connect(self.root / "jobs.sqlite3") as jobs:
            jobs.executescript("""
                CREATE TABLE dirty (tab, row_id, header);
                CREATE TABLE exact_local_applications (cycle, company, apply_id);
                CREATE TABLE exact_local_acknowledgements (apply_id);
                CREATE TABLE exact_local_apply_chunks (apply_id);
            """)
        writable = State(str(self.root / "state.db"))
        writable.save_cycle(cycle)
        writable.close()
        self.state = State(str(self.root / "state.db"), readonly=True)
        self.addCleanup(self.state.close)
        self.company = {
            "Company": "Samtec", "Company ID": "COMP-0739", "Company Status": "Active",
            "Official Careers URL": "https://jobs.jobvite.com/samtec/search",
            "ATS / Source": "Jobvite", "Active Cycle ID": "CYC-OLD",
        }
        self.local = SnapshotRepository(self.root / "jobs.sqlite3", self.company)
        self.remote = SnapshotRepository(None, self.company)
        revision = source_revision(self.company)
        identity = {"schema": "operator-company-scan-request-v1", "request_id": "samtec-fixture",
                    "company_id": "COMP-0739", "source_revision": revision}
        request = {"mode": "company-only", "request_id": "samtec-fixture", "company_ids": ["COMP-0739"],
                   "source_revision": revision, "operator_request": identity, "start_last": [],
                   "enqueued_at": "2026-11-20T12:00:00Z"}
        (self.root / "next-scan.json").write_text(json.dumps(request))
        receipts = self.root / "operator-company-requests" / "receipts"
        receipts.mkdir(parents=True)
        (receipts / (digest({"request_id": "samtec-fixture"}) + ".json")).write_text(json.dumps(
            {**identity, "request_sha256": digest(request), "state": "REQUEST_WRITTEN"}))
        self.manifest = build_manifest(
            cycle, self.root / "inventories.sqlite3", self.root / "jobs.sqlite3",
            reason="test", created_at="2026-11-20T12:00:00Z")

    def measure(self):
        return measure_operator_membership(
            self.local, self.remote, self.state, self.root, self.manifest,
            {"state": "NO_RELEASE", "source_manifest_sha256": digest("fixture")},
            expires_at="2026-11-21T00:00:00Z",
        )

    def test_composed_scope_and_current_workbook_are_read_only(self):
        original = {path: path.read_bytes() for path in self.root.glob("*.sqlite3")}
        claims = self.measure()
        self.assertEqual((claims["company_id"], claims["version"]), ("COMP-0739", 2))
        self.assertEqual(self.measure(), claims)
        self.assertEqual({path: path.read_bytes() for path in original}, original)
        self.remote.remote_blocker = "CYC-FOREIGN"
        with self.assertRaisesRegex(ValueError, "workbook_blockers_changed"):
            self.measure()

    def test_returned_provider_must_match_before_the_plan(self):
        fact = {"official_careers_url": self.company["Official Careers URL"]}
        scope = {"company_id": "COMP-0739"}
        with self.assertRaisesRegex(ValueError, "returned_source_changed"):
            verify_operator_source_identity(self.manifest, scope, self.company, fact,
                                            inventory={"ats": "Jobvite", "source_url": "https://jobs.jobvite.com/other/search"})
