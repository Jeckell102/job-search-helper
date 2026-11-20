import unittest

from job_search_helper.amentum import fetch_amentum, supports_amentum, _read
from job_search_helper.ats import HTTPResponse


class Public:
    def get(self, url):
        self.url = url
        return HTTPResponse(
            202,
            b"<script>window.awsWafCookieDomainList = ['clinchtalent.com']</script>",
            {"x-amzn-waf-action": "challenge"},
        )


class Usable:
    def get(self, url):
        return HTTPResponse(202, b"<html><body><h1>Amentum</h1><table class='table'><tr class='job-search-results-title'></tr></table></body></html>", {})


class AmentumTests(unittest.TestCase):
    def test_only_unfiltered_official_listing_is_supported(self):
        self.assertTrue(supports_amentum("Amentum careers", "https://www.amentumcareers.com/jobs/search"))
        self.assertFalse(supports_amentum("Amentum careers", "https://www.amentumcareers.com/jobs/search?page=2"))
        self.assertFalse(supports_amentum("Amentum careers", "https://other.example/jobs/search"))

    def test_aws_waf_challenge_is_blocked_not_partial(self):
        result = fetch_amentum("https://www.amentumcareers.com/jobs/search", "COMP-0005", "Amentum", Public())
        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.jobs, [])
        self.assertIn("denied access", result.reason)

    def test_http_202_is_usable_only_when_it_is_not_a_challenge_shell(self):
        self.assertIn("Amentum", _read(Usable(), "https://www.amentumcareers.com/jobs/search"))

