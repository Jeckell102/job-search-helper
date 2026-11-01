from collections import Counter

from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.parallel_flight import SOURCE, fetch_parallel_flight

COMPANY_ID = "COMP-0194"
COMPANY = "Parallel Flight Technologies"
ROLE = SOURCE + "/flight-test-engineer"


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
        return HTTPResponse(self.status if url == SOURCE else 200, body,
                            {"content-type": "text/html"})


def zero_page(extra=""):
    return ("<main><h1>Careers - Parallel Flight Technologies</h1>"
            "<h2>Join Our Team</h2><p>We welcome applicants and resumes.</p>"
            "<h3>Positions</h3><p>Please check back later for open positions!</p>"
            f"{extra}</main>")


def test_positions_zero_state_is_complete_but_resume_invitation_is_not_inventory():
    result = fetch_parallel_flight(SOURCE, COMPANY_ID, COMPANY, Pages(zero_page(
        '<a href="mailto:jobs@parallelflight.com">Send a resume</a>')))
    assert result.status == "complete"
    assert result.jobs == []


def test_dynamic_role_link_fetches_full_description_and_dispatches():
    root = ("<main><h1>Careers - Parallel Flight Technologies</h1>"
            f'<a href="{ROLE}">Flight Test Engineer</a></main>')
    detail = "<main><h1>Flight Test Engineer</h1><p>" + ("Test and validate aircraft systems. " * 12) + "</p></main>"
    result = fetch_inventory("Browser", SOURCE, COMPANY_ID, COMPANY,
                             discovery_transport=Pages(root, detail))
    assert result.status == "complete", result.reason
    assert result.jobs[0]["url"] == ROLE
    assert "Test and validate aircraft systems" in result.jobs[0]["description"]


def test_fail_closed_for_wrong_source_challenge_blank_and_contradiction():
    assert fetch_parallel_flight(SOURCE, "OTHER", COMPANY, Pages(zero_page())).status == "unsupported"
    assert fetch_parallel_flight(SOURCE, COMPANY_ID, COMPANY, Pages(zero_page(), status=403)).status == "blocked"
    assert fetch_parallel_flight(
        SOURCE, COMPANY_ID, COMPANY,
        Pages("<html><title>Just a moment</title><p>Verify you are human</p></html>"),
    ).status == "blocked"
    assert fetch_parallel_flight(SOURCE, COMPANY_ID, COMPANY, Pages(zero_page(), status=404)).status == "partial"
    assert fetch_parallel_flight(SOURCE, COMPANY_ID, COMPANY, Pages("<html></html>")).status == "partial"
    contradictory = zero_page(f'<a href="{ROLE}">Role</a>')
    assert fetch_parallel_flight(SOURCE, COMPANY_ID, COMPANY, Pages(contradictory)).status == "partial"


def test_generic_resume_invitation_without_positions_state_is_not_complete():
    page = ("<main><h1>Careers - Parallel Flight Technologies</h1>"
            "<p>Send your resume and portfolio to jobs@parallelflight.com.</p></main>")
    assert fetch_parallel_flight(SOURCE, COMPANY_ID, COMPANY, Pages(page)).status == "partial"

