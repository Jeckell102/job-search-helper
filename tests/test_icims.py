from contextlib import redirect_stdout, redirect_stderr
from html import escape
from io import BytesIO, StringIO
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

from job_search_helper.ats import FetchError, HTTPTransport, Inventory, _safe_api_url, fetch_inventory, resolve_board
from job_search_helper.engine import Engine, State, _inventory_source
from job_search_helper.repository import MemoryRepository
from job_search_helper.screening import screen_posting
from test_ats import Transport, response
from test_discovery import html


ROOT = "https://careers-acme.icims.com"
BOARD = ROOT + "/jobs/search"


def job_url(ident=1):
    return ROOT + f"/jobs/{ident}/solutions-engineer/job"


def listing(ids=(1,), page=1, pages=1, scope="", next_url=None, options=""):
    canonical = BOARD + ("?" + scope if scope else "")
    next_link = ""
    if page < pages:
        next_url = next_url or BOARD + f"?pr={page}" + ("&" + scope if scope else "")
        next_link = f'<link rel="next" href="{escape(next_url, quote=True)}">'
    body = f'<link rel="canonical" href="{escape(canonical, quote=True)}">{next_link}'
    body += f'<div class="iCIMS_ListingsPage"><form id="searchForm">{options}</form>'
    if ids:
        body += f'<h2 class="iCIMS_SubHeader_Jobs">Search Results Page {page} of {pages}</h2>'
        body += '<ul class="iCIMS_JobsTable">'
        for ident in ids:
            body += f'<li class="iCIMS_JobCardItem"><div><a href="{job_url(ident)}?in_iframe=1">Solutions Engineer</a></div></li>'
        body += '</ul>'
    else:
        body += '<div class="iCIMS_GenericMessage">Sorry, no jobs were found that match your search criteria. Please try other selections.</div>'
    return html(body + '</div>')


def detail(ident=1, **changes):
    item = {"@type": "JobPosting", "url": job_url(ident), "title": "Solutions Engineer",
            "description": "<h2>Responsibilities</h2><p>Lead customer integrations.</p><p>Travel 20%.</p>",
            "identifier": {"@type": "PropertyValue", "value": f"2026-{ident}"},
            "jobLocation": [{"address": {"addressLocality": "Dayton", "addressRegion": "OH", "addressCountry": "US"}},
                            {"address": {"addressLocality": "Reston", "addressRegion": "VA", "addressCountry": "US"}}],
            "jobLocationType": "TELECOMMUTE", "datePosted": "2026-09-23", "occupationalCategory": "Engineering",
            "baseSalary": {"currency": "USD", "value": {"minValue": 140000, "maxValue": 180000, "unitText": "YEAR"}}}
    item.update(changes)
    return html('<script type="application/ld+json">' + json.dumps(item) + '</script>')


