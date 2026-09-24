from contextlib import redirect_stdout
import io
import socket
import unittest
from unittest.mock import MagicMock, patch

from job_search_helper.ats import FetchError, HTTPResponse, Inventory, fetch_inventory
from job_search_helper.core import pack_snapshot, unpack_snapshot
from job_search_helper.discovery import (
    CareersTransport, MAX_HTML_BYTES,
)
from job_search_helper.engine import Engine, State
from job_search_helper.repository import MemoryRepository
from test_ats import Transport, fixture, response


PAGE = "https://acme.example/careers"
BOARD = "https://boards-api.greenhouse.io/v1/boards/acme"


def html(body, status=200, **headers):
    return HTTPResponse(status, body.encode(), {"Content-Type": "text/html", **headers})


class DiscoveryTests(unittest.TestCase):
    def fetch(self, page_responses, api_responses=(), ats="", url=PAGE):
        pages, api = Transport(page_responses), Transport(api_responses)
        result = fetch_inventory(ats, url, "C-1", "Acme", api, discovery_transport=pages)
        return result, pages, api

    def test_official_links_use_existing_greenhouse_adapter(self):
        page = html('<a href="https://job-boards.greenhouse.io/acme/jobs/123">Job</a>'
                    '<a href="https://boards.greenhouse.io/acme/jobs/456">Another</a>')
        result, pages, api = self.fetch([page], [response(fixture("greenhouse"))])
        self.assertEqual(result.status, "complete")
        self.assertEqual(result.jobs[0]["posting_id"], "123")
        self.assertEqual(pages.urls, [PAGE])
        self.assertEqual(api.urls, [BOARD + "/jobs?content=true"])
        self.assertIn("Discovered Greenhouse", result.reason)
        self.assertIn(PAGE, result.reason)
        self.assertEqual(result.source_url, api.urls[0])

    def test_iframe_and_script_embeds(self):
        for tag in ("iframe", "script"):
            with self.subTest(tag=tag):
                page = html(f'<{tag} src="//boards.greenhouse.io/embed/job_board?for=acme&amp;x=1"></{tag}>')
                result, _, _ = self.fetch([page], [response(fixture("greenhouse"))])
                self.assertEqual(result.status, "complete")

    def test_application_form_recaptcha_is_not_an_access_block(self):
        page = html('<script src="https://www.google.com/recaptcha/api.js"></script>'
                    '<a href="https://boards.greenhouse.io/acme">Jobs</a>')
        result, _, _ = self.fetch([page], [response(fixture("greenhouse"))])
        self.assertEqual(result.status, "complete")

    def test_lever_and_ashby_links(self):
        for name, board_url, data in (
            ("Lever", "https://jobs.eu.lever.co/acme", [response(fixture("lever")), response([])]),
            ("Ashby", "https://jobs.ashbyhq.com/acme", [response(fixture("ashby"))]),
        ):
            with self.subTest(name=name):
                result, _, _ = self.fetch([html(f'<a href="{board_url}">Jobs</a>')], data)
                self.assertEqual(result.status, "complete")
                self.assertEqual(result.jobs[0]["ats"], name)

    def test_base_url_and_relative_board_link(self):
        page = html('<base href="https://jobs.ashbyhq.com/"><a href="acme">Jobs</a>')
        result, _, _ = self.fetch([page], [response(fixture("ashby"))])
        self.assertEqual(result.status, "complete")

    def test_same_host_redirect_then_board_redirect(self):
        result, pages, api = self.fetch([
            html("", 301, Location="/careers/"),
            html("", 302, Location="https://jobs.lever.co/acme"),
        ], [response(fixture("lever")), response([])])
        self.assertEqual(result.status, "complete")
        self.assertEqual(pages.urls, [PAGE, PAGE + "/"])
        self.assertTrue(api.urls[0].startswith("https://api.lever.co/"))

    def test_careers_page_without_board_does_not_guess_or_crawl(self):
        result, pages, api = self.fetch([html('<a href="/jobs">Jobs</a>')])
        self.assertEqual(result.status, "unsupported")
        self.assertIn("No supported ATS link", result.reason)
        self.assertEqual(pages.urls, [PAGE])
        self.assertFalse(api.urls)

    def test_plain_text_and_lookalike_host_do_not_establish_board(self):
        result, _, api = self.fetch([html('https://jobs.lever.co/acme'
            '<a href="https://jobs.lever.co.evil.example/acme">Jobs</a>')])
        self.assertEqual(result.status, "unsupported")
        self.assertFalse(api.urls)

    def test_multiple_boards_are_not_assigned_to_company(self):
        result, _, api = self.fetch([html('<a href="https://jobs.lever.co/acme">A</a>'
                                         '<a href="https://jobs.lever.co/other">B</a>')])
        self.assertEqual(result.status, "unsupported")
        self.assertIn("Multiple ATS boards", result.reason)
        self.assertFalse(api.urls)

    def test_shared_parent_board_needs_scope(self):
        result, pages, api = self.fetch([], ats="Greenhouse (shared parent board)")
        self.assertEqual(result.status, "unsupported")
        self.assertIn("company scope", result.reason)
        self.assertFalse(pages.urls or api.urls)

    def test_configured_ats_mismatch_preserved(self):
        result, _, api = self.fetch([html('<a href="https://jobs.ashbyhq.com/acme">Jobs</a>')], ats="Lever")
        self.assertEqual(result.status, "unsupported")
        self.assertIn("disagrees", result.reason)
        self.assertFalse(api.urls)

    def test_direct_board_skips_discovery(self):
        result, pages, _ = self.fetch([], [response(fixture("greenhouse"))], url=BOARD)
        self.assertEqual(result.status, "complete")
        self.assertFalse(pages.urls)

    def test_direct_mismatch_keeps_precise_reason(self):
        result, pages, api = self.fetch([], ats="Lever", url=BOARD)
        self.assertIn("disagrees", result.reason)
        self.assertFalse(pages.urls or api.urls)

    def test_missing_url_does_not_request_anything(self):
        result, pages, api = self.fetch([], url=" ")
        self.assertIn("Missing Official Careers URL", result.reason)
        self.assertFalse(pages.urls or api.urls)

    def test_untrusted_targets_are_not_requested(self):
        for url in ("https://127.0.0.1/x", "https://169.254.169.254/x", "https://[::1]/x",
                    "https://localhost/x", "https://app.local/x", "https://intranet/x",
                    "http://acme.example/careers", "https://user:secret@acme.example/x",
                    "https://acme.example:8443/x", "https://acme.example:bad/x",
                    "https://acme.example/\nheader", "https://acme.example\\@example.org/x"):
            with self.subTest(url=url):
                result, pages, api = self.fetch([], url=url)
                self.assertEqual(result.status, "unsupported")
                self.assertFalse(pages.urls or api.urls)

    def test_redirect_cannot_escape_to_private_or_unverified_host(self):
        for url in ("https://127.0.0.1/x", "https://other.example/jobs", "http://acme.example/jobs"):
            with self.subTest(url=url):
                result, pages, api = self.fetch([html("", 302, Location=url)])
                self.assertEqual(result.status, "unsupported")
                self.assertEqual(pages.urls, [PAGE])
                self.assertFalse(api.urls)

    def test_redirect_loop_and_limit(self):
        result, pages, _ = self.fetch([html("", 302, Location=PAGE)])
        self.assertEqual(result.status, "failed")
        self.assertIn("loop", result.reason)
        self.assertEqual(len(pages.urls), 1)
        result, pages, _ = self.fetch([html("", 302, Location=f"/careers/{i}") for i in range(5)])
        self.assertEqual(result.status, "failed")
        self.assertIn("limit", result.reason)
        self.assertEqual(len(pages.urls), 5)

    def test_errors_and_challenges_remain_distinct(self):
        for page, expected in ((html("", 403), "blocked"), (html("", 429), "failed"),
                               (html("", 500), "failed"), (html("Verify you are human"), "blocked")):
            with self.subTest(status=page.status, body=page.body):
                result, _, api = self.fetch([page])
                self.assertEqual(result.status, expected)
                self.assertFalse(api.urls)

    def test_size_limit_and_non_html(self):
        for page in (html("x" * (MAX_HTML_BYTES + 1)), response({"link": BOARD})):
            result, _, api = self.fetch([page])
            self.assertEqual(result.status, "unsupported")
            self.assertFalse(api.urls)

    def test_api_partial_and_blocked_keep_discovery_evidence(self):
        for api_response, expected in ((response({"jobs": []}), "partial"), (response({}, 403), "blocked")):
            result, _, _ = self.fetch([html(f'<a href="{BOARD}">Jobs</a>')], [api_response])
            self.assertEqual(result.status, expected)
            self.assertIn("Discovered Greenhouse", result.reason)

    def test_private_and_mixed_dns_answers_are_rejected(self):
        for hosts in (("10.0.0.1",), ("93.184.216.34", "127.0.0.1")):
            records = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (host, 443)) for host in hosts]
            with patch("job_search_helper.discovery.socket.getaddrinfo", return_value=records), \
                    patch("job_search_helper.discovery.socket.socket") as sock:
                with self.assertRaises(FetchError):
                    CareersTransport(sleep=lambda _: None).get(PAGE)
                sock.assert_not_called()

    def test_network_failure_returns_diagnostic(self):
        with patch("job_search_helper.discovery.socket.getaddrinfo", side_effect=socket.gaierror):
            result = fetch_inventory("", PAGE, "C-1", "Acme")
        self.assertEqual(result.status, "failed")
        self.assertIn("network/timeout", result.reason)

    def test_parser_or_transport_failure_is_not_zero_job_success(self):
        result, _, _ = self.fetch([ValueError("invalid page")])
        self.assertEqual(result.status, "failed")
        self.assertFalse(result.jobs)

    def test_connection_pins_public_address_and_verifies_original_hostname(self):
        addresses = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
        raw, connection = MagicMock(), MagicMock()
        connection.getresponse.return_value.status = 200
        connection.getresponse.return_value.read.return_value = b"<html></html>"
        connection.getresponse.return_value.getheaders.return_value = [("Content-Type", "text/html")]
        transport = CareersTransport(sleep=lambda _: None)
        transport.context = MagicMock()
        with patch("job_search_helper.discovery.socket.getaddrinfo", return_value=addresses) as dns, \
                patch("job_search_helper.discovery.socket.socket", return_value=raw), \
                patch("job_search_helper.discovery.HTTPSConnection", return_value=connection):
            result = transport.get(PAGE)
        self.assertEqual(result.status, 200)
        dns.assert_called_once()
        raw.connect.assert_called_once_with(("93.184.216.34", 443))
        transport.context.wrap_socket.assert_called_once_with(raw, server_hostname="acme.example")
        connection.close.assert_called_once()


