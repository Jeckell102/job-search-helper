from job_search_helper.ats import HTTPResponse
from job_search_helper.gd_land_systems import SOURCE, fetch_gd_land_systems


DETAIL = "<html><title>Estimating Specialist</title><p>GD Land Systems responsibilities and qualifications. " + ("details " * 40) + "</p></html>"
LISTING = """<html><body><div>Business Unit: GD Land Systems</div>
<a href="/careers/estimating-specialist-sterling-heights-mi-us-18408973-gdls-opportunity">Estimating Specialist</a>
</body></html>"""


class Pages:
    def __init__(self, status=200):
        self.status = status
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        if self.status != 200:
            return HTTPResponse(self.status, b"blocked")
        if url == SOURCE:
            return HTTPResponse(200, LISTING.encode(), {})
        return HTTPResponse(200, DETAIL.encode(), {})


def test_gdls_requires_live_access_and_marks_403_blocked():
    result = fetch_gd_land_systems(SOURCE, "COMP-0097", "General Dynamics Land Systems", Pages(403))
    assert result.status == "blocked"
    assert "HTTP 403" in result.reason


def test_gdls_accepts_only_scoped_inventory_and_rereads_it():
    pages = Pages()
    result = fetch_gd_land_systems(SOURCE, "COMP-0097", "General Dynamics Land Systems", pages)
    assert result.status == "complete", result.reason
    assert len(result.jobs) == 1
    assert result.jobs[0]["posting_id"] == "18408973"
    assert pages.calls.count(SOURCE) == 2
