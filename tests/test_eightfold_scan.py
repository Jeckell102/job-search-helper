import unittest

from job_search_helper.eightfold import scan


ROOT = "https://talent.mtsi-va.com"
DOMAIN = "mtsi-va.com"
CID = "COMP-0017"
COMPANY = "Modern Technology Solutions, Inc. (MTSI)"


def listing_record(i):
    ident = str(1133913869838 + i)
    return {
        "id": ident,
        "name": f"MTSI Test Role {i}",
        "displayJobId": f"MTSI-{i}",
        "positionUrl": f"/careers/job/{ident}",
    }


def detail_record(item):
    ident = item["id"]
    return {
        **item,
        "publicUrl": ROOT + item["positionUrl"],
        "jobDescription": f"<p>Complete published body for {ident}</p><ul><li>Requirement</li></ul>",
        "standardizedLocations": ["McLean, VA"],
        "department": "Engineering",
        "workLocationOption": "Hybrid",
    }


class ReplayClient:
    def __init__(self, pages, details):
        self.pages = pages
        self.details = details
        self.search_calls = []
        self.detail_calls = []
        self.root = ROOT
        self.domain = DOMAIN

    def data(self, kind, value):
        if kind == "search":
            self.search_calls.append(value)
            page = self.pages[len(self.search_calls) - 1]
            return {"count": 11, "positions": page, "appliedFilters": {}}
        self.detail_calls.append(value)
        return self.details[value]


class EightfoldScanTests(unittest.TestCase):
    def setUp(self):
        self.items = [listing_record(i) for i in range(11)]
        self.pages = [self.items[:10], self.items[10:]]
        self.details = {item["id"]: detail_record(item) for item in self.items}

    def test_complete_scan_fetches_all_bodies_and_rereads_every_page(self):
        client = ReplayClient(self.pages + self.pages, self.details)
        result = scan(client, CID, COMPANY, listing_first=True)
        self.assertEqual(result.status, "complete")
        self.assertEqual(len(result.jobs), 11)
        self.assertEqual(len(client.detail_calls), 11)
        self.assertEqual(client.search_calls, [0, 10, 0, 10])
        self.assertTrue(all(job["description"] for job in result.jobs))

    def test_later_page_duplicate_stops_before_detail_requests(self):
        duplicate_page = [self.items[0]]
        client = ReplayClient([self.items[:10], duplicate_page], self.details)
        result = scan(client, CID, COMPANY, listing_first=True)
        self.assertEqual(result.status, "partial")
        self.assertEqual(client.detail_calls, [])
        self.assertIn("repeated job IDs", result.reason)

    def test_default_scan_preserves_verified_partial_details(self):
        duplicate_page = [self.items[0]]
        client = ReplayClient([self.items[:10], duplicate_page], self.details)
        result = scan(client, CID, COMPANY)
        self.assertEqual(result.status, "partial")
        self.assertEqual(len(client.detail_calls), 10)
        self.assertEqual(len(result.jobs), 10)

    def test_same_count_final_page_id_drift_is_incomplete(self):
        drifted = [listing_record(99)]
        client = ReplayClient([self.items[:10], self.items[10:], self.items[:10], drifted], self.details)
        result = scan(client, CID, COMPANY, listing_first=True)
        self.assertEqual(result.status, "partial")
        self.assertEqual(len(client.detail_calls), 11)
        self.assertIn("changed during scan", result.reason)


if __name__ == "__main__":
    unittest.main()
