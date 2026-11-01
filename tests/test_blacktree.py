import unittest

from job_search_helper.ats import HTTPResponse, fetch_inventory


SOURCE = "https://blacktree.com.au/careers/"
HTML = b"""<h3>Opportunities to work with us</h3><h4>In Demand Positions</h4><ul><li>Systems Engineers / RF Engineers</li><li>Electronics Technicians</li><li>Project Managers</li></ul>"""


class Transport:
    def __init__(self, pages): self.pages = list(pages)
    def get(self, url):
        self.assertEqual(url, SOURCE)
        return self.pages.pop(0)
    def assertEqual(self, first, second):
        if first != second: raise AssertionError((first, second))


class BlackTreeTests(unittest.TestCase):
    def test_complete_static_inventory_is_rechecked(self):
        transport = Transport([HTTPResponse(200, HTML), HTTPResponse(200, HTML)])
        result = fetch_inventory("Browser", SOURCE, "COMP-0042", "BlackTree Technology", discovery_transport=transport)
        self.assertEqual(result.status, "complete")
        self.assertEqual([job["title"] for job in result.jobs], ["Systems Engineers / RF Engineers", "Electronics Technicians", "Project Managers"])
        self.assertEqual(result.ats, "BlackTree careers")

    def test_changed_inventory_fails_closed(self):
        changed = HTML.replace(b"Project Managers", b"Program Managers")
        transport = Transport([HTTPResponse(200, HTML), HTTPResponse(200, changed)])
        result = fetch_inventory("Browser", SOURCE, "COMP-0042", "BlackTree Technology", discovery_transport=transport)
        self.assertEqual(result.status, "partial")
        self.assertEqual(len(result.jobs), 3)

    def test_unverified_company_cannot_use_adapter(self):
        result = fetch_inventory("BlackTree careers", SOURCE, "COMP-OTHER", "Other", discovery_transport=Transport([]))
        self.assertEqual(result.status, "unsupported")