class IcimsTests(unittest.TestCase):
    def setUp(self):
        capture = redirect_stderr(StringIO())
        capture.__enter__()
        self.addCleanup(capture.__exit__, None, None, None)

    def fetch(self, responses, url=BOARD, ats="iCIMS", pages=None):
        transport = Transport(responses)
        result = fetch_inventory(ats, url, "C-1", "Acme", transport, discovery_transport=pages or Transport([]))
        return result, transport

    def test_intro_detail_root_and_search_resolve_to_same_inventory(self):
        for url in (ROOT, ROOT + "/jobs/", ROOT + "/jobs/intro?hashed=-435", BOARD + "?ss=1&pr=4", job_url()):
            with self.subTest(url=url):
                self.assertEqual(resolve_board("iCIMS", url), ("iCIMS", "search", ROOT + "/jobs/"))

    def test_percent_sign_in_job_slug_resolves(self):
        url = ROOT + "/jobs/11551/network-technician-%28up-to-75%25-conus-oconus-travel%29/job"
        self.assertEqual(resolve_board("iCIMS", url), ("iCIMS", "search", ROOT + "/jobs/"))

    def test_full_descriptions_locations_stable_id_and_salary(self):
        result, t = self.fetch([listing(), detail()])
        self.assertEqual(result.status, "complete", result.reason)
        row = result.jobs[0]
        self.assertEqual(row["posting_id"], "1")
        self.assertEqual(row["req_id"], "2026-1")
        self.assertIn("Lead customer integrations.", row["description"])
        self.assertIn("Travel 20%", row["description"])
        self.assertEqual(row["location"], "Dayton, OH, US; Reston, VA, US")
        self.assertEqual(row["work_arrangement"], "Remote")
        self.assertEqual(row["department"], "Engineering")
        self.assertEqual(row["created_at"], "2026-09-23")
        self.assertIn("180000", row["compensation"])
        self.assertEqual(row["url"], job_url())
        self.assertEqual(parse_qs(urlsplit(t.urls[0]).query)["in_iframe"], ["1"])

    def test_salary_range_with_yr_abbreviation_keeps_crossing_range(self):
        salary = (
            "<p>Salary Statement</p><p>Estimated Starting Salary Range: "
            "USD $75,650.00/Yr. - USD $126,050.00/Yr. "
            "Salary to be determined by experience.</p>"
        )
        result, _ = self.fetch([
            listing(),
            detail(
                description=salary + "<p>Lead customer integrations.</p>",
                baseSalary={"currency": "USD", "value": 75650, "unitText": "YEAR"},
            ),
        ])
        self.assertEqual(result.status, "complete")
        self.assertIsNone(screen_posting(result.jobs[0]).reason)

    def test_paginates_all_advertised_pages_and_rechecks_first(self):
        first = listing((1, 2), pages=2)
        result, t = self.fetch([first, detail(1), detail(2), listing((3,), page=2, pages=2), detail(3), first])
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual([job["posting_id"] for job in result.jobs], ["1", "2", "3"])
        self.assertEqual([parse_qs(urlsplit(url).query)["pr"] for url in t.urls if "/search?" in url], [["0"], ["1"], ["0"]])

    def test_keyword_scope_preserved_and_tracking_removed(self):
        scope = "searchKeyword=Design+Group&searchRelation=keyword_all"
        result, t = self.fetch([listing(scope=scope), detail()], url=BOARD + "?" + scope + "&hashed=9&width=1000&pr=2",
                               ats="iCIMS shared parent board")
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual(result.source_url, BOARD + "?" + scope)
        self.assertEqual(parse_qs(urlsplit(t.urls[0]).query)["searchKeyword"], ["Design Group"])
        self.assertEqual(_inventory_source(result.source_url), result.source_url)
        self.assertNotEqual(_inventory_source(result.source_url), _inventory_source(BOARD))

    def test_valid_facet_and_stale_facet(self):
        options = '<select name="searchCompany"><option value="42">Acme</option></select>'
        result, _ = self.fetch([listing(scope="searchCompany=42", options=options), detail()], url=BOARD + "?searchCompany=42")
        self.assertEqual(result.status, "complete", result.reason)
        result, t = self.fetch([listing(scope="searchCompany=bad", options=options)], url=BOARD + "?searchCompany=bad")
        self.assertEqual(result.status, "unsupported")
        self.assertEqual(len(t.urls), 1)

    def test_canonical_scope_loss_cannot_be_complete_or_fetch_details(self):
        result, t = self.fetch([listing()], url=BOARD + "?searchKeyword=Acme")
        self.assertEqual(result.status, "partial")
        self.assertIn("scope", result.reason)
        self.assertEqual(len(t.urls), 1)

    def test_verified_empty_not_arbitrary_page_or_javascript_phrase(self):
        result, _ = self.fetch([listing(ids=())])
        self.assertEqual(result.status, "complete")
        contradictory = listing(ids=())
        contradictory.body += b'<h2 class="iCIMS_SubHeader_Jobs">Page 1 of 2</h2>'
        result, _ = self.fetch([contradictory])
        self.assertEqual(result.status, "partial")
        for body in ('<html>Maintenance</html>', '<script>Sorry, no jobs were found that match your search criteria. Please try other selections.</script>',
                     '<div class="iCIMS_ListingsPage"><form id="searchForm"></form></div>'):
            result, _ = self.fetch([html(body)])
            self.assertEqual(result.status, "partial")

    def test_missing_page_and_repeated_or_changed_page_stay_partial(self):
        first = listing(pages=2)
        for later in (listing(ids=()), listing((2,), pages=2), listing((1,), page=2, pages=2), listing((2,), page=2, pages=3)):
            result, _ = self.fetch([first, detail(), later])
            self.assertEqual(result.status, "partial")
            self.assertEqual(len(result.jobs), 1)
        result, _ = self.fetch([first, detail(), listing((2,), page=2, pages=2), detail(2), listing((3,), pages=2)])
        self.assertEqual(result.status, "partial")
        self.assertIn("changed", result.reason)

    def test_page_cap_and_unsafe_next_page(self):
        with patch("job_search_helper.icims.MAX_PAGES", 1):
            result, _ = self.fetch([listing(pages=2), detail()])
            self.assertEqual(result.status, "partial")
            self.assertIn("cap", result.reason)
        for url in ("https://evil.example/jobs/search?pr=1", BOARD + "?pr=9", BOARD + "?pr=1&searchKeyword=Other"):
            result, t = self.fetch([listing(pages=2, next_url=url)])
            self.assertEqual(result.status, "partial")
            self.assertEqual(len(t.urls), 1)

    def test_missing_malformed_or_mismatched_description_keeps_earlier_jobs(self):
        for bad in (detail(2, description=""), detail(2, description={"text": "Broken"}), detail(3),
                    html('<script type="application/ld+json">{invalid}</script>'), html('<h1>Job unavailable</h1>')):
            result, _ = self.fetch([listing((1, 2)), detail(), bad])
            self.assertEqual(result.status, "partial")
            self.assertEqual(len(result.jobs), 1)
            self.assertIn("job detail", result.reason)

    def test_job_graph_and_single_location_object(self):
        original = json.loads(detail(jobLocation={"address": {"addressLocality": "Dayton"}}).body.decode().split('>', 1)[1].split('</script>')[0])
        data = html('<script type="application/ld+json">' + json.dumps({"@graph": [{"@type": "Organization"}, original]}) + '</script>')
        result, _ = self.fetch([listing(), data])
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual(result.jobs[0]["location"], "Dayton")

    def test_blocked_transient_and_redirect_failures(self):
        for code, expected in ((403, "blocked"), (401, "blocked"), (429, "partial"), (500, "partial"), (302, "partial")):
            result, _ = self.fetch([listing((1, 2)), detail(), html("unavailable", code)])
            self.assertEqual(result.status, expected)
            self.assertEqual(len(result.jobs), 1)
            self.assertIn(str(code), result.reason)
        result, _ = self.fetch([html('<title>Just a moment</title>Verify you are human')])
        self.assertEqual(result.status, "blocked")

    def test_rejects_unknown_filters_login_urls_and_ats_mismatches_without_network(self):
        for url, ats in ((BOARD + "?unknown=x", "iCIMS"), (ROOT + "/jobs/login", "iCIMS"),
                         (job_url() + "?mode=apply", "iCIMS"), (BOARD, "Workday"),
                         (BOARD, "iCIMS parent board"), (BOARD + "?searchKeyword=x&searchKeyword=y", "iCIMS")):
            result, t = self.fetch([], url=url, ats=ats)
            self.assertEqual(result.status, "unsupported", url)
            self.assertFalse(t.urls)
        self.assertEqual(fetch_inventory("iCIMS", "https://acme.wd1.myworkdayjobs.com/Careers", "C", "Acme", Transport([])).status, "unsupported")

    def test_api_allowlist_stops_application_actions_and_lookalike_hosts(self):
        for url in (job_url() + "?mode=apply", job_url() + "?apply=", ROOT + "/jobs/login", ROOT + "/jobs/1/../job",
                    ROOT + "/jobs/1/%2e%2e/job", ROOT + "/jobs/1/%252e%252e/job",
                    BOARD.replace(".com", ".com.evil.example"), BOARD + "?apply=yes"):
            with self.subTest(url=url), self.assertRaises(FetchError):
                _safe_api_url(url)
        _safe_api_url(BOARD + "?in_iframe=1&pr=0")
        _safe_api_url(job_url() + "?in_iframe=1")
        with self.assertRaises(FetchError):
            HTTPTransport().post(BOARD, {})

    def test_cross_host_detail_link_does_not_get_requested(self):
        data = listing()
        data.body = data.body.replace(job_url().encode(), b"https://evil.example/jobs/1/fake/job")
        result, t = self.fetch([data])
        self.assertEqual(result.status, "partial")
        self.assertEqual(len(t.urls), 1)

    def test_discovers_portal_links_and_redirects_without_losing_scope(self):
        url = BOARD + "?searchKeyword=Acme"
        for page in (html(f'<iframe src="{url}"></iframe>'), html("", 302, Location=url)):
            result, _ = self.fetch([listing(scope="searchKeyword=Acme"), detail()], url="https://acme.example/careers", pages=Transport([page]))
            self.assertEqual(result.status, "complete", result.reason)
            self.assertIn("Discovered iCIMS", result.reason)

    def test_transport_retries_regular_html_errors_but_not_challenges(self):
        for content, expected_calls in ((b"<html>Maintenance; application CAPTCHA unavailable</html>", 3),
                                        (b"<title>Just a moment</title>Verify you are human", 1)):
            class Opener:
                calls = 0
                def open(self, request, timeout):
                    self.calls += 1
                    raise HTTPError(request.full_url, 503, "Unavailable", {}, BytesIO(content))
            t = HTTPTransport(sleep=lambda _: None)
            t.opener = Opener()
            t.get(BOARD)
            self.assertEqual(t.opener.calls, expected_calls)


