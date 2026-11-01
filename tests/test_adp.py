from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit

from job_search_helper.adp import API, API_PATH, CAREERS_PATH, HOST
from job_search_helper.ats import FetchError, HTTPResponse, HTTPTransport, Inventory, _safe_api_url, fetch_inventory, resolve_board
from job_search_helper.engine import Engine, State, _inventory_source
from job_search_helper.repository import MemoryRepository
from test_ats import Transport, response
from test_discovery import html


CID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
PARAMS = {"cid": CID, "ccId": "9201677718185_2", "lang": "en_US"}
BOARD = f"https://{HOST}{CAREERS_PATH}?" + urlencode(PARAMS)
SOURCE = API + "?" + urlencode(PARAMS)
AIRGAIN_HOST = "workforcenow.cloud.adp.com"
AIRGAIN_PARAMS = {"cid": "a5bb880d-c347-4e46-9d87-7fa641c11036", "ccId": "19000101_000001", "lang": "en_US"}
AIRGAIN_BOARD = f"https://{AIRGAIN_HOST}{CAREERS_PATH}?" + urlencode(AIRGAIN_PARAMS) + "&type=JS"


def posting(number=1, full=False):
    row = {"itemID": f"9201491629842_{number}", "requisitionTitle": "Solutions Engineer", "clientRequisitionID": f"REQ-{number}",
           "postDate": "2026-09-23T10:00:00.000-04:00", "customFieldGroup": {
               "stringFields": [{"nameCode": {"codeValue": "HomeDepartment"}, "stringValue": "Engineering"},
                                {"nameCode": {"codeValue": "ExternalJobID"}, "stringValue": str(100 + number)}],
               "indicatorFields": [{"nameCode": {"codeValue": "InternalPostingFlag"}, "indicatorValue": False}],
               "codeFields": [{"nameCode": {"codeValue": "SalaryType"}, "codeValue": "AN", "shortName": "Annually"}]},
           "requisitionLocations": [{"nameCode": {"shortName": "Dayton, OH, US"}}, {"nameCode": {"shortName": "Remote, US"}}],
           "payGradeRange": {"minimumRate": {"amountValue": 140000, "currencyCode": "USD"},
                             "maximumRate": {"amountValue": 180000, "currencyCode": "USD"}}}
    if full:
        row["requisitionDescription"] = "<h2>Responsibilities</h2><p>Lead customer deployments.</p><p>Travel 20%.</p>"
    return row


def page(total=1, start=1, items=None):
    return response({"meta": {"totalNumber": total, "startSequence": start},
                     "jobRequisitions": [posting()] if items is None else items})


