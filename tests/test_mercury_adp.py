import copy
import json
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from job_search_helper.adp_myjobs import fetch_adp_myjobs
from job_search_helper.ats import HTTPResponse


FIXTURE = Path(__file__).parent / "fixtures" / "adp_myjobs" / "mercury-listing117.json"
TOKEN = "M" * 40


class MercuryTransport:
    def __init__(self, listing, final=None, details=None, total_override=None):
        self.listing = listing
        self.final = final if final is not None else listing
        self.details = details or {}
        self.total_override = total_override
        self.urls = []

    def get(self, url):
        self.urls.append(url)
        return HTTPResponse(200, json.dumps({"myJobsToken": TOKEN}).encode())

    def get_with_headers(self, url, headers):
        self.urls.append(url)
        assert headers["myJobsToken"] == TOKEN
        if "/search-meta/" in url:
            ident = url.rsplit("/", 1)[-1]
            return HTTPResponse(200, json.dumps({"jobRequisitions": [self.details[ident]]}).encode())
        query = parse_qs(urlsplit(url).query)
        if query.get("$skip", ["0"])[0] == "0" and len([x for x in self.urls if "apply-custom-filters" in x]) > 1:
            payload = copy.deepcopy(self.final)
        else:
            payload = copy.deepcopy(self.listing)
        if self.total_override is not None:
            payload["count"] = self.total_override
        return HTTPResponse(200, json.dumps(payload).encode())


class PagedMercuryTransport:
    def __init__(self, pages, reread, details):
        self.pages = pages
        self.reread = reread
        self.details = details
        self.calls = {}

    def get(self, url):
        return HTTPResponse(200, json.dumps({"myJobsToken": TOKEN}).encode())

    def get_with_headers(self, url, headers):
        assert headers["myJobsToken"] == TOKEN
        if "/search-meta/" in url:
            ident = url.rsplit("/", 1)[-1]
            return HTTPResponse(200, json.dumps({"jobRequisitions": [self.details[ident]]}).encode())
        query = parse_qs(urlsplit(url).query)
        offset = int(query["$skip"][0])
        call = self.calls.get(offset, 0)
        self.calls[offset] = call + 1
        payload = self.pages[offset] if call == 0 else self.reread[offset]
        return HTTPResponse(200, json.dumps(payload).encode())


class MercuryAdpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.listing = json.loads(FIXTURE.read_text())
        cls.details = {}
        for row in cls.listing["jobRequisitions"]:
            ident = str(row["reqId"])
            cls.details[ident] = {
                "itemID": ident,
                "requisitionTitle": row["jobTitle"],
                "clientRequisitionID": row["clientRequisitionID"],
                "requisitionDescription": f"<p>Full public description for {ident}.</p><ul><li>Required experience</li></ul>",
                "requisitionLocations": row.get("requisitionLocations", []),
            }

    def test_mercury_117_inventory_accepts_final_reordering(self):
        reordered = copy.deepcopy(self.listing)
        reordered["jobRequisitions"] = list(reversed(reordered["jobRequisitions"]))
        transport = MercuryTransport(self.listing, reordered, self.details)
        result = fetch_adp_myjobs("ADP MyJobs", "https://myjobs.adp.com/mercurysystemscareers", "COMP-0084", "Mercury Systems", transport)
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual(len(result.jobs), 117)
        listing_urls = [u for u in transport.urls if "apply-custom-filters" in u]
        self.assertTrue(all(parse_qs(urlsplit(u).query)["$top"] == ["200"] for u in listing_urls))

    def test_mercury_final_duplicate_rejected(self):
        changed = copy.deepcopy(self.listing)
        changed["jobRequisitions"][-1] = copy.deepcopy(changed["jobRequisitions"][0])
        transport = MercuryTransport(self.listing, changed, self.details)
        result = fetch_adp_myjobs("ADP MyJobs", "https://myjobs.adp.com/mercurysystemscareers", "COMP-0084", "Mercury Systems", transport)
        self.assertEqual(result.status, "partial")

    def test_mercury_count_drift_rejected(self):
        transport = MercuryTransport(self.listing, self.listing, self.details, total_override=118)
        result = fetch_adp_myjobs("ADP MyJobs", "https://myjobs.adp.com/mercurysystemscareers", "COMP-0084", "Mercury Systems", transport)
        self.assertEqual(result.status, "partial")

    def test_mercury_final_substitution_rejected_even_when_count_is_117(self):
        changed = copy.deepcopy(self.listing)
        replacement = copy.deepcopy(changed["jobRequisitions"][-1])
        replacement["reqId"] = "5001299999999"
        replacement["clientRequisitionID"] = "26-REPLACED"
        replacement["jobTitle"] = "Replacement public role"
        changed["jobRequisitions"][-1] = replacement
        details = dict(self.details)
        details[replacement["reqId"]] = {
            "itemID": replacement["reqId"], "requisitionTitle": replacement["jobTitle"],
            "clientRequisitionID": replacement["clientRequisitionID"],
            "requisitionDescription": "<p>Replacement full description.</p>", "requisitionLocations": [],
        }
        transport = MercuryTransport(self.listing, changed, details)
        result = fetch_adp_myjobs("ADP MyJobs", "https://myjobs.adp.com/mercurysystemscareers", "COMP-0084", "Mercury Systems", transport)
        self.assertEqual(result.status, "partial")

    def test_mercury_205_cross_page_reorder_accepts_only_same_global_set(self):
        rows = []
        for i in range(205):
            row = copy.deepcopy(self.listing["jobRequisitions"][i % len(self.listing["jobRequisitions"])])
            row["reqId"] = str(6000000000000 + i)
            row["clientRequisitionID"] = f"M-{i}"
            row["jobTitle"] = f"Mercury future role {i}"
            rows.append(row)
        details = {}
        for row in rows:
            details[row["reqId"]] = {
                "itemID": row["reqId"], "requisitionTitle": row["jobTitle"],
                "clientRequisitionID": row["clientRequisitionID"],
                "requisitionDescription": f"<p>Full body {row['reqId']}</p>", "requisitionLocations": [],
            }
        def payload(page):
            return {"count": 205, "jobRequisitions": page}
        first, second = rows[:200], rows[200:]
        # Exchange one posting between pages during the final reread. The
        # per-page order and membership may move, while the global set stays exact.
        reread_first = first[:-1] + [second[0]]
        reread_second = [first[-1]] + second[1:]
        pages = {0: payload(first), 200: payload(second)}
        reread = {0: payload(reread_first), 200: payload(reread_second)}
        result = fetch_adp_myjobs("ADP MyJobs", "https://myjobs.adp.com/mercurysystemscareers", "COMP-0084", "Mercury Systems", PagedMercuryTransport(pages, reread, details))
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual(len(result.jobs), 205)

        drift = {"count": 205, "jobRequisitions": copy.deepcopy(reread_second)}
        drift["jobRequisitions"][-1] = copy.deepcopy(drift["jobRequisitions"][0])
        bad = PagedMercuryTransport(pages, {0: reread[0], 200: drift}, details)
        result = fetch_adp_myjobs("ADP MyJobs", "https://myjobs.adp.com/mercurysystemscareers", "COMP-0084", "Mercury Systems", bad)
        self.assertEqual(result.status, "partial")

    def test_other_adp_sites_keep_default_page_size_20(self):
        listing = {"count": 0, "jobRequisitions": []}
        transport = MercuryTransport(listing, listing, {})
        result = fetch_adp_myjobs("ADP MyJobs", "https://myjobs.adp.com/astronautics", "C-1", "Astronautics", transport)
        self.assertEqual(result.status, "complete")
        urls = [u for u in transport.urls if "apply-custom-filters" in u]
        self.assertTrue(urls)
        self.assertEqual(parse_qs(urlsplit(urls[0]).query)["$top"], ["20"])


if __name__ == "__main__":
    unittest.main()
