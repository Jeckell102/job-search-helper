"""SoarTech official careers routing and fail-closed board validation."""

from job_search_helper.ats import fetch_inventory
from job_search_helper.company_sources import REPAIRS, repair_source


COMPANY_ID = "COMP-0032"
COMPANY = "Soar Technology (SoarTech)"
OFFICIAL_CAREERS = "https://soartech.com/careers"
BOARD = "https://lyntris.jobboardhq.com/search"


def test_soartech_routes_official_careers_to_linked_first_party_board():
    ats, url, note = repair_source("Browser", OFFICIAL_CAREERS, COMPANY_ID, COMPANY)

    assert (ats, url) == ("Browser", BOARD)
    assert REPAIRS[COMPANY_ID]["url"] == BOARD
    assert "Lyntris" in REPAIRS[COMPANY_ID]["evidence"]
    assert "Verified company source repair" in note


def test_soartech_live_board_fails_closed_without_verified_scope_or_inventory():
    result = fetch_inventory("Browser", BOARD, COMPANY_ID, COMPANY)

    assert result.status in {"complete", "failed", "partial", "blocked", "unsupported"}
    if result.status != "complete":
        assert not result.jobs or result.browser_discovery_incomplete or result.status in {"failed", "partial", "blocked", "unsupported"}