class AdpTests(unittest.TestCase):
    def setUp(self):
        capture = redirect_stderr(StringIO())
        capture.__enter__()
        self.addCleanup(capture.__exit__, None, None, None)

    def fetch(self, responses, url=BOARD, ats="ADP", pages=None):
        t = Transport(responses)
        result = fetch_inventory(ats, url, "C-1", "Acme", t, discovery_transport=pages or Transport([]))
        return result, t

    def test_resolves_public_page_api_and_job_url_to_same_board(self):
        for url in (BOARD, BOARD + "&jobId=101&type=JS&selectedMenuKey=CurrentOpenings&hsCtaAttrib=123",
                    SOURCE, SOURCE + "&locale=en_US&%24skip=21&%24top=20"):
            self.assertEqual(resolve_board("ADP", url), ("ADP", urlencode(PARAMS), API + "?"))
        self.assertEqual(_inventory_source(BOARD), SOURCE)

    def test_airgain_cloud_origin_is_preserved_for_board_api_details_and_output(self):
        legacy = BOARD.replace(HOST, "workforcenow.adp.com")
        for board, host in ((AIRGAIN_BOARD, AIRGAIN_HOST), (legacy, HOST)):
            with self.subTest(host=host):
                name, params, root = resolve_board("ADP", board)
                self.assertEqual(name, "ADP")
                self.assertEqual(root, f"https://{host}{API_PATH}?")
                self.assertIn("ccId=", params)

        items = [posting(index, full=True) for index in range(1, 22)]
        responses = [page(21, 1, items[:20])]
        responses += [response(item) for item in items[:20]]
        responses += [page(21, 21, items[20:])]
        responses += [response(items[20]), page(21, 1, items[:20])]
        result, transport = self.fetch(responses, url=AIRGAIN_BOARD)
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual(len(result.jobs), 21)
        self.assertTrue(all(url.startswith(f"https://{AIRGAIN_HOST}/") for url in transport.urls))
        self.assertTrue(all(job["url"].startswith(f"https://{AIRGAIN_HOST}/") for job in result.jobs))

        legacy_result, _ = self.fetch(
            [HTTPResponse(404, b"legacy board unavailable")], url=legacy)
        self.assertIn(legacy_result.status, {"failed", "partial"})

    def test_full_details_and_separate_stable_external_and_requisition_ids(self):
        result, t = self.fetch([page(), response(posting(full=True))])
        self.assertEqual(result.status, "complete", result.reason)
        row = result.jobs[0]
        self.assertEqual(row["posting_id"], "9201491629842_1")
        self.assertEqual(row["req_id"], "REQ-1")
        self.assertEqual(parse_qs(urlsplit(row["url"]).query)["jobId"], ["101"])
        self.assertIn("Lead customer deployments.", row["description"])
        self.assertIn("Travel 20%", row["description"])
        self.assertEqual(row["location"], "Dayton, OH, US; Remote, US")
        self.assertEqual(row["department"], "Engineering")
        self.assertIn("Annually", row["compensation"])
        self.assertIn("180000", row["compensation"])
        self.assertEqual(row["work_arrangement"], "")
        self.assertEqual(parse_qs(urlsplit(t.urls[0]).query)["$skip"], ["1"])
        self.assertIn("/9201491629842_1?", t.urls[1])

    def test_one_based_pagination_has_no_gaps_and_rechecks_first_page(self):
        with patch("job_search_helper.adp.PAGE_SIZE", 2):
            first = page(3, 1, [posting(1), posting(2)])
            result, t = self.fetch([first, response(posting(1, True)), response(posting(2, True)),
                                   page(3, 3, [posting(3)]), response(posting(3, True)), first])
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual(len(result.jobs), 3)
        self.assertEqual([parse_qs(urlsplit(url).query)["$skip"] for url in t.urls if "$skip" in parse_qs(urlsplit(url).query)], [["1"], ["3"], ["1"]])

    def test_career_center_locale_and_keyword_scope_are_retained(self):
        result, t = self.fetch([page(0, 0, [])], url=BOARD + "&userQuery=Design+Group&utm_source=site", ats="ADP shared parent board")
        self.assertEqual(result.status, "complete")
        query = parse_qs(urlsplit(t.urls[0]).query)
        self.assertEqual(query["ccId"], [PARAMS["ccId"]])
        self.assertEqual(query["locale"], ["en_US"])
        self.assertEqual(query["userQuery"], ["Design Group"])
        self.assertEqual(query["$skip"], ["0"])
        self.assertEqual(result.source_url, SOURCE + "&userQuery=Design+Group")
        self.assertNotEqual(_inventory_source(result.source_url), _inventory_source(BOARD))
        self.assertNotEqual(_inventory_source(BOARD.replace(PARAMS["ccId"], "19000101_000001")), _inventory_source(BOARD))
        self.assertNotEqual(_inventory_source(BOARD.replace(CID, "bbbbbbbb-bbbb-cccc-dddd-eeeeeeeeeeee")), _inventory_source(BOARD))

    def test_keyword_search_accepts_full_set_beyond_page_size_but_never_truncation(self):
        with patch("job_search_helper.adp.PAGE_SIZE", 1):
            result, t = self.fetch([page(2, 0, [posting(1), posting(2)]), response(posting(1, True)), response(posting(2, True))],
                                   url=BOARD + "&userQuery=Engineer")
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual(len(result.jobs), 2)
        self.assertEqual(len(t.urls), 3)
        for data in (page(2, 0), page(1, 1)):
            result, _ = self.fetch([data], url=BOARD + "&userQuery=Engineer")
            self.assertEqual(result.status, "partial")

    def test_default_language_and_canonical_query_order(self):
        reversed_url = f"https://{HOST}{CAREERS_PATH}?ccId={PARAMS['ccId']}&cid={CID.upper()}"
        self.assertEqual(resolve_board("", reversed_url), resolve_board("", BOARD))

    def test_unsupported_or_conflicting_scope_never_requests_or_discovers(self):
        for url in (BOARD.replace("cid=", "company="), BOARD.replace("ccId=", "center="), BOARD + "&cid=other",
                    BOARD + "&locationsList=Remote", BOARD + "&search=Acme", BOARD + "&lang=fr_CA",
                    BOARD.replace(CAREERS_PATH, "/mascsr/applicant/careercenter-auth"), BOARD.replace("en_US", "bad")):
            with self.subTest(url=url):
                pages = Transport([])
                result, t = self.fetch([], url=url, pages=pages)
                self.assertEqual(result.status, "unsupported")
                self.assertFalse(t.urls or pages.urls)
        result, _ = self.fetch([], ats="ADP parent board")
        self.assertEqual(result.status, "unsupported")

    def test_ats_mismatch_in_both_directions(self):
        result, _ = self.fetch([], ats="Workday")
        self.assertEqual(result.status, "unsupported")
        for url in ("https://acme.wd1.myworkdayjobs.com/Careers", "https://careers-acme.icims.com/jobs/search",
                    "https://jobs.lever.co/acme"):
            result = fetch_inventory("ADP", url, "C", "Acme", Transport([]))
            self.assertEqual(result.status, "unsupported")

    def test_empty_inventory_requires_valid_zero_count_and_offset(self):
        result, _ = self.fetch([page(0, 1, [])])
        self.assertEqual(result.status, "complete")
        for data in ({}, {"jobRequisitions": []}, {"jobRequisitions": [], "meta": {"totalNumber": 0}},
                     {"jobRequisitions": [], "meta": {"totalNumber": False, "startSequence": 1}}):
            result, _ = self.fetch([response(data)])
            self.assertEqual(result.status, "partial")

    def test_wrong_offset_short_page_and_count_change_are_partial(self):
        result, _ = self.fetch([page(1, 0)])
        self.assertEqual(result.status, "partial")
        result, _ = self.fetch([page(2)])
        self.assertEqual(result.status, "partial")
        with patch("job_search_helper.adp.PAGE_SIZE", 1):
            result, _ = self.fetch([page(2), response(posting(full=True)), page(3, 2, [posting(2)])])
            self.assertEqual(result.status, "partial")
            self.assertEqual(len(result.jobs), 1)

    def test_duplicate_page_cap_and_changing_first_page_cannot_complete(self):
        with patch("job_search_helper.adp.PAGE_SIZE", 1):
            result, _ = self.fetch([page(2), response(posting(full=True)), page(2, 2)])
            self.assertEqual(result.status, "partial")
            self.assertIn("repeated", result.reason)
            with patch("job_search_helper.adp.MAX_PAGES", 1):
                result, _ = self.fetch([page(2), response(posting(full=True))])
                self.assertEqual(result.status, "partial")
                self.assertIn("cap", result.reason)
            result, _ = self.fetch([page(2), response(posting(full=True)), page(2, 2, [posting(2)]),
                                   response(posting(2, True)), page(2, 1, [posting(3)])])
            self.assertEqual(result.status, "partial")
            self.assertIn("changed", result.reason)

    def test_mismatched_missing_and_internal_details_never_complete(self):
        missing_title = posting(full=True)
        missing_title["requisitionTitle"] = ""
        wrong_external = posting(full=True)
        wrong_external["customFieldGroup"]["stringFields"][1]["stringValue"] = "other"
        internal = posting(full=True)
        internal["customFieldGroup"]["indicatorFields"][0]["indicatorValue"] = True
        for bad in (posting(), posting(2, True), missing_title, wrong_external, internal):
            result, _ = self.fetch([page(), response(bad)])
            self.assertEqual(result.status, "partial")
            self.assertFalse(result.jobs)

    def test_bad_identifier_cannot_turn_into_arbitrary_endpoint(self):
        for ident in ("../candidate", "x?foo=bar", "x/y", "https://evil.example/", None):
            item = posting()
            item["itemID"] = ident
            result, t = self.fetch([page(items=[item])])
            self.assertEqual(result.status, "partial")
            self.assertEqual(len(t.urls), 1)

    def test_late_http_failures_keep_completed_postings(self):
        for status, expected in ((403, "blocked"), (429, "partial"), (500, "partial"), (404, "partial"), (302, "partial")):
            result, _ = self.fetch([page(2, 1, [posting(1), posting(2)]), response(posting(1, True)), response({}, status)])
            self.assertEqual(result.status, expected)
            self.assertEqual(len(result.jobs), 1)
            self.assertIn("Redirect refused" if status == 302 else str(status), result.reason)
        result, _ = self.fetch([HTTPResponse(200, b"<html>Verify you are human</html>")])
        self.assertEqual(result.status, "blocked")

    def test_public_get_endpoint_allowlist(self):
        for url in (SOURCE.replace(".com", ".com.evil.example"), SOURCE.replace("/public/", "/private/"),
                    SOURCE.replace("job-requisitions", "job-application.submit"), API + "/../candidate?" + urlencode(PARAMS),
                    SOURCE + "&candidateId=42", SOURCE + "&%24skip=bad", BOARD):
            with self.subTest(url=url), self.assertRaises(FetchError):
                _safe_api_url(url)
        _safe_api_url(SOURCE + "&%24skip=1&%24top=20")
        _safe_api_url(API + "/9201491629842_1?" + urlencode(PARAMS))
        with self.assertRaises(FetchError):
            HTTPTransport().post(SOURCE, {})

    def test_discovery_links_iframes_and_redirects_preserve_company_center(self):
        for page_response in (html(f'<a href="{BOARD.replace("&", "&amp;")}">Jobs</a>'),
                              html(f'<iframe src="{BOARD.replace("&", "&amp;")}"></iframe>'), html("", 302, Location=BOARD)):
            result, _ = self.fetch([page(), response(posting(full=True))], url="https://acme.example/careers", pages=Transport([page_response]))
            self.assertEqual(result.status, "complete", result.reason)
            self.assertEqual(result.source_url, SOURCE)
            self.assertIn("Discovered ADP", result.reason)

    def test_discovery_with_two_centers_requires_selection(self):
        other = BOARD.replace(PARAMS["ccId"], "19000101_000001")
        pages = Transport([html(f'<a href="{BOARD}">A</a><a href="{other}">B</a>')])
        result, t = self.fetch([], url="https://acme.example/careers", pages=pages)
        self.assertEqual(result.status, "unsupported")
        self.assertFalse(t.urls)


