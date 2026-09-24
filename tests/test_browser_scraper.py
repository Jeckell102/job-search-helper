import unittest
import builtins
from unittest.mock import patch

from job_search_helper.ats import Inventory
from job_search_helper.browser_scraper import _extract_links, jobs_from_json_payload, with_browser_fallback


class FakeLocator:
    def __init__(self, anchors):
        self.anchors = anchors

    def evaluate_all(self, _script):
        return self.anchors


class FakePage:
    def __init__(self, anchors):
        self.anchors = anchors

    def locator(self, _selector):
        return FakeLocator(self.anchors)


class BrowserFallbackTests(unittest.TestCase):
    def test_successful_direct_fetch_does_not_open_browser(self):
        direct = lambda *args: Inventory("complete", [{"title": "x"}], "ok")
        with patch("job_search_helper.browser_scraper.fetch_browser_inventory") as browser:
            result = with_browser_fallback(direct)("ATS", "https://example.com/careers", "C", "Acme")
        self.assertEqual(result.status, "complete")
        browser.assert_not_called()

    def test_blocked_direct_fetch_can_return_browser_inventory(self):
        direct = lambda *args: Inventory("blocked", [], "HTTP 403", "https://example.com/careers", "Workday")
        browser_result = Inventory("complete", [{"title": "Field Engineer"}], "scraped", "https://example.com/careers", "Workday")
        with patch("job_search_helper.browser_scraper.fetch_browser_inventory", return_value=browser_result) as browser:
            result = with_browser_fallback(direct)("Workday", "https://example.com/careers", "C", "Acme")
        self.assertEqual(result.status, "complete")
        self.assertIn("Direct fetch returned blocked", result.reason)
        browser.assert_called_once()

    def test_missing_playwright_is_manual_review_not_closure(self):
        from job_search_helper.browser_scraper import fetch_browser_inventory
        original_import = builtins.__import__

        def missing_playwright(name, *args, **kwargs):
            if name == "playwright.sync_api":
                raise ImportError("missing")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=missing_playwright):
            result = fetch_browser_inventory("Workday", "https://example.com/careers", "C", "Acme")
        self.assertEqual(result.status, "unsupported")
        self.assertIn("Playwright", result.reason)

    def test_frontend_json_payloads_normalize_to_inventory_jobs(self):
        payload = {
            "data": {
                "postings": [{
                    "jobTitle": "Field Service Program Manager",
                    "jobId": "123",
                    "jobDetailUrl": "/careers/jobs/123",
                    "jobLocation": {"name": "Remote US"},
                    "jobDescription": "<p>Lead deployments and customer troubleshooting.</p>",
                }]
            }
        }
        jobs = jobs_from_json_payload(payload, "https://example.com/careers", "C", "Acme", "Browser")
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["posting_id"], "123")
        self.assertEqual(jobs[0]["url"], "https://example.com/careers/jobs/123")
        self.assertIn("Lead deployments", jobs[0]["description"])

    def test_rendered_link_scraper_ignores_self_careers_link(self):
        links = _extract_links(FakePage([
            {"text": "Career", "href": "https://www.foretellix.com/career/"},
            {"text": "Field Engineer", "href": "https://www.foretellix.com/career/field-engineer"},
        ]), "https://www.foretellix.com/career/")
        self.assertEqual(links, [{"url": "https://www.foretellix.com/career/field-engineer", "title": "Field Engineer"}])


if __name__ == "__main__":
    unittest.main()
