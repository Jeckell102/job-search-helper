"""Flying Lion official-source routing and browser-only failure behavior."""

from job_search_helper.ats import fetch_inventory
from job_search_helper.company_sources import REPAIRS, repair_source


COMPANY_ID = "COMP-0195"
COMPANY = "Flying Lion"
OFFICIAL_CAREERS = "https://flyinglioninc.com/careers"


def test_flying_lion_routes_to_official_browser_careers_source():
    ats, url, note = repair_source("Browser", OFFICIAL_CAREERS, COMPANY_ID, COMPANY)

    assert (ats, url) == ("Browser", OFFICIAL_CAREERS)
    assert REPAIRS[COMPANY_ID]["url"] == OFFICIAL_CAREERS
    assert "Flying Lion careers page" in REPAIRS[COMPANY_ID]["evidence"]
    assert "Verified company source repair" in note


def test_flying_lion_browser_route_fails_closed_without_an_ats():
    result = fetch_inventory("Browser", OFFICIAL_CAREERS, COMPANY_ID, COMPANY)

    assert result.status in {"failed", "partial", "blocked", "unsupported"}
    assert not result.jobs
    assert "network" in result.reason.casefold() or "board discovery" in result.reason.casefold()
