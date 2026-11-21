from contextlib import nullcontext
from hashlib import sha256
import json
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from job_search_helper.acquiretm import SOURCE, _DetailClient, inventory, posting, fetch_acquiretm
from job_search_helper.ats import FetchError, HTTPResponse, fetch_inventory, validate_outcome_failure
from job_search_helper.browser_scraper import with_browser_fallback


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


class UpdatePanelPage:
    """Advance the exact clicked page only after its simulated async update."""

    def __init__(self, mode):
        self.mode = mode
        self.url = SOURCE
        self.number = 1
        self.clock_ns = 0
        self.events = []

    def goto(self, url, **kwargs):
        assert url == SOURCE
        self.number = 1
        self.events.append('listing')

    def content(self):
        return '<html><body>' + self.body_html() + '</body></html>'

    def body_html(self):
        total = 3 if self.mode == 'changed_total' and self.number == 2 else 2
        return html(self.number, total)

    def get_by_role(self, role, *, name, exact):
        assert (role, name, exact) == ('link', 'Go to page 2 of job results', True)

        def click(**kwargs):
            self.events.append('click_page_2')
            if self.mode == 'immediate':
                self.number = 2

        return SimpleNamespace(click=click)

    def wait_for_function(self, predicate, *, arg, timeout):
        if isinstance(arg, str):
            self.events.append('old_wait')
            if self.mode == 'timeout':
                raise TimeoutError('synthetic initial wait timeout')
            # The old wait sees a different representation even while page one is visible.
            assert 'document.body.innerHTML !== old' in predicate and self.body_html() != arg
            self.clock_ns += 2_000_000
            return
        self.events.append('membership_wait')
        assert arg == {'path': '/job_details_clean.aspx', 'seen': ['1']}
        assert 'previous.has(id)' in predicate and timeout == 11_998
        if self.mode == 'same_page':
            raise TimeoutError('synthetic persistent repeat')
        self.clock_ns += 18_000_000
        self.number = 2


class AcquireTests(unittest.TestCase):
    def test_complete_two_pages(self):
        self.assertEqual(set(inventory(Page())), {"1", "2"})

    def test_missing_and_repeated_pages(self):
        for page in [Page(repeat=True), Page(total=3)]:
            with self.assertRaises(FetchError):
                inventory(page)

    def test_normal_dispatch_types_only_the_proven_premature_page_two_read(self):
        for mode in ('delayed', 'timeout', 'same_page', 'changed_total', 'immediate'):
            with self.subTest(mode=mode):
                page = UpdatePanelPage(mode)
                detail_urls = []

                def get(url, **kwargs):
                    identifier = url.removeprefix(SOURCE.replace('home.aspx', 'job_details_clean.aspx?ID='))
                    assert identifier in {'1', '2'}
                    detail_urls.append(url)
                    entry = {'id': identifier, 'url': url, 'title': f'Engineer {identifier}'}
                    return HTTPResponse(200, detail(entry).encode())

                context = SimpleNamespace(new_page=lambda: page, request=SimpleNamespace(get=get))
                browser = SimpleNamespace(new_context=lambda: context, close=lambda: page.events.append('closed'))
                playwright = SimpleNamespace(chromium=SimpleNamespace(launch=lambda **kwargs: browser))
                fake = SimpleNamespace(sync_playwright=lambda: nullcontext(playwright))
                with (patch.dict(sys.modules, {'playwright.sync_api': fake}),
                      patch('job_search_helper.acquiretm.time.monotonic_ns', lambda: page.clock_ns),
                      patch.object(_DetailClient, '_cooldown')):
                    result = with_browser_fallback(fetch_inventory)(
                        'AcquireTM', SOURCE, 'COMP-0490', 'Amphenol Aerospace',
                    )

                self.assertEqual((result.ats, result.source_url), ('AcquireTM', SOURCE))
                if mode == 'immediate':
                    self.assertEqual(result.status, 'complete', result.reason)
                    self.assertEqual({job['posting_id'] for job in result.jobs}, {'1', '2'})
                    self.assertEqual(len(detail_urls), 2)
                    self.assertEqual(page.events.count('click_page_2'), 2)
                    self.assertNotIn('membership_wait', page.events)
                    self.assertIsNone(result.outcome_failure)
                    continue

                self.assertEqual((result.status, result.jobs, detail_urls), ('partial', [], []))
                self.assertEqual(page.events.count('click_page_2'), 1)
                self.assertEqual(page.events.count('membership_wait'), 0 if mode == 'timeout' else 1)
                if mode != 'delayed':
                    self.assertIsNone(result.outcome_failure)
                    continue

                first = sha256(b'["1"]').hexdigest()
                refreshed = sha256(b'["2"]').hexdigest()
                expected = {
                    'schema': 'outcome-failure-v1', 'category': 'pagination_regression',
                    'evidence_code': 'acquiretm_updatepanel_premature_read',
                    'evidence': {
                        'page': 2, 'advertised_total': 2, 'first_page_count': 1, 'refreshed_page_count': 1,
                        'first_page_ids_sha256': first, 'premature_page_ids_sha256': first,
                        'refreshed_page_ids_sha256': refreshed, 'premature_elapsed_ms': 2,
                        'refreshed_elapsed_ms': 20,
                    },
                }
                self.assertEqual(result.outcome_failure, expected)
                self.assertEqual(validate_outcome_failure(result.outcome_failure), expected)
                self.assertIsNone(validate_outcome_failure({key: value for key, value in expected.items()
                                                            if key != 'evidence'}))

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

    def test_detail_client_reuses_good_body_and_retries_rate_limit(self):
        entry = {"id": "1", "title": "Engineer 1", "url": SOURCE.replace("home.aspx", "job_details_clean.aspx?ID=1")}
        class Response:
            def __init__(self, status, body, headers=None):
                self.status, self.body, self.headers = status, body.encode(), headers or {}
        class Request:
            def __init__(self): self.calls = 0
            def get(self, url, **kwargs):
                self.calls += 1
                return Response(429, "Too Many Requests", {"Retry-After": "0"}) if self.calls == 1 else Response(200, detail(entry))
        request = Request()
        sleeps = []
        client = _DetailClient(request, interval=0, sleep=sleeps.append)
        self.assertIn("JobPosting", client.get_body(entry["url"]))
        self.assertEqual(client.get_body(entry["url"]), client.get_body(entry["url"]))
        self.assertEqual(request.calls, 2)

    def test_scope(self):
        self.assertEqual(fetch_acquiretm(SOURCE + "?filter=1", "c", "Amphenol").status, "unsupported")


if __name__ == "__main__":
    unittest.main()
