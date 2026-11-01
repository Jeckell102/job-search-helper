import json
import unittest

from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.kratos import SEARCH, SOURCE


def posting(jid, title, description=""):
    return {"jid": jid, "job_title": title, "jobdescription": description,
            "cid": 85347, "companyname": "Kratos Defense"}


class Public:
    def __init__(self, responses): self.responses = list(responses); self.calls = []
    def post(self, url, payload, headers=None):
        self.calls.append((url, payload, headers))
        if url != SEARCH or headers != {"cid": "85347"}: raise AssertionError((url, headers))
        return HTTPResponse(200, json.dumps(self.responses.pop(0)).encode())


class KratosTests(unittest.TestCase):
    def test_complete_inventory_fetches_and_rechecks_every_detail(self):
        listing = [posting(1, "Engineer"), posting(2, "Analyst")]
        public = Public([listing, [posting(1, "Engineer", "A" * 90)], [posting(2, "Analyst", "B" * 90)], listing])
        result = fetch_inventory("Kratos careers", SOURCE, "COMP-0068", "Kratos Defense & Security Solutions", public)
        self.assertEqual(result.status, "complete")
        self.assertEqual([job["title"] for job in result.jobs], ["Engineer", "Analyst"])
        self.assertEqual(len(public.calls), 4)

    def test_detail_mismatch_fails_closed(self):
        listing = [posting(1, "Engineer")]
        public = Public([listing, [posting(1, "Changed", "A" * 90)]])
        result = fetch_inventory("Kratos careers", SOURCE, "COMP-0068", "Kratos Defense & Security Solutions", public)
        self.assertEqual(result.status, "partial")
        self.assertEqual(result.jobs, [])

    def test_changed_inventory_fails_closed(self):
        listing = [posting(1, "Engineer")]
        public = Public([listing, [posting(1, "Engineer", "A" * 90)], [posting(2, "Engineer")]])
        result = fetch_inventory("Kratos careers", SOURCE, "COMP-0068", "Kratos Defense & Security Solutions", public)
        self.assertEqual(result.status, "partial")
        self.assertEqual(len(result.jobs), 1)

    def test_other_company_cannot_use_adapter(self):
        result = fetch_inventory("Kratos careers", SOURCE, "COMP-OTHER", "Other", Public([]))
        self.assertEqual(result.status, "unsupported")
