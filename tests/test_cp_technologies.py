from collections import Counter

from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.cp_technologies import SOURCE, fetch_cp_technologies


COMPANY_ID = "COMP-0430"
COMPANY = "CP Technologies"
ROLE = SOURCE + "network-engineer/"


class Pages:
    def __init__(self, root, role=None, status=200):
        self.pages = {SOURCE: root}
        if role is not None:
            self.pages[ROLE] = role
        self.status = status
        self.calls = Counter()

    def get(self, url):
        self.calls[url] += 1
        return HTTPResponse(self.status if url == SOURCE else 200,
                            self.pages.get(url, "Not found").encode(),
                            {"content-type": "text/html"})


def test_explicit_zero_openings_is_complete():
    page = "<main><h1>Careers</h1><p>CP Technologies career opportunities</p><p>No current openings. Please continue to check back.</p></main>"
    result = fetch_cp_technologies(SOURCE, COMPANY_ID, COMPANY, Pages(page))
    assert result.status == "complete"
    assert result.jobs == []


def test_dynamic_role_link_fetches_full_description_and_dispatches():
    root = f'<main><h1>Careers</h1><p>Explore current CP Technologies career opportunities.</p><a href="{ROLE}">Network Engineer</a></main>'
    detail = "<main><h1>Network Engineer</h1><p>" + ("Build communications systems. " * 12) + "</p></main>"
    result = fetch_inventory("Direct inquiry", SOURCE, COMPANY_ID, COMPANY, discovery_transport=Pages(root, detail))
    assert result.status == "complete", result.reason
    assert result.jobs[0]["url"] == ROLE
    assert "Build communications systems" in result.jobs[0]["description"]


def test_errors_challenges_blank_silent_shell_contradiction_and_identity_fail_closed():
    page = Pages("<main><h1>Careers</h1><p>CP Technologies career opportunities</p><p>No current openings.</p></main>", status=404)
    assert fetch_cp_technologies(SOURCE, COMPANY_ID, COMPANY, page).status == "partial"
    challenge = Pages("<html><title>Just a moment</title><p>Verify you are human</p></html>")
    assert fetch_cp_technologies(SOURCE, COMPANY_ID, COMPANY, challenge).status == "blocked"
    assert fetch_cp_technologies(SOURCE, COMPANY_ID, COMPANY, Pages("<html></html>")).status == "partial"
    contradictory = f'<main><h1>Careers</h1><p>No current openings.</p><a href="{ROLE}">Role</a></main>'
    assert fetch_cp_technologies(SOURCE, COMPANY_ID, COMPANY, Pages(contradictory)).status == "partial"
    assert fetch_cp_technologies(SOURCE, "OTHER", COMPANY, Pages("valid page")).status == "unsupported"
    assert fetch_cp_technologies(SOURCE, COMPANY_ID, "Other Company", Pages("valid page")).status == "unsupported"
