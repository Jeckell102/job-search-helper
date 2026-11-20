import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.hii import SOURCE, fetch_hii, normalize_title


class HiiBoard:
    def __init__(self, *, total=2, drift=False, duplicate=False, missing=False, suffix=False):
        self.total = total
        self.drift = drift
        self.duplicate = duplicate
        self.missing = missing
        self.suffix = suffix
        self.list_reads = 0

    def get(self, url):
        if "/job/" in url:
            ident = url.rstrip("/").split("/")[-1]
            if ident == "1002" and self.missing:
                return HTTPResponse(404, b"not found")
            if ident == "1002" and not self.missing:
                return HTTPResponse(200, b"<h1>Position has been filled.</h1>")
            title = "Systems Engineer"
            if self.suffix:
                title += " - Req. 1001"
            return HTTPResponse(200, (f'<span itemprop="title">{title}</span>'
                                      f'<div itemprop="description">Full public body for {ident}</div>').encode())
        self.list_reads += 1
        start = int(parse_qs(urlsplit(url).query).get("startrow", [0])[0])
        total = 3 if self.drift and self.list_reads > 1 else self.total
        if self.missing and start:
            return HTTPResponse(200, f"Results <b>{start + 1} – {start}</b> of <b>{total}</b>".encode())
        ids = [1001, 1002]
        if self.duplicate:
            ids = [1001, 1001]
        links = "".join(f'<a class="jobTitle-link" href="/job/Role-{ident}/{ident}/">'
                        f'{"Systems Engineer" if ident == 1001 else "Test Role"}</a>' for ident in ids)
        return HTTPResponse(200, f"Results <b>1 – {len(ids)}</b> of <b>{total}</b>{links}".encode())


class HiiTests(unittest.TestCase):
    def run_fetch(self, board):
        with tempfile.TemporaryDirectory() as directory:
            return fetch_hii(SOURCE, "COMP-0080", "HII Mission Technologies", board,
                             Path(directory) / "checkpoint.json")

    def test_title_suffix_is_normalized_and_requisition_is_preserved(self):
        result = self.run_fetch(HiiBoard(suffix=True))
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual(result.jobs[0]["title"], "Systems Engineer")
        self.assertEqual(result.jobs[0]["req_id"], "1001")

    def test_explicit_filled_listing_is_accounted_as_closed(self):
        result = self.run_fetch(HiiBoard(missing=True))
        self.assertEqual(result.status, "complete", result.reason)
        closed = [job for job in result.jobs if job.get("is_closed")]
        self.assertEqual(len(closed), 1)

    def test_duplicate_canonical_ids_are_deduplicated(self):
        result = self.run_fetch(HiiBoard(duplicate=True, total=2))
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual(len(result.jobs), 1)
        self.assertEqual(len({job["posting_id"] for job in result.jobs}), 1)

    def test_count_drift_is_partial(self):
        result = self.run_fetch(HiiBoard(drift=True))
        self.assertEqual(result.status, "partial")

    def test_missing_page_is_partial(self):
        result = self.run_fetch(HiiBoard(total=50, missing=True))
        self.assertEqual(result.status, "partial")

    def test_normalize_title_is_stable(self):
        self.assertEqual(normalize_title("Analyst (Job ID: 1001)"), "Analyst")

    def test_normal_pipeline_routes_hii_to_the_scoped_adapter(self):
        board = HiiBoard()
        with tempfile.TemporaryDirectory() as directory:
            result = fetch_inventory("SuccessFactors", SOURCE, "COMP-0080", "HII Mission Technologies",
                                     discovery_transport=board,
                                     transport=board)
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual(len(result.jobs), 2)


if __name__ == "__main__":
    unittest.main()
