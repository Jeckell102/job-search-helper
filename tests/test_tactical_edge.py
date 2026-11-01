from collections import Counter

from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.tactical_edge import SOURCE, fetch_tactical_edge

COMPANY_ID = "COMP-0453"
COMPANY = "Tactical Edge"

PAGE = b'''<html><title>Careers - Tactical Edge</title><h1>Careers</h1>
<h2>Open Positions</h2><div class="fusion-modal modal openpositions2">
<h3>Java and Oracle Developers (Huntsville, AL)</h3><div class="modal-body">
<p>Tactical Edge is a software engineering company responsible for designing software solutions.</p>
<h2>Position Description</h2><p>Tactical Edge is seeking junior Java and Oracle Developers.</p>
<h2>Duties and Responsibilities</h2><ul><li>Design, develop, code, test, and debug software.</li></ul>
<h2>Desired Qualifications</h2><ul><li>Experience with JavaScript and Oracle.</li></ul>
</div></div></html>'''


class Pages:
    def __init__(self, body=PAGE, statuses=None):
        self.body = body
        self.statuses = statuses or {}
        self.calls = Counter()

    def get(self, url):
        self.calls[url] += 1
        return HTTPResponse(self.statuses.get(url, 200), self.body, {})


def test_fetches_modal_role_and_rereads_page():
    pages = Pages()
    result = fetch_inventory("Browser", SOURCE, COMPANY_ID, COMPANY, discovery_transport=pages)
    assert result.status == "complete", result.reason
    assert len(result.jobs) == 1
    assert result.jobs[0]["title"] == "Java and Oracle Developers (Huntsville, AL)"
    assert "Duties and Responsibilities" in result.jobs[0]["description"]
    assert pages.calls[SOURCE] == 2


def test_rejects_wrong_scope_and_blocked_page():
    assert fetch_tactical_edge(SOURCE, "OTHER", COMPANY, Pages()).status == "unsupported"
    assert fetch_inventory("Browser", SOURCE, COMPANY_ID, COMPANY,
                           discovery_transport=Pages(statuses={SOURCE: 403})).status == "blocked"


def test_detects_reread_drift():
    pages = Pages()
    original = pages.body
    def changing_get(url):
        pages.calls[url] += 1
        body = original if pages.calls[url] == 1 else original.replace(b"Java and Oracle", b"Python")
        return HTTPResponse(200, body, {})
    pages.get = changing_get
    assert fetch_tactical_edge(SOURCE, COMPANY_ID, COMPANY, pages).status == "partial"
