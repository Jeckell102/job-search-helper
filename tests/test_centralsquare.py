from collections import Counter

from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.centralsquare import COMPANY, COMPANY_ID, SOURCE, fetch_centralsquare

LIST = b'''<html><h1>CentralSquare Technologies Career Center</h1><span>Open Positions</span>
<a href="/v3/Jobs/JobDetails.aspx?cid=7724&amp;jid=123&amp;locvalue=1108">Systems Support Specialist II</a></html>'''
DETAIL = b'''<html><p class="jobtitle">Systems Support Specialist II</p><span class="joblocation">Remote</span>
<h2>About CentralSquare Technologies</h2><p>CentralSquare Technologies builds public sector software.</p>
<span class="sectionheader">Job Description</span><p>''' + b"A detailed role description for CentralSquare Technologies. " * 10 + b'''</p></html>'''


class Pages:
    def __init__(self, detail=DETAIL, status=200):
        self.calls = Counter()
        self.detail = detail
        self.status = status

    def get(self, url):
        self.calls[url] += 1
        if "JobDetails.aspx" in url:
            return HTTPResponse(self.status, self.detail, {})
        return HTTPResponse(self.status, LIST, {})


def test_fetches_full_board_and_rereads():
    pages = Pages()
    result = fetch_inventory("Browser", SOURCE, COMPANY_ID, COMPANY, discovery_transport=pages)
    assert result.status == "complete", result.reason
    assert len(result.jobs) == 1
    assert result.jobs[0]["posting_id"] == "123"
    assert "Job Description" in result.jobs[0]["description"]
    assert pages.calls[SOURCE] == 2


def test_rejects_wrong_scope_and_blocked_board():
    assert fetch_centralsquare(SOURCE, "OTHER", COMPANY, Pages()).status == "unsupported"
    assert fetch_inventory("Browser", SOURCE, COMPANY_ID, COMPANY,
                           discovery_transport=Pages(status=403)).status == "blocked"


def test_detects_reread_drift():
    pages = Pages()
    original = pages.get
    def changing(url):
        pages.calls[url] += 1
        if "JobDetails.aspx" in url:
            return HTTPResponse(200, pages.detail, {})
        body = LIST if pages.calls[SOURCE] == 1 else LIST.replace(b"jid=123", b"jid=124")
        return HTTPResponse(200, body, {})
    pages.get = changing
    assert fetch_inventory("Browser", SOURCE, COMPANY_ID, COMPANY, discovery_transport=pages).status == "partial"
