from urllib.parse import parse_qs, urlsplit

from job_search_helper.ats import fetch_inventory, resolve_board
from job_search_helper.company_sources import REPAIRS, repair_source


COMPANY_ID = "COMP-0469"
COMPANY = "Mutualink"
LEGACY = "https://www.mutualink.net/careers/"
BOARD = REPAIRS[COMPANY_ID]["url"]


def test_repair_routes_mutualink_to_official_adp_board():
    ats, url, note = repair_source("Browser", LEGACY, COMPANY_ID, COMPANY)
    assert ats == "ADP"
    assert url == BOARD
    assert "workforcenow.adp.com" in note


def test_mutualink_adp_board_is_employer_scoped():
    ats, params, root = resolve_board("ADP", BOARD)
    assert ats == "ADP"
    query = parse_qs(params)
    assert query["cid"] == ["62f98b62-0dc2-459c-8cc3-68eb6e41bac4"]
    assert query["ccId"] == ["19000101_000001"]
    assert root.startswith("https://workforcenow.adp.com/")


def test_mutualink_does_not_count_without_live_inventory():
    result = fetch_inventory("ADP", BOARD, COMPANY_ID, COMPANY)
    assert result.status in {"failed", "partial", "blocked", "unsupported"}
    assert not result.jobs
    assert result.source_url.endswith("lang=en_US")
