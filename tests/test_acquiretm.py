import json
import unittest

from job_search_helper.acquiretm import SOURCE, _DetailClient, inventory, posting, fetch_acquiretm
from job_search_helper.ats import FetchError


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
