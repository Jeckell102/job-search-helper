import copy
import json
from unittest.mock import patch

from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.workday import resolve_workday


SOURCE = "https://symbotic.wd504.myworkdayjobs.com/Symbotic"


def response(payload):
    return HTTPResponse(200, json.dumps(payload).encode())


def listing(path="/job/Robotics-Engineer_R123"):
    return {"title": "Robotics Engineer", "externalPath": path,
            "locationsText": "Wilmington, MA", "postedOn": "Posted Today"}


def detail():
    return {"jobPostingInfo": {"id": "opaque-123", "jobPostingId": "R123",
            "jobPostingSiteId": "Symbotic", "title": "Robotics Engineer",
            "jobDescription": "<p>Symbotic is seeking a robotics engineer.</p>",
            "location": "Wilmington, MA", "additionalLocations": [],
            "remoteType": "", "startDate": "2026-10-01", "posted": True}}


class Transport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.posts = []

    def post(self, url, payload):
        self.posts.append((url, copy.deepcopy(payload)))
        return self.responses.pop(0)

    def get(self, url):
        return self.responses.pop(0)


def test_workday_tenant_resolution_and_normal_dispatch():
    assert resolve_workday("Workday", SOURCE) == (
        "Workday", "Symbotic", "https://symbotic.wd504.myworkdayjobs.com/wday/cxs/symbotic/")
    transport = Transport([response({"total": 1, "jobPostings": [listing()], "facets": []}),
                           response(detail())])
    result = fetch_inventory("Workday", SOURCE, "COMP-0200", "Symbotic", transport)
    assert result.status == "complete"
    assert len(result.jobs) == 1
    assert result.jobs[0]["posting_id"] == "opaque-123"
    assert result.jobs[0]["description"]
    assert transport.posts[0][0].endswith("/symbotic/Symbotic/jobs")
    assert transport.posts[0][1]["limit"] == 20
    assert transport.posts[0][1]["offset"] == 0


def test_load_more_contract_terminates_and_duplicate_posting_is_partial():
    transport = Transport([response({"total": 2, "jobPostings": [listing()], "facets": []}),
                           response({"total": 2, "jobPostings": [listing()], "facets": []}),
                           response(detail())])
    with patch("job_search_helper.workday.PAGE_SIZE", 1):
        result = fetch_inventory("Workday", SOURCE, "COMP-0200", "Symbotic", transport)
    assert result.status == "partial"
    assert "repeated" in result.reason.lower()


def test_identity_is_guarded():
    result = fetch_inventory("Workday", "https://example.com/careers/", "COMP-0200", "Symbotic", Transport([]))
    assert result.status in {"failed", "unsupported"}
