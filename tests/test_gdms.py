import unittest

from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.gdms import SOURCE


LONG = "This public General Dynamics Mission Systems posting describes the role, responsibilities, qualifications, work environment, and expected collaboration with program teams. " * 3


def listing(rows, next_page=False):
    links = "".join(f'<a href="/careers/{slug}-2026-{ident}-opportunity">{title}</a>'
                     for ident, slug, title in rows)
    if next_page:
        links += '<a href="/careers/job-search?page=0">1</a><a href="/careers/job-search?page=1">2</a>'
    else:
        links += '<a href="/careers/job-search?page=0">1</a><a href="/careers/job-search?page=1">2</a>'
    return f"<html><body>{links}</body></html>"


def detail(title):
    return f"<html><body><h1>{title}</h1><p>{LONG}</p></body></html>"


class Pages:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        body = self.responses.get(url)
        if body is None:
            return HTTPResponse(404, b"", {})
        return HTTPResponse(200, body.encode(), {"content-type": "text/html"})


class GDMSIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.rows = [(75769, "devops-engineer-intern", "DevOps Engineer Intern"),
                     (76641, "advanced-billing-associate", "Advanced Billing Associate")]
        page0 = listing(self.rows[:1], next_page=True)
        page1 = listing(self.rows[1:], next_page=False)
        self.pages = Pages({
            SOURCE: page0,
            SOURCE + "?page=1": page1,
            "https://gdmissionsystems.com/careers/devops-engineer-intern-2026-75769-opportunity": detail("DevOps Engineer Intern"),
            "https://gdmissionsystems.com/careers/advanced-billing-associate-2026-76641-opportunity": detail("Advanced Billing Associate"),
        })

    def test_complete_inventory_routes_and_rereads(self):
        result = fetch_inventory("GDMS Careers", SOURCE, "COMP-0096",
                                 "General Dynamics Mission Systems", self.pages)
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual(len(result.jobs), 2)
        self.assertEqual([job["title"] for job in result.jobs],
                         ["DevOps Engineer Intern", "Advanced Billing Associate"])
        self.assertEqual(self.pages.calls.count(SOURCE), 2)
        self.assertEqual(self.pages.calls.count(SOURCE + "?page=1"), 2)

    def test_wrong_source_is_rejected(self):
        result = fetch_inventory("GDMS Careers", "https://gdmissionsystems.com/careers",
                                 "COMP-0096", "General Dynamics Mission Systems", self.pages)
        self.assertEqual(result.status, "unsupported")

    def test_unavailable_listing_is_blocked(self):
        pages = Pages({SOURCE: ""})
        pages.get = lambda url: HTTPResponse(403, b"", {})
        result = fetch_inventory("GDMS Careers", SOURCE, "COMP-0096",
                                 "General Dynamics Mission Systems", pages)
        self.assertEqual(result.status, "blocked")

    def test_routing_uses_installed_adapter(self):
        result = fetch_inventory("GDMS Careers", SOURCE, "COMP-0096",
                                 "General Dynamics Mission Systems", self.pages)
        self.assertEqual(result.ats, "GDMS Careers")


if __name__ == "__main__":
    unittest.main()
