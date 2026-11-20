"""MVRsimulation official careers routing and fail-closed validation."""

from job_search_helper.ats import fetch_inventory
from job_search_helper.company_sources import REPAIRS, repair_source


COMPANY_ID = "COMP-0340"
COMPANY = "MVRsimulation"
OFFICIAL_CAREERS = "https://mvrsimulation.com/"


def test_mvrsimulation_routes_to_official_browser_careers_source():
    ats, url, note = repair_source("Browser", OFFICIAL_CAREERS, COMPANY_ID, COMPANY)

    assert (ats, url) == ("Browser", OFFICIAL_CAREERS)
    assert REPAIRS[COMPANY_ID]["url"] == OFFICIAL_CAREERS
    assert "Official MVRsimulation homepage" in REPAIRS[COMPANY_ID]["evidence"]
    assert "Verified company source repair" in note


def test_mvrsimulation_does_not_infer_closure_from_unavailable_source():
    result = fetch_inventory("Browser", OFFICIAL_CAREERS, COMPANY_ID, COMPANY)

    assert result.status in {"failed", "partial", "blocked", "unsupported"}
    assert not result.jobs
    assert "404" in result.reason or "network" in result.reason.casefold() or "board discovery" in result.reason or "no public" in result.reason.casefold()
