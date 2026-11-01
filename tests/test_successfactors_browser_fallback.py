import unittest
from unittest.mock import patch

from job_search_helper.ats import Inventory
from job_search_helper.browser_scraper import with_browser_fallback
from job_search_helper.successfactors import SITES


SOURCE = "https://careers.leonardodrs.com/go/All-Jobs/8131200/"


class SuccessFactorsBrowserFallbackTests(unittest.TestCase):
    def test_known_successfactors_partial_never_merges_unscoped_browser_ids(self):
        direct = Inventory(
            "partial",
            [{"posting_id": str(i), "url": f"{SOURCE}job/{i}/", "title": f"Role {i}", "description": "full"}
             for i in range(25)],
            "listing pagination incomplete",
            SOURCE,
            "SuccessFactors",
        )
        browser = Inventory(
            "partial",
            [{"posting_id": f"browser-{i}", "url": f"{SOURCE}job/{i}/", "title": f"Role {i}", "description": "full"}
             for i in range(25)],
            "browser inventory incomplete",
            SOURCE,
            "Browser",
        )

        def direct_fetch(*_args):
            return direct

        wrapped = with_browser_fallback(direct_fetch)
        with patch("job_search_helper.browser_scraper.fetch_browser_inventory", return_value=browser) as browser_call:
            result = wrapped("SuccessFactors", SOURCE, "COMP-0081", "Leonardo DRS")
        self.assertIs(result, direct)
        self.assertEqual(len(result.jobs), 25)
        browser_call.assert_not_called()

    def test_unknown_failed_board_still_uses_browser_fallback(self):
        direct = Inventory("failed", [], "not supported yet", "https://example.test/careers", "Unknown")
        browser = Inventory("partial", [], "browser incomplete", "https://example.test/careers", "Browser")
        wrapped = with_browser_fallback(lambda *_args: direct)
        with patch("job_search_helper.browser_scraper.fetch_browser_inventory", return_value=browser) as browser_call:
            result = wrapped("Unknown", "https://example.test/careers", "COMP-X", "Example")
        browser_call.assert_called_once()
        # With no browser jobs, the wrapper correctly retains the direct
        # failure while still proving that browser discovery was attempted.
        self.assertEqual(result.status, "failed")

    def test_known_board_is_registered_as_structured_successfactors(self):
        self.assertEqual(SITES[SOURCE], "careers.leonardodrs.com")

