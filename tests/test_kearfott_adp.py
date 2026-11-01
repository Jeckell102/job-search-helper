import copy
import json
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from job_search_helper.adp_myjobs import fetch_adp_myjobs
from job_search_helper.ats import HTTPResponse

FIXTURE = Path(__file__).parent / "fixtures" / "adp_myjobs" / "kearfott-listing42.json"
TOKEN = "K" * 40


class KearfottTransport:
    def __init__(self, listing, final=None, details=None, total_override=None):
        self.listing = listing; self.final = final if final is not None else listing
        self.details = details or {}; self.total_override = total_override; self.calls = []

    def get(self, url):
        self.calls.append(url); return HTTPResponse(200, json.dumps({"myJobsToken": TOKEN}).encode())

    def get_with_headers(self, url, headers):
        assert headers["myJobsToken"] == TOKEN
        self.calls.append(url)
        if "/search-meta/" in url:
            ident = url.rsplit("/", 1)[-1]
            return HTTPResponse(200, json.dumps({"jobRequisitions": [self.details[ident]]}).encode())
        q = parse_qs(urlsplit(url).query)
        payload = copy.deepcopy(self.final if len([x for x in self.calls if "apply-custom-filters" in x]) > 1 else self.listing)
        if self.total_override is not None: payload["count"] = self.total_override
        return HTTPResponse(200, json.dumps(payload).encode())


class KearfottAdpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.listing = json.loads(FIXTURE.read_text())
        cls.details = {}
        for row in cls.listing["jobRequisitions"]:
            ident = str(row["reqId"])
            cls.details[ident] = {"itemID": ident, "requisitionTitle": row["jobTitle"],
                                  "clientRequisitionID": row["clientRequisitionID"],
                                  "requisitionDescription": f"<p>Full Kearfott body {ident}</p>",
                                  "requisitionLocations": row.get("requisitionLocations", [])}

    def run_fetch(self, final=None, total_override=None, details=None):
        return fetch_adp_myjobs("ADP MyJobs", "https://myjobs.adp.com/kearfott", "COMP-0264", "Kearfott Corporation", KearfottTransport(self.listing, final, details or self.details, total_override))

    def test_42_inventory_uses_200_page_and_accepts_reordered_final_set(self):
        final = copy.deepcopy(self.listing); final["jobRequisitions"] = list(reversed(final["jobRequisitions"]))
        result = self.run_fetch(final)
        self.assertEqual(result.status, "complete", result.reason); self.assertEqual(len(result.jobs), 42)

    def test_final_substitution_duplicate_and_count_drift_rejected(self):
        substitute = copy.deepcopy(self.listing); row = copy.deepcopy(substitute["jobRequisitions"][-1]); row["reqId"] = "9999999999999"; substitute["jobRequisitions"][-1] = row
        details = dict(self.details); details[row["reqId"]] = {"itemID": row["reqId"], "requisitionTitle": row["jobTitle"], "clientRequisitionID": row["clientRequisitionID"], "requisitionDescription": "<p>Replacement</p>", "requisitionLocations": []}
        self.assertEqual(self.run_fetch(substitute, details=details).status, "partial")
        duplicate = copy.deepcopy(self.listing); duplicate["jobRequisitions"][-1] = copy.deepcopy(duplicate["jobRequisitions"][0])
        self.assertEqual(self.run_fetch(duplicate).status, "partial")
        self.assertEqual(self.run_fetch(total_override=43).status, "partial")


if __name__ == "__main__": unittest.main()
