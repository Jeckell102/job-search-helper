from collections import Counter

from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.foretellix import SOURCE, fetch_foretellix


COMPANY_ID = "COMP-0227"
COMPANY = "Foretellix"
ROLE = SOURCE + "field-engineer"


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


def test_validated_explicit_zero_is_complete():
    page = ("<html><title>Career - Foretellix</title><main><h1>Careers</h1>"
            "<p>Foretellix careers</p><h2>Open Positions</h2>"
            "<p>No open positions at the moment. Check back soon!</p></main></html>")
    result = fetch_foretellix(SOURCE, COMPANY_ID, COMPANY, Pages(page))
    assert result.status == "complete"
    assert result.jobs == []


def test_only_exact_zero_phrase_is_accepted():
    page = "<main><h1>Careers</h1><p>Foretellix career opportunities</p><p>No current openings.</p></main>"
    assert fetch_foretellix(SOURCE, COMPANY_ID, COMPANY, Pages(page)).status == "partial"


def test_dynamic_role_link_fetches_full_description_and_dispatches():
    root = (f'<main><h1>Careers</h1><p>Foretellix career opportunities</p>'
            f'<a href="{ROLE}">Field Engineer</a></main>')
    detail = "<main><h1>Field Engineer</h1><p>" + ("Validate autonomous vehicle systems. " * 12) + "</p></main>"
    result = fetch_inventory("Foretellix careers", SOURCE, COMPANY_ID, COMPANY,
                            discovery_transport=Pages(root, detail))
    assert result.status == "complete", result.reason
    assert result.jobs[0]["url"] == ROLE
    assert "Validate autonomous vehicle systems" in result.jobs[0]["description"]


def test_redirect_error_challenge_blank_contradiction_and_identity_fail_closed():
    valid = ("<main><h1>Careers</h1><p>Foretellix careers</p>"
             "<p>No open positions at the moment. Check back soon!</p></main>")
    assert fetch_foretellix(SOURCE, COMPANY_ID, COMPANY, Pages(valid, status=302)).status == "partial"
    assert fetch_foretellix(SOURCE, COMPANY_ID, COMPANY,
                            Pages("<html><title>Just a moment</title><p>Verify you are human</p></html>")).status == "blocked"
    assert fetch_foretellix(SOURCE, COMPANY_ID, COMPANY, Pages("<html></html>")).status == "partial"
    contradictory = valid.replace("</p></main>", f'</p><a href="{ROLE}">Role</a></main>')
    assert fetch_foretellix(SOURCE, COMPANY_ID, COMPANY, Pages(contradictory)).status == "partial"
    wrong = valid.replace("Foretellix", "Other Employer")
    assert fetch_foretellix(SOURCE, COMPANY_ID, COMPANY, Pages(wrong)).status == "partial"
    assert fetch_foretellix(SOURCE, "OTHER", COMPANY, Pages(valid)).status == "unsupported"
    assert fetch_foretellix(SOURCE, COMPANY_ID, "Other Employer", Pages(valid)).status == "unsupported"


def test_dispatch_is_exact_company_and_source():
    from unittest.mock import patch
    from job_search_helper.ats import Inventory

    with patch("job_search_helper.foretellix.fetch_foretellix",
               return_value=Inventory("complete", [], ats="Foretellix careers")) as adapter:
        result = fetch_inventory("Foretellix careers", SOURCE, COMPANY_ID, COMPANY,
                                discovery_transport=Pages("valid"))
    assert result.status == "complete"
    assert adapter.call_args.args[:3] == (SOURCE, COMPANY_ID, COMPANY)
    assert fetch_inventory("Foretellix careers", SOURCE, "OTHER", COMPANY,
                           discovery_transport=Pages("valid")).status != "complete"
