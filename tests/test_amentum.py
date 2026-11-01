import unittest

from job_search_helper.amentum import fetch_amentum, supports_amentum
from job_search_helper.ats import HTTPResponse


class Public:
    def get(self, url):
        self.url = url
        return HTTPResponse(
            202,
            b"<script>window.awsWafCookieDomainList = ['clinchtalent.com']</script>",
            {"x-amzn-waf-action": "challenge"},
        )


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

