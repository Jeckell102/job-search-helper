from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.scythe_robotics import SOURCE, fetch_scythe_robotics

COMPANY_ID = "COMP-0506"
COMPANY = "Scythe Robotics"


class Pages:
    def __init__(self, body):
        self.body = body.encode()
        self.calls = 0

    def get(self, url):
        self.calls += 1
        return HTTPResponse(200, self.body, {"content-type": "text/html"})


def test_explicit_zero_openings_is_complete_and_rechecked():
    page = Pages("<html><title>Scythe Robotics Careers</title><main>"
                 "<h1>Scythe Robotics Careers</h1>"
                 "<p>No positions available at this time</p></main></html>")
    result = fetch_scythe_robotics(SOURCE, COMPANY_ID, COMPANY, page)
    assert result.status == "complete", result.reason
    assert result.jobs == []
    assert page.calls == 2


def test_routed_inventory_uses_scythe_adapter():
    page = Pages("<html><title>Scythe Robotics Careers</title><main>"
                 "<h1>Scythe Robotics Careers</h1>"
                 "<p>No positions available at this time</p></main></html>")
    result = fetch_inventory("Browser", SOURCE, COMPANY_ID, COMPANY, discovery_transport=page)
    assert result.status == "complete", result.reason
    assert result.ats == "Dover careers"


def test_identity_mismatch_fails_closed():
    result = fetch_scythe_robotics(SOURCE, COMPANY_ID, "Other Company", Pages("valid"))
    assert result.status == "unsupported"
