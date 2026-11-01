import unittest
from unittest.mock import patch

from job_search_helper.ats import FetchError, HTTPResponse
from job_search_helper.successfactors import _get


class _SequenceClient:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def get(self, _url):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class SuccessFactorsRetryTests(unittest.TestCase):
    @patch("job_search_helper.successfactors.time.sleep")
    def test_failed_transport_retries_then_succeeds(self, sleep):
        client = _SequenceClient([
            FetchError("failed", "connection reset"),
            FetchError("failed", "connection reset"),
            HTTPResponse(200, b"ok"),
        ])
        self.assertEqual(_get(client, "https://careers.leonardodrs.com/"), "ok")
        self.assertEqual(client.calls, 3)
        self.assertEqual(sleep.call_count, 2)

    @patch("job_search_helper.successfactors.time.sleep")
    def test_transient_http_status_retries(self, sleep):
        client = _SequenceClient([HTTPResponse(503, b""), HTTPResponse(200, b"ok")])
        self.assertEqual(_get(client, "https://careers.leonardodrs.com/"), "ok")
        self.assertEqual(client.calls, 2)
        self.assertEqual(sleep.call_count, 1)

    @patch("job_search_helper.successfactors.time.sleep")
    def test_non_transient_http_status_does_not_retry(self, sleep):
        for status, expected in ((404, "partial"), (403, "blocked")):
            with self.subTest(status=status):
                client = _SequenceClient([HTTPResponse(status, b"")])
                with self.assertRaises(FetchError) as raised:
                    _get(client, "https://careers.leonardodrs.com/")
                self.assertEqual(raised.exception.status, expected)
                self.assertEqual(client.calls, 1)
        self.assertEqual(sleep.call_count, 0)

    @patch("job_search_helper.successfactors.time.sleep")
    def test_failed_transport_exhausts_bounded_retries(self, sleep):
        client = _SequenceClient([FetchError("failed", "timeout")] * 3)
        with self.assertRaises(FetchError) as raised:
            _get(client, "https://careers.leonardodrs.com/")
        self.assertEqual(raised.exception.status, "failed")
        self.assertEqual(client.calls, 3)
        self.assertEqual(sleep.call_count, 2)


if __name__ == "__main__":
    unittest.main()
