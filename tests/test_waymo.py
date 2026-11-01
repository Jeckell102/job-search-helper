import json

from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.company_sources import repair_source


COMPANY_ID = "COMP-0517"
COMPANY = "Waymo"
CAREERS = "https://careers.withwaymo.com/"


class Greenhouse:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        return HTTPResponse(200, json.dumps({
            "meta": {"total": len(self.rows)},
            "jobs": self.rows,
        }).encode(), {"content-type": "application/json"})


def posting(identifier=8234553):
    return {
        "id": identifier,
        "title": "Senior Systems Engineer",
        "updated_at": "2026-11-01T12:00:00Z",
        "absolute_url": f"https://careers.withwaymo.com/jobs?gh_jid={identifier}",
        "location": {"name": "Mountain View, California, United States"},
        "content": "<p>Build safe autonomous systems.</p>",
        "departments": [{"name": "Systems Engineering"}],
        "offices": [{"name": "Mountain View"}],
    }


def test_waymo_repair_routes_official_careers_page_to_scoped_greenhouse_api():
    ats, board, note = repair_source("Browser", CAREERS, COMPANY_ID, COMPANY)
    assert ats == "Greenhouse"
    assert board == "https://boards-api.greenhouse.io/v1/boards/waymo"
    assert "Verified company source repair" in note


def test_waymo_greenhouse_inventory_is_complete_and_uses_employer_scope():
    transport = Greenhouse([posting()])
    result = fetch_inventory("Greenhouse", "https://boards-api.greenhouse.io/v1/boards/waymo",
                             COMPANY_ID, COMPANY, transport)
    assert result.status == "complete"
    assert len(result.jobs) == 1
    assert result.jobs[0]["posting_id"] == "8234553"
    assert transport.calls == [
        "https://boards-api.greenhouse.io/v1/boards/waymo/jobs?content=true"
    ]


def test_waymo_repair_does_not_override_changed_or_other_company_sources():
    assert repair_source("Browser", CAREERS, COMPANY_ID, "Other Employer") == (
        "Browser", CAREERS, ""
    )
    changed = "https://careers.withwaymo.com/jobs/search/?department=engineering"
    assert repair_source("Browser", changed, COMPANY_ID, COMPANY) == (
        "Browser", changed, ""
    )
