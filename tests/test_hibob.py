import copy
import json
from pathlib import Path
import unittest

from job_search_helper.ats import HTTPResponse, HTTPTransport, FetchError, _safe_api_url
from job_search_helper.hibob import SOURCE, fetch_hibob, safe_api_path


def _job(ident, title=None, description=None):
    return {
        "id": ident,
        "title": title or f"Primer Role {ident[:4]}",
        "departmentId": "254863755",
        "department": "320 Professional Services",
        "employmentTypeId": "Permanent",
        "employmentType": "Permanent",
        "siteId": 2517366,
        "site": "Pasadena Office",
        "country": "United States",
        "language": "en",
        "description": "Primary role description with verified responsibilities." if description is None else description,
        "requirements": "Required experience and qualifications.",
        "responsibilities": None,
        "benefits": "Benefits and support details.",
        "publishedAt": "2026-10-19T17:15:48.820817999Z",
        "workspaceTypeId": "hybrid",
        "workspaceType": "Hybrid",
        "payTransparencySalaryAdditionalInfo": "Compensation details.",
    }


IDS = [
    "6231b4b1-12d0-49bf-a964-70f6ced19564",
    "4e8996c3-bf5a-4ec8-9901-ec7700c0cb3f",
    "f4b2d6c8-7c0d-4f0f-ae8b-000000000606",
    "93000000-0000-4000-8000-000000000930",
]


def _payload(jobs=None):
    return {"filterGroups": {"departments": [], "sites": [], "jobTypes": [], "workspaceTypes": []},
            "jobAdDetails": jobs if jobs is not None else [_job(i) for i in IDS]}


SITE = {"companyName": "Primer Technology", "isPublished": False, "isBobCareerSite": True, "language": "en-GB"}


class HibobTransport:
    def __init__(self, jobs=None, site=None, mutate=False):
        self.jobs = copy.deepcopy(jobs if jobs is not None else _payload())
        self.site = copy.deepcopy(site if site is not None else SITE)
        self.mutate = mutate
        self.calls = []
        self.reads = 0

    def get_with_headers(self, url, headers):
        self.calls.append((url, dict(headers)))
        if url.endswith("/api/career-site"):
            body = copy.deepcopy(self.site)
            return HTTPResponse(200, json.dumps(body).encode())
        if url.endswith("/api/job-ad"):
            self.reads += 1
            body = copy.deepcopy(self.jobs)
            if self.mutate and self.reads > 1:
                body["jobAdDetails"][0]["title"] = "Changed after initial read"
            return HTTPResponse(200, json.dumps(body).encode())
        raise AssertionError(f"unexpected public request: {url}")


