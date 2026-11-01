from contextlib import redirect_stderr
from io import StringIO
import json
from html import escape as html_escape
from pathlib import Path
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


def scoped_careers_page(items, total, page=0, pages=2):
    cards = []
    for contest, title in items:
        cards.append(f"""
        <div class="career-reference-wrapper">
          <div class="career-reference__title"><a class="career-reference__title-link"
            href="https://textron.taleo.net/careersection/textron/jobdetail.ftl?job={contest}">{title}</a></div>
          <div class="career-reference__city">Hunt Valley,</div>
          <div class="career-reference__state">Maryland,</div>
          <div class="career-reference__country">United States</div>
          <div class="career-reference__date">Posted Date: September 23, 2026</div>
          <div class="career-reference__reference-number">Reference Number: {contest}</div>
          <div class="accordion__content__inner"><p>{title} responsibilities and qualifications.</p></div>
        </div>
        """)
    pagination = "".join(
        f'<a href="https://www.textronsystems.com/careers/apply-today?page={number}">Page {number + 1}</a>'
        for number in range(pages)
    )
    return html(f"""
      <html><body><h4>{total} job(s) match your search criteria</h4>
      {''.join(cards)}{pagination}<span>Current page {page + 1}</span></body></html>
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


class MoxaCaptureTransport:
    """Replay the captured Moxa board, search JSON, and all 12 details."""
    def __init__(self, *, mutate=None):
        fixture = Path(__file__).parent / "fixtures" / "moxa" / "models.json"
        models = json.loads(fixture.read_text())
        portal = models["portal"]
        self.models = models
        self.board = (f"<script>var portalNo = '{portal['portal']}'; "
                      f"var urlCode = '{portal['career_section']}'; "
                      f"var lang = '{portal['lang']}';</script>").encode()
        self.search = models["listing"]
        self.details = {}
        for contest, model in models["details"].items():
            history = html_escape("!|!".join(model["initial_history"]), quote=True)
            self.details[contest] = (
                f'<meta property="og:title" content="{html_escape(model["meta_title"], quote=True)}">'
                f'<input id="initialHistory" value="{history}">'
            ).encode()
        self.mutate = mutate
        self.urls = []
        self.posts = []

    def get(self, url):
        self.urls.append(url)
        if "jobdetail.ftl" in url:
            contest = parse_qs(urlsplit(url).query)["job"][0]
            body = self.details[contest]
            if self.mutate:
                body = self.mutate("detail", contest, body)
            return HTTPResponse(200, body, {"Content-Type": "text/html"})
        return HTTPResponse(200, self.board, {"Content-Type": "text/html"})

    def post(self, url, payload):
        self.posts.append((url, payload))
        data = json.loads(json.dumps(self.search))
        if self.mutate:
            data = self.mutate("search", "", data)
        return HTTPResponse(200, json.dumps(data).encode(), {"Content-Type": "application/json"})


class MoxaPagedTransport(MoxaCaptureTransport):
    """Synthetic 26-job extension used only to exercise the second page gate."""
    def __init__(self, *, final_change=False):
        super().__init__()
        base = list(self.search["requisitionList"])
        template = self.models["details"]["260078"]
        for index in range(13, 27):
            contest, title, job_id = f"SYN{index:03d}", f"Synthetic Moxa Role {index}", f"900{index:06d}"
            item = json.loads(json.dumps(base[(index - 13) % len(base)]))
            item["contestNo"], item["jobId"], item["column"][0] = contest, job_id, title
            base.append(item)
            parts = list(template["initial_history"])
            parts[5], parts[12], parts[13] = job_id, title, contest
            self.models["details"][contest] = {"meta_title": title, "initial_history": parts}
            history = html_escape("!|!".join(parts), quote=True)
            self.details[contest] = (
                f'<meta property="og:title" content="{html_escape(title, quote=True)}">'
                f'<input id="initialHistory" value="{history}">'
            ).encode()
        self.pages = [base[:25], base[25:]]
        self.page_calls = {}
        self.final_change = final_change

    def post(self, url, payload):
        page = int(payload["pageNo"])
        self.page_calls[page] = self.page_calls.get(page, 0) + 1
        entries = list(self.pages[page - 1])
        if self.final_change and page == 2 and self.page_calls[page] > 1:
            entries = [self.pages[0][-1]]
        data = {"requisitionList": entries,
                "pagingData": {"totalCount": 26, "pageSize": 25, "currentPageNo": page}}
        self.posts.append((url, payload))
        return HTTPResponse(200, json.dumps(data).encode(), {"Content-Type": "application/json"})

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

    def test_moxa_listing_260084_with_mismatched_detail_title_stays_partial(self):
        """The captured Moxa listing must not pass with a different detail title."""
        moxa_board = "https://tas-moxa.taleo.net/careersection/mx_ext/jobsearch.ftl?lang=en"
        responses = [
            search_page(portal="8115020123", code="mx_ext"),
            listing([entry("260084", "Captured Moxa listing title")], total=1),
            detail("Different detail title", "260084"),
            listing([entry("260084", "Captured Moxa listing title")], total=1),
        ]
        transport = Transport(responses)
        result = fetch_inventory("Oracle / Taleo", moxa_board, "COMP-0147", "Moxa", transport)
        self.assertEqual(result.status, "partial")
        self.assertTrue(any("posting" in message.casefold() or "title" in message.casefold()
                            for message in (result.reason,)))

    def test_moxa_captured_board_retrieves_all_12_and_decodes_ampersand_title(self):
        transport = MoxaCaptureTransport()
        result = fetch_inventory(
            "Oracle / Taleo",
            "https://tas-moxa.taleo.net/careersection/mx_ext/jobsearch.ftl?lang=en",
            "COMP-0147", "Moxa", transport)
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual(len(result.jobs), 12)
        self.assertEqual({job["posting_id"] for job in result.jobs}, {
            "260078", "26006N", "26006X", "26008D", "26007R", "260084",
            "260057", "26006W", "26006B", "26007L", "260076", "260011"})
        ampersand = next(job for job in result.jobs if job["posting_id"] == "260084")
        self.assertEqual(ampersand["title"], "Channel Sales Manager - Industrial Automation & Networking, Northeast")
        self.assertTrue(ampersand["description"])
        self.assertNotIn("Apply for this position online", ampersand["description"])
        self.assertGreaterEqual(len(transport.posts), 2)

    def test_moxa_captured_listing_title_mismatch_stays_partial(self):
        def mutate(kind, contest, data):
            if kind == "search":
                for item in data["requisitionList"]:
                    if item.get("contestNo") == "260084":
                        item["column"][0] = "Wrong title for captured detail"
            return data
        result = fetch_inventory(
            "Oracle / Taleo",
            "https://tas-moxa.taleo.net/careersection/mx_ext/jobsearch.ftl?lang=en",
            "COMP-0147", "Moxa", MoxaCaptureTransport(mutate=mutate))
        self.assertEqual(result.status, "partial")

    def test_moxa_26_job_second_page_and_final_recheck(self):
        source = "https://tas-moxa.taleo.net/careersection/mx_ext/jobsearch.ftl?lang=en"
        stable = MoxaPagedTransport()
        result = fetch_inventory("Oracle / Taleo", source, "COMP-0147", "Moxa", stable)
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual(len(result.jobs), 26)
        self.assertGreaterEqual(stable.page_calls[1], 2)
        self.assertGreaterEqual(stable.page_calls[2], 2)

        changed = MoxaPagedTransport(final_change=True)
        result = fetch_inventory("Oracle / Taleo", source, "COMP-0147", "Moxa", changed)
        self.assertEqual(result.status, "partial")

    def test_moxa_snapshot_identity_and_full_qualification_fields_are_required(self):
        source = "https://tas-moxa.taleo.net/careersection/mx_ext/jobsearch.ftl?lang=en"
        for change in ("internal_id", "contest", "title", "missing_qualifications", "inconsistent_pair"):
            with self.subTest(change=change):
                transport = MoxaCaptureTransport()
                model = transport.models["details"]["260084"]
                parts = list(model["initial_history"])
                if change == "internal_id": parts[5] = "999999"
                elif change == "contest": parts[13] = "OTHER"
                elif change == "title": parts[12] = "Other title"
                elif change == "missing_qualifications": parts[16] = parts[17] = "!*!"
                else: parts[17] += " unexpected change"
                history = html_escape("!|!".join(parts), quote=True)
                transport.details["260084"] = (
                    f'<meta property="og:title" content="{html_escape(model["meta_title"], quote=True)}">'
                    f'<input id="initialHistory" value="{history}">'
                ).encode()
                result = fetch_inventory("Oracle / Taleo", source, "COMP-0147", "Moxa", transport)
                self.assertEqual(result.status, "partial")
                self.assertEqual(len(result.jobs), 11)
                self.assertNotIn("260084", {job["posting_id"] for job in result.jobs})

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

    def test_textron_systems_scoped_page_wins_over_shared_parent_board(self):
        url = "https://www.textronsystems.com/careers/apply-today"
        pages = Transport([
            scoped_careers_page([("111", "Systems Engineer")], 2),
            scoped_careers_page([("222", "Program Manager")], 2, page=1),
            scoped_careers_page([("111", "Systems Engineer")], 2),
        ])
        result = fetch_inventory("Taleo", url, "COMP-0088", "Textron Systems", discovery_transport=pages)
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual([job["posting_id"] for job in result.jobs], ["111", "222"])
        self.assertEqual(result.source_url, url)
        self.assertEqual(result.ats, "Taleo")
        self.assertFalse(pages.posts)
        self.assertEqual(pages.urls, [url, url + "?page=1", url])


if __name__ == "__main__":
    unittest.main()
