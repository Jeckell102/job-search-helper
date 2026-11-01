"""Verified company repairs preserve caller edits and use the current provider."""

import unittest
from unittest.mock import patch

from job_search_helper.ats import Inventory, fetch_inventory
from job_search_helper.browser_scraper import with_browser_fallback
from job_search_helper.company_sources import REPAIRS, repair_source


class SourceRepairs(unittest.TestCase):
    def test_empty_source_resolves_only_exact_company(self):
        company_id = "COMP-0143"
        entry = REPAIRS[company_id]
        _, url, note = repair_source("Browser", "", company_id, entry["company"])
        self.assertEqual(url, entry["url"])
        self.assertTrue(note)
        self.assertEqual(
            repair_source("Browser", "", "another-id", entry["company"]),
            ("Browser", "", ""),
        )
        self.assertEqual(
            repair_source("Browser", "", company_id, "Other Company"),
            ("Browser", "", ""),
        )

    def test_user_changed_source_wins(self):
        entry = REPAIRS["COMP-0143"]
        url = "https://new.example/jobs"
        self.assertEqual(
            repair_source("Browser", url, "COMP-0143", entry["company"]),
            ("Browser", url, ""),
        )

    def test_direct_fetcher_routes_repaired_url(self):
        entry = REPAIRS["COMP-0143"]
        with patch(
            "job_search_helper.dayforce.fetch_dayforce",
            return_value=Inventory("complete", ats="Dayforce"),
        ) as fetch:
            result = fetch_inventory("Browser", "", "COMP-0143", entry["company"])
        self.assertEqual(fetch.call_args.args[1], entry["url"])
        self.assertIn("Verified company source repair", result.reason)

    def test_browser_uses_same_repaired_source(self):
        entry = REPAIRS["COMP-0143"]
        seen = []

        def direct(*args):
            seen.append(args)
            return Inventory("blocked", ats="Dayforce")

        with patch(
            "job_search_helper.shared_boards.fetch_shared_browser",
            return_value=Inventory("complete", ats="Dayforce"),
        ) as browser:
            result = with_browser_fallback(direct)("Browser", "", "COMP-0143", entry["company"])
        self.assertEqual(seen[0][1], entry["url"])
        self.assertEqual(browser.call_args.args[1], entry["url"])
        self.assertEqual(result.status, "complete")
