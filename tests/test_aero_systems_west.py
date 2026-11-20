"""Aero Systems West first-party source and scope tests."""
import json

from job_search_helper.aero_systems_west import SOURCE, fetch_aero_systems_west
from job_search_helper.ats import fetch_inventory


class Response:
    def __init__(self, status, html):
        self.status = status
        self.body = html.encode()
        self.headers = {}


class Transport:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        value = self.responses[url]
        return value() if callable(value) else value


CAREERS = "<html><h1>Careers at Aero Systems West</h1><p>Explore current employer-posted opportunities with the Aero Systems West team.</p><a href='/careers/job/suas-technician'>sUAS Technician I</a></html>"
DETAIL = "<html><h1>sUAS Technician I</h1><p>Support manufacturing, assembly, quality control, maintenance, and repair of Aero Systems West unmanned aircraft systems.</p></html>"


def test_source_scope_and_full_description_reread():
    role = "https://aerosystemswest.com/careers/job/suas-technician"
    transport = Transport({SOURCE: Response(200, CAREERS), role: Response(200, DETAIL)})
    result = fetch_aero_systems_west(SOURCE, "COMP-0182", "Aero Systems West", transport)
    assert result.status == "complete"
    assert len(result.jobs) == 1
    assert result.jobs[0]["description"].startswith("sUAS Technician I")
    assert transport.calls == [SOURCE, role, SOURCE]


def test_403_is_blocked_and_does_not_fall_back_to_aggregator():
    transport = Transport({SOURCE: Response(403, "forbidden")})
    result = fetch_inventory("Browser", SOURCE, "COMP-0182", "Aero Systems West", transport)
    assert result.status == "blocked"
    assert not result.jobs
    assert "blocked" in result.reason.casefold()


def test_current_404_is_partial_and_not_zero_inventory():
    transport = Transport({SOURCE: Response(404, "<h1>Page not found</h1>")})
    result = fetch_inventory("Browser", SOURCE, "COMP-0182", "Aero Systems West", transport)
    assert result.status == "partial"
    assert not result.jobs
    assert "404" in result.reason
    assert "aggregator" not in json.dumps(result.jobs).casefold()