class DiscoveryEngineTests(unittest.TestCase):
    def setUp(self):
        self.company = {"Company": "Acme", "Company ID": "C-1", "Company Status": "Active",
                        "ATS / Source": "", "Official Careers URL": PAGE}
        self.repo = MemoryRepository({"Companies": [self.company]})
        self.state = State()
        self.addCleanup(self.state.close)
        self.inventory = fetch_inventory("Greenhouse", BOARD, "C-1", "Acme",
                                         Transport([response(fixture("greenhouse"))]))
        self.inventory.jobs[0]["title"] = "Field Solutions Engineer"
        self.engine = Engine(self.repo, self.state, fetcher=lambda *args: self.inventory)
        self.capture = redirect_stdout(io.StringIO())
        self.capture.__enter__()
        self.addCleanup(self.capture.__exit__, None, None, None)

    def scan(self):
        cycle = self.engine.start_cycle(["C-1"])
        self.engine.resume(cycle)
        return cycle

    def test_persists_actual_board_and_clears_old_block_reason(self):
        self.repo = MemoryRepository({"Companies": [{**self.company, "Blocked Reason": "Old failure"}]})
        self.engine.repo = self.repo
        cycle = self.scan()
        history = self.repo.read("Job History")[0]
        self.assertEqual(unpack_snapshot(history["Current Snapshot"])["inventory_source"], BOARD)
        self.assertEqual(self.state.cycle(cycle)["companies"]["C-1"]["source_url"], self.inventory.source_url)
        row = self.repo.read("Companies")[0]
        self.assertEqual(row["Blocked Reason"], "")
        self.assertEqual(row["ATS / Source"], "Greenhouse")
        self.assertTrue(row["Last Checked"])
        self.assertEqual(row["Official Careers URL"], PAGE)

    def test_changed_board_at_same_careers_url_never_closes_old_jobs(self):
        self.scan()
        original = self.repo.read("Job History")[0]
        self.inventory = Inventory("complete", [], source_url="https://api.ashbyhq.com/posting-api/job-board/acme")
        self.scan()
        self.scan()
        self.assertEqual(self.repo.read("Job History")[0], original)

    def test_same_board_still_counts_complete_absences(self):
        self.scan()
        self.inventory = Inventory("complete", [], source_url=BOARD + "/jobs?content=true")
        self.scan()
        self.assertEqual(self.repo.read("Job History")[0]["Consecutive Missing Scans"], 1)
        self.scan()
        self.assertEqual(self.repo.read("Job History")[0]["Job Status"], "Closed")

    def test_partial_discovery_never_counts_absences(self):
        self.scan()
        original = self.repo.read("Job History")[0]
        self.inventory = Inventory("partial", [], source_url=BOARD + "/jobs?content=true")
        self.scan()
        self.scan()
        self.assertEqual(self.repo.read("Job History")[0], original)

    def test_legacy_direct_board_baseline_still_matches(self):
        self.scan()
        tables = self.repo.tables
        snapshot = unpack_snapshot(tables["Job History"][0]["Current Snapshot"])
        snapshot["inventory_source"] = "https://boards.greenhouse.io/acme"
        tables["Job History"][0]["Current Snapshot"] = pack_snapshot(snapshot)
        self.repo._sheets = MemoryRepository(tables)._sheets
        self.inventory = Inventory("complete", [], source_url=BOARD + "/jobs?content=true")
        self.scan()
        self.assertEqual(self.repo.read("Job History")[0]["Consecutive Missing Scans"], 1)


if __name__ == "__main__":
    unittest.main()
