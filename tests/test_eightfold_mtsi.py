import json
import unittest
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from job_search_helper.eightfold import Client, fetch_eightfold
from job_search_helper.ats import FetchError
from job_search_helper.mtsi import fetch_mtsi


class Response:
    status = 200
    headers = {}
    def __init__(self, data): self._body = json.dumps({"status": 200, "data": data}).encode()
    def body(self): return self._body
    def dispose(self): pass


class Request:
    def __init__(self): self.urls=[]
    def get(self, url, **kwargs):
        self.urls.append(url)
        q=parse_qs(urlsplit(url).query)
        return Response({"count": 0, "positions": []} if urlsplit(url).path.endswith("/search") else {})


class EightfoldMtsiTests(unittest.TestCase):
    def test_unknown_sort_rejected_before_any_request_or_browser_launch(self):
        req=Request()
        with self.assertRaises(FetchError):
            Client(type('Context',(),{'request':req})(),'https://talent.mtsi-va.com','mtsi-va.com','unverified')
        result=fetch_eightfold('https://talent.mtsi-va.com/careers','COMP-0017','Modern Technology Solutions, Inc. (MTSI)',sort_by='unverified')
        self.assertEqual(result.status,'unsupported')
        self.assertEqual(req.urls,[])

    def test_mtsi_hot_sort_is_propagated_with_valid_offsets(self):
        req=Request(); client=Client(type("Context",(),{"request":req})(),"https://talent.mtsi-va.com","mtsi-va.com","hot")
        client.data("search",0); client.data("search",10)
        queries=[parse_qs(urlsplit(url).query) for url in req.urls]
        self.assertEqual([q["start"] for q in queries],[["0"],["10"]])
        self.assertEqual([q["sort_by"] for q in queries],[["hot"],["hot"]])
        self.assertTrue(all(q["domain"]==["mtsi-va.com"] for q in queries))

    def test_default_sort_behavior_remains_unmodified(self):
        req=Request(); client=Client(type("Context",(),{"request":req})(),"https://searchcareers.caci.com","caci.com")
        client.data("search",20)
        query=parse_qs(urlsplit(req.urls[0]).query)
        self.assertEqual(query["start"],["20"]); self.assertNotIn("sort_by",query)

    def test_mtsi_route_enables_hot_sort_and_listing_first(self):
        with patch("job_search_helper.eightfold.fetch_eightfold") as fetch:
            fetch.return_value = object()
            result = fetch_mtsi(
                "https://talent.mtsi-va.com/careers",
                "COMP-0017", "Modern Technology Solutions, Inc. (MTSI)")
        self.assertIs(result, fetch.return_value)
        fetch.assert_called_once_with(
            "https://talent.mtsi-va.com/careers", "COMP-0017",
            "Modern Technology Solutions, Inc. (MTSI)", "Eightfold",
            sort_by="hot", listing_first=True)


if __name__ == "__main__": unittest.main()
