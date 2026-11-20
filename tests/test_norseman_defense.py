from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.company_sources import REPAIRS, repair_source
from job_search_helper.norseman_defense import SOURCE, fetch_norseman_defense

COMPANY_ID = "COMP-0303"
COMPANY = "Norseman Defense Technologies"


class Page:
    def __init__(self, body, status=200):
        self.body = body.encode()
        self.status = status

    def get(self, url):
        assert url == SOURCE
        return HTTPResponse(self.status, self.body, {"content-type": "text/html"})


def test_routes_official_homepage_to_guarded_source():
    ats, url, note = repair_source("LinkedIn Jobs", "https://norseman.tech/company/careers", COMPANY_ID, COMPANY)
    assert (ats, url) == ("Norseman Defense careers", SOURCE)
    assert REPAIRS[COMPANY_ID]["url"] == SOURCE
    assert "LinkedIn" in REPAIRS[COMPANY_ID]["evidence"]
    assert "Verified company source repair" in note


def test_linkedin_only_source_is_not_a_complete_empty_inventory():
    html = '<html><title>Norseman Defense Technologies</title><a href="https://www.linkedin.com/jobs/search?f_C=744258">View Open Positions</a></html>'
    result = fetch_inventory("Norseman Defense careers", SOURCE, COMPANY_ID, COMPANY, discovery_transport=Page(html))
    assert result.status == "partial"
    assert not result.jobs
    assert "LinkedIn-only" in result.reason


def test_transport_failure_remains_incomplete():
    result = fetch_inventory("Norseman Defense careers", SOURCE, COMPANY_ID, COMPANY, discovery_transport=Page("", 503))
    assert result.status == "partial"
    assert "HTTP 503" in result.reason


def test_identity_guard_rejects_wrong_company():
    result = fetch_norseman_defense(SOURCE, "OTHER", COMPANY, Page("official"))
    assert result.status == "unsupported"
