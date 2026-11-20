import json
import re
import unittest
from urllib.parse import unquote, urlsplit, parse_qs

from job_search_helper.ats import HTTPResponse
from job_search_helper.oracle import fetch_oracle


URL = "https://icfcjb.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/Aerospace/jobs"


def response(value):
    return HTTPResponse(200, json.dumps(value).encode())


class HoneywellBoard:
    def __init__(self, count=6, counter_by_sort=None, short_page=True):
        self.ids = [str(100000 + i) for i in range(count)]
        self.counter_by_sort = counter_by_sort or {s: count for s in (
            "POSTING_DATES_DESC", "POSTING_DATES_ASC", "REQUISITION_ID_ASC")}
        self.short_page = short_page
        self.calls = {}

    def get(self, url):
        decoded = unquote(url)
        if "recruitingCEJobRequisitionDetails" in decoded:
            ident = re.search(r'Id="(\d+)"', decoded).group(1)
            return response({"items": [{"Id": ident, "Title": f"Role {ident}",
                "ExternalDescriptionStr": "<p>Full description</p>",
                "PrimaryLocation": "Phoenix, AZ", "otherWorkLocations": [],
                "secondaryLocations": []}]})
        query = parse_qs(urlsplit(url).query)
        finder = query["finder"][0]
        sort = re.search(r"sortBy=([A-Z_]+)", finder).group(1)
        offset = int(re.search(r"offset=(\d+)", finder).group(1))
        key = (sort, offset)
        self.calls[key] = self.calls.get(key, 0) + 1
        rows = self.ids[offset:offset + 20]
        if self.short_page and offset == 20 and rows:
            rows = rows[:3]
        return response({"items": [{"TotalJobsCount": self.counter_by_sort[sort],
            "requisitionList": [{"Id": ident} for ident in rows]}]})


class Page:
    def get(self, url):
        return HTTPResponse(200, b'<base href="/x?siteNumber=CX_4001">')


class HoneywellTests(unittest.TestCase):
    def test_short_nonterminal_page_continues_to_empty_boundary(self):
        board = HoneywellBoard(count=23)
        result = fetch_oracle("Oracle Recruiting Cloud", URL, "COMP-0436",
                              "Honeywell Aerospace Technologies", board, Page())
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual(len(result.jobs), 23)
        self.assertIn("full descriptions", result.reason)

    def test_same_partition_overlap_is_rejected(self):
        board = HoneywellBoard(count=23)
        original = board.get
        def overlapping(url):
            value = original(url)
            if "recruitingCEJobRequisitions" in url and "offset%3D20" in url:
                body = json.loads(value.body)
                body["items"][0]["requisitionList"][0]["Id"] = board.ids[0]
                return response(body)
            return value
        board.get = overlapping
        result = fetch_oracle("Oracle Recruiting Cloud", URL, "COMP-0436",
                              "Honeywell Aerospace Technologies", board, Page())
        self.assertEqual(result.status, "partial")
        self.assertIn("overlap or duplicate", result.reason)

    def test_duplicate_identifier_is_rejected_even_when_counter_is_stale(self):
        board = HoneywellBoard(count=6, counter_by_sort={
            "POSTING_DATES_DESC": 7, "POSTING_DATES_ASC": 6, "REQUISITION_ID_ASC": 7})
        board.ids[-1] = board.ids[-2]
        result = fetch_oracle("Oracle Recruiting Cloud", URL, "COMP-0436",
                              "Honeywell Aerospace Technologies", board, Page())
        self.assertEqual(result.status, "partial")

    def test_788_789_counter_discrepancy_is_reconciled_against_ids(self):
        board = HoneywellBoard(count=8, counter_by_sort={
            "POSTING_DATES_DESC": 9, "POSTING_DATES_ASC": 8, "REQUISITION_ID_ASC": 9})
        result = fetch_oracle("Oracle Recruiting Cloud", URL, "COMP-0436",
                              "Honeywell Aerospace Technologies", board, Page())
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual(len(result.jobs), 8)
        self.assertIn("8 vs 9", result.reason)

    def test_membership_drift_between_scan_and_recheck_is_partial(self):
        board = HoneywellBoard(count=6)
        original = board.get
        def drift(url):
            value = original(url)
            decoded = unquote(url)
            if ("recruitingCEJobRequisitions" in decoded
                    and "sortBy=POSTING_DATES_DESC" in decoded
                    and "offset=0" in decoded
                    and board.calls[("POSTING_DATES_DESC", 0)] > 1):
                body = json.loads(value.body)
                body["items"][0]["requisitionList"][0]["Id"] = "999999"
                return response(body)
            return value
        board.get = drift
        result = fetch_oracle("Oracle Recruiting Cloud", URL, "COMP-0436",
                              "Honeywell Aerospace Technologies", board, Page())
        self.assertEqual(result.status, "partial")
        self.assertIn("membership changed", result.reason)


if __name__ == "__main__":
    unittest.main()
