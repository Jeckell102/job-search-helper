import unittest
from urllib.parse import urlsplit

from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.successfactors import KOMATSU_SOURCE, fetch_successfactors


def _listing(start, total=100):
    first = start + 1
    last = min(start + 50, total)
    links = "".join(
        f'<a class="jobTitle-link" href="/job/Role-{i}/{i:05d}/">Role {i}</a>'
        for i in range(first, last + 1)
    )
    return f"Results <b>{first} – {last}</b> of <b>{total}</b>{links}"


class KomatsuBoard:
    def __init__(self):
        self.urls = []

    def get(self, url):
        self.urls.append(url)
        path = urlsplit(url).path
        if path.startswith("/job/"):
            ident = int(path.rstrip("/").split("/")[-1].split("-", 1)[0])
            return HTTPResponse(200, (
                f'<span itemprop="title">Role {ident}</span>'
                f'<div itemprop="description">Full description {ident}</div>'
            ).encode())
        start = int(path.rstrip("/").split("/")[-1]) if path.rstrip("/").split("/")[-1].isdigit() else 0
        return HTTPResponse(200, _listing(start).encode())

    def post(self, url, payload, headers=None):
        import json
        page = int(payload["pageNumber"])
        rows = []
        for i in range(page * 50 + 1, min(page * 50 + 50, 100) + 1):
            rows.append({"response": {"id": str(100 + i), "urlTitle": f"Role-{i}", "unifiedStandardTitle": f"Role {i}"}})
        return HTTPResponse(200, json.dumps({"jobSearchResult": rows, "totalJobs": 100}).encode())


class KomatsuTests(unittest.TestCase):
    def test_path_pagination_and_two_pass_listing_recheck(self):
        board = KomatsuBoard()
        result = fetch_successfactors(KOMATSU_SOURCE, "COMP-0240", "Komatsu", board)
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual(len(result.jobs), 100)
        self.assertEqual(len({job["posting_id"] for job in result.jobs}), 100)
        self.assertIn("https://komatsu.jobs/viewalljobs/50/", board.urls)
        self.assertGreaterEqual(board.urls.count(KOMATSU_SOURCE), 2)

    def test_company_route_repairs_official_careers_page(self):
        board = KomatsuBoard()
        result = fetch_inventory(
            "Browser", "https://www.komatsu.com/en-us/careers", "COMP-0240", "Komatsu",
            discovery_transport=board,
        )
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual(len(result.jobs), 100)


if __name__ == "__main__":
    unittest.main()
