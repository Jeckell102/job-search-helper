from job_search_helper.ats import fetch_inventory
from job_search_helper.company_sources import repair_source


COMPANY_ID = "COMP-0132"
COMPANY = "HPE Aruba Networking"
SOURCE = "https://careers.hpe.com/us/en/networking"


def test_repair_routes_to_current_official_networking_landing_page():
    ats, url, note = repair_source("Phenom", "https://careers.hpe.com/us/en/aruba", COMPANY_ID, COMPANY)
    assert ats == "Phenom"
    assert url == SOURCE
    assert "Verified company source repair" in note


def test_combined_hpe_networking_page_is_not_accepted_as_aruba_inventory():
    result = fetch_inventory("Phenom", SOURCE, COMPANY_ID, COMPANY)
    assert result.status == "unsupported"
    assert result.jobs == []
    assert "combines Aruba and Juniper" in result.reason


def test_juniper_landing_is_also_rejected_for_aruba_scope():
    result = fetch_inventory(
        "Phenom", "https://careers.hpe.com/us/en/HPE-juniper-networking", COMPANY_ID, COMPANY
    )
    assert result.status == "unsupported"
    assert "Aruba-only" in result.reason
