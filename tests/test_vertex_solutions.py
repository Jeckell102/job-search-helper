from job_search_helper.ats import fetch_inventory
from job_search_helper.company_sources import REPAIRS, repair_source


COMPANY_ID = "COMP-0338"
COMPANY = "Vertex Solutions"
SOURCE = "https://www.vertexsolutions.com/careers/"


class Response:
    status = 200
    headers = {}
    body = b'<a href="https://employers.indeed.com/jobs?status=open">VIEW OPEN POSITIONS</a>'


class Pages:
    def get(self, url):
        return Response()


def test_vertex_routes_old_source_to_canonical_official_careers_page():
    ats, url, note = repair_source("Browser", "https://vertexsolutions.com/careers/", COMPANY_ID, COMPANY)
    assert (ats, url) == ("Indeed employer dashboard", SOURCE)
    assert REPAIRS[COMPANY_ID]["url"] == SOURCE
    assert "Indeed" in REPAIRS[COMPANY_ID]["evidence"]
    assert "Verified company source repair" in note


def test_vertex_guard_rejects_non_public_indeed_dashboard_as_complete_inventory():
    result = fetch_inventory("Indeed employer dashboard", SOURCE, COMPANY_ID, COMPANY,
                             discovery_transport=Pages())
    assert result.status == "blocked"
    assert not result.jobs
    assert "not a public employer-scoped" in result.reason


def test_vertex_live_failure_fails_closed_without_jobs():
    result = fetch_inventory("Indeed employer dashboard", SOURCE, COMPANY_ID, COMPANY)
    assert result.status in {"failed", "blocked", "partial", "unsupported"}
    assert not result.jobs
