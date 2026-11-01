"""Inspired Flight official-source routing and browser-only failure behavior."""

from job_search_helper.ats import fetch_inventory
from job_search_helper.company_sources import REPAIRS, repair_source


COMPANY_ID = "COMP-0172"
COMPANY = "Inspired Flight Technologies"
OFFICIAL_CAREERS = "https://www.inspiredflight.com/careers"


def test_inspired_flight_routes_to_official_browser_careers_source():
    ats, url, note = repair_source("Browser", OFFICIAL_CAREERS, COMPANY_ID, COMPANY)

    assert (ats, url) == ("Browser", OFFICIAL_CAREERS)
    assert REPAIRS[COMPANY_ID]["url"] == OFFICIAL_CAREERS
    assert "Inspired Flight careers" in REPAIRS[COMPANY_ID]["evidence"]
    assert "Verified company source repair" in note


def test_inspired_flight_browser_route_fails_closed_without_live_access():
    result = fetch_inventory("Browser", OFFICIAL_CAREERS, COMPANY_ID, COMPANY)

    assert result.status in {"failed", "partial", "blocked", "unsupported"}
    assert not result.jobs
    assert "network" in result.reason.casefold() or "board discovery" in result.reason.casefold()
