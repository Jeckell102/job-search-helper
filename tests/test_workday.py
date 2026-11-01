import copy
from contextlib import redirect_stderr, redirect_stdout
from io import BytesIO, StringIO
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from job_search_helper.ats import FetchError, HTTPResponse, HTTPTransport, _safe_api_url, fetch_inventory, resolve_board
from job_search_helper.engine import Engine, State, _inventory_source
from job_search_helper.workday import _posting, _reconcile_changed_workday
from job_search_helper.repository import MemoryRepository
from test_ats import Transport, response
from test_discovery import html


BOARD = "https://acme.wd501.myworkdayjobs.com/en-US/Careers"
ROOT = "https://acme.wd501.myworkdayjobs.com/wday/cxs/acme/Careers"


def listing(number=1):
    return {"title": "Solutions Engineer", "externalPath": f"/job/Remote/Solutions-Engineer_REQ{number}",
            "locationsText": "2 Locations", "postedOn": "Posted Today", "bulletFields": [f"REQ{number}"]}


def detail(number=1):
    return {"jobPostingInfo": {"id": f"opaque-{number}", "jobPostingId": f"Solutions-Engineer_REQ{number}",
            "jobPostingSiteId": "Careers", "jobReqId": f"REQ{number}", "title": "Solutions Engineer",
            "jobDescription": "<p>Lead customer integrations.</p><p>Annual salary: $150,000-$180,000.</p>",
            "location": "Remote, US", "additionalLocations": ["Dayton, Ohio"],
            "remoteType": "Remote", "startDate": "2026-09-23", "posted": True}}


def page(total=1, entries=None, facets=None):
    return response({"total": total, "jobPostings": [listing()] if entries is None else entries,
                     "facets": facets or []})


class WorkdayTransport(Transport):
    def __init__(self, responses):
        super().__init__(responses)
        self.posts = []

    def post(self, url, payload):
        self.posts.append((url, copy.deepcopy(payload)))
        return self.get(url)


