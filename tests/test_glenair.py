from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.glenair import fetch_glenair

SOURCE = "https://www.glenair.com/contact/employment.htm"
COMPANY_ID = "COMP-0489"
COMPANY = "Glenair"


class Page:
    def __init__(self, body, status=200):
        self.body = body.encode()
        self.status = status

    def get(self, url):
        assert url == SOURCE
        return HTTPResponse(self.status, self.body, {"content-type": "text/html"})


def test_official_inquiry_form_is_not_a_complete_empty_inventory():
    html = "<h1>Glenair Employment Submission</h1><p>This is not a job application.</p>"
    result = fetch_inventory("Direct inquiry", SOURCE, COMPANY_ID, COMPANY, discovery_transport=Page(html))
    assert result.status == "partial"
    assert "not a public job board" in result.reason
    assert result.jobs == []


def test_transport_failure_remains_incomplete():
    result = fetch_inventory("Direct inquiry", SOURCE, COMPANY_ID, COMPANY, discovery_transport=Page("", 503))
    assert result.status == "partial"
    assert "HTTP 503" in result.reason


def test_identity_guard_rejects_wrong_company():
    result = fetch_glenair(SOURCE, "OTHER", COMPANY, Page("x"))
    assert result.status == "unsupported"
