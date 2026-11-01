import json

from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.garmin import API, SOURCE, fetch_garmin


def _payload(start, count=2, total=2):
    jobs = []
    for i in range(start, start + count):
        jobs.append({"data": {
            "slug": str(20000 + i), "title": f"Role {i}",
            "description": "Full Garmin role description " + ("details " * 40),
            "apply_url": f"https://careers-garmin.icims.com/jobs/{20000 + i}/login",
            "req_id": str(20000 + i), "full_location": "Olathe, Kansas",
            "category": "Engineering", "posted_date": "2026-11-01",
        }})
    return json.dumps({"jobs": jobs, "totalCount": total, "count": total}).encode()


class Pages:
    def __init__(self, bodies):
        self.bodies = bodies
        self.calls = 0

    def get(self, url):
        page = int(url.split("page=")[1].split("&")[0])
        body = self.bodies[page]
        self.calls += 1
        return HTTPResponse(200, body, {"content-type": "application/json"})


def test_garmin_paginates_and_rereads():
    pages = Pages({1: _payload(0, 100, 101), 2: _payload(100, 1, 101)})
    result = fetch_garmin(SOURCE, "COMP-0437", "Garmin", pages)
    assert result.status == "complete"
    assert len(result.jobs) == 101
    assert pages.calls == 4


def test_garmin_routes_repaired_source_through_installed_pipeline():
    pages = Pages({1: _payload(0, 2, 2), 2: _payload(0, 2, 2)})
    result = fetch_inventory("Browser", "https://www.garmin.com/pl-PL/careers/",
                             "COMP-0437", "Garmin", pages)
    assert result.status == "complete"
    assert result.source_url == SOURCE
    assert result.ats == "Garmin Jibe"


def test_garmin_rejects_wrong_scope_and_drift():
    pages = Pages({1: _payload(0, 2, 2), 2: _payload(0, 2, 2)})
    assert fetch_garmin(SOURCE, "OTHER", "Garmin", pages).status == "unsupported"
    drift = Pages({1: _payload(0, 100, 101), 2: _payload(1, 1, 101)})
    assert fetch_garmin(SOURCE, "COMP-0437", "Garmin", drift).status == "partial"


def test_garmin_accepts_garmin_canada_application_host():
    body = json.loads(_payload(0, 1, 1))
    body["jobs"][0]["data"]["apply_url"] = "https://canada-garmin.icims.com/jobs/20000/login"
    pages = Pages({1: json.dumps(body).encode()})
    result = fetch_garmin(SOURCE, "COMP-0437", "Garmin", pages)
    assert result.status == "complete"
    assert len(result.jobs) == 1
