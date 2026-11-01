import unittest

from job_search_helper.ats import HTTPResponse
from job_search_helper.rohde_schwarz_usa import SOURCE, fetch_rohde_schwarz_usa


class Board:
    def __init__(self, total=31):
        self.total = total
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        if "offset=30" in url:
            ids = range(31, self.total + 1)
        else:
            ids = range(1, min(30, self.total) + 1)
        if "career-jobboard" in url:
            links = "".join(
                f'<a href="/us/career/jobs/role-{i}_251563-{i}.html">Role {i}</a>'
                for i in ids
            )
            body = (
                '<input id="filter_USA" checked><label>USA '
                f'<span class="job-search-result-count">{self.total}</span></label>{links}'
            )
        else:
            identifier = url.rsplit("-", 1)[-1].split(".", 1)[0]
            body = f'<main><h1>Role {identifier}</h1><p>Rohde &amp; Schwarz USA ' + ("details " * 100) + '</p></main>'
        return HTTPResponse(200, body.encode(), {"content-type": "text/html"})


class RohdeSchwarzTests(unittest.TestCase):
    def test_exhaustive_offset_pages_and_reread(self):
        board = Board()
        result = fetch_rohde_schwarz_usa(SOURCE, "COMP-0151", "Rohde & Schwarz USA", board)
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual(len(result.jobs), 31)
        self.assertEqual(len({job["posting_id"] for job in result.jobs}), 31)
        self.assertEqual(board.calls.count(SOURCE + "?term=%2A&filter%5BrsCountry%5D%5B%5D=USA&offset=30"), 2)

    def test_count_mismatch_does_not_complete(self):
        board = Board(total=31)
        original = board.get
        board.get = lambda url: original(url.replace("offset=30", "offset=60"))
        result = fetch_rohde_schwarz_usa(SOURCE, "COMP-0151", "Rohde & Schwarz USA", board)
        self.assertEqual(result.status, "partial")

    def test_identity_is_pinned(self):
        result = fetch_rohde_schwarz_usa(SOURCE, "OTHER", "Rohde & Schwarz USA", Board())
        self.assertEqual(result.status, "unsupported")


if __name__ == "__main__":
    unittest.main()
