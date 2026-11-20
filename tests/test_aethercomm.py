from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.aethercomm import SOURCE, fetch_aethercomm
from job_search_helper.company_sources import REPAIRS, repair_source


COMPANY_ID = "COMP-0128"
COMPANY = "Aethercomm"


class Page:
    def __init__(self, body, status=200):
        self.body = body.encode()
        self.status = status

    def get(self, url):
        assert url == SOURCE
        return HTTPResponse(self.status, self.body, {"content-type": "text/html"})


def test_routes_aethercomm_to_frontgrade_shared_source():
    ats, url, note = repair_source("Browser", "https://www.aethercomm.com/careers/", COMPANY_ID, COMPANY)
    assert (ats, url) == ("Frontgrade shared careers", SOURCE)
    assert "shared careers portal" in REPAIRS[COMPANY_ID]["evidence"]
    assert "Verified company source repair" in note


def test_shared_parent_board_does_not_infer_empty_aethercomm_inventory():
    html = "<title>Frontgrade Careers</title><h2>FG Aethercomm</h2><a>View All Positions</a>"
    result = fetch_inventory("Browser", SOURCE, COMPANY_ID, COMPANY, discovery_transport=Page(html))
    assert result.status == "partial"
    assert not result.jobs
    assert "shared parent board" in result.reason


def test_transport_failure_remains_incomplete():
    result = fetch_inventory("Browser", SOURCE, COMPANY_ID, COMPANY, discovery_transport=Page("", 503))
    assert result.status == "partial"
    assert "HTTP 503" in result.reason


def test_identity_guard_rejects_wrong_company():
    result = fetch_aethercomm(SOURCE, "OTHER", COMPANY, Page("Frontgrade Aethercomm"))
    assert result.status == "unsupported"
