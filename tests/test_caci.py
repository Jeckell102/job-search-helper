import json
import tempfile
import unittest
from pathlib import Path

from job_search_helper.ats import FetchError
from job_search_helper.caci import COMPANY, COMPANY_ID, SOURCE, fetch_caci, scan
from job_search_helper.eightfold import Client


ROOT = "https://searchcareers.caci.com"


def listing(i, stamp="2026-11-01T00:00:00Z"):
    ident = str(700000000000 + i)
    return {"id": ident, "name": f"CACI Role {i}", "displayJobId": f"CACI-{i}",
            "positionUrl": f"/careers/job/{ident}", "timestamp": stamp}


def detail(item):
    return {**item, "publicUrl": ROOT + item["positionUrl"],
            "jobDescription": "<p>Full published CACI body with requirements and responsibilities.</p>",
            "standardizedLocations": ["Reston, VA"]}


class Replay:
    def __init__(self, items, reread=None):
        self.items = items
        self.reread = reread
        self.search_calls = 0
        self.detail_calls = []

    def data(self, kind, value):
        if kind == "position_details":
            self.detail_calls.append(str(value))
            return detail(next(x for x in self.items if x["id"] == str(value)))
        self.search_calls += 1
        source = self.items if self.reread is None or self.search_calls <= ((len(self.items) + 9) // 10) else self.reread
        start = value
        return {"count": len(source), "positions": source[start:start + 10], "appliedFilters": {}}


class CaciTests(unittest.TestCase):
    def test_repeated_boundary_is_rejected_before_detail_union(self):
        items = [listing(i) for i in range(11)]
        client = Replay(items[:10] + [items[0]])
        with tempfile.TemporaryDirectory() as tmp:
            result = scan(client, str(Path(tmp) / "checkpoint.json"))
        self.assertEqual(result.status, "partial")
        self.assertEqual(client.detail_calls, [])
        self.assertIn("repeated", result.reason)

    def test_tied_timestamps_are_valid_when_identity_order_is_stable(self):
        items = [listing(i) for i in range(11)]
        with tempfile.TemporaryDirectory() as tmp:
            result = scan(Replay(items), str(Path(tmp) / "checkpoint.json"))
        self.assertEqual(result.status, "complete")
        self.assertEqual(len(result.jobs), 11)

    def test_changing_listing_is_not_accepted_by_count_match(self):
        items = [listing(i) for i in range(11)]
        changed = items[:10] + [listing(99)]
        with tempfile.TemporaryDirectory() as tmp:
            result = scan(Replay(items, changed), str(Path(tmp) / "checkpoint.json"))
        self.assertEqual(result.status, "partial")
        self.assertIn("membership changed", result.reason)

    def test_scope_is_exact_and_does_not_expand_to_shared_board(self):
        result = fetch_caci("https://searchcareers.caci.com/careers?query=all", COMPANY_ID, COMPANY)
        self.assertEqual(result.status, "unsupported")
        result = fetch_caci(SOURCE, "COMP-9999", COMPANY)
        self.assertEqual(result.status, "unsupported")


class Response:
    def __init__(self, status, payload):
        self.status = status
        self._payload = json.dumps(payload).encode()
        self.headers = {"retry-after": "0"}
    def body(self): return self._payload
    def dispose(self): pass


class Request:
    def __init__(self): self.calls = 0
    def get(self, url, **kwargs):
        self.calls += 1
        if self.calls < 3:
            return Response(429, {"status": 429, "error": {"message": "rate limited"}})
        return Response(200, {"status": 200, "data": {"count": 0, "positions": [], "appliedFilters": {}}})


class CaciRateLimitTests(unittest.TestCase):
    def test_bounded_429_retry_recovers(self):
        request = Request()
        client = Client(type("Context", (), {"request": request})(), ROOT, "caci.com", "timestamp")
        data = client.data("search", 0)
        self.assertEqual(data["count"], 0)
        self.assertEqual(request.calls, 3)


if __name__ == "__main__":
    unittest.main()
