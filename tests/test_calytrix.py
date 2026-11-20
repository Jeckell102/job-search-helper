from job_search_helper.ats import fetch_inventory
from job_search_helper.calytrix import OFFICIAL_SITE, repair_calytrix_source
from job_search_helper.company_sources import REPAIRS, repair_source


COMPANY_ID = "COMP-0339"
COMPANY = "Calytrix Technologies"
LEGACY_SOURCE = "https://calytrix.com/careers/"
CANONICAL_SOURCE = OFFICIAL_SITE


def test_repair_routes_saved_legacy_source_to_canonical_official_site():
    ats, url, note = repair_source("Browser", LEGACY_SOURCE, COMPANY_ID, COMPANY)
    assert ats == "Browser"
    assert url == CANONICAL_SOURCE
    assert url == CANONICAL_SOURCE
    assert "Verified company source repair" in note


def test_current_official_homepage_is_the_only_verified_first_party_route():
    ats, url, note = repair_calytrix_source()
    assert (ats, url) == ("Browser", OFFICIAL_SITE)
    assert "No employer-scoped public ATS" in REPAIRS[COMPANY_ID]["evidence"]


def test_canonical_browser_route_fails_closed_without_live_ats():
    result = fetch_inventory("Browser", CANONICAL_SOURCE, COMPANY_ID, COMPANY)
    assert result.status in {"partial", "failed", "blocked", "unsupported"}
