"""Focused MITRE Phenom reconciliation coverage."""
from urllib.parse import parse_qs, urlsplit

from job_search_helper.ats import FetchError, HTTPResponse
from job_search_helper.phenom import fetch_phenom

from test_phenom import APP, BASE, SOURCE, detail, entry, html, listing


class MitreBoard:
    def __init__(self, pages, detail_status=None):
        self.pages = pages
        self.detail_status = detail_status or {}
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        if "/job/" in url:
            ident = url.rsplit("/", 1)[-1]
            status = self.detail_status.get(ident, 200)
            if status != 200:
                return HTTPResponse(status, b"denied")
            return detail(int(ident))
        offset = int(parse_qs(urlsplit(url).query).get("from", ["0"])[0])
        return self.pages[offset]


def mitre_fetch(board):
    return fetch_phenom("Phenom", SOURCE,
                        "COMP-0025", "MITRE", board)


def test_mitre_reconciles_duplicate_rows_to_unique_membership():
    # The raw board count is three rows, but row 2 is repeated and there are
    # only two unique public IDs.  The duplicate must not create a duplicate
    # detail or make the inventory incomplete.
    pages = {
        0: listing([entry(1), entry(2)], total=3, offset=0),
        2: listing([entry(2)], total=3, offset=2),
    }
    board = MitreBoard(pages)
    result = mitre_fetch(board)
    assert result.status == "complete", result.reason
    assert {job["posting_id"] for job in result.jobs} == {"1", "2"}
    assert [u for u in board.calls if "/job/" in u] == [
        "https://careers.example.com/us/en/job/1",
        "https://careers.example.com/us/en/job/2",
    ]


def test_mitre_repeated_page_is_a_bounded_pagination_gap():
    pages = {
        0: listing([entry(1)], total=2, offset=0),
        1: listing([entry(1)], total=2, offset=1),
    }
    result = mitre_fetch(MitreBoard(pages))
    assert result.status == "partial"
    assert "pagination gap" in result.reason


def test_mitre_denied_detail_is_not_counted_as_complete():
    pages = {0: listing([entry(1)], total=1, offset=0)}
    result = mitre_fetch(MitreBoard(pages, {"1": 403}))
    assert result.status == "blocked"
    assert result.jobs == []


def test_mitre_lifecycle_change_is_reconciled_not_silently_retained():
    class MovingBoard(MitreBoard):
        def __init__(self):
            super().__init__({0: listing([entry(1)], total=1, offset=0)})
            self.round = 0

        def get(self, url):
            if "/job/" not in url and "from=" not in url and self.round:
                return listing([], total=0, offset=0)
            if "/job/" not in url and "from=" not in url:
                self.round += 1
            return super().get(url)

    result = mitre_fetch(MovingBoard())
    assert result.status == "complete"
    assert result.jobs == []


def test_mitre_scope_is_exact_and_not_parent_inventory():
    board = MitreBoard({0: listing([entry(1)], total=1, offset=0)})
    board.pages[0] = html({}, APP)
    result = mitre_fetch(board)
    assert result.status in {"partial", "unsupported"}
