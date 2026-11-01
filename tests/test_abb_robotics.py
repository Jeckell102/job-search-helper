from job_search_helper.ats import fetch_inventory
from job_search_helper.company_sources import repair_source


COMPANY_ID = "COMP-0242"
COMPANY = "ABB Robotics"
SOURCE = "https://careers.abb/global/en/"
BOARD = "https://careers.abb/global/en/search-results"


def test_repair_routes_abb_to_verified_phenom_board():
    ats, url, note = repair_source("Browser", SOURCE, COMPANY_ID, COMPANY)
    assert ats == "Phenom"
    assert url == BOARD
    assert "ABB" in note


def test_phenom_support_recognizes_abb_host():
    result = fetch_inventory("Phenom", BOARD, COMPANY_ID, COMPANY)
    assert result.ats == "Phenom"
    assert result.source_url == BOARD or result.status in {"failed", "blocked", "partial"}
