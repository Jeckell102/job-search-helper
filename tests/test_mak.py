import unittest
from pathlib import Path

from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.mak import fetch_mak


class FakeTransport:
    def __init__(self, mapping):
        self.mapping = mapping
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        return HTTPResponse(200, self.mapping[url].encode())


class MakTests(unittest.TestCase):
    def test_scoped_board_routes_and_retrieves_full_posting(self):
        detail = (Path(__file__).parent / "fixtures/shared_boards/jazzhr-detail.html").read_text()
        listing = '<div class="jobs-list"><a href="https://mak.applytojob.com/apply/AONmJi1N5j/Assistant-Customer-Technical-Representative-ACTR">Assistant Customer Technical Representative (ACTR)</a></div>'
        url = "https://mak.applytojob.com/apply"
        transport = FakeTransport({url: listing, "https://mak.applytojob.com/apply/AONmJi1N5j/Assistant-Customer-Technical-Representative-ACTR": detail})
        result = fetch_inventory("JazzHR", url, "COMP-0331", "MAK Technologies", transport)
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual(len(result.jobs), 1)
        self.assertGreater(len(result.jobs[0]["description"]), 100)
        self.assertEqual(result.ats, "JazzHR")

    def test_wrong_identity_fails_closed(self):
        result = fetch_mak("https://mak.applytojob.com/apply", "COMP-0331", "Other Company")
        self.assertEqual(result.status, "unsupported")


if __name__ == "__main__":
    unittest.main()
