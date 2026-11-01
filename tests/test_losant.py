from collections import Counter

from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.losant import SOURCE, fetch_losant


COMPANY_ID = "COMP-0277"
COMPANY = "Losant"
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
        return HTTPResponse(self.status if url == SOURCE else 200,
                            self.pages.get(url, "Not found").encode(),
                            {"content-type": "text/html"})


def test_explicit_zero_openings_is_complete():
    page = ("<main><h1>The Losant Team</h1><p>Losant career opportunities</p>"
            "<p>Currently, we are not actively seeking job candidates.</p></main>")
    result = fetch_losant(SOURCE, COMPANY_ID, COMPANY, Pages(page))
    assert result.status == "complete"
    assert result.jobs == []


def test_dynamic_role_link_fetches_full_description_and_dispatches():
    root = (f'<main><h1>Careers at Losant</h1><p>Explore current Losant opportunities.</p>'
            f'<a href="{ROLE}">Software Engineer</a></main>')
    detail = "<main><h1>Software Engineer</h1><p>" + ("Build the IoT platform. " * 12) + "</p></main>"
    result = fetch_inventory("Browser", SOURCE, COMPANY_ID, COMPANY,
                             discovery_transport=Pages(root, detail))
    assert result.status == "complete", result.reason
    assert result.jobs[0]["url"] == ROLE
    assert "Build the IoT platform" in result.jobs[0]["description"]


def test_errors_challenges_blank_silent_shell_contradiction_and_identity_fail_closed():
    page = Pages("<main><h1>Careers</h1><p>Losant</p><p>Currently, we are not actively seeking job candidates.</p></main>", status=404)
    assert fetch_losant(SOURCE, COMPANY_ID, COMPANY, page).status == "partial"
    challenge = Pages("<html><title>Just a moment</title><p>Verify you are human</p></html>")
    assert fetch_losant(SOURCE, COMPANY_ID, COMPANY, challenge).status == "blocked"
    assert fetch_losant(SOURCE, COMPANY_ID, COMPANY, Pages("<html></html>")).status == "partial"
    contradictory = f'<main><h1>Careers at Losant</h1><p>Currently, we are not actively seeking job candidates.</p><a href="{ROLE}">Role</a></main>'
    assert fetch_losant(SOURCE, COMPANY_ID, COMPANY, Pages(contradictory)).status == "partial"
    assert fetch_losant(SOURCE, "OTHER", COMPANY, Pages("valid page")).status == "unsupported"
    assert fetch_losant(SOURCE, COMPANY_ID, "Other Company", Pages("valid page")).status == "unsupported"
