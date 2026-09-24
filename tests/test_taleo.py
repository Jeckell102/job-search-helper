from contextlib import redirect_stderr
from io import StringIO
import json
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from job_search_helper.ats import FetchError, HTTPResponse, HTTPTransport, _safe_api_url, fetch_inventory, resolve_board
from job_search_helper.taleo import SEARCH_PATH
from test_discovery import html


HOST = "textron.taleo.net"
ROOT = f"https://{HOST}/careersection/"
BOARD = ROOT + "tabbu/jobsearch.ftl"
DETAIL = ROOT + "tabbu/jobdetail.ftl?job=345210&lang=en"
SEARCH = f"https://{HOST}{SEARCH_PATH}?lang=en&portal=50140708226"


def listing(items=None, total=None, page=1, page_size=25):
    if items is None:
        items = [entry()]
    if total is None:
        total = len(items)
    return HTTPResponse(200, json.dumps({
        "requisitionList": items,
        "pagingData": {"totalCount": total, "pageSize": page_size, "currentPageNo": page},
    }).encode(), {"Content-Type": "application/json"})


def entry(contest="345210", title="A&P Mobile Service Technician", location='["US-Alabama-Birmingham"]'):
    return {"jobId": "1544480", "contestNo": contest, "column": [title, "Full-time", location, "Engineering"], "linkedColumn": 0}


def search_page(portal="50140708226", code="tabbu"):
    return html(f"""
        <html><body>
        <script>var portalNo = '{portal}'; var urlCode = '{code}'; var lang = 'en';</script>
        </body></html>
    """)


def detail(title="A&P Mobile Service Technician", contest="345210"):
    return html(f"""
        <html><head><meta property="og:title" content="{title}" /></head>
        <body><h1>{title}</h1><h2>Job Description</h2>
        <p>Maintain aircraft systems and support field service customers.</p>
        <p>Travel up to 20%.</p>
        <p>Apply for this position online</p>
        <input id="initialHistory" value="{title}!|!{contest}!|!Maintain aircraft systems" />
        </body></html>
    """)


class Transport:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.urls = []
        self.posts = []

    def get(self, url):
        self.urls.append(url)
        result = next(self.responses)
        if isinstance(result, Exception):
            raise result
        return result

    def post(self, url, payload):
        self.posts.append((url, payload))
        result = next(self.responses)
        if isinstance(result, Exception):
            raise result
        return result


