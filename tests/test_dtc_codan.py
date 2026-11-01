from collections import Counter

from job_search_helper.ats import HTTPResponse, fetch_inventory

SOURCE = "https://www.dtccodan.com/about/careers/"
COMPANY_ID = "COMP-0467"
COMPANY = "DTC, a Codan Company"
DETAIL_URL = "https://careers.codan.com.au/job/Whiteley-Engineer-Unit/1360000001/"
LIST = f'''<html><table aria-label="Results 1 to 1 of 1"><a class="jobTitle-link" href="{DETAIL_URL}">Embedded Software Engineer</a></table></html>'''.encode()
DETAIL = f'''<html><link rel="canonical" href="{DETAIL_URL}"><span itemprop="title">Embedded Software Engineer</span><div itemprop="description">DTC | A Codan Company develops critical communications technology. This is a complete role description with responsibilities and qualifications for the position.</div></html>'''.encode()


class Pages:
    def __init__(self, status=200):
        self.calls = Counter(); self.status = status

    def get(self, url):
        self.calls[url] += 1
        return HTTPResponse(self.status, DETAIL if "/job/" in url else LIST, {})


def test_fetches_scoped_board_and_rereads():
    pages = Pages()
    result = fetch_inventory("Browser", SOURCE, COMPANY_ID, COMPANY, discovery_transport=pages)
    assert result.status == "complete", result.reason
    assert len(result.jobs) == 1
    assert result.jobs[0]["posting_id"] == "1360000001"
    assert pages.calls["https://careers.codan.com.au/search/?q=DTC"] == 2


def test_rejects_wrong_scope_and_blocked_board():
    from job_search_helper.dtc_codan import fetch_dtc_codan
    assert fetch_dtc_codan(SOURCE, "OTHER", COMPANY, Pages()).status == "unsupported"
    assert fetch_inventory("Browser", SOURCE, COMPANY_ID, COMPANY, discovery_transport=Pages(403)).status == "blocked"
