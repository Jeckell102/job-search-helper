"""ModalAI official-source routing and browser-only terminal behavior."""

from job_search_helper.ats import fetch_inventory
from job_search_helper.company_sources import REPAIRS, repair_source


COMPANY_ID = "COMP-0173"
COMPANY = "ModalAI"
LEGACY = "https://modalai.com/careers"
OFFICIAL = "https://www.modalai.com/pages/careers"


def test_modalai_repairs_legacy_route_to_official_careers_page():
    ats, url, note = repair_source("Browser", LEGACY, COMPANY_ID, COMPANY)

    assert (ats, url) == ("ModalAI careers", OFFICIAL)
    assert REPAIRS[COMPANY_ID]["url"] == OFFICIAL
    assert "Shopify careers page" in REPAIRS[COMPANY_ID]["evidence"]
    assert "Verified company source repair" in note


def test_modalai_public_careers_page_is_not_counted_without_live_job_inventory():
    result = fetch_inventory("ModalAI careers", OFFICIAL, COMPANY_ID, COMPANY)

    assert result.status in {"failed", "partial", "blocked", "unsupported"}
    assert not result.jobs
    assert result.source_url == OFFICIAL
    assert ("network" in result.reason.casefold()
            or "board discovery" in result.reason.casefold()
            or "ats" in result.reason.casefold()
            or "job" in result.reason.casefold())
