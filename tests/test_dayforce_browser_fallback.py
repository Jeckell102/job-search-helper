import unittest
from unittest.mock import patch

from job_search_helper.ats import Inventory
from job_search_helper.browser_scraper import with_browser_fallback
from job_search_helper.dayforce import SOURCE


class DayforceBrowserFallbackTests(unittest.TestCase):
    def test_known_elbit_dayforce_partial_is_not_merged_with_generic_browser(self):
        direct = Inventory("partial", [{"posting_id": "7933", "url": SOURCE + "/7933", "title": "Role", "description": "full"}], "detail incomplete", SOURCE, "Dayforce")
        browser = Inventory("partial", [{"posting_id": "browser-hash", "url": SOURCE + "/7933", "title": "Role", "description": "full"}], "browser incomplete", SOURCE, "Browser")
        with patch("job_search_helper.browser_scraper.fetch_browser_inventory", return_value=browser) as browser_call:
            result = with_browser_fallback(lambda *_args: direct)("Dayforce", SOURCE, "COMP-0089", "Elbit Systems of America")
        self.assertIs(result, direct)
        browser_call.assert_not_called()

    def test_unknown_dayforce_board_keeps_existing_generic_behavior(self):
        source = "https://example.dayforcehcm.com/careers"
        direct = Inventory("failed", [], "not supported yet", source, "Dayforce")
        browser = Inventory("partial", [], "browser incomplete", source, "Browser")
        with patch("job_search_helper.shared_boards.fetch_shared_browser", return_value=browser) as browser_call:
            result = with_browser_fallback(lambda *_args: direct)("Dayforce", source, "COMP-X", "Example")
        # An unrecognized Dayforce route must not be promoted to a complete
        # inventory by the generic fallback; its direct failure remains safe.
        self.assertIs(result, direct)


if __name__ == "__main__":
    unittest.main()
