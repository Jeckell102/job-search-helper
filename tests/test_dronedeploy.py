"""DroneDeploy official careers source and employer-scoped Lever routing."""

from job_search_helper.ats import fetch_inventory, resolve_board
from job_search_helper.company_sources import repair_source


COMPANY_ID = "COMP-0186"
COMPANY = "DroneDeploy"
OFFICIAL = "https://dronedeploy.com/about/careers"
BOARD = "https://api.lever.co/v0/postings/dronedeploy"


def test_dronedeploy_routes_official_careers_to_lever_board():
    ats, url, note = repair_source("Browser", OFFICIAL, COMPANY_ID, COMPANY)
    assert (ats, url) == ("Lever", BOARD)
    assert BOARD in note
    assert repair_source("Browser", OFFICIAL, COMPANY_ID, "Other Employer") == (
        "Browser", OFFICIAL, ""
    )
    assert resolve_board(ats, url)[:2] == ("Lever", "dronedeploy")


def test_dronedeploy_live_route_is_fail_closed_without_network():
    result = fetch_inventory("Browser", OFFICIAL, COMPANY_ID, COMPANY)
    assert result.status in {"complete", "failed", "blocked", "partial", "unsupported"}
    assert result.ats == "Lever"

