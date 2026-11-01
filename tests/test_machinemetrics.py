from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.machinemetrics import SOURCE


COMPANY_ID = "COMP-0278"
COMPANY = "MachineMetrics"


BODY = b"""
<html><body><h1>Join the MachineMetrics Team</h1>
<h3 class="job-title">Technical Applications Engineer</h3>
<p>MachineMetrics is looking for a Technical Sales Engineer with deep industrial connectivity expertise to own the technical relationship across the full sales cycle and into post-sale onboarding. This is a hands-on, customer-facing role with customers and engineering teams.</p>
</body></html>
"""


class Pages:
    def __init__(self, status=200, body=BODY):
        self.status = status
        self.body = body
        self.calls = 0

    def get(self, url):
        self.calls += 1
        return HTTPResponse(self.status, self.body, {"content-type": "text/html"})


def test_machinemetrics_routes_verified_source_and_rereads_featured_role():
    pages = Pages()
    result = fetch_inventory("Browser", SOURCE, COMPANY_ID, COMPANY, discovery_transport=pages)
    assert result.status == "complete", result.reason
    assert len(result.jobs) == 1
    assert result.jobs[0]["title"] == "Technical Applications Engineer"
    assert pages.calls == 2


def test_machinemetrics_fails_closed_for_wrong_scope_and_unreachable_page():
    assert fetch_inventory("Browser", SOURCE, "OTHER", COMPANY).status in {"failed", "unsupported", "partial", "blocked"}
    result = fetch_inventory("Browser", SOURCE, COMPANY_ID, COMPANY, discovery_transport=Pages(503, b""))
    assert result.status == "partial"
    assert result.jobs == []
