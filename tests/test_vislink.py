"""Vislink's first-party static careers page is parsed fail-closed."""
from job_search_helper.ats import HTTPResponse, fetch_inventory

SOURCE = "https://www.vislink.com/about/careers/"
DETAIL = "https://www.vislink.com/careers/technical-manager-of-quality-rf-wireless-video-equipment/"
COMPANY_ID = "COMP-0487"
COMPANY = "Vislink Technologies"

LISTING = f'''<html><body><a href="{DETAIL}?utm=ignored">Technical Manager of Quality</a></body></html>'''.encode()
DETAIL_HTML = ('''<html><body><h1>Technical Manager of Quality – RF/Wireless Video Equipment</h1>'''
               '''<h5>Full-time, Onsite,</h5><h5>Mount Olive, New Jersey</h5>'''
               '''<main><h1>Position Overview:</h1><p>We are seeking a technically skilled Quality Manager '''
               + "quality and manufacturing " * 30 + '''</p><h2>Key Responsibilities</h2>'''
               '''<p>Global quality oversight and supplier quality management.</p></main></body></html>''').encode()


class Transport:
    def __init__(self, responses): self.responses = list(responses)
    def get(self, url):
        if not self.responses: raise AssertionError("unexpected request: " + url)
        expected, response = self.responses.pop(0)
        assert url == expected, (url, expected)
        return response


def ok_transport(listing=LISTING):
    return Transport([(SOURCE, HTTPResponse(200, listing)), (DETAIL, HTTPResponse(200, DETAIL_HTML)),
                       (SOURCE, HTTPResponse(200, listing))])


def test_vislink_static_roles_have_canonical_urls_and_no_required_req_metadata():
    result = fetch_inventory("Browser", SOURCE, COMPANY_ID, COMPANY, discovery_transport=ok_transport())
    assert result.status == "complete", result.reason
    assert len(result.jobs) == 1
    assert result.jobs[0]["url"] == DETAIL
    assert result.jobs[0]["req_id"] == ""
    assert len(result.jobs[0]["description"]) > 500


def test_vislink_access_denial_is_blocked():
    result = fetch_inventory("Browser", SOURCE, COMPANY_ID, COMPANY,
                             discovery_transport=Transport([(SOURCE, HTTPResponse(403, b"Just a moment..."))]))
    assert result.status == "blocked"
    assert not result.jobs


def test_vislink_missing_detail_fails_closed():
    result = fetch_inventory("Browser", SOURCE, COMPANY_ID, COMPANY,
                             discovery_transport=Transport([(SOURCE, HTTPResponse(200, LISTING)),
                                                             (DETAIL, HTTPResponse(404, b"missing"))]))
    assert result.status == "partial"
    assert not result.jobs


def test_vislink_addition_between_rereads_is_partial():
    added = LISTING.replace(b"</body>", b'<a href="https://www.vislink.com/careers/new-role/">New Role</a></body>')
    result = fetch_inventory("Browser", SOURCE, COMPANY_ID, COMPANY,
                             discovery_transport=Transport([(SOURCE, HTTPResponse(200, LISTING)),
                                                             (DETAIL, HTTPResponse(200, DETAIL_HTML)),
                                                             (SOURCE, HTTPResponse(200, added))]))
    assert result.status == "partial"
    assert not result.jobs
