from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import unittest
from unittest.mock import patch

from job_search_helper.ats import FetchError, HTTPResponse, HTTPTransport, Inventory, _safe_api_url, fetch_inventory, resolve_board
from job_search_helper.paylocity import ROOT, DETAIL
from job_search_helper.engine import Engine, State, _inventory_source
from job_search_helper.repository import MemoryRepository
from test_ats import Transport
from test_discovery import html


CID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
OTHER = "bbbbbbbb-bbbb-cccc-dddd-eeeeeeeeeeee"
BOARD = ROOT + CID


def entry(number=1):
    return {"JobId": number, "JobTitle": "Solutions Engineer", "IsInternal": False,
            "Description": "Short excerpt", "LocationName": "Remote", "IsRemote": True,
            "PublishedDate": "2026-09-23", "HiringDepartment": "Engineering"}


def listing(items=None, cid=CID, **changes):
    data = {"Jobs": [entry()] if items is None else items, "ShowInternal": False, "ModuleId": "123",
            "LeadJoinUrl": "/Recruiting/PublicLeads/New/" + cid}
    data.update(changes)
    return html(f'<meta property="og:url" content="{ROOT}{cid}/Acme">'
                '<script>window.pageData = ' + json.dumps(data) + ';</script>')


def detail(number=1, cid=CID, description="<p>Full duties <strong>and responsibilities</strong>.</p>", title="Solutions Engineer"):
    return html(f'<meta property="og:url" content="{DETAIL}{number}">'
                f'<a href="{ROOT}{cid}/Acme">All Jobs</a><a href="/Recruiting/Jobs/Apply/{number}">Apply</a>'
                f'<span class="job-preview-title left"><span>{title}</span></span>'
                '<div class="preview-location">Fully Remote <span>&bull;</span> US</div>'
                '<div class="job-preview-details"><div class="vertical-padding">'
                '<div class="job-listing-header">Job Type</div><div>Full-time</div></div>'
                f'<div class="job-listing-header">Description</div><div>{description}</div>'
                '<div class="job-listing-header">Requirements</div><div><ul><li>Travel 20%.</li></ul></div>'
                '<div class="job-listing-header">Salary Description</div><div>$140,000 - $180,000 annually</div>'
                '</div><footer>Not part of description</footer><script>doNotExecute()</script>')


