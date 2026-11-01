import unittest
from unittest.mock import Mock

from job_search_helper.ats import fetch_inventory
from job_search_helper.saic import (
    COMPANY,
    COMPANY_ID,
    SOURCE,
    _listing_url,
    _same_page_url,
    fetch_saic,
)


class SaicRoutingTests(unittest.TestCase):
    def test_routes_through_the_verified_company_scoped_board(self):
        result = fetch_inventory("TalentBrew", SOURCE, COMPANY_ID, COMPANY)

        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.ats, "SAIC TalentBrew")
        self.assertEqual(result.source_url, SOURCE)
        self.assertIn("verified browser adapter", result.reason)

    def test_rejects_other_company_or_filtered_routes(self):
        wrong_company = fetch_saic(SOURCE, COMPANY_ID, "Other Company")
        wrong_source = fetch_saic("https://jobs.saic.com/?bid=5081", COMPANY_ID, COMPANY)

        self.assertEqual(wrong_company.status, "unsupported")
        self.assertEqual(wrong_source.status, "unsupported")

    def test_listing_urls_and_redirect_validation_are_pinned(self):
        self.assertEqual(_listing_url(1), SOURCE)
        self.assertEqual(_listing_url(2), "https://jobs.saic.com/search/jobs/in?page=2")
        self.assertTrue(_same_page_url(SOURCE, 1))
        self.assertTrue(_same_page_url("https://jobs.saic.com/search/jobs/in?page=2", 2))
        self.assertFalse(_same_page_url("https://jobs.saic.com/search/jobs?page=2", 2))
        self.assertFalse(_same_page_url("https://evil.example/jobs", 1))

    def test_fetcher_does_not_use_transport_or_follow_application_routes(self):
        transport = Mock()
        result = fetch_saic(SOURCE, COMPANY_ID, COMPANY, transport)

        self.assertEqual(result.status, "blocked")
        transport.request.assert_not_called()
