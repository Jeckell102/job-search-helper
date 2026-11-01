import json
import unittest

from job_search_helper.ats import HTTPResponse
from job_search_helper.panasonic import API, TAGS, fetch_panasonic


class Fake:
    def __init__(self):
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        from urllib.parse import parse_qs, urlsplit
        q = parse_qs(urlsplit(url).query)
        tag = q["tags3"][0]
        rows = []
        for i in range(2):
            n = (0 if tag == TAGS[0] else 10) + i
            rows.append({"data": {"slug": str(n), "title": "Connect Engineer", "description": "A complete public job description with enough detail to validate this posting.", "responsibilities": "Build and support systems.", "qualifications": "Engineering experience.", "tags3": [tag], "req_id": f"R-{n}", "full_location": "Remote", "posted_date": "2026-10-01"}})
        body = {"totalCount": 2, "count": 2, "jobs": rows}
        return HTTPResponse(200, json.dumps(body).encode(), {})


class PanasonicTests(unittest.TestCase):
    def test_scoped_feed_is_complete(self):
        fake = Fake()
        result = fetch_panasonic("COMP-0296", "Panasonic Connect", fake)
        self.assertEqual(result.status, "complete")
        self.assertEqual(len(result.jobs), 4)
        self.assertEqual(len({job["posting_id"] for job in result.jobs}), 4)
        self.assertTrue(all(url.startswith("https://careers.na.panasonic.com/jobs/") for url in [j["url"] for j in result.jobs]))
        self.assertEqual(len(fake.calls), 2)


if __name__ == "__main__":
    unittest.main()
