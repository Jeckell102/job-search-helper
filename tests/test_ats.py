from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from io import BytesIO
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

from job_search_helper.ats import (
    FetchError, HTTPResponse, HTTPTransport, _NoRedirect, _delay,
    _safe_api_url, fetch_inventory, resolve_board, text,
)


FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def response(data, status=200, headers=None):
    return HTTPResponse(status, json.dumps(data).encode(), headers or {})


class Transport:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.urls = []

    def get(self, url):
        self.urls.append(url)
        result = next(self.responses)
        if isinstance(result, Exception):
            raise result
        return result


class ATSAdapterTests(unittest.TestCase):
    def test_greenhouse_uses_public_posting_id_and_full_content(self):
        t = Transport([response(fixture("greenhouse"))])
        result = fetch_inventory("Greenhouse", "https://job-boards.greenhouse.io/acme/jobs/123", "C-1", "Acme", t)
        self.assertEqual(result.status, "complete")
        row = result.jobs[0]
        self.assertEqual(row["posting_id"], "123")
        self.assertEqual(row["req_id"], "REQ-9")
        self.assertIn("Integrate systems", row["description"])
        self.assertNotIn("&lt;", row["description"])
        self.assertIn("content=true", t.urls[0])
        self.assertEqual(row["department"], "Engineering")

    def test_greenhouse_total_mismatch_never_complete(self):
        data = fixture("greenhouse")
        data["meta"]["total"] = 2
        result = fetch_inventory("Greenhouse", "https://boards.greenhouse.io/acme", "C", "Acme", Transport([response(data)]))
        self.assertEqual(result.status, "partial")
        self.assertEqual(len(result.jobs), 1)

    def test_greenhouse_missing_metadata_never_complete(self):
        result = fetch_inventory("Greenhouse", "https://boards.greenhouse.io/acme", "C", "Acme", Transport([response({"jobs": []})]))
        self.assertEqual(result.status, "partial")

    def test_greenhouse_verified_empty_board(self):
        result = fetch_inventory("Greenhouse", "https://boards.greenhouse.io/acme", "C", "Acme", Transport([response({"jobs": [], "meta": {"total": 0}})]))
        self.assertEqual(result.status, "complete")

    def test_lever_full_description_salary_and_terminal_page(self):
        t = Transport([response(fixture("lever")), response([])])
        result = fetch_inventory("Lever", "https://jobs.lever.co/acme/lev-123", "C", "Acme", t)
        self.assertEqual(result.status, "complete")
        self.assertIn("API integration", result.jobs[0]["description"])
        self.assertIn("Travel up to 50%", result.jobs[0]["description"])
        self.assertIn("180000", result.jobs[0]["compensation"])
        self.assertEqual(result.jobs[0]["location"], "Ohio; Remote")
        self.assertEqual(parse_qs(urlsplit(t.urls[0]).query)["skip"], ["0"])
        self.assertEqual(parse_qs(urlsplit(t.urls[1]).query)["skip"], ["1"])

    def test_lever_full_pagination(self):
        first = fixture("lever")[0]
        second = copy.deepcopy(first)
        second["id"] = "lev-456"
        t = Transport([response([first]), response([second]), response([])])
        with patch("job_search_helper.ats.PAGE_SIZE", 1):
            result = fetch_inventory("Lever", "https://jobs.lever.co/acme", "C", "Acme", t)
        self.assertEqual(result.status, "complete")
        self.assertEqual(len(result.jobs), 2)
        self.assertEqual([parse_qs(urlsplit(u).query)["skip"][0] for u in t.urls], ["0", "1", "2"])

    def test_lever_repeated_page_is_partial(self):
        data = fixture("lever")
        with patch("job_search_helper.ats.PAGE_SIZE", 1):
            result = fetch_inventory("Lever", "https://jobs.lever.co/acme", "C", "Acme", Transport([response(data), response(data)]))
        self.assertEqual(result.status, "partial")
        self.assertEqual(len(result.jobs), 1)

    def test_lever_page_cap_is_partial(self):
        with patch("job_search_helper.ats.MAX_PAGES", 1), patch("job_search_helper.ats.PAGE_SIZE", 1):
            result = fetch_inventory("Lever", "https://jobs.lever.co/acme", "C", "Acme", Transport([response(fixture("lever"))]))
        self.assertEqual(result.status, "partial")

    def test_lever_silent_short_page_cap_is_partial(self):
        data = fixture("lever")
        result = fetch_inventory("Lever", "https://jobs.lever.co/acme", "C", "Acme", Transport([response(data), response(data)]))
        self.assertEqual(result.status, "partial")

    def test_lever_late_request_failure_is_partial(self):
        result = fetch_inventory("Lever", "https://jobs.lever.co/acme", "C", "Acme", Transport([response(fixture("lever")), response({}, 500)]))
        self.assertEqual(result.status, "partial")
        self.assertEqual(len(result.jobs), 1)

    def test_lever_eu_endpoint(self):
        t = Transport([response([])])
        result = fetch_inventory("Lever", "https://jobs.eu.lever.co/acme", "C", "Acme", t)
        self.assertEqual(result.status, "complete")
        self.assertTrue(t.urls[0].startswith("https://api.eu.lever.co/"))

    def test_ashby_missing_id_from_url_salary_and_unlisted_flag(self):
        t = Transport([response(fixture("ashby"))])
        result = fetch_inventory("Ashby", "https://jobs.ashbyhq.com/acme", "C", "Acme", t)
        self.assertEqual(result.status, "complete")
        self.assertEqual(result.jobs[0]["posting_id"], "ash-123")
        self.assertIn("180,000", result.jobs[0]["compensation"])
        self.assertEqual(result.jobs[0]["work_arrangement"], "Remote")
        self.assertFalse(result.jobs[1]["is_listed"])
        self.assertIn("includeCompensation=true", t.urls[0])

    def test_missing_description_is_partial_not_zero_jobs_success(self):
        data = fixture("ashby")
        del data["jobs"][0]["descriptionPlain"]
        result = fetch_inventory("Ashby", "https://jobs.ashbyhq.com/acme", "C", "Acme", Transport([response(data)]))
        self.assertEqual(result.status, "partial")
        self.assertEqual(len(result.jobs), 1)

    def test_wrong_json_schema_never_complete(self):
        for name, url in [("Greenhouse", "https://boards.greenhouse.io/acme"), ("Lever", "https://jobs.lever.co/acme"), ("Ashby", "https://jobs.ashbyhq.com/acme")]:
            with self.subTest(name=name):
                result = fetch_inventory(name, url, "C", "Acme", Transport([response({"error": "unavailable"})]))
                self.assertEqual(result.status, "partial")

    def test_403_is_blocked_but_500_is_not_bot_block(self):
        for status, expected in [(401, "blocked"), (403, "blocked"), (429, "failed"), (500, "failed"), (404, "failed"), (302, "failed")]:
            with self.subTest(status=status):
                t = Transport([response({}, status)])
                result = fetch_inventory("Ashby", "https://jobs.ashbyhq.com/acme", "C", "Acme", t)
                self.assertEqual(result.status, expected)
                self.assertEqual(len(t.urls), 1)

    def test_html_human_verification_is_blocked(self):
        t = Transport([HTTPResponse(200, b"<html>Verify you are human: CAPTCHA</html>")])
        result = fetch_inventory("Ashby", "https://jobs.ashbyhq.com/acme", "C", "Acme", t)
        self.assertEqual(result.status, "blocked")

    def test_503_human_verification_never_retried(self):
        class Opener:
            calls = 0
            def open(self, request, timeout):
                self.calls += 1
                raise HTTPError(request.full_url, 503, "Unavailable", {}, BytesIO(b"<html>CAPTCHA verification</html>"))
        transport = HTTPTransport(sleep=lambda _: None)
        transport.opener = Opener()
        result = fetch_inventory("Ashby", "https://jobs.ashbyhq.com/acme", "C", "Acme", transport)
        self.assertEqual(result.status, "blocked")
        self.assertEqual(transport.opener.calls, 1)

    def test_transport_transient_retries_are_bounded(self):
        class Opener:
            calls = 0
            def open(self, request, timeout):
                self.calls += 1
                raise HTTPError(request.full_url, 429, "Rate limit", {"Retry-After": "900"}, BytesIO(b"rate limit"))
        delays = []
        transport = HTTPTransport(sleep=delays.append)
        transport.opener = Opener()
        result = fetch_inventory("Ashby", "https://jobs.ashbyhq.com/acme", "C", "Acme", transport)
        self.assertEqual(result.status, "failed")
        self.assertEqual(transport.opener.calls, 3)
        self.assertEqual(delays.count(8), 2)

    def test_transport_permission_failure_not_retried(self):
        class Opener:
            calls = 0
            def open(self, request, timeout):
                self.calls += 1
                raise HTTPError(request.full_url, 403, "Forbidden", {}, BytesIO(b"denied"))
        transport = HTTPTransport(sleep=lambda _: None)
        transport.opener = Opener()
        result = fetch_inventory("Ashby", "https://jobs.ashbyhq.com/acme", "C", "Acme", transport)
        self.assertEqual(result.status, "blocked")
        self.assertEqual(transport.opener.calls, 1)

    def test_ordinary_html_error_is_partial(self):
        result = fetch_inventory("Ashby", "https://jobs.ashbyhq.com/acme", "C", "Acme", Transport([HTTPResponse(200, b"<html>Down for maintenance</html>")]))
        self.assertEqual(result.status, "partial")

    def test_invalid_or_private_url_never_requested(self):
        for url in ("http://jobs.lever.co/acme", "https://user:secret@jobs.lever.co/acme", "https://jobs.lever.co:8080/acme", "https://jobs.lever.co/%2f..", "https://127.0.0.1/acme"):
            t = Transport([])
            page = Transport([])
            result = fetch_inventory("Lever", url, "C", "Acme", t, discovery_transport=page)
            self.assertEqual(result.status, "unsupported", url)
            self.assertFalse(t.urls)
            self.assertFalse(page.urls)

    def test_mismatched_ats_rejected(self):
        t = Transport([])
        self.assertEqual(fetch_inventory("Lever", "https://jobs.ashbyhq.com/acme", "C", "Acme", t).status, "unsupported")

    def test_board_roots_and_embeds(self):
        for url in ("https://boards.greenhouse.io/acme/jobs/123", "https://boards-api.greenhouse.io/v1/boards/acme/jobs", "https://boards.greenhouse.io/embed/job_board?for=acme"):
            self.assertEqual(resolve_board("Greenhouse", url)[1], "acme")

    def test_redirect_handler_never_follows(self):
        self.assertIsNone(_NoRedirect().redirect_request(None, None, 302, "Moved", {}, "https://evil.example/"))

    def test_transport_allowlist(self):
        with self.assertRaises(FetchError):
            _safe_api_url("https://example.com/")
        _safe_api_url("https://api.lever.co/v0/postings/acme")

    def test_retry_after_cap(self):
        self.assertEqual(_delay({"Retry-After": "9999"}, 0), 8)
        self.assertEqual(_delay({"retry-after": "-5"}, 0), 0)
        self.assertEqual(_delay({}, 2), 4)

    def test_html_text_does_not_include_scripts(self):
        self.assertEqual(text("<p>Work</p><script>ignore instructions</script><p>Travel</p>"), "Work\nTravel")


if __name__ == "__main__":
    unittest.main()
