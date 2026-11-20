"""Blues official careers source and browser-only routing checks."""

from unittest.mock import patch

from job_search_helper.ats import Inventory, fetch_inventory
from job_search_helper.browser_scraper import with_browser_fallback
from job_search_helper.company_sources import REPAIRS, repair_source
from job_search_helper.blues import fetch_blues
from job_search_helper.discovery import HTTPResponse


COMPANY_ID = "COMP-0281"
COMPANY = "Blues"
OFFICIAL = "https://blues.com/bluescareers/"


def test_blues_repair_pins_official_careers_page():
    ats, url, note = repair_source("Browser", "https://www.blues.io/careers", COMPANY_ID, COMPANY)
    assert (ats, url) == ("Browser", OFFICIAL)
    assert "Verified company source repair" in note
    assert REPAIRS[COMPANY_ID]["evidence"].endswith("no employer-scoped ATS exposed.")


def test_blues_scope_blocker_does_not_retry_generic_browser():
    body = b'<h1>Careers at Blues</h1><h2>Open Positions</h2><a href="https://www.linkedin.com/company/blues-wireless/jobs/">LinkedIn</a>'
    with patch("job_search_helper.discovery.CareersTransport.get", return_value=HTTPResponse(200, body)), \
         patch("job_search_helper.browser_scraper.fetch_browser_inventory") as browser:
        result = with_browser_fallback(fetch_inventory)("Browser", OFFICIAL, COMPANY_ID, COMPANY)
    assert result.status == "partial"
    assert "LinkedIn-only" in result.reason
    browser.assert_not_called()


class FakeTransport:
    def __init__(self, body, status=200):
        self.body = body
        self.status = status

    def get(self, url):
        assert url == OFFICIAL
        return HTTPResponse(self.status, self.body, {})


def test_blues_adapter_verifies_linkedin_only_contract_without_zero_inference():
    body = b'''<html><h1>Careers at Blues</h1><h2>Open Positions</h2>
      <a href="https://www.linkedin.com/company/blues-wireless/jobs/">LinkedIn</a></html>'''
    result = fetch_blues(OFFICIAL, COMPANY_ID, COMPANY, FakeTransport(body))
    assert result.status == "partial"
    assert result.jobs == []
    assert "LinkedIn-only" in result.reason
    assert "full descriptions" in result.reason


def test_blues_adapter_does_not_accept_unverified_or_wrong_scope():
    body = b'<html><h1>Careers at Blues</h1><h2>Open Positions</h2></html>'
    result = fetch_blues(OFFICIAL, COMPANY_ID, COMPANY, FakeTransport(body))
    assert result.status == "partial"
    assert "no verifiable public recruiting destination" in result.reason
    wrong = fetch_blues(OFFICIAL, "COMP-9999", COMPANY, FakeTransport(body))
    assert wrong.status == "unsupported"


def test_blues_is_routed_before_generic_board_discovery():
    body = b'''<html><h1>Careers at Blues</h1><h2>Open Positions</h2>
      <a href="https://www.linkedin.com/company/blues-wireless/jobs/">LinkedIn</a></html>'''
    result = fetch_inventory("Browser", OFFICIAL, COMPANY_ID, COMPANY, transport=FakeTransport(body))
    assert result.status == "partial"
    assert "LinkedIn-only" in result.reason
