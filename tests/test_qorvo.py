import unittest
from urllib.parse import parse_qs, urlsplit

from job_search_helper.ats import HTTPResponse
from job_search_helper.successfactors import QORVO_SOURCE, fetch_successfactors


def _listing(ids, total):
    first = min(ids) if ids else 1
    last = max(ids) if ids else 0
    links = "".join(
        f'<a class="jobTitle-link" href="/job/Role-{ident}/{ident:04d}/">Role {ident}</a>'
        for ident in ids
    )
    return f"Results <b>{first} – {last}</b> of <b>{total}</b>{links}".encode()


class QorvoBoard:
    def __init__(self, pages, *, final_pages=None, pagination_pages=None):
        self.pages = pages
        self.final_pages = final_pages
        self.pagination_pages = pagination_pages
        self.reads = {}
        self.urls = []

    def get(self, url):
        self.urls.append(url)
        if "/job/" in url:
            ident = int(url.rstrip("/").split("/")[-1])
            return HTTPResponse(
                200,
                (f'<span itemprop="title">Role {ident}</span>'
                 f'<div itemprop="description"><p>Full public description for {ident}.</p></div>').encode(),
            )
        start = int(parse_qs(urlsplit(url).query).get("startrow", [0])[0])
        self.reads[start] = self.reads.get(start, 0) + 1
        if self.final_pages is not None and self.reads[start] > 1:
            page = self.final_pages[start]
        elif self.pagination_pages is not None and start in self.pagination_pages:
            page = self.pagination_pages[start]
        else:
            page = self.pages[start]
        return HTTPResponse(200, _listing(*page))


class QorvoTests(unittest.TestCase):
    def test_exact_query_routing_and_full_descriptions(self):
        board = QorvoBoard({0: (range(1, 26), 26), 25: (range(26, 27), 26)})
        result = fetch_successfactors(QORVO_SOURCE, "COMP-0155", "Qorvo", board)
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual(len(result.jobs), 26)
        self.assertEqual(len({job["posting_id"] for job in result.jobs}), 26)
        self.assertTrue(all("Full public description" in job["description"] for job in result.jobs))
        listing_urls = [u for u in board.urls if "/job/" not in u]
        self.assertTrue(any("startrow=25" in u for u in listing_urls))
        for url in listing_urls:
            query = parse_qs(urlsplit(url).query, keep_blank_values=True)
            self.assertEqual(query["q"], [""])
            self.assertEqual(query["sortColumn"], ["referencedate"])
            self.assertEqual(query["sortDirection"], ["desc"])
            self.assertEqual(urlsplit(url).hostname, "careers.qorvo.com")

    def test_count_drift_during_pagination_is_partial(self):
        board = QorvoBoard(
            {0: (range(1, 26), 26), 25: (range(26, 27), 26)},
            pagination_pages={25: (range(26, 28), 27)},
        )
        self.assertEqual(fetch_successfactors(QORVO_SOURCE, "COMP-0155", "Qorvo", board).status, "partial")

    def test_addition_or_closure_between_listing_snapshots_is_partial(self):
        board = QorvoBoard(
            {0: (range(1, 26), 26), 25: (range(26, 27), 26)},
            final_pages={0: (range(1, 26), 27), 25: (range(27, 28), 27)},
        )
        self.assertEqual(fetch_successfactors(QORVO_SOURCE, "COMP-0155", "Qorvo", board).status, "partial")

    def test_duplicate_listing_id_is_partial(self):
        board = QorvoBoard({0: ([1, 1], 2)})
        self.assertEqual(fetch_successfactors(QORVO_SOURCE, "COMP-0155", "Qorvo", board).status, "partial")


if __name__ == "__main__":
    unittest.main()
