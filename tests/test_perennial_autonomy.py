from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.company_sources import REPAIRS, repair_source
from job_search_helper.perennial_autonomy import SOURCE, fetch_perennial_autonomy


COMPANY_ID = "COMP-0167"
COMPANY = "Perennial Autonomy"


class Page:
    def __init__(self, body, status=200):
        self.body = body.encode()
        self.status = status

    def get(self, url):
        assert url == SOURCE
        return HTTPResponse(self.status, self.body, {"content-type": "text/html"})


def test_routes_legacy_and_careers_urls_to_official_site():
    ats, url, note = repair_source("Direct inquiry", "https://www.perennialrobotics.com/careers", COMPANY_ID, COMPANY)
    assert (ats, url) == ("Perennial Autonomy careers", SOURCE)
    assert REPAIRS[COMPANY_ID]["url"] == SOURCE
    assert "no employer-scoped ATS" in REPAIRS[COMPANY_ID]["evidence"]
    assert "Verified company source repair" in note


def test_official_marketing_site_is_not_a_complete_empty_inventory():
    html = "<html><title>Perennial Autonomy</title><h1>Perennial Autonomy</h1><p>Battle-proven autonomy.</p></html>"
    result = fetch_perennial_autonomy(SOURCE, COMPANY_ID, COMPANY, Page(html))
    assert result.status == "partial"
    assert not result.jobs
    assert "no public careers page" in result.reason


def test_transport_failure_remains_incomplete():
    result = fetch_inventory("Direct inquiry", SOURCE, COMPANY_ID, COMPANY, discovery_transport=Page("", 503))
    assert result.status == "partial"
    assert "HTTP 503" in result.reason


def test_identity_guard_rejects_wrong_company():
    result = fetch_perennial_autonomy(SOURCE, "OTHER", COMPANY, Page("official"))
    assert result.status == "unsupported"
