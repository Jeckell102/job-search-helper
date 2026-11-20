"""Kägwerks source repair and browser routing checks."""

from unittest.mock import patch

from job_search_helper.ats import Inventory, fetch_inventory
from job_search_helper.company_sources import REPAIRS, repair_source


COMPANY_ID = "COMP-0310"
COMPANY = "Kägwerks"


def test_kaegwerks_repair_accepts_queue_url_and_pins_careers_route():
    entry = REPAIRS[COMPANY_ID]
    ats, url, note = repair_source("Browser", "https://kagwerks.com/", COMPANY_ID, COMPANY)
    assert (ats, url) == (entry["ats"], entry["url"])
    assert "Verified company source repair" in note


def test_kaegwerks_repair_accepts_legacy_careers_route():
    entry = REPAIRS[COMPANY_ID]
    ats, url, _ = repair_source("Browser", "https://www.kaegwerks.com/careers/", COMPANY_ID, COMPANY)
    assert (ats, url) == (entry["ats"], entry["url"])


def test_kaegwerks_browser_fallback_is_used_after_direct_failure():
    direct = Inventory("failed", reason="DNS resolution failed", source_url=REPAIRS[COMPANY_ID]["url"], ats="Browser")
    browser = Inventory("blocked", reason="Browser source unavailable: DNS resolution failed", source_url=REPAIRS[COMPANY_ID]["url"], ats="Browser")
    with patch("job_search_helper.browser_scraper.fetch_browser_inventory", return_value=browser) as fallback:
        from job_search_helper.browser_scraper import with_browser_fallback
        result = with_browser_fallback(lambda *args: direct)("Browser", "https://kagwerks.com/", COMPANY_ID, COMPANY)
    assert result.status == "failed"
    fallback.assert_called_once_with("Browser", REPAIRS[COMPANY_ID]["url"], COMPANY_ID, COMPANY)


def test_kaegwerks_installed_dispatch_reaches_browser_source():
    with patch("job_search_helper.ats._fetch_inventory", return_value=Inventory("blocked", ats="Browser")) as fetch:
        result = fetch_inventory("Browser", "https://kagwerks.com/", COMPANY_ID, COMPANY)
    assert result.status == "blocked"
    assert fetch.call_args.args[:4] == ("Browser", REPAIRS[COMPANY_ID]["url"], COMPANY_ID, COMPANY)