class IcimsEngineTests(unittest.TestCase):
    def setUp(self):
        title = patch("job_search_helper.engine.classify_title", return_value="review")
        title.start()
        self.addCleanup(title.stop)
        self.repo = MemoryRepository({"Companies": [{"Company": "Acme", "Company ID": "C-1", "Company Status": "Active",
                         "ATS / Source": "iCIMS", "Official Careers URL": BOARD, "Blocked Reason": "Unsupported ATS"}]})
        self.state = State()
        self.addCleanup(self.state.close)
        with redirect_stderr(StringIO()):
            self.inventory = fetch_inventory("iCIMS", BOARD, "C-1", "Acme", Transport([listing(), detail()]))
        self.engine = Engine(self.repo, self.state, fetcher=lambda *args: self.inventory)

    def scan(self):
        with redirect_stdout(StringIO()):
            cycle = self.engine.start_cycle(["C-1"])
            self.engine.resume(cycle)

    def test_success_updates_dates_and_clears_block_reason(self):
        self.scan()
        company = self.repo.read("Companies")[0]
        self.assertTrue(company["Last Checked"])
        self.assertTrue(company["Last Successful Scan"])
        self.assertEqual(company["Blocked Reason"], "")

    def test_changed_filter_or_incomplete_scan_does_not_close_previous_jobs(self):
        self.scan()
        original = self.repo.read("Job History")[0]
        checked = self.repo.read("Companies")[0]["Last Successful Scan"]
        self.inventory = Inventory("partial", [], "Missing iCIMS page", BOARD)
        self.scan()
        self.assertEqual(self.repo.read("Companies")[0]["Last Successful Scan"], checked)
        self.inventory = Inventory("complete", [], source_url=BOARD + "?searchCompany=42")
        self.scan()
        self.scan()
        self.assertEqual(self.repo.read("Job History")[0], original)


if __name__ == "__main__":
    unittest.main()
