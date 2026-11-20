import copy
import json
import tempfile
import unittest
from pathlib import Path

from job_search_helper.ats import HTTPResponse
from job_search_helper.kbr import (FEED, HOST, SITE, SOURCE, WIDGET,
                                   _reconcile_extra_inventory, fetch_kbr)

ROW = {
    "id": "R123", "requisition_status": "Open",
    "application_url": f"https://{HOST}/{SITE}/job/City/Engineer_R123",
}


class Public:
    def __init__(self, rows=None, widget_status=404):
        self.rows = copy.deepcopy(rows or [ROW])
        self.widget_status = widget_status
        self.calls = 0

    def get(self, url):
        if url == WIDGET and self.widget_status == 404:
            return HTTPResponse(404, b"")
        if url == WIDGET:
            return HTTPResponse(200, json.dumps({"name": "KBR", "jobs": []}).encode())
        self.calls += 1
        data = {"source": "workday_raas", "generated_at": "2026-11-01",
                "total_jobs": len(self.rows), "jobs": copy.deepcopy(self.rows)}
        return HTTPResponse(200, json.dumps(data).encode())


class Workday:
    def __init__(self, empty_shell=False, denied=0, total=1611):
        self.empty_shell = empty_shell
        self.denied = denied
        self.total = total
        self.get_calls = 0
        self.post_calls = []
        self.sleep_calls = []

    def sleep(self, seconds):
        self.sleep_calls.append(seconds)

    def get(self, url):
        self.get_calls += 1
        if self.get_calls <= self.denied:
            return HTTPResponse(403, b"denied")
        ident = url.rsplit("_", 1)[-1].split(".", 1)[0]
        return HTTPResponse(200, json.dumps({"jobPostingInfo": {
            "id": "opaque-" + ident, "jobPostingSiteId": SITE, "posted": True,
            "title": "Updated title", "jobDescription": "Full responsibilities",
            "jobReqId": ident,
        }}).encode())

    def post(self, url, payload):
        self.post_calls.append(payload.copy())
        query = payload["searchText"]
        if query:
            return HTTPResponse(200, json.dumps({
                "total": 1, "jobPostings": [{"externalPath": "/job/City/Engineer_" + query}],
            }).encode())
        if self.empty_shell:
            return HTTPResponse(200, json.dumps({"total": self.total, "jobPostings": []}).encode())
        offset = payload["offset"]
        count = min(20, self.total - offset)
        if self.total == 1:
            postings = [{"externalPath": "/job/City/Engineer_R123"}]
        else:
            postings = [{"externalPath": f"/job/City/Role_R{offset + i + 1}"}
                        for i in range(count)]
        return HTTPResponse(200, json.dumps({"total": self.total, "jobPostings": postings}).encode())


class KBRTests(unittest.TestCase):
    def run_fetch(self, rows=None, transport=None, checkpoint=None):
        with tempfile.TemporaryDirectory() as directory:
            path = checkpoint or Path(directory) / "kbr-progress.json"
            return fetch_kbr(SOURCE, "c", "KBR", Public(rows), transport or Workday(total=1), path), path

    def test_linked_and_missing_link_records(self):
        for link in [ROW["application_url"], None]:
            row = dict(ROW, application_url=link)
            result, _ = self.run_fetch([row], Workday(total=1))
            self.assertEqual(result.status, "complete", result.reason)
            self.assertEqual(result.jobs[0]["title"], "Updated title")

    def test_438_feed_vs_1611_workday_reconciliation_records_extras(self):
        transport = Workday(total=1611)
        total, extras = _reconcile_extra_inventory(transport, {"R1", "R2"})
        self.assertEqual(total, 1611)
        self.assertEqual(len(extras), 1609)
        self.assertEqual(len(transport.post_calls), 81)

    def test_extra_inventory_prevents_completion(self):
        result, _ = self.run_fetch(transport=Workday(total=20))
        self.assertEqual(result.status, "partial")
        self.assertIn("extra Workday", result.reason)

    def test_403_detail_retries_with_cooldown(self):
        transport = Workday(denied=2, total=1)
        result, _ = self.run_fetch(transport=transport)
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual(transport.get_calls, 3)
        self.assertEqual(transport.sleep_calls, [0.5, 1.0])

    def test_empty_workday_shell_is_partial_not_zero_inventory(self):
        result, _ = self.run_fetch(transport=Workday(empty_shell=True, total=438))
        self.assertEqual(result.status, "partial")
        self.assertIn("ended before", result.reason.lower())

    def test_legacy_completed_ids_without_bodies_are_refetched(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "progress.json"
            path.write_text(json.dumps({"completed_ids": ["R123"]}), encoding="utf-8")
            row = dict(ROW)
            result = fetch_kbr(SOURCE, "c", "KBR", Public([row]), Workday(total=1), path)
            self.assertEqual(result.status, "complete", result.reason)
            self.assertEqual(len(result.jobs), 1)
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["missing_ids"], [])

    def test_wrong_requisition_and_unavailable_lookup(self):
        class Wrong(Workday):
            def get(self, url):
                response = super().get(url)
                data = json.loads(response.body)
                data["jobPostingInfo"]["jobReqId"] = "R456"
                return HTTPResponse(200, json.dumps(data).encode())
        result, _ = self.run_fetch(transport=Wrong(total=1))
        self.assertEqual(result.status, "partial")

    def test_foreign_link(self):
        row = dict(ROW, application_url=ROW["application_url"].replace(HOST, "other.wd5.myworkdayjobs.com"))
        result, _ = self.run_fetch([row], Workday(total=20))
        self.assertEqual(result.status, "partial")

    def test_absent_workable_supplement(self):
        result, _ = self.run_fetch(transport=Workday(total=1))
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual(len(result.jobs), 1)


if __name__ == "__main__":
    unittest.main()