class AdpEngineTests(unittest.TestCase):
    def setUp(self):
        title = patch("job_search_helper.engine.classify_title", return_value="review")
        title.start()
        self.addCleanup(title.stop)
        self.repo = MemoryRepository({"Companies": [{"Company": "Acme", "Company ID": "C-1", "Company Status": "Active",
                         "ATS / Source": "ADP", "Official Careers URL": BOARD, "Blocked Reason": "Unsupported ATS"}]})
        self.state = State()
        self.addCleanup(self.state.close)
        with redirect_stderr(StringIO()):
            self.inventory = fetch_inventory("ADP", BOARD, "C-1", "Acme", Transport([page(), response(posting(full=True))]))
        self.engine = Engine(self.repo, self.state, fetcher=lambda *args: self.inventory)

    def scan(self):
        with redirect_stdout(StringIO()):
            cycle = self.engine.start_cycle(["C-1"])
            self.engine.resume(cycle)

    def test_complete_inventory_updates_dates_and_clears_block_reason(self):
        self.scan()
        company = self.repo.read("Companies")[0]
        self.assertTrue(company["Last Checked"])
        self.assertTrue(company["Last Successful Scan"])
        self.assertEqual(company["Blocked Reason"], "")

    def test_partial_scan_and_changed_career_center_do_not_close_old_jobs(self):
        self.scan()
        original = self.repo.read("Job History")[0]
        checked = self.repo.read("Companies")[0]["Last Successful Scan"]
        self.inventory = Inventory("partial", [], "Missing ADP page", SOURCE)
        self.scan()
        self.assertEqual(self.repo.read("Companies")[0]["Last Successful Scan"], checked)
        self.inventory = Inventory("complete", [], source_url=SOURCE.replace(PARAMS["ccId"], "19000101_000001"))
        self.scan()
        self.scan()
        self.assertEqual(self.repo.read("Job History")[0], original)


if __name__ == "__main__":
    unittest.main()