class PaylocityTests(unittest.TestCase):
    def setUp(self):
        capture = redirect_stderr(StringIO())
        capture.__enter__()
        self.addCleanup(capture.__exit__, None, None, None)

    def fetch(self, responses, url=BOARD, ats="Paylocity", pages=None):
        transport = Transport(responses)
        result = fetch_inventory(ats, url, "C-1", "Acme", transport, discovery_transport=pages or Transport([]))
        return result, transport

    def test_case_slug_and_tracking_canonicalize_to_uuid(self):
        for url in (BOARD, BOARD + "/Acme", BOARD.lower() + "/Acme/", ROOT + CID.upper() + "?utm_source=site"):
            self.assertEqual(resolve_board("Paylocity", url), ("Paylocity", CID, ROOT))
            self.assertEqual(_inventory_source(url), BOARD)
        self.assertNotEqual(_inventory_source(BOARD), _inventory_source(ROOT + OTHER))

    def test_full_inventory_and_requirements_salary_without_application_requests(self):
        result, transport = self.fetch([listing(), detail(), listing()])
        self.assertEqual(result.status, "complete", result.reason)
        job = result.jobs[0]
        self.assertEqual(job["posting_id"], "1")
        self.assertEqual(job["title"], "Solutions Engineer")
        self.assertIn("Full duties and responsibilities.", job["description"])
        self.assertIn("Travel 20%.", job["description"])
        self.assertNotIn("Not part", job["description"])
        self.assertNotIn("Short excerpt", job["description"])
        self.assertEqual(job["work_arrangement"], "Remote")
        self.assertIn("annually", job["compensation"])
        self.assertIn("US", job["location"])
        self.assertEqual(job["department"], "Engineering")
        self.assertEqual(job["created_at"], "2026-09-23")
        self.assertEqual(transport.urls, [BOARD, DETAIL + "1", BOARD])

    def test_multiple_jobs_and_reordered_final_list(self):
        result, transport = self.fetch([listing([entry(2), entry(1)]), detail(1), detail(2), listing([entry(1), entry(2)])])
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual([job["posting_id"] for job in result.jobs], ["1", "2"])
        self.assertEqual(len(transport.urls), 4)

    def test_empty_requires_explicit_valid_inventory_and_recheck(self):
        result, transport = self.fetch([listing([]), listing([])])
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual(result.jobs, [])
        self.assertEqual(len(transport.urls), 2)
        for data in (html(""), html("maintenance"), listing(Jobs=None), listing(ModuleId=""), listing(ShowInternal=True)):
            result, _ = self.fetch([data])
            self.assertEqual(result.status, "partial")

    def test_job_ids_must_be_unique_positive_integers_and_external(self):
        for items in ([entry(), entry()], [dict(entry(), JobId=True)], [dict(entry(), JobId=0)],
                      [dict(entry(), JobId="1")], [dict(entry(), IsInternal=True)], [dict(entry(), JobTitle=None)], [None]):
            result, _ = self.fetch([listing(items)])
            self.assertEqual(result.status, "partial")

    def test_board_identity_must_match_embedded_and_meta_data(self):
        for page in (listing(cid=OTHER), listing(LeadJoinUrl="/Recruiting/PublicLeads/New/" + OTHER),
                     listing(LeadJoinUrl="https://evil.example/Recruiting/PublicLeads/New/" + CID)):
            result, _ = self.fetch([page])
            self.assertEqual(result.status, "partial")

    def test_different_posting_company_or_title_is_not_complete(self):
        for page in (detail(2), detail(cid=OTHER), detail(title="Different title"), detail(description=""), html("Job removed")):
            result, _ = self.fetch([listing(), page])
            self.assertEqual(result.status, "partial")

    def test_job_text_with_angle_brackets_is_preserved(self):
        result, _ = self.fetch([listing(), detail(description="<p>Travel &lt;20% &amp; budgets &gt;$5m.</p>"), listing()])
        self.assertEqual(result.status, "complete", result.reason)
        self.assertIn("Travel <20% & budgets >$5m.", result.jobs[0]["description"])

    def test_board_change_including_empty_to_nonempty_is_partial(self):
        for responses in ([listing(), detail(), listing([])], [listing([]), listing()],
                          [listing(), detail(), listing([dict(entry(), JobTitle="Changed")])]):
            result, _ = self.fetch(responses)
            self.assertEqual(result.status, "partial")
            self.assertIn("changed", result.reason)

    def test_failure_retains_fetched_jobs_without_completeness(self):
        result, _ = self.fetch([listing([entry(1), entry(2)]), detail(1), html("Unavailable", status=503)])
        self.assertEqual(result.status, "partial")
        self.assertEqual(len(result.jobs), 1)
        self.assertIn("detail 2", result.reason)

    def test_network_failure_on_final_check_is_partial(self):
        result, _ = self.fetch([listing(), detail(), OSError("offline")])
        self.assertEqual(result.status, "partial")
        self.assertEqual(len(result.jobs), 1)

    def test_denials_challenges_redirects_and_rate_limits_never_complete(self):
        for page, expected in ((html("Denied", status=403), "blocked"),
                               (html("<title>Just a moment</title>"), "blocked"),
                               (html("", status=302, Location="https://other.example"), "failed"),
                               (html("", status=429), "failed")):
            result, transport = self.fetch([page])
            self.assertEqual(result.status, expected)
            self.assertEqual(len(transport.urls), 1)

    def test_captcha_application_script_is_not_a_challenge(self):
        page = detail()
        page.body = b'<script src="https://www.google.com/recaptcha/api.js"></script>' + page.body
        result, _ = self.fetch([listing(), page, listing()])
        self.assertEqual(result.status, "complete", result.reason)

    def test_bad_content_encoding_size_or_json_is_partial(self):
        for page in (HTTPResponse(200, b"{}", {"Content-Type": "application/json"}), HTTPResponse(200, b"\xff"),
                     html('<script>window.pageData = {bad};</script>'),
                     html('<script>window.pageData = {}; malicious();</script>')):
            result, _ = self.fetch([page])
            self.assertEqual(result.status, "partial")
        with patch("job_search_helper.paylocity.MAX_HTML_BYTES", 2):
            result, _ = self.fetch([listing()])
        self.assertEqual(result.status, "partial")

    def test_bounded_job_count(self):
        with patch("job_search_helper.paylocity.MAX_JOBS", 1):
            result, _ = self.fetch([listing([entry(1), entry(2)])])
        self.assertEqual(result.status, "partial")

    def test_filtered_internal_application_and_detail_urls_not_broadened(self):
        for url in (BOARD + "?location=US", BOARD + "?page=2", BOARD + "#search=engineer", DETAIL + "1",
                    BOARD.replace("/All/", "/Internal/"), BOARD.replace("/All/", "/Apply/")):
            pages = Transport([])
            result, transport = self.fetch([], url=url, pages=pages)
            self.assertEqual(result.status, "unsupported")
            self.assertFalse(transport.urls or pages.urls)
        result, _ = self.fetch([], ats="Paylocity parent shared")
        self.assertEqual(result.status, "unsupported")

    def test_ats_mismatch_in_both_directions(self):
        result, _ = self.fetch([], ats="Workday")
        self.assertEqual(result.status, "unsupported")
        for url in ("https://acme.wd1.myworkdayjobs.com/Careers", "https://jobs.lever.co/acme",
                    "https://careers-acme.icims.com/jobs/search",
                    "https://workforcenow.adp.com/mascsr/default/mdf/recruitment/recruitment.html?cid=" + CID + "&ccId=1"):
            result, _ = self.fetch([], url=url)
            self.assertEqual(result.status, "unsupported")

    def test_transport_is_pinned_to_read_only_paths(self):
        for url in (BOARD, DETAIL + "1"):
            _safe_api_url(url)
        for url in (BOARD + "?filter=x", BOARD.replace("https:", "http:"), DETAIL.replace("/Details/", "/Apply/") + "1",
                    BOARD.replace("recruiting.paylocity.com", "recruiting.paylocity.com.evil.example"),
                    "https://recruiting.paylocity.com/Recruiting/Jobs/FileUpload", BOARD.replace("https://", "https://user@")):
            with self.assertRaises(FetchError):
                _safe_api_url(url)
        with self.assertRaises(FetchError):
            HTTPTransport().post(BOARD, {})

    def test_discovery_link_iframe_and_redirect(self):
        for page in (html(f'<a href="{BOARD}/Acme">Jobs</a>'), html(f'<iframe src="{BOARD}"></iframe>'),
                     html("", status=302, Location=BOARD)):
            result, _ = self.fetch([listing(), detail(), listing()], url="https://acme.example/careers", pages=Transport([page]))
            self.assertEqual(result.status, "complete", result.reason)
            self.assertIn("Discovered Paylocity", result.reason)

    def test_discovery_deduplicates_slug_variants_but_rejects_different_boards(self):
        pages = Transport([html(f'<a href="{BOARD}/Acme">A</a><a href="{BOARD.lower()}">B</a>')])
        result, _ = self.fetch([listing([]), listing([])], url="https://acme.example/careers", pages=pages)
        self.assertEqual(result.status, "complete", result.reason)
        pages = Transport([html(f'<a href="{BOARD}">A</a><a href="{ROOT}{OTHER}">B</a>')])
        result, transport = self.fetch([], url="https://acme.example/careers", pages=pages)
        self.assertEqual(result.status, "unsupported")
        self.assertFalse(transport.urls)


