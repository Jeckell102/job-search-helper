import json
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

from job_search_helper import acquiretm
from job_search_helper.acquiretm import SOURCE, _DetailClient, inventory, posting, fetch_acquiretm
from job_search_helper.ats import FetchError, fetch_inventory


DESC = "Responsibilities and qualifications. " * 12


def html(ident, total=2):
    return (f'<div>{total} positions found.</div>'
            f'<a href="job_details_clean.aspx?ID={ident}">Engineer {ident}</a>'
            f'<a aria-label="Go to page {2 if ident == 1 else 1} of job results">page</a>')


class Page:
    def __init__(self, repeat=False, total=2):
        self.number, self.repeat, self.total, self.url = 1, repeat, total, SOURCE

    def goto(self, *args, **kwargs):
        self.number = 1

    def content(self):
        return html(1 if self.repeat else self.number, self.total)

    def wait_for_function(self, *args, **kwargs):
        return None

    def get_by_role(self, *args, **kwargs):
        owner = self
        class Link:
            def click(self, **kwargs):
                owner.number = int(kwargs.get("name", args[1]).split()[3]) if kwargs.get("name") else 2
        # The production call passes name as a keyword.
        class KeywordLink:
            def click(self, **kwargs):
                owner.number = int(args[0] if args else 2)
        class ExactLink:
            def click(self, **kwargs):
                owner.number = int(kwargs.get("name", "Go to page 2").split()[3])
        return ExactLink()


def detail(entry, *, employer="Amphenol Aerospace", description=DESC):
    record = {
        "@type": "JobPosting", "title": entry["title"],
        "identifier": {"value": entry["id"]}, "url": entry["url"],
        "hiringOrganization": {"name": employer}, "description": description,
    }
    return '<script type="application/ld+json">' + json.dumps(record) + '</script>'


class AcquireTests(unittest.TestCase):
    def test_complete_two_pages(self):
        self.assertEqual(set(inventory(Page())), {"1", "2"})

    def test_missing_and_repeated_pages(self):
        for page in [Page(repeat=True), Page(total=3)]:
            with self.assertRaises(FetchError):
                inventory(page)

    def test_schema_identity_full_body_and_employer(self):
        entry = {"id": "1", "title": "Engineer 1", "url": SOURCE.replace("home.aspx", "job_details_clean.aspx?ID=1")}
        result = posting(detail(entry), entry, "COMP-0490", "Amphenol Aerospace")
        self.assertEqual(result["posting_id"], "1")
        self.assertGreater(len(result["description"]), 120)
        for bad in ["Other Employer", "Amphenol Pcd"]:
            with self.assertRaises(FetchError):
                posting(detail(entry, employer=bad), entry, "COMP-0490", "Amphenol Aerospace")

    def test_short_or_rate_limit_body_never_counts_as_content(self):
        entry = {"id": "1", "title": "Engineer 1", "url": SOURCE.replace("home.aspx", "job_details_clean.aspx?ID=1")}
        for body in [detail(entry, description="short"), "<html><title>Too Many Requests</title></html>"]:
            with self.assertRaises(FetchError):
                posting(body, entry, "COMP-0490", "Amphenol Aerospace")

    def test_scope(self):
        self.assertEqual(fetch_acquiretm(SOURCE + "?filter=1", "c", "Amphenol").status, "unsupported")

    def test_normal_dispatch_paces_details_and_final_listing_from_response_completion(self):
        client = PacedDispatch(self)
        result = client.run()
        self.assertEqual(result.status, "complete")
        self.assertEqual({job["posting_id"] for job in result.jobs}, {"1", "2"})
        self.assertEqual(client.events, [("listing", 0), ("detail", 0), ("detail", 15), ("listing", 30)])

    def test_timeout_and_short_retry_after_use_response_spacing_then_cache(self):
        fixture = PacedDispatch(self, [TimeoutError(), (503, {"Retry-After": "5"})])
        client = fixture.make_client(fixture.request)
        url = fetch_url(1)
        body = client.get_body(url)
        self.assertIn("JobPosting", body)
        self.assertEqual(client.get_body(url), body)
        self.assertEqual(fixture.events, [("detail", 0), ("detail", 15), ("detail", 30)])

    def test_first_429_or_long_wait_blocks_without_a_second_call(self):
        for status, value in [(429, ""), (429, "0"), (429, "3600"), (503, "3600"), (503, "inf")]:
            with self.subTest(status=status, value=value):
                fixture = PacedDispatch(self, [(status, {"retry-after": value})])
                result = fixture.run()
                self.assertEqual(result.status, "blocked")
                self.assertFalse(result.jobs)
                if value:
                    self.assertIn("Retry-After", result.reason)
                self.assertEqual(fixture.events, [("listing", 0), ("detail", 0)])

    def test_partial_returns_after_detail_gap_before_company_can_retry(self):
        fixture = PacedDispatch(self, [TimeoutError()] * 3)
        result = fixture.run()
        self.assertEqual(result.status, "partial")
        self.assertEqual(fixture.events, [("listing", 0), ("detail", 0), ("detail", 15), ("detail", 30)])
        self.assertEqual(fixture.now, 45)

    def test_shutdown_failure_preserves_observed_provider_hold(self):
        for failure_point in ("browser", "playwright"):
            with self.subTest(failure_point=failure_point):
                fixture = PacedDispatch(self, [(429, {"Retry-After": "3600"})])
                result = fixture.run(failure_point=failure_point)
                self.assertEqual(result.status, "blocked")
                self.assertIn("Retry-After", result.reason)
                self.assertEqual(fixture.events, [("listing", 0), ("detail", 0)])


