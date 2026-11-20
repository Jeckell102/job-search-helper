"""Vexar Defense source repair and fail-closed browser validation."""

from job_search_helper.ats import fetch_inventory
from job_search_helper.company_sources import REPAIRS, repair_source


COMPANY_ID = "COMP-0324"
COMPANY = "Vexar Defense"
SOURCE = "https://vexardefense.com/"


def test_vexar_repairs_stale_careers_route_to_official_homepage():
    ats, url, note = repair_source(
        "Browser", "https://vexardefense.com/careers/", COMPANY_ID, COMPANY
    )
    assert (ats, url) == ("Browser", SOURCE)
    assert REPAIRS[COMPANY_ID]["url"] == SOURCE
    assert "public ATS" in REPAIRS[COMPANY_ID]["evidence"]
    assert "Verified company source repair" in note


def test_vexar_browser_route_does_not_infer_zero_jobs():
    result = fetch_inventory("Browser", SOURCE, COMPANY_ID, COMPANY)
    assert result.status in {"failed", "partial", "blocked", "unsupported"}
    assert not result.jobs
    assert "inventory" in result.reason.casefold() or "network" in result.reason.casefold()
