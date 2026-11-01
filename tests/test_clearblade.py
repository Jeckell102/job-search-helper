from collections import Counter

from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.clearblade import SOURCE, fetch_clearblade

COMPANY_ID = "COMP-0275"
COMPANY = "ClearBlade"
ROLES = [
    ("Software Executives", "ClearBlade is looking for successful Software Sales Executives with a proven track record selling enterprise software solutions to a technical audience."),
    ("Software Sales Engineers", "ClearBlade is looking for Sales Engineers with a strong software technical background and experience successfully solving customer problems with enterprise software solutions."),
    ("Software Engineers", "ClearBlade is looking for Software Engineers who want to build new features for its IoT Platform."),
]


class Pages:
    def __init__(self, root, statuses=None):
        self.root = root
        self.statuses = statuses or {}
        self.calls = Counter()

    def get(self, url):
        self.calls[url] += 1
        return HTTPResponse(self.statuses.get(url, 200), self.root.encode(), {"content-type": "text/html"})


def listing(extra=""):
    cards = "".join(
        f'<div class="cop_cms_item" role="listitem"><div class="cop_card"><h3 class="cop_card_title">{title}</h3><div><p>{description}</p></div><a href="mailto:careers@clearblade.com">Apply now</a></div></div>'
        for title, description in ROLES
    )
    return f'<main><h1>ClearBlade Careers</h1><h2>Open positions.</h2><div class="cop_cms_wrap">{cards}{extra}</div></main>'


def test_discovers_deduplicated_cards_with_stable_ids_and_rereads():
    duplicate = '<div class="cop_cms_item"><h3 class="cop_card_title">Software Engineers</h3><p>' + ROLES[2][1] + '</p></div>'
    pages = Pages(listing(duplicate))
    result = fetch_inventory("Browser", SOURCE, COMPANY_ID, COMPANY, discovery_transport=pages)
    assert result.status == "complete", result.reason
    assert [job["title"] for job in result.jobs] == sorted(title for title, _ in ROLES)
    assert [job["posting_id"] for job in result.jobs] == ["clearblade-card-software-engineers", "clearblade-card-software-executives", "clearblade-card-software-sales-engineers"]
    assert pages.calls[SOURCE] == 2
    assert all(job["description"] for job in result.jobs)


def test_rejects_wrong_scope_and_incomplete_cards():
    assert fetch_clearblade(SOURCE, "OTHER", COMPANY, Pages(listing())).status == "unsupported"
    short = listing().replace(ROLES[1][1], "")
    assert fetch_clearblade(SOURCE, COMPANY_ID, COMPANY, Pages(short)).status == "partial"


def test_fails_closed_for_blocked_blank_and_unstable_inventory():
    assert fetch_clearblade(SOURCE, COMPANY_ID, COMPANY, Pages(listing(), {SOURCE: 403})).status == "blocked"
    assert fetch_clearblade(SOURCE, COMPANY_ID, COMPANY, Pages("<html></html>")).status == "partial"
    pages = Pages(listing())
    original = pages.get
    def drift(url):
        response = original(url)
        if url == SOURCE and pages.calls[url] == 2:
            response = HTTPResponse(200, listing().replace(ROLES[-1][0], "Different Role").encode(), {})
        return response
    pages.get = drift
    assert fetch_clearblade(SOURCE, COMPANY_ID, COMPANY, pages).status == "partial"
