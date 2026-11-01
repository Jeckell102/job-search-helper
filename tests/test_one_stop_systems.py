from collections import Counter

from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.one_stop_systems import SOURCE, fetch_one_stop_systems


LISTING = b'''<html><main><h1>Careers</h1><h2>Open Positions</h2>
<a href="/pages/software-architect-manager">Software Architect Manager</a>
<a href="/pages/firmware-engineer">Firmware Engineer</a>
<a href="/pages/contact-hr">Contact HR</a></main></html>'''
DETAIL = b'''<html><main><h1>Software Architect Manager</h1>
<h2>Summary</h2><p>One Stop Systems is hiring a software architect manager.</p>
<h2>Responsibilities</h2><ul><li>Lead software architecture and engineering teams.</li></ul>
</main><footer>One Stop Systems</footer></html>'''


class Pages:
    def __init__(self, listing=LISTING, detail=DETAIL, statuses=None):
        self.listing = listing
        self.detail = detail
        self.statuses = statuses or {}
        self.calls = Counter()

    def get(self, url):
        self.calls[url] += 1
        return HTTPResponse(self.statuses.get(url, 200), self.listing if url == SOURCE else self.detail, {})


def test_fetches_first_party_roles_and_rereads_inventory():
    pages = Pages()
    result = fetch_inventory("Shopify", SOURCE, "COMP-0287", "One Stop Systems", discovery_transport=pages)
    assert result.status == "complete", result.reason
    assert len(result.jobs) == 2
    assert {job["posting_id"] for job in result.jobs} == {"software-architect-manager", "firmware-engineer"}
    assert all("Responsibilities" in job["description"] for job in result.jobs)
    assert pages.calls[SOURCE] == 2


def test_rejects_wrong_identity_and_blocked_source():
    pages = Pages(statuses={SOURCE: 429})
    assert fetch_one_stop_systems(SOURCE, "COMP-0287", "Other", pages).status == "unsupported"
    assert fetch_one_stop_systems(SOURCE, "COMP-0287", "One Stop Systems", pages).status == "blocked"


def test_detects_inventory_drift():
    pages = Pages()
    original = pages.listing
    def changing_get(url):
        pages.calls[url] += 1
        if url == SOURCE and pages.calls[url] == 2:
            return HTTPResponse(200, original.replace(b"firmware-engineer", b"electrical-engineer"), {})
        return HTTPResponse(200, pages.listing if url == SOURCE else pages.detail, {})
    pages.get = changing_get
    assert fetch_inventory("Shopify", SOURCE, "COMP-0287", "One Stop Systems", discovery_transport=pages).status == "partial"