class PaylocityEngineTests(unittest.TestCase):
    def setUp(self):
        title = patch("job_search_helper.engine.classify_title", return_value="review")
        title.start()
        self.addCleanup(title.stop)
        self.repo = MemoryRepository({"Companies": [{"Company": "Acme", "Company ID": "C-1", "Company Status": "Active",
                        "ATS / Source": "Paylocity", "Official Careers URL": BOARD, "Blocked Reason": "Unsupported ATS"}]})
        self.state = State()
        self.addCleanup(self.state.close)
        with redirect_stderr(StringIO()):
            self.inventory = fetch_inventory("Paylocity", BOARD, "C-1", "Acme", Transport([listing(), detail(), listing()]))
        self.engine = Engine(self.repo, self.state, fetcher=lambda *args: self.inventory)

    def scan(self):
        with redirect_stdout(StringIO()):
            cycle = self.engine.start_cycle(["C-1"])
            self.engine.resume(cycle)

    def test_complete_updates_dates_and_clears_old_reason(self):
        self.scan()
        company = self.repo.read("Companies")[0]
        self.assertTrue(company["Last Checked"])
        self.assertTrue(company["Last Successful Scan"])
        self.assertEqual(company["Blocked Reason"], "")

    def test_partial_and_changed_company_board_cannot_close_previous_jobs(self):
        self.scan()
        original = self.repo.read("Job History")[0]
        checked = self.repo.read("Companies")[0]["Last Successful Scan"]
        self.inventory = Inventory("partial", [], "Missing Paylocity detail", BOARD)
        self.scan()
        self.assertEqual(self.repo.read("Companies")[0]["Last Successful Scan"], checked)
        self.inventory = Inventory("complete", [], source_url=ROOT + OTHER)
        self.scan()
        self.scan()
        self.assertEqual(self.repo.read("Job History")[0], original)


if __name__ == "__main__":
    unittest.main()