class WorkdayTests(unittest.TestCase):
    def fetch(self, responses, url=BOARD, ats="Workday", pages=None):
        t = WorkdayTransport(responses)
        result = fetch_inventory(ats, url, "C-1", "Acme", t, discovery_transport=pages or Transport([]))
        return result, t

    def test_missing_detail_does_not_discard_later_jobs_or_claim_complete(self):
        result, t = self.fetch([page(2, [listing(1), listing(2)]),
                                HTTPResponse(404, b"missing"), response(detail(2))])
        self.assertEqual(result.status, "partial")
        self.assertEqual([j["req_id"] for j in result.jobs], ["REQ2"])
        self.assertIn("404", result.reason)
        self.assertEqual(len(t.urls), 3)

    def test_access_denial_stops_detail_requests(self):
        result, t = self.fetch([page(2, [listing(1), listing(2)]),
                                HTTPResponse(403, b"denied"), response(detail(2))])
        self.assertEqual(result.status, "blocked")
        self.assertFalse(result.jobs)
        self.assertEqual(len(t.urls), 2)

    def test_final_access_denial_does_not_retry_reconciliation(self):
        with patch("job_search_helper.workday.PAGE_SIZE", 1):
            result, t = self.fetch([page(2), page(0, [listing(2)]), response(detail()),
                                    response(detail(2)), HTTPResponse(403, b"denied")])
        self.assertEqual(result.status, "blocked")
        self.assertEqual([job["req_id"] for job in result.jobs], ["REQ1", "REQ2"])
        self.assertEqual(len(t.posts), 3)

    def test_resolves_locale_jobs_detail_and_api_urls(self):
        for url in (BOARD, BOARD + "/jobs", BOARD + listing()["externalPath"], ROOT, ROOT + "/jobs"):
            with self.subTest(url=url):
                self.assertEqual(resolve_board("Workday", url), ("Workday", "Careers", ROOT.removesuffix("Careers")))

    def test_full_details_and_stable_identity(self):
        result, t = self.fetch([page(), response(detail())])
        self.assertEqual(result.status, "complete", result.reason)
        row = result.jobs[0]
        self.assertEqual(row["posting_id"], "opaque-1")
        self.assertEqual(row["req_id"], "REQ1")
        self.assertIn("Lead customer integrations.", row["description"])
        self.assertIn("$150,000", row["description"])
        self.assertEqual(row["location"], "Remote, US; Dayton, Ohio")
        self.assertEqual(row["work_arrangement"], "Remote")
        self.assertEqual(row["created_at"], "2026-09-23")
        self.assertEqual(row["updated_at"], "")
        self.assertEqual(row["url"], BOARD.replace("/en-US", "") + listing()["externalPath"])
        self.assertEqual(t.urls, [ROOT + "/jobs", ROOT + listing()["externalPath"]])

    def test_pagination_uses_initial_total_when_later_pages_report_zero(self):
        with patch("job_search_helper.workday.PAGE_SIZE", 1):
            result, t = self.fetch([page(2), page(0, [listing(2)]), response(detail()),
                                    response(detail(2)), page(2), page(0, [listing(2)])])
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual(len(result.jobs), 2)
        self.assertEqual([body["offset"] for _, body in t.posts], [0, 1, 0, 1])

    def test_listings_finish_before_detail_delay_can_shift_pages(self):
        class MovingTransport:
            def __init__(self): self.detail_started = False; self.listing_calls = []
            def post(self, url, payload):
                self.listing_calls.append(payload['offset'])
                if payload['offset']:
                    return page(0, [listing(2)])
                return page(2)
            def get(self, url):
                self.detail_started = True
                return response(detail(2 if url.endswith('REQ2') else 1))
        with patch('job_search_helper.workday.PAGE_SIZE', 1):
            transport = MovingTransport()
            result = fetch_inventory('Workday', BOARD, 'C-1', 'Acme', transport)
        self.assertEqual(result.status, 'complete', result.reason)
        self.assertEqual([j['posting_id'] for j in result.jobs], ['opaque-1', 'opaque-2'])
        self.assertEqual(transport.listing_calls[:2], [0, 1])

    def test_scoped_search_is_preserved_in_request_and_inventory_identity(self):
        result, t = self.fetch([page(0, [])], url=BOARD + "/jobs?q=Design+Group&utm_source=example",
                               ats="Workday (shared parent board)")
        self.assertEqual(result.status, "complete")
        self.assertEqual(t.posts[0][1]["searchText"], "Design Group")
        self.assertEqual(result.source_url, ROOT + "?q=Design+Group")
        self.assertEqual(_inventory_source(result.source_url), _inventory_source(BOARD + "?q=Design+Group"))
        self.assertNotEqual(_inventory_source(result.source_url), _inventory_source(BOARD))

    def test_validates_nested_facets_and_preserves_multiple_values(self):
        facets = [{"facetParameter": "locationMainGroup", "values": [
            {"facetParameter": "locations", "values": [{"id": "a"}, {"id": "b"}]}]}]
        result, t = self.fetch([page(2, [listing(), listing(2)], facets), page(0, [])],
                               url=BOARD + "?locations=b&locations=a&q=Design")
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual(t.posts[0][1]["appliedFacets"], {})
        self.assertEqual(t.posts[0][1]["searchText"], "")
        self.assertEqual(t.posts[1][1]["appliedFacets"], {"locations": ["a", "b"]})
        self.assertEqual(t.posts[1][1]["searchText"], "Design")
        self.assertEqual(result.source_url, ROOT + "?locations=a&locations=b&q=Design")

    def test_unknown_or_stale_filter_never_silently_becomes_full_board(self):
        for query in ("unknown=x", "locations=stale"):
            result, t = self.fetch([page(0, [])], url=BOARD + "?" + query)
            self.assertEqual(result.status, "unsupported")
            self.assertIn("filter", result.reason)
            self.assertEqual(len(t.posts), 1)

    def test_known_invalid_boards_do_not_fall_back_to_html(self):
        for url, ats in ((BOARD, "Lever"), (BOARD, "Workday shared parent"),
                         (BOARD + "?locations=", "Workday"),
                         (BOARD + "?q=one&q=two", "Workday"),
                         (ROOT.replace("/cxs/acme/", "/cxs/other/"), "Workday"),
                         ("https://acme.wd501.myworkdayjobs.com/en-US", "Workday"),
                         (BOARD + "/login", "Workday")):
            with self.subTest(url=url, ats=ats):
                pages = Transport([])
                result, t = self.fetch([], url=url, ats=ats, pages=pages)
                self.assertEqual(result.status, "unsupported")
                self.assertFalse(t.urls or pages.urls)

    def test_listing_schema_count_and_early_empty_page_fail_closed(self):
        for responses in ([response({})], [page(True, [])], [page(0)],
                          [page(2), page(0, []), response(detail())]):
            result, _ = self.fetch(responses)
            self.assertEqual(result.status, "partial", result.reason)

    def test_repeated_page_does_not_fetch_duplicate_details(self):
        with patch("job_search_helper.workday.PAGE_SIZE", 1):
            result, t = self.fetch([page(2), page(0), response(detail())])
        self.assertEqual(result.status, "partial")
        self.assertEqual(len(result.jobs), 1)
        self.assertIn("repeated", result.reason)
        self.assertEqual(len(t.urls), 3)

    def test_count_change_first_page_change_and_page_cap_are_partial(self):
        with patch("job_search_helper.workday.PAGE_SIZE", 1):
            for responses in ([page(2), page(3, [listing(2)]), response(detail())],
                              [page(2), page(0, [listing(2)]), response(detail()), response(detail(2)),
                               page(2, [listing(3)]), page(0, [listing(2)]),
                               page(2, [listing(3)]), page(0, [listing(2)]), response({})]):
                result, _ = self.fetch(responses)
                self.assertEqual(result.status, "partial")
            with patch("job_search_helper.workday.MAX_PAGES", 1):
                result, _ = self.fetch([page(2), response(detail())])
                self.assertEqual(result.status, "partial")
                self.assertIn("cap", result.reason)

    def test_missing_or_unpublished_detail_prevents_complete_inventory(self):
        for change in ({"jobDescription": ""}, {"id": None}, {"posted": False},
                       {"jobPostingSiteId": "Other"}, {"additionalLocations": "Remote"}, {"jobDescription": {"text": "Broken"}}):
            data = detail()
            data["jobPostingInfo"].update(change)
            with redirect_stderr(StringIO()):
                result, _ = self.fetch([page(), response(data)])
            self.assertEqual(result.status, "partial")
            self.assertFalse(result.jobs)

    def test_no_arbitrary_paths_or_hosts_are_fetched_from_listings(self):
        for path in ("https://evil.example/job/x", "//evil.example/x", "/job/../apply", "/job/%2e%2e/apply",
                     "/job/%252e%252e/apply", "/job/x?redirect=evil", "/job/x#fragment", "/job/x\\apply", "/login"):
            with self.subTest(path=path), redirect_stderr(StringIO()):
                result, t = self.fetch([page(entries=[{**listing(), "externalPath": path}])])
                self.assertEqual(result.status, "partial")


    def test_late_http_failure_keeps_jobs_without_claiming_complete(self):
        for code, status in ((403, "blocked"), (429, "partial"), (500, "partial"), (404, "partial")):
            result, _ = self.fetch([page(2, [listing(), listing(2)]), response(detail()), response({}, code)])
            self.assertEqual(result.status, status)
            self.assertEqual(len(result.jobs), 1)
            self.assertIn(str(code), result.reason)

    def test_empty_board_and_challenge(self):
        result, _ = self.fetch([page(0, [])])
        self.assertEqual(result.status, "complete")
        result, _ = self.fetch([HTTPResponse(200, b"<html>Verify you are human</html>")])
        self.assertEqual(result.status, "blocked")

    def test_careers_link_and_redirect_preserve_workday_scope(self):
        for page_response in (html(f'<a href="{BOARD}?q=Acme">Jobs</a>'),
                              html("", 302, Location=BOARD + "?q=Acme")):
            pages = Transport([page_response])
            result, t = self.fetch([page(0, [])], url="https://acme.example/careers", pages=pages)
            self.assertEqual(result.status, "complete", result.reason)
            self.assertEqual(t.posts[0][1]["searchText"], "Acme")
            self.assertIn("Discovered Workday", result.reason)

    def test_multiple_workday_scopes_need_explicit_selection(self):
        pages = Transport([html(f'<a href="{BOARD}?q=Acme">A</a><a href="{BOARD}?q=Other">B</a>')])
        result, _ = self.fetch([], url="https://acme.example/careers", pages=pages)
        self.assertEqual(result.status, "unsupported")
        self.assertIn("Multiple", result.reason)

    def test_endpoint_allowlist_and_post_restriction(self):
        for url in (ROOT + "/apply", ROOT.replace("/cxs/acme/", "/cxs/other/") + "/jobs",
                    ROOT.replace(".com/", ".com.evil.example/") + "/jobs",
                    ROOT + "/job/../apply", ROOT + "/jobs?redirect=anything"):
            with self.subTest(url=url), self.assertRaises(FetchError):
                _safe_api_url(url)
        _safe_api_url(ROOT + "/jobs")
        _safe_api_url(ROOT + listing()["externalPath"])
        with self.assertRaises(FetchError):
            HTTPTransport().post("https://api.lever.co/v0/postings/acme", {})

    def test_post_retries_keep_search_body_and_json_content_type(self):
        requests = []
        class Opener:
            def open(self, request, timeout):
                requests.append(request)
                raise HTTPError(request.full_url, 429, "Rate limited", {}, BytesIO(b""))
        transport = HTTPTransport(sleep=lambda _: None)
        transport.opener = Opener()
        payload = {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": "Acme"}
        response = transport.post(ROOT + "/jobs", payload)
        self.assertEqual(response.status, 429)
        self.assertEqual(len(requests), 3)
        for request in requests:
            self.assertEqual(request.get_method(), "POST")
            self.assertEqual(json.loads(request.data), payload)
            self.assertEqual(request.get_header("Content-type"), "application/json")


class WorkdayReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.endpoint = ROOT
        self.payload = {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": ""}
        self.host = "acme.wd501.myworkdayjobs.com"
        self.old = [_posting(detail(1), listing(1)["externalPath"], "Careers", self.host, "C-1", "Acme"),
                    _posting(detail(2), listing(2)["externalPath"], "Careers", self.host, "C-1", "Acme")]

    def reconcile(self, entries, total, detail_numbers=(), *, second_entries=None, second_total=None):
        first = response({"total": total, "jobPostings": entries})
        second = response({"total": total if second_total is None else second_total,
                           "jobPostings": entries if second_entries is None else second_entries})
        details = [response(detail(n)) for n in detail_numbers]
        # Reconciliation now fetches any new details before its mandatory
        # all-pages post-detail reread; keep the second listing response last.
        transport = WorkdayTransport([first, *details, second])
        return _reconcile_changed_workday(self.endpoint, self.payload, 2, "Careers", self.host,
                                          "C-1", "Acme", transport, self.old,
                                          {listing(n)["externalPath"]: listing(n) for n in (1, 2)})

    def test_addition_reuses_old_rows_and_fetches_new_detail(self):
        jobs, issue = self.reconcile([listing(1), listing(2), listing(3)], 3, [3])
        self.assertIn("reconciled cohort", issue)
        self.assertEqual([job["req_id"] for job in jobs], ["REQ1", "REQ2", "REQ3"])

    def test_removal_uses_stable_refreshed_cohort_without_union(self):
        jobs, issue = self.reconcile([listing(1)], 1)
        self.assertIn("reconciled cohort", issue)
        self.assertEqual([job["req_id"] for job in jobs], ["REQ1"])

    def test_same_count_substitution_fetches_only_new_detail(self):
        jobs, issue = self.reconcile([listing(1), listing(3)], 2, [3])
        self.assertIn("reconciled cohort", issue)
        self.assertEqual([job["req_id"] for job in jobs], ["REQ1", "REQ3"])

    def test_second_pass_count_drift_fails_closed(self):
        jobs, issue = self.reconcile([listing(1), listing(2)], 2,
                                     second_entries=[listing(1), listing(2), listing(3)], second_total=3)
        self.assertIsNone(jobs)
        self.assertIn("changed", issue)

    def test_duplicate_refresh_fails_closed(self):
        jobs, issue = self.reconcile([listing(1), listing(1)], 2)
        self.assertIsNone(jobs)
        self.assertIn("repeated", issue)

    def test_new_detail_failure_fails_closed(self):
        first = response({"total": 2, "jobPostings": [listing(1), listing(3)]})
        second = response({"total": 2, "jobPostings": [listing(1), listing(3)]})
        transport = WorkdayTransport([first, second, HTTPResponse(404, b"missing")])
        jobs, issue = _reconcile_changed_workday(self.endpoint, self.payload, 2, "Careers", self.host,
                                                  "C-1", "Acme", transport, self.old,
                                                  {listing(n)["externalPath"]: listing(n) for n in (1, 2)})
        self.assertIsNone(jobs)
        self.assertIn("could not be verified", issue)


class WorkdayEngineTests(unittest.TestCase):
    def setUp(self):
        classifier = patch("job_search_helper.engine.classify_title", return_value="review")
        classifier.start()
        self.addCleanup(classifier.stop)
        self.company = {"Company": "Acme", "Company ID": "C-1", "Company Status": "Active",
                        "ATS / Source": "Workday", "Official Careers URL": BOARD,
                        "Blocked Reason": "No supported, verified ATS board URL"}
        self.repo = MemoryRepository({"Companies": [self.company]})
        self.state = State()
        self.addCleanup(self.state.close)
        self.inventory = fetch_inventory("Workday", BOARD, "C-1", "Acme",
                                         WorkdayTransport([page(), response(detail())]))
        self.engine = Engine(self.repo, self.state, fetcher=lambda *args: self.inventory)

    def scan(self):
        with redirect_stdout(StringIO()):
            cycle = self.engine.start_cycle(["C-1"])
            self.engine.resume(cycle)

    def test_complete_inventory_advances_dates_and_clears_old_reason(self):
        self.scan()
        company = self.repo.read("Companies")[0]
        self.assertTrue(company["Last Checked"])
        self.assertTrue(company["Last Successful Scan"])
        self.assertEqual(company["Blocked Reason"], "")

    def test_incomplete_inventory_does_not_advance_last_checked(self):
        self.inventory = fetch_inventory("Workday", BOARD, "C-1", "Acme", WorkdayTransport([response({}, 403)]))
        self.scan()
        company = self.repo.read("Companies")[0]
        self.assertFalse(company.get("Last Checked"))
        self.assertIn("403", company["Blocked Reason"])

    def test_changed_search_scope_cannot_close_previous_scope_jobs(self):
        self.inventory = fetch_inventory("Workday", BOARD + "?q=Acme", "C-1", "Acme",
                                         WorkdayTransport([page(), response(detail())]))
        self.scan()
        original = self.repo.read("Job History")[0]
        self.inventory = fetch_inventory("Workday", BOARD + "?q=Other", "C-1", "Acme",
                                         WorkdayTransport([page(0, [])]))
        self.scan()
        history = self.repo.read("Job History")[0]
        self.assertEqual(history, original)


if __name__ == "__main__":
    unittest.main()
