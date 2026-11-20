from job_search_helper.ats import HTTPResponse
from job_search_helper.cornet import COMPANY, COMPANY_ID, SOURCE, fetch_cornet

class Pages:
    def __init__(self, status=200, body="<html><title>Cornet Technology</title></html>"):
        self.status, self.body, self.calls = status, body, 0
    def get(self, url):
        assert url == SOURCE
        self.calls += 1
        return HTTPResponse(self.status, self.body.encode(), {"content-type": "text/html"})

def test_rejects_wrong_company_or_non_official_scope():
    assert fetch_cornet(SOURCE, "OTHER", COMPANY, Pages()).status == "unsupported"
    assert fetch_cornet("https://cornetindia.com/careers/", COMPANY_ID, COMPANY, Pages()).status == "unsupported"

def test_fails_closed_on_official_access_denial():
    pages = Pages(403)
    assert fetch_cornet(transport=pages).status == "blocked"
    assert pages.calls == 1

def test_does_not_infer_zero_from_accessible_corporate_page():
    result = fetch_cornet(transport=Pages())
    assert result.status == "partial"
    assert result.jobs == []
