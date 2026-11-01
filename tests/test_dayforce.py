from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.dayforce import MULTITECH_SEARCH, MULTITECH_SOURCE, SEARCH, SOURCE, fetch_dayforce
import json
from pathlib import Path


def _row(ident):
    return {
        "jobPostingId": ident,
        "jobTitle": f"Role {ident}",
        "jobDescription": "A complete public Dayforce description with duties and qualifications. " * 5,
        "jobDetailsUrl": f"https://jobs.dayforcehcm.com/en-US/esa/ESACAREERSITE/jobs/{ident}",
        "clientNamespace": "esa",
        "jobBoardId": 4,
        "jobReqId": int(ident),
        "postingLocations": [{"city": "Boston", "state": "MA", "country": "USA"}],
        "postingStartTimestampUTC": "2026-10-29T00:00:00Z",
    }


def _ssr(row, req_id=None, content=None, *, client_id=54055, board_id=4):
    content = content or {
        "jobDescriptionHeader": "<p>Header</p>",
        "jobDescription": row["jobDescription"],
        "jobDescriptionFooter": "<p>Footer</p>",
    }
    job = {"jobPostingId": int(row["jobPostingId"]), "jobReqId": int(req_id or row.get("jobReqId", row["jobPostingId"])),
           "jobTitle": row["jobTitle"], "isInternal": False, "jobPostingContent": content}
    page = {"locale": "en-US", "query": {"clientNamespace": "esa", "careerSiteXRefCode": "ESACAREERSITE", "id": str(row["jobPostingId"])},
            "props": {"pageProps": {"jobUrl": row["jobDetailsUrl"], "jobData": job, "dehydratedState": {"queries": [
        {"queryKey": ["site-info"], "state": {"data": {"jobBoardId": board_id, "clientId": client_id,
          "clientNamespace": "esa", "jobBoardCode": "ESACAREERSITE"}}}
    ]}}}}
    return (b'<script id="__NEXT_DATA__" type="application/json">' + json.dumps(page).encode() + b'</script>')


class Transport:
    def __init__(self):
        self.rows = [_row("1001"), _row("1002"), _row("1003")]
        self.calls = []

    def post(self, url, payload, headers=None):
        self.calls.append((url, payload))
        start = payload["paginationStart"]
        rows = self.rows[start:start + 25]
        return HTTPResponse(200, __import__("json").dumps({"jobPostings": rows, "maxCount": len(self.rows), "count": len(rows), "offset": start}).encode())

    def get(self, url):
        ident = url.rstrip('/').rsplit('/', 1)[-1]
        row = next(row for row in self.rows if row["jobPostingId"] == ident)
        return HTTPResponse(200, _ssr(row))


def test_dayforce_complete_inventory_and_recheck():
    result = fetch_dayforce("Dayforce", SOURCE, "COMP-0089", "Elbit Systems of America", Transport())
    assert result.status == "complete"
    assert len(result.jobs) == 3
    assert result.ats == "Dayforce"


def test_dayforce_normal_entrypoint_dispatches():
    result = fetch_inventory("Dayforce", SOURCE, "COMP-0089", "Elbit Systems of America", Transport())
    assert result.status == "complete"


def test_multitech_dayforce_complete_inventory():
    class MultiTransport(Transport):
        def post(self, url, payload, headers=None):
            self.calls.append((url, payload))
            assert url == MULTITECH_SEARCH
            assert payload["clientNamespace"] == "multitech"
            assert payload["jobBoardCode"] == "CANDIDATEPORTAL"
            start = payload["paginationStart"]
            rows = []
            for ident in ["925", "918", "912"][start:start + 25]:
                row = _row(ident)
                row["jobDetailsUrl"] = f"https://jobs.dayforcehcm.com/en-US/multitech/CANDIDATEPORTAL/jobs/{ident}"
                rows.append(row)
            return HTTPResponse(200, __import__("json").dumps({"jobPostings": rows, "maxCount": 3, "count": len(rows)}).encode())

    result = fetch_dayforce("Dayforce", MULTITECH_SOURCE, "COMP-0143", "MultiTech", MultiTransport())
    assert result.status == "complete"
    assert len(result.jobs) == 3


