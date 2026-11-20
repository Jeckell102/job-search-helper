import json

from job_search_helper.ats import HTTPResponse, fetch_inventory, resolve_board
from job_search_helper.company_sources import REPAIRS, repair_source


COMPANY_ID = "COMP-0293"
COMPANY = "Carbyne"
OFFICIAL = "https://www.carbyne.com/careers/"
QUEUE_SOURCE = "https://www.axon.com/careers"
BOARD = REPAIRS[COMPANY_ID]["url"]


def _job(job_id, department, title="Carbyne role"):
    return {
        "id": job_id,
        "title": title,
        "absolute_url": f"https://job-boards.greenhouse.io/axon/jobs/{job_id}",
        "location": {"name": "United States"},
        "departments": [{"id": department.split()[0], "name": department}],
        "content": f"<p>{title} description</p>",
    }


def test_carbyne_route_is_identity_guarded_and_greenhouse_resolves():
    ats, url, note = repair_source("Browser", OFFICIAL, COMPANY_ID, COMPANY)
    assert (ats, url) == ("Greenhouse", BOARD)
    assert BOARD in note
    assert repair_source("Browser", OFFICIAL, COMPANY_ID, "Other Employer") == ("Browser", OFFICIAL, "")
    assert resolve_board(ats, url)[:2] == ("Greenhouse", "axon")
    assert repair_source("Browser", QUEUE_SOURCE, COMPANY_ID, COMPANY)[:2] == ("Greenhouse", BOARD)


def test_carbyne_scopes_shared_axon_board_and_reconciles_reread():
    rows = [
        _job("1", "1576 Carbyne Network Engineering", "Network Engineer"),
        _job("2", "2045 Carbyne Product", "Product Manager"),
        _job("3", "1001 Manufacturing Engineering", "Non-Carbyne role"),
    ]
    payload = json.dumps({"meta": {"total": len(rows)}, "jobs": rows}).encode()

    class Transport:
        def get(self, url, **kwargs):
            return HTTPResponse(200, payload, {"Content-Type": "application/json"})

    result = fetch_inventory("Greenhouse", BOARD, COMPANY_ID, COMPANY, Transport())
    assert result.status == "complete", result.reason
    assert {job["posting_id"] for job in result.jobs} == {"1", "2"}
    assert all("Carbyne" in job["department"] for job in result.jobs)