def fetch_url(ident):
    return SOURCE.replace("home.aspx", f"job_details_clean.aspx?ID={ident}")


class PacedDispatch:
    def __init__(self, test, responses=()):
        self.test = test
        self.responses = iter(responses)
        self.now = 0
        self.events = []
        self.page = Page()
        self.original_goto = self.page.goto
        self.page.goto = self.goto
        self.request = SimpleNamespace(get=self.get)

    def goto(self, *args, **kwargs):
        self.events.append(("listing", self.now))
        self.original_goto(*args, **kwargs)

    def sleep(self, delay):
        self.now += delay

    def make_client(self, request):
        return _DetailClient(request, clock=lambda: self.now, sleep=self.sleep)

    def get(self, url, *, max_redirects, timeout):
        self.test.assertEqual((max_redirects, timeout), (0, 30_000))
        self.events.append(("detail", self.now))
        self.now += 3
        reply = next(self.responses, None)
        if isinstance(reply, Exception):
            raise reply
        if reply is not None:
            status, headers = reply
            return SimpleNamespace(status=status, headers=headers)
        ident = url.rsplit("=", 1)[-1]
        body = detail({"id": ident, "title": f"Engineer {ident}", "url": url})
        return SimpleNamespace(status=200, headers={}, body=body.encode())

    def run(self, *, failure_point=None):
        def close():
            if failure_point == "browser":
                raise OSError("simulated browser shutdown error")

        context = SimpleNamespace(new_page=lambda: self.page, request=self.request)
        browser = SimpleNamespace(new_context=lambda: context, close=close)
        engine = SimpleNamespace(chromium=SimpleNamespace(launch=lambda **kwargs: browser))

        @contextmanager
        def playwright():
            try:
                yield engine
            finally:
                if failure_point == "playwright":
                    raise OSError("simulated Playwright shutdown error")

        with patch.object(acquiretm, "_DetailClient", self.make_client), patch(
            "playwright.sync_api.sync_playwright", playwright
        ):
            return fetch_inventory("AcquireTM", SOURCE, "COMP-0490", "Amphenol Aerospace")


if __name__ == "__main__":
    unittest.main()
