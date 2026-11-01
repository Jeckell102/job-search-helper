import copy
import unittest

from job_search_helper.ats import HTTPResponse, Inventory, fetch_inventory
from job_search_helper.dematic import fetch_dematic


SOURCE = "https://kiongroup.wd3.myworkdayjobs.com/en-US/KION_SCS"


def response(payload, status=200):
    import json
    return HTTPResponse(status, json.dumps(payload).encode())


def listing():
    return {"title": "Controls Engineer", "externalPath": "/job/US-Controls-Engineer_REQ1",
            "locationsText": "Atlanta, GA", "postedOn": "Posted Today", "bulletFields": ["REQ1"]}


def detail():
    return {"jobPostingInfo": {"id": "opaque-1", "jobPostingId": "Controls-Engineer_REQ1",
            "jobPostingSiteId": "KION_SCS", "jobReqId": "REQ1", "title": "Controls Engineer",
            "jobDescription": "<p>Design and support warehouse automation controls.</p>",
            "location": "Atlanta, GA", "additionalLocations": [], "remoteType": "",
            "startDate": "2026-10-01", "posted": True}}


class Transport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.posts = []
        self.urls = []

    def post(self, url, payload):
        self.posts.append((url, copy.deepcopy(payload)))
        return self.responses.pop(0)

    def get(self, url):
        self.urls.append(url)
        return self.responses.pop(0)


class DematicTests(unittest.TestCase):
    def test_scoped_board_returns_complete_inventory(self):
        transport = Transport([response({"total": 1, "jobPostings": [listing()], "facets": []}),
                               response(detail())])
        result = fetch_dematic(SOURCE, "COMP-0248", "Dematic", transport)
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual(len(result.jobs), 1)
        self.assertEqual(result.jobs[0]["title"], "Controls Engineer")
        self.assertEqual(transport.posts[0][0], "https://kiongroup.wd3.myworkdayjobs.com/wday/cxs/kiongroup/KION_SCS/jobs")

    def test_wrong_source_fails_closed(self):
        result = fetch_dematic("https://www.dematic.com/en-us/about/careers/", "COMP-0248", "Dematic", Transport([]))
        self.assertEqual(result.status, "unsupported")

    def test_normal_dispatch_uses_scoped_adapter(self):
        transport = Transport([response({"total": 0, "jobPostings": [], "facets": []})])
        result = fetch_inventory("Workday", SOURCE, "COMP-0248", "Dematic", transport)
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual(result.jobs, [])


if __name__ == "__main__":
    unittest.main()
