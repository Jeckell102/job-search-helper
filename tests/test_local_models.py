from dataclasses import replace
import json
from pathlib import Path
import unittest

from job_search_helper.ats import HTTPResponse, Inventory, fetch_inventory
from job_search_helper.posting import canonicalize_url, job_key, material_hash
from job_search_helper.models import InventorySnapshot, JobPosting, SourceScope


POSTING = {"posting_id": "00123", "req_id": "REQ-9", "title": "Principal Engineer",
           "location": "Ohio", "work_arrangement": "Remote", "compensation": "USD 90000 annual base",
           "description": "<p>Build systems</p>", "url": "https://example.com/jobs/00123?utm_source=test",
           "updated_at": "taleo-job-id:987", "is_listed": False}


class LocalModelTests(unittest.TestCase):
    def test_adapter_evidence_retains_id_salary_title_and_raw_dates(self):
        posting = JobPosting.from_adapter(POSTING)
        self.assertEqual(posting.posting_id, "00123")
        self.assertEqual(posting.requisition_id, "REQ-9")
        self.assertEqual(posting.description, POSTING["description"])
        self.assertEqual(posting.source_modified_raw, "taleo-job-id:987")
        self.assertEqual(posting.source_created_raw, "")
        self.assertFalse(posting.is_listed)
        self.assertEqual(posting.material_hash, material_hash(POSTING))

    def test_unknown_adapter_fields_survive(self):
        row = dict(POSTING, compensation_evidence={"currency": "USD", "base": None})
        posting = JobPosting.from_adapter(row)
        row["compensation_evidence"]["base"] = 100
        self.assertIsNone(json.loads(posting.metadata_json)["compensation_evidence"]["base"])

    def test_large_unicode_description_not_truncated(self):
        text = "Full evidence \u00e9\n" * 6000
        self.assertEqual(JobPosting.from_adapter(dict(POSTING, description=text)).description, text)

    def test_material_hash_ignores_url_but_evidence_hash_tracks_it(self):
        first = JobPosting.from_adapter(POSTING)
        second = replace(first, url="https://example.com/new/00123")
        self.assertEqual(first.material_hash, second.material_hash)
        self.assertNotEqual(first.evidence_hash, second.evidence_hash)
        self.assertNotEqual(first.material_hash, replace(first, location="New York").material_hash)

    def test_invalid_shapes_fail_without_silently_dropping_evidence(self):
        for change in ({"is_listed": "false"}, {"description": {}}, {"posting_id": "", "url": ""},
                       {"url": "file:///tmp/private"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                JobPosting.from_adapter(dict(POSTING, **change))

    def test_scope_changes_are_distinct_but_parameter_order_is_not(self):
        scope = SourceScope("source-1", "https://example.com/jobs?team=1&utm_source=x", "v1", '{"b":2,"a":1}')
        same = SourceScope("source-1", "https://example.com/jobs?team=1", "v1", '{"a":1,"b":2}')
        self.assertEqual(scope.fingerprint, same.fingerprint)
        for changed in (replace(scope, source_id="source-2"), replace(scope, adapter_version="v2"),
                        replace(scope, canonical_inventory_url="https://example.com/jobs?team=2")):
            self.assertNotEqual(scope.fingerprint, changed.fingerprint)

    def test_inventory_boundary_preserves_partial_and_unlisted_evidence(self):
        scope = SourceScope("source-1", "https://example.com/jobs", "v1")
        for status in ("complete", "partial", "blocked", "failed", "unsupported"):
            inventory = Inventory(status, [dict(POSTING)], "original reason", scope.canonical_inventory_url, "Taleo")
            snapshot = InventorySnapshot.from_adapter(inventory, scope)
            inventory.jobs[0]["title"] = "changed"
            self.assertEqual(snapshot.status, status)
            self.assertEqual(snapshot.reason, "original reason")
            self.assertEqual(snapshot.jobs[0].title, "Principal Engineer")
            self.assertFalse(snapshot.jobs[0].is_listed)

    def test_greenhouse_fixture_crosses_boundary_without_contract_changes(self):
        payload = (Path(__file__).parent / "fixtures/greenhouse.json").read_bytes()

        class Transport:
            def get(self, _url):
                return HTTPResponse(200, payload)

        inventory = fetch_inventory("Greenhouse", "https://boards.greenhouse.io/acme", "C-1", "Acme", Transport())
        snapshot = InventorySnapshot.from_adapter(inventory, SourceScope("source-1", inventory.source_url, "v1"))
        self.assertEqual(snapshot.status, "complete")
        self.assertEqual(snapshot.jobs[0].posting_id, "123")
        self.assertEqual(snapshot.jobs[0].requisition_id, "REQ-9")
        self.assertEqual(snapshot.jobs[0].material_hash, material_hash(inventory.jobs[0]))

    def test_golden_legacy_identity(self):
        self.assertEqual(canonicalize_url("https://EXAMPLE.com/jobs?source=42&gh_jid=00123&utm_campaign=x#top"),
                         "https://example.com/jobs?gh_jid=00123&source=42")
        self.assertEqual(job_key("COMP-1", "Greenhouse", "00123", POSTING["url"]), "comp-1:greenhouse:00123")
        self.assertEqual(job_key("COMP-1", "Greenhouse", "", "https://example.com/?gh_jid=1"),
                         "comp-1:greenhouse:url-05eb8767eff9fc529f12e96999e9fee013e97b331b683b12d3f2456259e0c1a2")

    def test_golden_material_hash(self):
        self.assertEqual(material_hash({}), "32a44a71323224569308f67e212efeb5fd323d2b406379adf733ca1d808381f2")
        self.assertEqual(material_hash(POSTING), "39f467333638caa121dbff1766240a3a4d0b6b7bbf3f5ac7f15eda7359b2f776")
