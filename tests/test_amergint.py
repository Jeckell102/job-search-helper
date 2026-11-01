"""AMERGINT acquisition boundary and fail-closed source tests."""

from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.company_sources import REPAIRS, repair_source


COMPANY_ID = "COMP-0048"
COMPANY = "AMERGINT Technologies"
SOURCE = "https://amergint.com/careers/"


class StaticPage:
    def __init__(self, body, status=200):
        self.body = body
        self.status = status

    def get(self, url):
        assert url == SOURCE
        return HTTPResponse(self.status, self.body)


def test_amergint_route_is_pinned_to_the_official_source():
    ats, url, note = repair_source("Browser", SOURCE, COMPANY_ID, COMPANY)
    entry = REPAIRS[COMPANY_ID]
    assert (ats, url) == (entry["ats"], entry["url"])
    assert "Verified company source repair" in note
    assert repair_source("Browser", SOURCE, COMPANY_ID, "Other Employer") == (
        "Browser", SOURCE, ""
    )


def test_redirect_page_without_amergint_jobs_stays_partial():
    result = fetch_inventory(
        "Browser",
        SOURCE,
        COMPANY_ID,
        COMPANY,
        discovery_transport=StaticPage(
            b'<link rel="canonical" href="https://www.caci.com/space">'
            b"<title>Space | CACI</title>"
        ),
    )
    assert result.status == "partial"
    assert result.jobs == []
    assert "inventory completeness is unknown" in result.reason


def test_access_denial_is_not_treated_as_empty_inventory():
    result = fetch_inventory(
        "Browser", SOURCE, COMPANY_ID, COMPANY,
        discovery_transport=StaticPage(b"Forbidden", status=403),
    )
    assert result.status == "blocked"
    assert result.jobs == []