class HibobTests(unittest.TestCase):
    def test_transport_enforces_pinned_anonymous_read_only_scope(self):
        endpoint=SOURCE.rstrip('/') + '/api/job-ad'
        _safe_api_url(endpoint)
        _safe_api_url(SOURCE.rstrip('/') + '/api/career-site')
        for url in (endpoint + '?offset=0', endpoint + '#fragment',
                    'https://other.careers.hibob.com/api/job-ad',
                    SOURCE.rstrip('/') + '/api/user', 'http://' + endpoint.split('://')[1]):
            with self.subTest(url=url), self.assertRaises(FetchError):
                _safe_api_url(url)
        client=HTTPTransport()
        for headers in ({}, {'companyIdentifier':'other'}, {'companyIdentifier':'primertechnology','Authorization':'invalid'}):
            with self.subTest(headers=headers), self.assertRaises(FetchError):
                client.get_with_headers(endpoint, headers)
        with self.assertRaises(FetchError):
            client.post(endpoint, {}, {'companyIdentifier':'primertechnology'})

    def test_captured_public_fixtures_replay_four_full_jobs(self):
        root = Path(__file__).parent / "fixtures" / "hibob"
        listing = json.loads((root / "listing.json").read_text())
        site = json.loads((root / "site.json").read_text())
        result = fetch_hibob(SOURCE, "COMP-0456", "Primer", HibobTransport(listing, site))
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual(len(result.jobs), 4)
        self.assertTrue(all(len(job["description"]) > 100 for job in result.jobs))

    def test_primer_retrieves_all_four_complete_jobs_and_preserves_content(self):
        transport = HibobTransport()
        result = fetch_hibob(SOURCE, "COMP-0456", "Primer", transport)
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual({job["posting_id"] for job in result.jobs}, set(IDS))
        self.assertTrue(all("verified responsibilities" in job["description"] for job in result.jobs))
        self.assertTrue(all("Benefits" in job["description"] for job in result.jobs))
        self.assertEqual([c[0] for c in transport.calls].count(SOURCE.rstrip("/") + "/api/career-site"), 2)
        self.assertEqual([c[0] for c in transport.calls].count(SOURCE.rstrip("/") + "/api/job-ad"), 2)
        self.assertTrue(all(c[1] == {"companyIdentifier": "primertechnology"} for c in transport.calls))
        self.assertTrue(all("Compensation details." in job["description"] for job in result.jobs))

    def test_primer_missing_description_is_partial_but_keeps_valid_jobs(self):
        jobs = [_job(IDS[0]), _job(IDS[1], description=""), _job(IDS[2])]
        result = fetch_hibob(SOURCE, "COMP-0456", "Primer", HibobTransport(_payload(jobs)))
        self.assertEqual(result.status, "partial")
        self.assertEqual({job["posting_id"] for job in result.jobs}, {IDS[0], IDS[2]})

    def test_primer_duplicate_or_malformed_identity_is_partial(self):
        jobs = [_job(IDS[0]), _job(IDS[0]), _job(IDS[2])]
        result = fetch_hibob(SOURCE, "COMP-0456", "Primer", HibobTransport(_payload(jobs)))
        self.assertEqual(result.status, "partial")
        jobs = [_job(IDS[0]), _job("not-a-uuid"), _job(IDS[2])]
        result = fetch_hibob(SOURCE, "COMP-0456", "Primer", HibobTransport(_payload(jobs)))
        self.assertEqual(result.status, "partial")

    def test_primer_final_site_or_inventory_drift_is_partial(self):
        result = fetch_hibob(SOURCE, "COMP-0456", "Primer", HibobTransport(mutate=True))
        self.assertEqual(result.status, "partial")

    def test_primer_requires_exact_company_identity_and_public_source(self):
        for args in [("OTHER", "Primer", SOURCE), ("COMP-0456", "Other", SOURCE), ("COMP-0456", "Primer", SOURCE + "?x=1"),
                     ("COMP-0456", "Primer", "https://other.example/careers")]:
            with self.subTest(args=args):
                result = fetch_hibob(args[2], args[0], args[1], HibobTransport())
                self.assertEqual(result.status, "unsupported")

    def test_primer_rejects_foreign_site_metadata(self):
        site = dict(SITE, companyName="Other Company")
        result = fetch_hibob(SOURCE, "COMP-0456", "Primer", HibobTransport(site=site))
        self.assertEqual(result.status, "partial")

    def test_primer_rejects_reported_count_mismatch_or_unsupported_pagination(self):
        for field, value in (("count", 99), ("nextPageToken", "opaque")):
            with self.subTest(field=field):
                payload = _payload()
                payload[field] = value
                result = fetch_hibob(SOURCE, "COMP-0456", "Primer", HibobTransport(payload))
                self.assertEqual(result.status, "partial")

    def test_primer_public_api_allowlist_rejects_query_private_and_foreign_urls(self):
        self.assertTrue(safe_api_path(__import__("urllib.parse", fromlist=["urlsplit"]).urlsplit(SOURCE.rstrip("/") + "/api/job-ad")))
        for url in (
            SOURCE.rstrip("/") + "/api/job-ad?x=1",
            SOURCE.rstrip("/") + "/api/company",
            "https://api.hibob.com/api/job-ad",
            SOURCE.rstrip("/") + "/api/job-ad#fragment",
        ):
            with self.subTest(url=url):
                self.assertFalse(safe_api_path(__import__("urllib.parse", fromlist=["urlsplit"]).urlsplit(url)))


if __name__ == "__main__":
    unittest.main()
