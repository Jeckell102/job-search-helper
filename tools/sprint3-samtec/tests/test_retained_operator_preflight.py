import base64
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from job_search_helper.company_events import source_revision
from job_search_helper.engine import State
from job_search_helper.retained_operator_preflight import measure_operator_membership, verify_operator_source_identity
from job_search_helper.retained_operator_run import run_operator_membership
from job_search_helper.retained_operator_journal import FETCH_CLAIMED, RetainedOperatorJournal
from job_search_helper.retained_work_exception import build_manifest, digest
from job_search_helper.repository import SCHEMAS
from job_search_helper.selected_recovery_authorization import Ed25519AuthorizationVerifier, canonical
from job_search_helper.sheet_profile import COMPACT_PROFILE, COMPACT_SCHEMAS


class SnapshotRepository:
    is_local = True
    readonly = True
    spreadsheet_id = "workbook"
    schemas = SCHEMAS
    profile = None

    def __init__(self, path, company):
        self.path = path
        self.company = company
        self.remote_blocker = None

    def matches(self, tab, identity):
        assert tab == "Companies" and identity == {"Company ID": "COMP-0739"}
        return [(2, dict(self.company))]

    def get_meta(self, key):
        assert key == "sheets_profile"
        return self.profile

    def validate_schema(self):
        return True

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
            self.runtime(),
            expires_at="2026-11-21T00:00:00Z",
        )

    def runtime(self):
        return {"state": "NO_RELEASE", "source_manifest_sha256": digest("fixture"),
                "config_sha256": digest("config"), "dependency_manifest_sha256": digest("dependencies")}

    def test_composed_scope_and_current_workbook_are_read_only(self):
        original = {path: path.read_bytes() for path in self.root.glob("*.sqlite3")}
        claims = self.measure()
        self.assertEqual((claims["company_id"], claims["version"]), ("COMP-0739", 2))
        self.assertEqual(self.measure(), claims)
        self.assertEqual({path: path.read_bytes() for path in original}, original)
        self.remote.remote_blocker = "CYC-FOREIGN"
        with self.assertRaisesRegex(ValueError, "workbook_blockers_changed"):
            self.measure()

    def test_wrong_workbook_holds_even_when_company_fields_match(self):
        self.remote.spreadsheet_id = "wrong"
        with self.assertRaisesRegex(ValueError, "workbook_identity_changed"):
            self.measure()

    def test_compact_cycles_are_local_only_and_profile_mismatch_is_rejected(self):
        self.local.profile = COMPACT_PROFILE
        with self.assertRaisesRegex(ValueError, "workbook_schema_changed"):
            self.measure()
        self.remote.schemas = COMPACT_SCHEMAS
        read = self.remote.read_columns

        def read_compact(tab, headers):
            self.assertNotEqual(tab, "Scan Cycles")
            return read(tab, headers)

        self.remote.read_columns = read_compact
        self.assertEqual(self.measure()["company_id"], "COMP-0739")
        self.local.remote_blocker = "CYC-FOREIGN"
        with self.assertRaisesRegex(ValueError, "blocker"):
            self.measure()

    def test_returned_provider_must_match_before_the_plan(self):
        fact = {"official_careers_url": self.company["Official Careers URL"]}
        scope = {"company_id": "COMP-0739"}
        with self.assertRaisesRegex(ValueError, "returned_source_changed"):
            verify_operator_source_identity(self.manifest, scope, self.company, fact,
                                            inventory={"ats": "Jobvite", "source_url": "https://jobs.jobvite.com/other/search"})

    def test_execution_claim_survives_an_ambiguous_provider_exit(self):
        claims = self.measure()
        key = Ed25519PrivateKey.generate()
        verifier = Ed25519AuthorizationVerifier({"fixture": key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)})
        approval = {"payload": claims, "key_id": "fixture",
                    "signature": base64.b64encode(key.sign(canonical(claims))).decode("ascii")}
        fetch = Mock(side_effect=RuntimeError("fixture provider interrupted"))
        open_local = Mock(side_effect=AssertionError("writer must stay unopened"))
        open_remote = Mock(side_effect=AssertionError("writer must stay unopened"))
        measure_remote = Mock(return_value=self.remote)
        args = (self.local, measure_remote, self.state, self.root, self.manifest, self.runtime())
        options = dict(approval=approval, verifier=verifier, fetcher=fetch, local_writer=open_local,
                       remote_writer=open_remote, request_id="samtec-fixture", company_id="COMP-0739",
                       now=datetime(2026, 11, 20, 12, tzinfo=timezone.utc))
        with self.assertRaisesRegex(RuntimeError, "fixture provider interrupted"):
            run_operator_membership(*args, **options)
        self.assertEqual(RetainedOperatorJournal(self.root).inspect()["state"], FETCH_CLAIMED)
        with self.assertRaisesRegex(ValueError, "journal_fetch_ambiguous"):
            run_operator_membership(*args, **options)
        fetch.assert_called_once()
        measure_remote.assert_called_once()
        open_local.assert_not_called()
        open_remote.assert_not_called()
