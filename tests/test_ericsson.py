import json
from pathlib import Path

from job_search_helper.ats import HTTPResponse
from job_search_helper.ericsson import fetch_ericsson


class Transport:
    def __init__(self):
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        if "/api/pcsx/search?" in url:
            from urllib.parse import parse_qs, urlsplit
            start = int(parse_qs(urlsplit(url).query)["start"][0])
            entries = [] if start else [{"id": 123, "name": "Network Engineer", "displayJobId": "R1", "positionUrl": "/careers/job/123", "locations": ["Austin,Texas,United States"]}]
            return HTTPResponse(200, json.dumps({"status": 200, "data": {"count": 1, "positions": entries, "appliedFilters": {}}}).encode(), {})
        return HTTPResponse(200, json.dumps({"status": 200, "data": {"id": 123, "name": "Network Engineer", "displayJobId": "R1", "jobDescription": "<h2>Join our team</h2><p>" + "A detailed opportunity. " * 30 + "</p>", "standardizedLocations": ["Austin, TX, US"], "department": "Engineering", "workLocationOption": "hybrid"}}).encode(), {})


def test_ericsson_normal_inventory_and_reread():
    result = fetch_ericsson("https://jobs.ericsson.com/careers", "COMP-0136", "Ericsson", Transport())
    assert result.status == "complete"
    assert len(result.jobs) == 1
    assert result.jobs[0]["title"] == "Network Engineer"
    assert len(result.jobs[0]["description"]) > 100


def test_ericsson_rejects_wrong_scope():
    result = fetch_ericsson("https://jobs.ericsson.com/careers?query=us", "COMP-0136", "Ericsson", Transport())
    assert result.status == "unsupported"


def test_ericsson_checkpoint_resumes_completed_details(tmp_path):
    checkpoint = tmp_path / "ericsson.json"
    first = fetch_ericsson("https://jobs.ericsson.com/careers", "COMP-0136", "Ericsson",
                           Transport(), checkpoint_path=checkpoint)
    assert first.status == "complete"
    saved = json.loads(checkpoint.read_text())
    assert saved["phase"] == "complete"
    assert saved["total"] == 1
    assert len(saved["jobs"]) == 1

    second_transport = Transport()
    second = fetch_ericsson("https://jobs.ericsson.com/careers", "COMP-0136", "Ericsson",
                            second_transport, checkpoint_path=checkpoint)
    assert second.status == "complete"
    assert second.jobs == first.jobs
    # The resumed call rereads the listing for stability but does not refetch the detail.
    assert sum("position_details" in url for url in second_transport.calls) == 0
