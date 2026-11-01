"""Digital Force Technologies source repair and fail-closed checks."""

from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.company_sources import REPAIRS, repair_source


SOURCE = "https://www.digitalforcetech.com/company/careers/"
COMPANY_ID = "COMP-0043"
COMPANY = "Digital Force Technologies"


class StaticPage:
    def get(self, url):
        assert url == SOURCE
        return HTTPResponse(200, b"<h2>Current Openings</h2><p>Join us.</p>")


def test_digital_force_repair_pins_official_browser_source():
    entry = REPAIRS[COMPANY_ID]
    ats, url, note = repair_source("Browser", SOURCE, COMPANY_ID, COMPANY)
    assert (ats, url) == (entry["ats"], entry["url"])
    assert note

    assert repair_source("Browser", SOURCE, COMPANY_ID, "Other Employer") == (
        "Browser", SOURCE, ""
    )


def test_digital_force_static_page_without_job_links_fails_closed():
    result = fetch_inventory(
        "Browser", SOURCE, COMPANY_ID, COMPANY, discovery_transport=StaticPage()
    )
    assert result.status == "partial"
    assert result.jobs == []
    assert "inventory completeness is unknown" in result.reason
