import json
import unittest

from job_search_helper.ats import HTTPResponse, fetch_inventory


CAREERS = "https://www.u-blox.com/en/job-openings"
DETAIL = "https://fs-4627.my.salesforce-sites.com/recruit/fRecruit__ApplyJob?vacancyNo=VN2705"


class Transport:
    def __init__(self):
        self.listings = 0

    def post(self, url, payload):
        self.listings += 1
        return HTTPResponse(200, json.dumps({"nbHits": 1, "page": 0, "nbPages": 1, "hits": [{
            "id": "a2SaV000006Gg7tUAC", "name": "FPGA Engineer", "link_https": DETAIL,
            "locations_legacy": ["Thalwil, Switzerland"], "department": "Engineering", "percentage": "Full Time",
        }]}).encode())

    def get(self, url):
        body = '<script type="application/ld+json">{"@type":"JobPosting","title":"FPGA Engineer","description":"<p>Build FPGA systems.</p>"}</script>'
        return HTTPResponse(200, body.encode(), {"Content-Type": "text/html"})


class UbloxTests(unittest.TestCase):
    def test_public_algolia_listing_and_details(self):
        transport = Transport()
        result = fetch_inventory("Salesforce-hosted recruiting", CAREERS, "C", "u-blox", transport)
        self.assertEqual(result.status, "complete")
        self.assertEqual(len(result.jobs), 1)
        self.assertEqual(result.jobs[0]["req_id"], "VN2705")
        self.assertIn("Build FPGA systems", result.jobs[0]["description"])
        self.assertEqual(transport.listings, 2)

    def test_other_salesforce_urls_are_not_accepted(self):
        result = fetch_inventory("Salesforce-hosted recruiting", "https://example.com/jobs", "C", "u-blox", Transport())
        self.assertEqual(result.status, "unsupported")

