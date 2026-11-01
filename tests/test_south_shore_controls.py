from collections import Counter

from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.south_shore_controls import SOURCE, fetch_south_shore_controls

COMPANY_ID = "COMP-0403"
COMPANY = "South Shore Controls"
ROLES = sorted([
    SOURCE.rstrip("/") + "-automation-controls-engineer/",
    SOURCE.rstrip("/") + "-electrical-systems-planner/",
    SOURCE.rstrip("/") + "-electrical-panel-builder/",
])


class Pages:
    def __init__(self, root, details=None, statuses=None):
        self.pages = {SOURCE: root, **(details or {})}
        self.statuses = statuses or {}
        self.calls = Counter()

    def get(self, url):
        self.calls[url] += 1
        return HTTPResponse(self.statuses.get(url, 200), self.pages.get(url, b"Not found").encode(), {"content-type": "text/html"})


def listing(extra=""):
    links = "".join(f'<a href="{url}">Role</a>' for url in ROLES)
    return f"<main><h1>South Shore Controls Career Opportunities</h1><h2>Available Roles</h2>{links}{extra}</main>"


def detail(title, body="Published responsibilities and qualifications. " * 15):
    return f"<main><h1>Contact Us</h1><h2>{title}</h2><p>South Shore Controls</p><p>Position Overview</p><p>{body}</p><form><p>Contact Information</p></form></main>"


def test_fetches_every_current_role_with_full_description_and_rereads_listing():
    pages = Pages(listing(), {url: detail(f"Role {i}") for i, url in enumerate(ROLES)})
    result = fetch_inventory("Browser", SOURCE, COMPANY_ID, COMPANY, discovery_transport=pages)
    assert result.status == "complete", result.reason
    assert [job["url"] for job in result.jobs] == ROLES
    assert all(len(job["description"]) > 100 for job in result.jobs)
    assert all("Contact Information" not in job["description"] for job in result.jobs)
    assert pages.calls[SOURCE] == 2


def test_rejects_wrong_scope_and_missing_or_removed_role_pages():
    assert fetch_south_shore_controls(SOURCE, "OTHER", COMPANY, Pages(listing())).status == "unsupported"
    missing = Pages(listing(), {ROLES[0]: detail("Role")}, {ROLES[1]: 404})
    assert fetch_south_shore_controls(SOURCE, COMPANY_ID, COMPANY, missing).status == "partial"
    short = Pages(listing(), {url: detail("Role") for url in ROLES} | {ROLES[2]: "<main><h1>Role</h1></main>"})
    assert fetch_south_shore_controls(SOURCE, COMPANY_ID, COMPANY, short).status == "partial"


def test_fail_closed_for_blocked_blank_and_unstable_listing():
    blocked = Pages(listing(), statuses={SOURCE: 403})
    assert fetch_south_shore_controls(SOURCE, COMPANY_ID, COMPANY, blocked).status == "blocked"
    assert fetch_south_shore_controls(SOURCE, COMPANY_ID, COMPANY, Pages("<html></html>")).status == "partial"
    changing = Pages(listing(), {url: detail("Role") for url in ROLES})
    changing.pages[SOURCE] = listing()
    original = changing.get
    def drift(url):
        response = original(url)
        if url == SOURCE and changing.calls[url] == 2:
            response = HTTPResponse(200, listing().replace(ROLES[-1], "").encode(), {})
        return response
    changing.get = drift
    assert fetch_south_shore_controls(SOURCE, COMPANY_ID, COMPANY, changing).status == "partial"