def test_elbit_rejects_duplicate_or_changed_public_inventory():
    class Duplicate(Transport):
        def post(self, url, payload, headers=None):
            self.calls.append((url, payload))
            rows = [_row("1001"), _row("1001")]
            return HTTPResponse(200, __import__("json").dumps({"jobPostings": rows, "maxCount": 2, "count": 2}).encode())

    result = fetch_dayforce("Dayforce", SOURCE, "COMP-0089", "Elbit Systems of America", Duplicate())
    assert result.status == "partial"
    assert not result.jobs

    class Drift(Transport):
        def __init__(self):
            super().__init__(); self.calls = []
        def post(self, url, payload, headers=None):
            self.calls.append((url, payload))
            start = payload["paginationStart"]
            total = 3 if len(self.calls) == 1 else 4
            rows = self.rows[start:start + 25]
            return HTTPResponse(200, __import__("json").dumps({"jobPostings": rows, "maxCount": total, "count": len(rows)}).encode())

    result = fetch_dayforce("Dayforce", SOURCE, "COMP-0089", "Elbit Systems of America", Drift())
    assert result.status == "partial"


def test_elbit_rejects_unscoped_or_incomplete_detail_records():
    for change in (
        {"jobDescription": ""},
        {"jobDetailsUrl": "https://jobs.dayforcehcm.com/en-US/other/jobs/1001"},
        {"jobDetailsUrl": "https://jobs.dayforcehcm.com/en-US/esa/ESACAREERSITE/jobs/1001?x=1"},
        {"jobPostingId": "../1001"},
    ):
        row = _row("1001"); row.update(change)
        class One(Transport):
            def post(self, url, payload, headers=None):
                self.calls.append((url, payload))
                return HTTPResponse(200, __import__("json").dumps({"jobPostings": [row], "maxCount": 1, "count": 1}).encode())
        result = fetch_dayforce("Dayforce", SOURCE, "COMP-0089", "Elbit Systems of America", One())
        assert result.status == "partial", change
        assert not result.jobs


def test_elbit_replay_fixture_keeps_all_published_content_sections_and_ids():
    fixture = json.loads((Path(__file__).parent / "fixtures" / "dayforce" / "elbit-7933.json").read_text())
    assert fixture["posting_id"] == 7933
    assert fixture["req_id"] == 845
    assert fixture["posting_id"] != fixture["req_id"]
    content = fixture["content"]
    assert set(content) == {"jobDescriptionHeader", "jobDescription", "jobDescriptionFooter"}
    assert all(isinstance(content[key], str) and content[key].strip() for key in content)
    # The three sections are independently published by Dayforce and must all
    # survive normalization; checking distinctive text prevents body-only parsers.
    assert "Company Information:" in content["jobDescriptionHeader"]
    assert "Responsibilities and Tasks:" in content["jobDescription"]
    assert "Great Benefits We Offer:" in content["jobDescriptionFooter"]
    combined = "\n\n".join(content.values())
    row = _row(str(fixture["posting_id"]))
    row.update(jobTitle=fixture["title"], jobDescription=combined,
               jobDetailsUrl=fixture["source"], jobReqId=fixture["req_id"], reqId=fixture["req_id"])

    class Actual(Transport):
        def post(self, url, payload, headers=None):
            self.calls.append((url, payload))
            return HTTPResponse(200, json.dumps({"jobPostings": [row], "maxCount": 1, "count": 1, "offset": 0}).encode())

        def get(self, url):
            body = (Path(__file__).parent / "fixtures" / "dayforce" / "elbit-7933.html").read_bytes()
            return HTTPResponse(200, body)

    result = fetch_dayforce("Dayforce", SOURCE, "COMP-0089", "Elbit Systems of America", Actual())
    assert result.status == "complete", result.reason
    assert result.jobs[0]["posting_id"] == "7933"
    assert result.jobs[0]["req_id"] == "845"
    for marker in ("Company Information:", "Responsibilities and Tasks:", "Great Benefits We Offer:"):
        assert marker in result.jobs[0]["description"]

