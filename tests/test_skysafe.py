from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.skysafe import fetch_skysafe

SOURCE = "https://www.skysafe.io/contact"
COMPANY_ID = "COMP-0169"
COMPANY = "SkySafe"


class Page:
    def __init__(self, body, status=200):
        self.body = body.encode()
        self.status = status

    def get(self, url):
        assert url == SOURCE
        return HTTPResponse(self.status, self.body, {"content-type": "text/html"})


def test_official_page_without_ats_is_not_empty_complete_inventory():
    result = fetch_inventory("Direct inquiry", SOURCE, COMPANY_ID, COMPANY,
                             discovery_transport=Page("<h1>Contact SkySafe</h1>"))
    assert result.status == "partial"
    assert "does not expose a public employer-scoped ATS" in result.reason
    assert result.jobs == []


def test_transport_failure_remains_incomplete():
    result = fetch_inventory("Direct inquiry", SOURCE, COMPANY_ID, COMPANY,
                             discovery_transport=Page("", 503))
    assert result.status == "partial"
    assert "HTTP 503" in result.reason


def test_identity_guard_rejects_wrong_company():
    result = fetch_skysafe(SOURCE, "OTHER", COMPANY, Page("x"))
    assert result.status == "unsupported"
