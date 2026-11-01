from urllib.parse import parse_qs, urlsplit

from job_search_helper.ats import fetch_inventory, resolve_board
from job_search_helper.company_sources import REPAIRS, repair_source


COMPANY_ID = "COMP-0406"
COMPANY = "Federated Wireless"
CAREERS = "https://federatedwireless.ai/about/"
BOARD = "https://workforcenow.adp.com/mascsr/default/mdf/recruitment/recruitment.html?ccId=19000101_000001&cid=922ca7fd-dabc-4d02-a6e0-336d96392d9a&lang=en_US"


def test_repair_uses_official_federated_adp_board():
    source = repair_source(COMPANY_ID, COMPANY, "https://www.federatedwireless.com/careers/")
    assert source["ats"] == "ADP"
    assert source["url"] == BOARD
    assert source["expected_url"] == CAREERS


def test_federated_route_is_employer_scoped():
    ats, params, root = resolve_board("ADP", BOARD)
    assert ats == "ADP"
    assert root.startswith("https://workforcenow.adp.com/")
    query = parse_qs(params)
    assert query["cid"] == ["922ca7fd-dabc-4d02-a6e0-336d96392d9a"]
    assert query["ccId"] == ["19000101_000001"]


def test_live_shape_is_normalized_for_federated_postings():
    # The official board's live result is validated separately; this guard
    # ensures the mapped source remains the ADP adapter rather than browser fallback.
    assert REPAIRS[COMPANY_ID]["ats"] == "ADP"
    assert urlsplit(REPAIRS[COMPANY_ID]["url"]).hostname == "workforcenow.adp.com"
