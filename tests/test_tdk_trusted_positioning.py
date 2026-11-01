from collections import Counter

from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.tdk_trusted_positioning import SOURCE, fetch_tdk_trusted_positioning

COMPANY_ID = "COMP-0330"
COMPANY = "TDK Trusted Positioning"
ROLE = SOURCE + "/software-engineer"


class Pages:
    def __init__(self, root, role=None, status=200):
        self.pages = {SOURCE: root}
        if role is not None:
            self.pages[ROLE] = role
        self.status = status
        self.calls = Counter()

    def get(self, url):
        self.calls[url] += 1
        body = self.pages.get(url, "Not found")
        if isinstance(body, str):
            body = body.encode()
        return HTTPResponse(self.status if url == SOURCE else 200, body, {"content-type": "text/html"})


def zero_page(extra=""):
    return ("<main><h1>Careers - TDK Trusted Positioning</h1>"
            "<h2>Join TDK Trusted Positioning</h2><p>Explore careers with TDK Trusted Positioning.</p>"
            "<h3>Open positions</h3><p>There are currently no open positions.</p>"
            f"<a href=\"mailto:careers@example.com\">Send your resume</a>{extra}</main>")


def test_validated_zero_excludes_generic_resume_invitation():
    result = fetch_tdk_trusted_positioning(SOURCE, COMPANY_ID, COMPANY, Pages(zero_page()))
    assert result.status == "complete"
    assert result.jobs == []


def test_live_current_openings_phrase_is_complete_zero():
    page = ("<main><h1>Careers - TDK Trusted Positioning</h1>"
            "<h2>Current Job Openings</h2><p>No Current Openings.</p></main>")
    result = fetch_tdk_trusted_positioning(SOURCE, COMPANY_ID, COMPANY, Pages(page))
    assert result.status == "complete"
    assert result.jobs == []


def test_dynamic_role_fetches_full_description_and_dispatches():
    root = ("<main><h1>Careers - TDK Trusted Positioning</h1>"
            f'<a href="{ROLE}">Software Engineer</a></main>')
    detail = "<main><h1>Software Engineer</h1><p>" + ("Build trusted positioning systems. " * 12) + "</p></main>"
    result = fetch_inventory("Browser", SOURCE, COMPANY_ID, COMPANY, discovery_transport=Pages(root, detail))
    assert result.status == "complete", result.reason
    assert result.jobs[0]["url"] == ROLE
    assert "Build trusted positioning systems" in result.jobs[0]["description"]


def test_fail_closed_for_wrong_source_challenge_blank_and_contradiction():
    assert fetch_tdk_trusted_positioning(SOURCE, "OTHER", COMPANY, Pages(zero_page())).status == "unsupported"
    assert fetch_tdk_trusted_positioning(SOURCE, COMPANY_ID, COMPANY, Pages(zero_page(), status=403)).status == "blocked"
    assert fetch_tdk_trusted_positioning(SOURCE, COMPANY_ID, COMPANY, Pages("<html><title>Just a moment</title><p>Verify you are human</p></html>")).status == "blocked"
    assert fetch_tdk_trusted_positioning(SOURCE, COMPANY_ID, COMPANY, Pages(zero_page(), status=404)).status == "partial"
    assert fetch_tdk_trusted_positioning(SOURCE, COMPANY_ID, COMPANY, Pages("<html></html>")).status == "partial"
    assert fetch_tdk_trusted_positioning(SOURCE, COMPANY_ID, COMPANY, Pages(zero_page(f'<a href="{ROLE}">Role</a>'))).status == "partial"


def test_resume_invitation_alone_does_not_close_inventory():
    page = ("<main><h1>Careers - TDK Trusted Positioning</h1>"
            "<p>Send your resume to careers@example.com for future opportunities.</p></main>")
    assert fetch_tdk_trusted_positioning(SOURCE, COMPANY_ID, COMPANY, Pages(page)).status == "partial"