class TaleoTests(unittest.TestCase):
    def setUp(self):
        capture = redirect_stderr(StringIO())
        capture.__enter__()
        self.addCleanup(capture.__exit__, None, None, None)

    def fetch(self, responses, url=BOARD, ats="Taleo"):
        transport = Transport(responses)
        result = fetch_inventory(ats, url, "C-1", "Textron", transport)
        return result, transport

    def test_resolves_search_and_detail_urls_to_board(self):
        for url in (BOARD, ROOT + "tabbu/moresearch.ftl?lang=en", DETAIL, ROOT + "tabbu/jobapply.ftl?job=345210&lang=en"):
            self.assertEqual(resolve_board("Taleo", url), ("Taleo", "tabbu/jobsearch.ftl", ROOT))
        self.assertEqual(resolve_board("", BOARD + "?utm_source=site"), ("Taleo", "tabbu/jobsearch.ftl", ROOT))

    def test_full_inventory_posts_public_search_and_fetches_detail(self):
        result, transport = self.fetch([search_page(), listing(), detail(), listing()])
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual(result.source_url, BOARD)
        self.assertEqual(result.jobs[0]["ats"], "Taleo")
        self.assertEqual(result.jobs[0]["posting_id"], "345210")
        self.assertEqual(result.jobs[0]["req_id"], "345210")
        self.assertEqual(result.jobs[0]["title"], "A&P Mobile Service Technician")
        self.assertIn("Birmingham", result.jobs[0]["location"])
        self.assertIn("Maintain aircraft systems", result.jobs[0]["description"])
        self.assertNotIn("Apply for this position online", result.jobs[0]["description"])
        self.assertEqual(transport.urls, [BOARD, DETAIL])
        self.assertEqual([url for url, _ in transport.posts], [SEARCH, SEARCH])
        self.assertEqual(transport.posts[0][1]["pageNo"], 1)
        self.assertIn("JOB_TITLE", transport.posts[0][1]["fieldData"]["fields"])

    def test_empty_board_requires_listing_and_recheck(self):
        result, transport = self.fetch([search_page(), listing([]), listing([])])
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual(result.jobs, [])
        self.assertEqual(len(transport.posts), 1)

    def test_pagination_and_final_recheck(self):
        one = entry("111", "First")
        two = entry("222", "Second")
        result, transport = self.fetch([
            search_page(), listing([one], total=2, page=1, page_size=1), detail("First", "111"),
            listing([two], total=2, page=2, page_size=1), detail("Second", "222"),
            listing([one], total=2, page=1, page_size=1),
        ])
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual([job["posting_id"] for job in result.jobs], ["111", "222"])
        self.assertEqual([payload["pageNo"] for _, payload in transport.posts], [1, 2, 1])

    def test_board_change_or_missing_detail_is_partial(self):
        result, _ = self.fetch([search_page(), listing(), detail(), listing([entry("999")])])
        self.assertEqual(result.status, "partial")
        self.assertIn("changed", result.reason)
        result, _ = self.fetch([search_page(), listing(), html("detail unavailable")])
        self.assertEqual(result.status, "partial")

    def test_denials_and_bad_shapes_do_not_complete(self):
        for responses, expected in (([html("denied", status=403)], "blocked"), ([search_page(), HTTPResponse(500, b"no")], "failed"), ([search_page(), HTTPResponse(200, b"{}")], "partial")):
            with self.subTest(expected=expected):
                result, _ = self.fetch(responses)
                self.assertEqual(result.status, expected)

    def test_unsupported_filters_mismatch_and_shared_scope(self):
        for url in (BOARD + "?location=Ohio", BOARD.replace("jobsearch", "foo"), BOARD.replace("https:", "http:")):
            result, transport = self.fetch([], url=url)
            self.assertEqual(result.status, "unsupported")
            self.assertFalse(transport.urls or transport.posts)
        self.assertEqual(self.fetch([], ats="Workday")[0].status, "unsupported")
        self.assertEqual(self.fetch([], ats="Taleo shared parent")[0].status, "unsupported")

    def test_transport_allowlist_and_post_guard(self):
        for url in (BOARD, DETAIL, SEARCH):
            _safe_api_url(url)
        for url in (BOARD + "?location=Ohio", ROOT + "tabbu/jobapply.ftl?cmd=evil", SEARCH + "&extra=1", BOARD.replace(HOST, HOST + ".evil.example")):
            with self.assertRaises(FetchError):
                _safe_api_url(url)
        with self.assertRaises(FetchError):
            HTTPTransport().post(BOARD, {})

    def test_discovery_finds_taleo_link(self):
        from test_ats import Transport as PageTransport
        page = html(f'<a href="{BOARD}">Search Jobs</a>')
        result, transport = self.fetch([search_page(), listing(), detail(), listing()], url="https://acme.example/careers", ats="")
        # Direct fetch path above should not have page discovery; check discovery through fetch_inventory separately.
        pages = PageTransport([page])
        api = Transport([search_page(), listing(), detail(), listing()])
        result = fetch_inventory("", "https://acme.example/careers", "C-1", "Textron", api, discovery_transport=pages)
        self.assertEqual(result.status, "complete", result.reason)
        self.assertIn("Discovered Taleo", result.reason)
        self.assertEqual(pages.urls, ["https://acme.example/careers"])


if __name__ == "__main__":
    unittest.main()
