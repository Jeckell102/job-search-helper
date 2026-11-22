import unittest

from job_search_helper.ats import FetchError, HTTPResponse
from job_search_helper.shared_boards import board_link, posting


class Detail:
    def __init__(self, url, body):
        self.url = url
        self.body = body

    def get(self, url):
        if url != self.url:
            raise AssertionError("Unexpected detail route")
        return HTTPResponse(200, self.body.encode())


class EmbraerDetailTests(unittest.TestCase):
    def setUp(self):
        self.board = board_link("https://embraer.breezy.hr/")
        self.url = self.board.root + "/p/123456789abc-example"
        self.entry = {"id": "123456789abc", "url": self.url, "name": "Example technician",
                      "company": {"friendly_id": "embraer"}}
        self.detail = (f'<meta property="og:url" content="{self.url}">'
                       '<a class="brand"><h1>Example employer</h1></a>'
                       '<div class="banner"><h1>Example technician</h1></div>'
                       '<div class="description"><p>Maintain and inspect aircraft.</p></div>')

    def test_exact_company_banner_and_description(self):
        row = posting(self.board, Detail(self.url, self.detail), self.entry, "COMP-0634", "Embraer")
        self.assertEqual(row["title"], self.entry["name"])
        self.assertEqual(row["description"], "Maintain and inspect aircraft.")
        self.assertEqual(row["url"], self.url)

    def test_wrong_identity_missing_content_and_unrelated_heading_stay_partial(self):
        for detail in (
            self.detail.replace("Example technician", "Other technician"),
            self.detail.replace(self.url, self.url + "-other"),
            self.detail.replace("<p>Maintain and inspect aircraft.</p>", ""),
            self.detail.replace('class="brand"', 'class="sidebar"'),
        ):
            with self.subTest(detail=detail), self.assertRaises(FetchError):
                posting(self.board, Detail(self.url, detail), self.entry, "COMP-0634", "Embraer")

    def test_other_company_does_not_inherit_the_exception(self):
        with self.assertRaises(FetchError):
            posting(self.board, Detail(self.url, self.detail), self.entry, "COMP-0000", "Other")
