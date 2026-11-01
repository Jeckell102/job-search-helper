import unittest

from job_search_helper.ats import HTTPResponse
from job_search_helper.fischer_connectors import SOURCE, fetch_fischer_connectors


class Client:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        return HTTPResponse(200, self.pages[url].encode(), {})


LISTING = """
<html><h1>Our job openings</h1>
<a href='/en/job-opening/alpha/'>Alpha</a>
<a href='/en/job-opening/beta/'>Beta</a>
<a href='/en/about-us/'>About</a>
</html>
"""
DETAIL = "<html><h1>{title}</h1><p>{body}</p></html>"


class FischerConnectorsTests(unittest.TestCase):
    def test_retrieves_scoped_details_and_rereads_listing(self):
        pages = {
            SOURCE: LISTING,
            "https://fischerconnectors.com/en/job-opening/alpha/": DETAIL.format(title="Alpha", body="A" * 700),
            "https://fischerconnectors.com/en/job-opening/beta/": DETAIL.format(title="Beta", body="B" * 700),
        }
        client = Client(pages)
        result = fetch_fischer_connectors(SOURCE, "COMP-0491", "Fischer Connectors", client)
        self.assertEqual(result.status, "complete")
        self.assertEqual(len(result.jobs), 2)
        self.assertEqual(client.calls.count(SOURCE), 2)

    def test_rejects_wrong_scope(self):
        result = fetch_fischer_connectors(SOURCE, "COMP-0491", "Other Company", Client({}))
        self.assertEqual(result.status, "unsupported")

    def test_detects_inventory_change(self):
        class Changing(Client):
            def __init__(self, pages):
                super().__init__(pages)
                self.listing_reads = 0

            def get(self, url):
                if url == SOURCE:
                    self.listing_reads += 1
                    if self.listing_reads == 2:
                        return HTTPResponse(200, (LISTING + "<a href='/en/job-opening/gamma/'>Gamma</a>").encode(), {})
                return super().get(url)

        pages = {
            SOURCE: LISTING,
            "https://fischerconnectors.com/en/job-opening/alpha/": DETAIL.format(title="Alpha", body="A" * 700),
            "https://fischerconnectors.com/en/job-opening/beta/": DETAIL.format(title="Beta", body="B" * 700),
        }
        result = fetch_fischer_connectors(SOURCE, "COMP-0491", "Fischer Connectors", Changing(pages))
        self.assertEqual(result.status, "partial")


if __name__ == "__main__":
    unittest.main()
