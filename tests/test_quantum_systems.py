import json

from job_search_helper.ats import HTTPResponse, fetch_inventory


SOURCE = "https://quantum-systems.com/us/jobs-quantum-usa/"


class Pages:
    def __init__(self, records, total=None):
        self.records = records
        self.total = total if total is not None else len(records)
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        page = int(url.rsplit("page=", 1)[1])
        body = self.records if page == 1 else []
        return HTTPResponse(200, json.dumps(body).encode(), {
            "X-WP-Total": str(self.total), "X-WP-TotalPages": "1"})


def record(identifier=101):
    return {"id": identifier, "date": "2026-11-01T12:00:00",
            "link": f"https://quantum-systems.com/us/jobs/role-{identifier}/",
            "title": {"rendered": "Systems Engineer"},
            "content": {"rendered": "<p>Build systems.</p>"}}


def test_quantum_systems_routes_and_parses_scoped_wordpress_posts():
    transport = Pages([record()])
    result = fetch_inventory("Browser", SOURCE, "COMP-0174", "Quantum Systems USA", transport)
    assert result.status == "complete"
    assert len(result.jobs) == 1
    assert len(transport.calls) == 2
    assert all("categories=75&per_page=100&page=" in call for call in transport.calls)


def test_quantum_systems_rejects_out_of_scope_detail_links():
    transport = Pages([{**record(), "link": "https://quantum-systems.com/us/jobs-europe/role-101/"}])
    result = fetch_inventory("Browser", SOURCE, "COMP-0174", "Quantum Systems USA", transport)
    assert result.status == "partial"
    assert result.jobs == []
