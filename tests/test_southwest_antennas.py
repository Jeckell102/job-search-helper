from collections import Counter
from html import escape
import json

from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.southwest_antennas import SOURCE, COMPANY_ID, COMPANY, fetch_southwest_antennas


def payload(careers, detail=None):
    props = {"app": {"careers": careers}}
    component = "About/Careers"
    if detail is not None:
        props = {"career": detail}
        component = "About/Career"
    return '<div id="app" data-page="' + escape(json.dumps({"component": component, "props": props})) + '"></div>'


class Pages:
    def __init__(self, careers, details=None, statuses=None):
        self.careers = careers
        self.details = details or {}
        self.statuses = statuses or {}
        self.calls = Counter()

    def get(self, url):
        self.calls[url] += 1
        if url == SOURCE:
            body = payload(self.careers)
        else:
            slug = url.rsplit("/", 1)[-1]
            body = payload([], self.details.get(slug, {}))
        return HTTPResponse(self.statuses.get(url, 200), body.encode(), {"content-type": "text/html"})


def role(ident="5", slug="rf-design-engineer-ii", live=1):
    return {"id": ident, "slug": slug, "position": "RF Design Engineer II", "department": "Production", "live": live}


def detail():
    return {"id": "5", "slug": "rf-design-engineer-ii", "position": "RF Design Engineer II", "live": 1, "job_description": "Responsibilities and qualifications. " * 30}


def test_explicit_zero_is_complete_and_historical_records_are_not_invented():
    pages = Pages([])
    result = fetch_inventory("Browser", SOURCE, COMPANY_ID, COMPANY, discovery_transport=pages)
    assert result.status == "complete"
    assert result.jobs == []
    assert pages.calls[SOURCE] == 2


def test_active_role_is_paginated_from_grouped_inventory_and_fully_read():
    pages = Pages({"Production": [role(), role("6", "closed-role", live=0)]}, {"rf-design-engineer-ii": detail()})
    result = fetch_southwest_antennas(SOURCE, COMPANY_ID, COMPANY, pages)
    assert result.status == "complete", result.reason
    assert result.jobs[0]["posting_id"] == "5"
    assert len(result.jobs[0]["description"]) > 100


def test_fail_closed_for_wrong_scope_blocked_missing_detail_and_inventory_drift():
    assert fetch_southwest_antennas(SOURCE, "OTHER", COMPANY, Pages([])).status == "unsupported"
    assert fetch_southwest_antennas(SOURCE, COMPANY_ID, COMPANY, Pages([], statuses={SOURCE: 403})).status == "blocked"
    pages = Pages({"Production": [role()]}, {"rf-design-engineer-ii": {}})
    assert fetch_southwest_antennas(SOURCE, COMPANY_ID, COMPANY, pages).status == "partial"
    pages = Pages({"Production": [role()]}, {"rf-design-engineer-ii": detail()})
    original = pages.get
    def drift(url):
        response = original(url)
        if url == SOURCE and pages.calls[url] == 2:
            response = HTTPResponse(200, payload([]).encode(), {})
        return response
    pages.get = drift
    assert fetch_southwest_antennas(SOURCE, COMPANY_ID, COMPANY, pages).status == "partial"
