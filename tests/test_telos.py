import pathlib
import sys
import unittest
from urllib.parse import urlsplit

ROOT = pathlib.Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))

from job_search_helper.ats import HTTPResponse, _safe_api_url
from job_search_helper.telos import VIEW, fetch_telos


EVIDENCE = pathlib.Path("/home/chris/.codex/.chatgpt-projects/g-p-6ab70f626df48191a04039506182677f/work/full-integrations-20261029/telos/evidence")


class EvidenceTransport:
    def __init__(self):
        self.calls = []
    def get(self, url):
        self.calls.append(url)
        parsed = urlsplit(url)
        if parsed.path == urlsplit(VIEW).path:
            body = (EVIDENCE / "viewAll.html").read_bytes()
        elif "/Posting/view/" in parsed.path:
            body = (EVIDENCE / ("detail-" + parsed.path.rsplit("/", 1)[1] + ".html")).read_bytes()
        else:
            raise AssertionError(url)
        return HTTPResponse(200, body, {"content-type": "text/html"})


class TelosTests(unittest.TestCase):
    def test_live_evidence_retrieves_all_sixteen_and_rechecks(self):
        transport = EvidenceTransport()
        result = fetch_telos("https://www.telos.com/careers", "COMP-0308", "Telos Corporation", transport)
        self.assertEqual(result.status, "complete")
        self.assertEqual(len(result.jobs), 16)
        self.assertEqual(len({j["posting_id"] for j in result.jobs}), 16)
        self.assertEqual(transport.calls.count(VIEW), 2)
        self.assertTrue(all(len(j["description"]) > 200 for j in result.jobs))

    def test_wrong_company_or_route_fails_closed(self):
        result = fetch_telos("https://www.telos.com/careers", "COMP-0308", "Other", EvidenceTransport())
        self.assertEqual(result.status, "unsupported")
        result = fetch_telos("https://evil.example/jobs", "COMP-0308", "Telos Corporation", EvidenceTransport())
        self.assertEqual(result.status, "unsupported")

    def test_safe_endpoint_guards(self):
        _safe_api_url(VIEW)
        _safe_api_url("https://telos.hua.hrsmart.com/hr/ats/Posting/view/3714")
        with self.assertRaises(Exception):
            _safe_api_url("https://telos.hua.hrsmart.com/hr/ats/Posting/view/abc")


if __name__ == "__main__":
    unittest.main()
