import json
from urllib.parse import urlsplit

from job_search_helper.ats import HTTPResponse
from job_search_helper.komatsu import SOURCE, SEARCH, fetch_komatsu


def listing(ids, total=None):
    total = total or len(ids)
    links = "".join(f'<a class="jobTitle-link" href="/job/Role-{i}/{i}-en_US">Role {i}</a>' for i in ids)
    return f'Results <b>1 – {total}</b> of <b>{total}</b>{links}'


class Board:
    def __init__(self, api=None, html_ids=(101, 102)):
        self.api = api or [101, 102]
        self.html_ids = tuple(html_ids)
        self.urls = []

    def get(self, url):
        self.urls.append(url)
        path = urlsplit(url).path
        if path.startswith("/job/"):
            ident = path.rstrip("/").split("/")[-1].split("-", 1)[0]
            return HTTPResponse(200, (f'<link rel="canonical" href="https://komatsu.jobs{path}" />'
                                      f'<span itemprop="title">Role {ident}</span>'
                                      f'<div itemprop="description">Full body {ident}</div>').encode())
        return HTTPResponse(200, listing(self.html_ids, len(self.html_ids)).encode())

    def post(self, url, payload, headers=None):
        rows = [{"response": {"url": f"https://komatsu.jobs/job/Role-{i}/{i}-en_US",
                               "unifiedStandardTitle": f"Role {i}"}} for i in self.api]
        return HTTPResponse(200, json.dumps({"jobSearchResult": rows, "totalJobs": len(rows)}).encode())


def test_idless_api_rows_reconcile_to_html_canonical_urls():
    result = fetch_komatsu(SOURCE, "COMP-0240", "Komatsu", Board())
    assert result.status == "complete", result.reason
    assert [j["posting_id"] for j in result.jobs] == ["101", "102"]
    assert all(j["url"].startswith("https://komatsu.jobs/job/") and j["description"] for j in result.jobs)


def test_api_only_record_is_not_accepted():
    result = fetch_komatsu(SOURCE, "COMP-0240", "Komatsu", Board(api=(101, 102, 103)))
    assert result.status == "partial"
    assert "membership diverged" in result.reason


def test_html_only_record_is_not_accepted():
    result = fetch_komatsu(SOURCE, "COMP-0240", "Komatsu", Board(api=(101,), html_ids=(101, 102)))
    assert result.status == "partial"
    assert "membership diverged" in result.reason


def test_explicit_independent_dealer_taxonomy_is_excluded_only_with_evidence():
    class DealerBoard(Board):
        def post(self, url, payload, headers=None):
            rows = [{"response": {"url": "https://komatsu.jobs/job/Role-101/101-en_US", "company": "Independent Dealer"}}]
            return HTTPResponse(200, json.dumps({"jobSearchResult": rows, "totalJobs": 1}).encode())
    result = fetch_komatsu(SOURCE, "COMP-0240", "Komatsu", DealerBoard(api=(101,)))
    assert result.status == "partial"
    assert "membership diverged" in result.reason
