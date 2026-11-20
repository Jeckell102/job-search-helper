"""Klas Government routing and fail-closed source validation."""

from job_search_helper.ats import fetch_inventory
from job_search_helper.company_sources import REPAIRS, repair_source


COMPANY_ID = "COMP-0040"
COMPANY = "Klas Government"
SOURCE = "https://www.klasgroup.com/"


def test_klas_repairs_legacy_and_current_routes_to_official_homepage():
    for source in (
        "https://www.klasgov.com/careers/",
        "https://www.klasgroup.com/careers/",
    ):
        ats, url, note = repair_source("Browser", source, COMPANY_ID, COMPANY)
        assert (ats, url) == ("Browser", SOURCE)
        assert "Verified company source repair" in note
    assert REPAIRS[COMPANY_ID]["url"] == SOURCE


def test_klas_does_not_substitute_anduril_parent_inventory():
    assert "Anduril parent-board" in REPAIRS[COMPANY_ID]["evidence"]
    assert "Klas-specific scope" in REPAIRS[COMPANY_ID]["evidence"]


def test_klas_browser_route_fails_closed_when_no_public_inventory_exists():
    result = fetch_inventory("Browser", SOURCE, COMPANY_ID, COMPANY)
    assert result.status in {"failed", "partial", "blocked", "unsupported"}
    assert not result.jobs
    assert "inventory" in result.reason.casefold() or "network" in result.reason.casefold()
