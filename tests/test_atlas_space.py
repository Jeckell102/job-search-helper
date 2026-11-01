from collections import Counter

from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.atlas_space import SOURCE, fetch_atlas_space


COMPANY_ID = "COMP-0362"
COMPANY = "ATLAS Space Operations"
ROLE = SOURCE + "satellite-network-engineer/"


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
    page = "<html><main><h1>Join the ATLAS Team</h1><p>Current Openings</p><p>No current openings. Please continue to check back.</p></main></html>"
    result = fetch_atlas_space(SOURCE, COMPANY_ID, COMPANY, Pages(page))
    assert result.status == "complete"
    assert result.jobs == []


def test_authoritative_active_openings_phrase_is_complete_zero():
    page = "<main><h1>Join the ATLAS Team</h1><h2>Current Openings</h2><p>No active job openings.</p></main>"
    result = fetch_atlas_space(SOURCE, COMPANY_ID, COMPANY, Pages(page))
    assert result.status == "complete"
    assert result.jobs == []


def test_dynamic_role_link_fetches_full_description_and_dispatches():
    root = f'<main><h1>Join the ATLAS Team</h1><a href="{ROLE}">Satellite Network Engineer</a></main>'
    detail = "<main><h1>Satellite Network Engineer</h1><p>" + ("Build satellite network systems. " * 12) + "</p></main>"
    result = fetch_inventory("ATLAS Space careers", SOURCE, COMPANY_ID, COMPANY, discovery_transport=Pages(root, detail))
    assert result.status == "complete", result.reason
    assert result.jobs[0]["url"] == ROLE
    assert "Build satellite network systems" in result.jobs[0]["description"]


def test_errors_challenges_blank_and_identity_mismatches_fail_closed():
    page = Pages("<main><h1>Join the ATLAS Team</h1><p>No current openings.</p></main>", status=404)
    assert fetch_atlas_space(SOURCE, COMPANY_ID, COMPANY, page).status == "partial"
    challenge = Pages("<html><title>Just a moment</title><p>Verify you are human</p></html>")
    assert fetch_atlas_space(SOURCE, COMPANY_ID, COMPANY, challenge).status == "blocked"
    assert fetch_atlas_space(SOURCE, COMPANY_ID, COMPANY, Pages("server error", status=500)).status == "partial"
    assert fetch_atlas_space(SOURCE, "OTHER", COMPANY, Pages("valid page")).status == "unsupported"
    assert fetch_atlas_space(SOURCE, COMPANY_ID, "Other Company", Pages("valid page")).status == "unsupported"
    assert fetch_atlas_space(SOURCE, COMPANY_ID, COMPANY, Pages("<html></html>")).status == "partial"
