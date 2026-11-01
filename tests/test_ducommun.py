import json

from job_search_helper.ats import HTTPResponse
from job_search_helper.ducommun import BOARD, SOURCE, fetch_ducommun


class Transport:
    def __init__(self, rows=None):
        self.rows = rows or []

    def get(self, url):
        if url == BOARD:
            return HTTPResponse(200, b'<html>Ducommun ducommun.csod.com "token":"abc"</html>')
        return HTTPResponse(200, json.dumps({"data": {"displayTitle": "Engineer", "externalDescription": "Ducommun " + "x" * 150}}).encode())

    def get_with_headers(self, url, headers):
        return self.get(url)

    def post(self, url, payload, headers=None):
        return HTTPResponse(200, json.dumps({"data": {"totalCount": len(self.rows), "requisitions": self.rows}}).encode())


def test_zero_inventory_is_complete_after_reread():
    result = fetch_ducommun(SOURCE, "COMP-0440", "Ducommun", Transport())
    assert result.status == "complete"
    assert result.jobs == []


def test_active_requisition_gets_full_detail():
    result = fetch_ducommun(SOURCE, "COMP-0440", "Ducommun", Transport([{"requisitionId": 42, "displayJobTitle": "Engineer"}]))
    assert result.status == "complete"
    assert result.jobs[0]["posting_id"] == "42"


def test_identity_is_guarded():
    result = fetch_ducommun("https://ducommun.csod.com/", "COMP-0440", "Ducommun", Transport())
    assert result.status == "unsupported"
