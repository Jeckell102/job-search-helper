from job_search_helper.antenna_research_associates import (
    BOARD, COMPANY, COMPANY_ID, SOURCE, fetch_antenna_research_associates,
)
from job_search_helper.ats import HTTPResponse


class Pages:
    def __init__(self, values):
        self.values = values

    def get(self, url):
        return HTTPResponse(200, self.values[url].encode(), {})


SOURCE_HTML = f'<a href="{BOARD}">Apply Here for All Locations</a>'
BOARD_HTML = '<div id="_app"></div>'


def test_board_shell_is_not_misclassified_as_zero_jobs():
    pages = Pages({SOURCE: SOURCE_HTML, BOARD: BOARD_HTML})
    result = fetch_antenna_research_associates(SOURCE, COMPANY_ID, COMPANY, pages)
    assert result.status == "blocked"
    assert not result.jobs
    assert "JavaScript shell" in result.reason


def test_wrong_identity_fails_closed():
    result = fetch_antenna_research_associates(SOURCE, "OTHER", COMPANY, Pages({}))
    assert result.status == "unsupported"


def test_missing_official_board_link_is_partial():
    pages = Pages({SOURCE: "<p>Join the ARA Team</p>"})
    result = fetch_antenna_research_associates(SOURCE, COMPANY_ID, COMPANY, pages)
    assert result.status == "partial"
