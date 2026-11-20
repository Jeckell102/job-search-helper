"""Ocean Aero official-source routing and browser-only failure behavior."""

from job_search_helper.ats import fetch_inventory
from job_search_helper.company_sources import REPAIRS, repair_source


COMPANY_ID = "COMP-0347"
COMPANY = "Ocean Aero"
OFFICIAL_CAREERS = "https://www.oceanaero.com/careers/"


def test_ocean_aero_routes_to_canonical_official_careers_source():
    ats, url, note = repair_source("Browser", "https://oceanaero.com/careers/", COMPANY_ID, COMPANY)

    assert (ats, url) == ("Browser", OFFICIAL_CAREERS)
    assert REPAIRS[COMPANY_ID]["url"] == OFFICIAL_CAREERS
    assert "LinkedIn and Indeed" in REPAIRS[COMPANY_ID]["evidence"]
    assert "Verified company source repair" in note


def test_ocean_aero_browser_route_fails_closed_when_live_source_is_unavailable():
    result = fetch_inventory("Browser", OFFICIAL_CAREERS, COMPANY_ID, COMPANY)

    assert result.status in {"failed", "partial", "blocked", "unsupported"}
    assert not result.jobs
    reason = result.reason.casefold()
    assert any(token in reason for token in ("network", "dns", "board discovery", "playwright", "timeout"))
