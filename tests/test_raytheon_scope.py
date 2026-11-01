"""Provider-invocation regressions for Raytheon's scoped RTX Phenom board."""
import json
import unittest
from urllib.parse import urlsplit, parse_qs

from job_search_helper.ats import HTTPResponse, fetch_inventory

PARENT = "https://careers.rtx.com/global/en"
SCOPED = "https://careers.rtx.com/global/en/raytheon"
APP = {"refNum": "RAYTGLOBAL", "baseUrl": "https://careers.rtx.com/global/en/",
       "siteType": "external", "locale": "en_global"}
EID = {"searchType": "landingPage", "query": 'businessUnit.businessUnit_sort:("Raytheon")'}


def entry(n=1, title=None):
    return {"jobId": str(n), "jobSeqNo": f"RAYTGLOBAL{n}EXTERNALENUS",
            "title": title or f"Raytheon Systems Engineer {n}",
            "siteType": "external", "jobVisibility": ["external"]}


def page(items, total=2, offset=0, *, lp="l-new-raytheon", eid=None):
    result = {"status": 200, "hits": len(items), "totalHits": total,
              "data": {"jobs": items, "keywords": ""}, "lpKey": lp,
              "eid": EID if eid is None else eid}
    body = ('<script>var phApp = phApp || ' + json.dumps(APP) + '; '
            'phApp.ddo = ' + json.dumps({"targetedJobs": result}) + '; '
            'phApp.sessionParams = {"from": "' + str(offset) + '"};</script>')
    return HTTPResponse(200, body.encode(), {"content-type": "text/html"})


def detail(n=1):
    job = entry(n)
    job.update(refNum="RAYTGLOBAL", reqId=f"REQ-{n}",
               businessUnit="Raytheon",
               description="<p>Full Raytheon job responsibilities and qualifications.</p>",
               requiredSkillsEducation="<p>Required engineering experience.</p>",
               preferredSkillsEducation="<p>Preferred systems experience.</p>")
    body = (f'<link rel="canonical" href="https://careers.rtx.com/global/en/job/{n}/raytheon-{n}">'
            '<script>var phApp = phApp || ' + json.dumps(APP) + '; '
            'phApp.ddo = ' + json.dumps({"jobDetail": {"status": 200, "data": {"job": job}}})
            + '; phApp.sessionParams = {};</script>')
    return HTTPResponse(200, body.encode(), {"content-type": "text/html"})


class ReplayTransport:
    def __init__(self, responses):
        self.responses = iter(responses); self.urls = []
    def get(self, url):
        self.urls.append(url)
        return next(self.responses)


def successful_pages(a=None, b=None, *, final_a=None, final_b=None, total=2):
    a, b = a or entry(1), b or entry(2)
    return [page([a], total), page([b], total, 1), detail(1), detail(2),
            page([final_a or a], total), page([final_b or b], total, 1)]


class RaytheonScopeTests(unittest.TestCase):
    def run_fetch(self, responses, url=PARENT):
        return fetch_inventory("Phenom (career site)", url, "COMP-0078", "Raytheon",
                               discovery_transport=ReplayTransport(responses))

    def test_configured_parent_row_is_repaired_to_scoped_provider_invocation(self):
        transport = ReplayTransport(successful_pages())
        result = fetch_inventory("Phenom (career site)", PARENT, "COMP-0078", "Raytheon",
                                discovery_transport=transport)
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual(len(result.jobs), 2)
        self.assertEqual(transport.urls[0], SCOPED)
        self.assertTrue(all(urlsplit(u).hostname == "careers.rtx.com" for u in transport.urls))

    def test_business_unit_and_landing_key_must_remain_identical_on_every_page(self):
        bad = page([entry(2)], 2, 1, eid={"searchType": "landingPage", "query": 'businessUnit.businessUnit_sort:("Collins Aerospace")'})
        result = self.run_fetch([page([entry(1)]), bad, detail(1)])
        self.assertEqual(result.status, "partial")
        self.assertEqual([j["posting_id"] for j in result.jobs], ["1"])

    def test_unfiltered_parent_response_cannot_complete_raytheon(self):
        result = self.run_fetch([page([entry(1)], lp=None, eid={"searchType": "allJobs", "query": ""})])
        self.assertNotEqual(result.status, "complete")
        self.assertEqual(result.jobs, [])

    def test_offset_page_must_not_repeat_first_page(self):
        result = self.run_fetch([page([entry(1)]), page([entry(1)], 2, 1), detail(1)])
        self.assertEqual(result.status, "partial")
        self.assertEqual([j["posting_id"] for j in result.jobs], ["1"])

    def test_total_change_and_final_membership_change_fail_closed(self):
        result = self.run_fetch([page([entry(1)]), page([entry(2)], 3, 1), detail(1)])
        self.assertEqual(result.status, "partial")
        # Every reconciliation pass changes the second-page identity; a single
        # changed pass is allowed to stabilize, but this never establishes
        # closure and must remain partial.
        responses = [page([entry(1)]), page([entry(2)], 2, 1), detail(1), detail(2)]
        for n in (99, 98, 97, 96):
            responses.extend([page([entry(1)], 2), page([entry(n)], 2, 1), detail(n)])
        result = self.run_fetch(responses)
        self.assertEqual(result.status, "partial")


if __name__ == "__main__":
    unittest.main()
