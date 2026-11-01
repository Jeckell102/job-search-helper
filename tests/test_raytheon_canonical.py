"""Raytheon canonical identity checks through the real Phenom provider."""
import gzip
import json
import unittest
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.phenom import _identity, _origin, _posting, _read


PARENT = "https://careers.rtx.com/global/en"
SCOPED = "https://careers.rtx.com/global/en/raytheon"
APP = {"refNum": "RAYTGLOBAL", "baseUrl": "https://careers.rtx.com/global/en/",
       "siteType": "external", "locale": "en_global"}
EID = {"searchType": "landingPage", "query": 'businessUnit.businessUnit_sort:("Raytheon")'}


def _entry(number, title=None):
    return {"jobId": str(number), "jobSeqNo": f"RAYTGLOBAL{number}EXTERNALENUS",
            "title": title or f"Raytheon Systems Engineer {number}",
            "siteType": "external", "jobVisibility": ["external"]}


def _listing(items, total=2, offset=0, *, generic=False):
    result = {"status": 200, "hits": len(items), "totalHits": total,
              "data": {"jobs": items, "keywords": ""},
              "lpKey": "l-new-raytheon" if not generic else "l-generic",
              "eid": EID if not generic else {"searchType": "landingPage", "query": ""}}
    body = ('<script>var phApp = phApp || ' + json.dumps(APP) + '; '
            'phApp.ddo = ' + json.dumps({"targetedJobs": result}) + '; '
            'phApp.sessionParams = {"from": "' + str(offset) + '"};</script>')
    return HTTPResponse(200, body.encode(), {"content-type": "text/html"})


def _detail(number, *, canonical="valid", generic=False):
    job = _entry(number)
    job.update(refNum="RAYTGLOBAL", reqId=f"REQ-{number}",
               businessUnit="Acme" if generic else "Raytheon",
               description="<p>Full public job responsibilities and qualifications.</p>",
               requiredSkillsEducation="<p>Required engineering experience.</p>",
               preferredSkillsEducation="<p>Preferred systems experience.</p>")
    body = ('<script>var phApp = phApp || ' + json.dumps(APP) + '; '
            'phApp.ddo = ' + json.dumps({"jobDetail": {"status": 200, "data": {"job": job}}})
            + '; phApp.sessionParams = {};</script>')
    if not generic:
        if canonical == "valid":
            href = f"https://careers.rtx.com/global/en/job/{number}/raytheon-{number}"
            body = f'<link rel="canonical" href="{href}">' + body
        elif canonical == "wrong-id":
            body = '<link rel="canonical" href="https://careers.rtx.com/global/en/job/999/wrong">' + body
        elif canonical == "wrong-origin":
            body = '<link rel="canonical" href="https://evil.example/job/1/foreign">' + body
        elif canonical == "multiple":
            body = ('<link rel="canonical" href="https://careers.rtx.com/global/en/job/'
                    f'{number}/first"><link rel="canonical" href="https://careers.rtx.com/global/en/job/'
                    f'{number}/second">' + body)
        elif canonical == "unicode-slug":
            # This is the exact shape observed in the recorded Raytheon
            # response for 01877262: the slug contains a non-breaking space.
            body = ('<link rel="canonical" href="https://careers.rtx.com/global/en/job/'
                    f'{number}/Sr-Principal-System-Administrators-Lead-\u00a0based-in-Tucson-AZ">' + body)
        elif canonical == "ascii-space":
            body = f'<link rel="canonical" href="https://careers.rtx.com/global/en/job/{number}/bad slug">' + body
        elif canonical == "control":
            body = f'<link rel="canonical" href="https://careers.rtx.com/global/en/job/{number}/bad\x01slug">' + body
        elif canonical == "dotdot":
            body = f'<link rel="canonical" href="https://careers.rtx.com/global/en/job/{number}/../bad">' + body
    return HTTPResponse(200, body.encode(), {"content-type": "text/html"})


class _Transport:
    def __init__(self, *, canonical="valid", generic=False):
        self.canonical = canonical
        self.generic = generic
        self.urls = []

    def get(self, url):
        self.urls.append(url)
        parsed = urlsplit(url)
        if parsed.path.endswith("/raytheon") or (self.generic and parsed.path.rstrip("/") == "/global/en"):
            offset = int(parse_qs(parsed.query).get("from", ["0"])[0])
            return _listing([_entry(1)] if offset == 0 else [_entry(2)], generic=self.generic)
        if "/job/1" in parsed.path:
            return _detail(1, canonical="valid" if self.canonical == "valid" else self.canonical,
                           generic=self.generic)
        if "/job/2" in parsed.path:
            return _detail(2, canonical=self.canonical, generic=self.generic)
        raise AssertionError(f"unexpected Phenom URL: {url}")


class RaytheonCanonicalTests(unittest.TestCase):
    def fetch(self, transport):
        return fetch_inventory("Phenom (career site)", PARENT, "COMP-0078", "Raytheon",
                               discovery_transport=transport)

    def test_actual_board_canonical_head_becomes_public_identity_url(self):
        result = self.fetch(_Transport())
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual({job["url"] for job in result.jobs}, {
            "https://careers.rtx.com/global/en/job/1/raytheon-1",
            "https://careers.rtx.com/global/en/job/2/raytheon-2",
        })

    def test_recorded_unicode_space_in_canonical_slug_is_valid(self):
        transport = _Transport(canonical="unicode-slug")
        result = self.fetch(transport)
        self.assertEqual(result.status, "complete", result.reason)
        self.assertTrue(any("Sr-Principal-System-Administrators-Lead-" in job["url"] for job in result.jobs))

    def test_actual_recorded_detail_html_round_trips_through_read_and_posting(self):
        fixture = Path(__file__).with_name("fixtures") / "phenom" / "raytheon-01877262.html.gz"
        body = gzip.open(fixture, "rb").read()
        source = "https://careers.rtx.com/global/en/job/01877262"

        class OneResponse:
            def get(self, url):
                self.url = url
                self.asserted = url == source
                return HTTPResponse(200, body, {"content-type": "text/html; charset=UTF-8"})

        transport = OneResponse()
        page = _read(source, transport, _origin(source))
        job = page[2]["jobDetail"]["data"]["job"]
        entry = {"jobId": job["jobId"], "jobSeqNo": job["jobSeqNo"], "title": job["title"]}
        entry.update(siteType=job["siteType"], jobVisibility=job["jobVisibility"])
        normalized = _posting(page, entry, _identity(page[1]), "COMP-0078", "Raytheon")
        self.assertEqual(normalized["posting_id"], "01877262")
        self.assertEqual(normalized["url"], "https://careers.rtx.com/global/en/job/01877262/Sr-Principal-System-Administrators-Lead-\u00a0based-in-Tucson-AZ")
        self.assertGreater(len(normalized["description"]), 1000)

    def test_wrong_id_origin_multiple_and_missing_canonical_fail_closed(self):
        for kind in ("wrong-id", "wrong-origin", "multiple", "missing", "ascii-space", "control", "dotdot"):
            result = self.fetch(_Transport(canonical=kind))
            self.assertNotEqual(result.status, "complete", kind)

    def test_other_phenom_board_without_raytheon_canonical_guard_remains_usable(self):
        result = fetch_inventory("Phenom", PARENT, "COMP-OTHER", "Acme",
                                discovery_transport=_Transport(generic=True))
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual({job["posting_id"] for job in result.jobs}, {"1", "2"})


if __name__ == "__main__":
    unittest.main()
