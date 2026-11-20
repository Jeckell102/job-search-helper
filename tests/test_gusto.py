from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.gusto import SOURCE

COMPANY_ID = "COMP-0180"
COMPANY = "Ascent AeroSystems"
ROLE = "https://jobs.gusto.com/postings/robinson-unmanned-test-role-11111111-1111-1111-1111-111111111111"


class Pages:
    def __init__(self, board, detail=None, status=200):
        self.board = board
        self.detail = detail or ""
        self.status = status
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        if url == SOURCE:
            return HTTPResponse(self.status, self.board.encode(), {})
        if url == ROLE:
            return HTTPResponse(200, self.detail.encode(), {})
        return HTTPResponse(404, b"", {})


def test_explicit_zero_board_is_complete():
    page = Pages("<main><h1>Robinson Unmanned</h1><p>There are no open positions currently</p></main>")
    result = fetch_inventory("Gusto", SOURCE, COMPANY_ID, COMPANY, discovery_transport=page)
    assert result.status == "complete"
    assert result.jobs == []
    assert page.calls.count(SOURCE) == 2


def test_posting_json_ld_is_normalized_and_reread():
    board = f'<main><a href="{ROLE}">Engineer</a></main>'
    detail = '''<script type="application/ld+json">{"@type":"JobPosting","title":"Flight Software Engineer","description":"Build safe autonomous aircraft systems with a cross-functional engineering team. This is a complete posting description.","hiringOrganization":{"name":"Robinson Unmanned"},"jobLocation":{"address":{"addressLocality":"Wilmington","addressRegion":"MA","addressCountry":"US"}},"datePosted":"2026-11-01"}</script>'''
    result = fetch_inventory("Gusto", SOURCE, COMPANY_ID, COMPANY, discovery_transport=Pages(board, detail))
    assert result.status == "complete", result.reason
    assert len(result.jobs) == 1
    assert result.jobs[0]["title"] == "Flight Software Engineer"


def test_denied_board_is_blocked():
    result = fetch_inventory("Gusto", SOURCE, COMPANY_ID, COMPANY, discovery_transport=Pages("", status=403))
    assert result.status == "blocked"
