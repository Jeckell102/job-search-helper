"""Offline compression recovery tests; no sockets, credentials or Sheet access."""
import copy
import gzip
import json
import unittest
from unittest.mock import patch

from job_search_helper.repository import GoogleRepository, RepositoryError, UncertainWriteError
from test_repository import FakeSheets, operation

try:
    import httplib2
    import google_auth_httplib2
    import googleapiclient.http
    from httplib2.decode import DecodeLimitError, DecodeRatioError
    from googleapiclient.http import HttpRequest, MAX_URI_LENGTH
except ImportError:
    httplib2 = None


if httplib2 is not None:
    class CompressionHTTP(httplib2.Http):
        """Real header negotiation and decoder, fake server, never opens a socket."""
        def __init__(self, *, ignore_identity=False, value=None):
            super().__init__(decode_limit_safe=128, decode_limit_ratio=20,
                             decode_limit_hard=1 << 20)
            self.calls = []
            self.ignore_identity = ignore_identity
            self.payload = json.dumps(value or {"values": [["repeated " * 5000]]}).encode()

        def _request(self, conn, host, uri, request_uri, method, body, headers, redirections, cachekey):
            self.calls.append({"uri": uri, "method": method, "body": body,
                               "headers": copy.deepcopy(headers)})
            response = httplib2.Response({"status": "200", "content-type": "application/json"})
            content = self.payload
            if headers.get("accept-encoding") != "identity" or self.ignore_identity:
                response["content-encoding"] = "gzip"
                content = gzip.compress(content)
            return response, httplib2._decompressContent(response, content, self.limit_kwargs)


    class SequenceHTTP:
        def __init__(self, outcomes):
            self.outcomes = iter(outcomes)
            self.calls = []

        def request(self, uri, method="GET", body=None, headers=None, **kwargs):
            self.calls.append({"uri": uri, "method": method, "body": body,
                               "headers": copy.deepcopy(headers)})
            value = next(self.outcomes)
            if isinstance(value, Exception):
                raise value
            return httplib2.Response({"status": "200"}), json.dumps(value).encode()


    class LocalCredentials:
        def before_request(self, request, method, uri, headers):
            headers["authorization"] = "Bearer local-test-token"

        def refresh(self, request):
            raise AssertionError("No real authentication is permitted")


@unittest.skipIf(httplib2 is None, "Google optional dependencies unavailable")
class ReadRecoveryTests(unittest.TestCase):
    def repo(self, interval=0):
        return GoogleRepository(None, "fixture", min_request_interval=interval)

    def request(self, transport, *, method="GET", headers=None, uri=None, resumable=None):
        return HttpRequest(transport, lambda response, content: json.loads(content),
                           uri or "https://sheets.example.invalid/v4/spreadsheets/fixture?ranges=one",
                           method=method, headers=headers or {}, resumable=resumable)

    def test_real_decoder_recovers_by_negotiation_and_preserves_auth(self):
        transport = CompressionHTTP()
        authorized = google_auth_httplib2.AuthorizedHttp(LocalCredentials(), http=transport)
        request = self.request(authorized, headers={"X-Custom": "keep", "Accept-Encoding": "gzip"})
        repo = self.repo()
        original_limits = transport.limit_kwargs.copy()
        with patch("googleapiclient.http._retry_request", wraps=googleapiclient.http._retry_request) as retry:
            result = repo._execute(request, "read")
        self.assertEqual(result, json.loads(transport.payload))
        self.assertEqual([call.args[1] for call in retry.call_args_list], [5, 0])
        self.assertEqual([call["headers"]["accept-encoding"] for call in transport.calls], ["gzip", "identity"])
        self.assertTrue(all(call["headers"]["authorization"] == "Bearer local-test-token" for call in transport.calls))
        self.assertTrue(all(call["headers"]["x-custom"] == "keep" for call in transport.calls))
        self.assertEqual(request.headers["Accept-Encoding"], "gzip")
        self.assertNotIn("accept-encoding", request.headers)
        self.assertIs(request.http, authorized)
        self.assertEqual(transport.limit_kwargs, original_limits)
        self.assertEqual(repo.metrics["read_requests"], 2)
        self.assertEqual(repo.metrics["read_response_bytes"], len(json.dumps(result, ensure_ascii=True).encode()))

    def test_default_compression_and_long_get_conversion_preserved(self):
        transport = CompressionHTTP()
        uri = "https://sheets.example.invalid/v4/spreadsheets/fixture?ranges=" + "a" * MAX_URI_LENGTH
        request = self.request(transport, uri=uri)
        self.repo()._execute(request, "read")
        first, second = transport.calls
        self.assertEqual(first["headers"]["accept-encoding"], "gzip, deflate")
        self.assertEqual(second["headers"]["accept-encoding"], "identity")
        for name in ("uri", "method", "body"):
            self.assertEqual(first[name], second[name])
        self.assertEqual(second["method"], "POST")
        self.assertEqual(second["headers"]["x-http-method-override"], "GET")
        self.assertEqual(second["headers"]["content-length"], str(len(second["body"])))
        self.assertNotIn("?", second["uri"])
        self.assertEqual(request.headers["x-http-method-override"], "GET")

    def test_duplicate_encoding_headers_removed_only_on_copy(self):
        headers = {"Accept-Encoding": "gzip", "ACCEPT-ENCODING": "deflate", "x-custom": "keep"}
        transport = SequenceHTTP([DecodeRatioError("private cell content"), {}])
        request = self.request(transport, headers=headers.copy())
        self.repo()._execute(request, "read")
        recovery = transport.calls[1]["headers"]
        self.assertEqual([key for key in recovery if key.lower() == "accept-encoding"], ["accept-encoding"])
        self.assertEqual(recovery["accept-encoding"], "identity")
        for key, value in headers.items():
            self.assertEqual(request.headers[key], value)

    def test_server_ignores_identity_still_hits_real_guard_and_stops(self):
        transport = CompressionHTTP(ignore_identity=True)
        repo = self.repo()
        repo._write_layout["cached"] = ([], 1)
        repo._metadata_cache = {"cached": True}
        repo._header_cache["cached"] = []
        with self.assertRaisesRegex(RepositoryError, "DecodeRatioError") as caught:
            repo._execute(self.request(transport), "read")
        self.assertEqual(len(transport.calls), 2)
        self.assertIsInstance(caught.exception.__cause__, DecodeRatioError)
        self.assertEqual(repo._write_layout, {})
        self.assertIsNone(repo._metadata_cache)
        self.assertEqual(repo._header_cache, {})

    def test_only_actual_ratio_error_recovers_not_limit_or_named_impostor(self):
        impostor = type("DecodeRatioError", (Exception,), {})
        for error in (DecodeLimitError("private cell content"), RuntimeError("private cell content"), impostor("private cell content")):
            with self.subTest(error=type(error)):
                transport = SequenceHTTP([error])
                with self.assertRaises(RepositoryError) as caught:
                    self.repo()._execute(self.request(transport), "read")
                self.assertEqual(len(transport.calls), 1)
                self.assertNotIn("private cell content", str(caught.exception))

    def test_identity_retry_failure_is_sanitized_and_not_retried(self):
        transport = SequenceHTTP([DecodeRatioError("private first body"), RuntimeError("private second body")])
        with self.assertRaisesRegex(RepositoryError, "RuntimeError") as caught:
            self.repo()._execute(self.request(transport), "read")
        self.assertEqual(len(transport.calls), 2)
        self.assertNotIn("private", str(caught.exception))

    def test_writes_never_retry_even_if_method_get(self):
        for method in ("GET", "POST"):
            with self.subTest(method=method):
                transport = SequenceHTTP([DecodeRatioError("private write response")])
                repo = self.repo()
                with self.assertRaisesRegex(UncertainWriteError, "No successful write is confirmed"):
                    repo._execute(self.request(transport, method=method), "write")
                self.assertEqual(len(transport.calls), 1)
                self.assertEqual(repo.metrics["write_requests"], 1)
                self.assertEqual(repo.metrics["read_requests"], 0)

    def test_unconfirmed_read_methods_and_already_identity_are_not_retried(self):
        cases = [("POST", {}), ("PATCH", {}), ("DELETE", {}),
                 ("GET", {"x-http-method-override": "DELETE"}),
                 ("GET", {b"x-http-method-override": "DELETE"}),
                 ("GET", {"x-http-method-override": b"DELETE"}),
                 ("POST", {"x-http-method-override": "GET", "X-HTTP-Method-Override": "DELETE"}),
                 ("GET", {"Accept-Encoding": "identity"})]
        for method, headers in cases:
            with self.subTest(method=method, headers=headers):
                transport = SequenceHTTP([DecodeRatioError("guard")])
                with self.assertRaises(RepositoryError):
                    self.repo()._execute(self.request(transport, method=method, headers=headers), "read")
                self.assertEqual(len(transport.calls), 1)

    def test_unknown_request_and_resumable_not_recovered(self):
        class Unknown:
            method, headers = "GET", {}
            def execute(self, **kwargs):
                raise DecodeRatioError("guard")
        with self.assertRaises(RepositoryError):
            self.repo()._execute(Unknown(), "read")
        request = self.request(SequenceHTTP([]), resumable=object())
        with patch.object(HttpRequest, "next_chunk", side_effect=DecodeRatioError("guard")) as execute:
            with self.assertRaises(RepositoryError):
                self.repo()._execute(request, "read")
        self.assertEqual(execute.call_count, 1)

    def test_recovery_is_paced_and_counted_as_additional_read(self):
        transport = SequenceHTTP([DecodeRatioError("guard"), {}])
        repo = self.repo(interval=2.5)
        with patch("job_search_helper.repository.time.monotonic", return_value=100.0), \
                patch("job_search_helper.repository.time.sleep") as sleep:
            repo._execute(self.request(transport), "read")
        sleep.assert_called_once_with(2.5)
        self.assertEqual(repo.metrics["read_requests"], 2)
        self.assertEqual(repo._next_request_at, 102.5)

    def test_successful_read_does_not_add_request_or_change_headers(self):
        transport = SequenceHTTP([{}])
        request = self.request(transport)
        repo = self.repo()
        repo._execute(request, "read")
        self.assertEqual(len(transport.calls), 1)
        self.assertNotIn("accept-encoding", request.headers)
        self.assertEqual(repo.metrics["read_requests"], 1)

    def test_recovered_commit_read_still_checks_expected_fields_before_write(self):
        owner = self
        class RecoveringSheets(FakeSheets):
            def get(self, **kwargs):
                value = super().get(**kwargs).execute()
                transport = SequenceHTTP([DecodeRatioError("guard"), value])
                return owner.request(transport)
        service = RecoveringSheets({"Job History": [{"Job Key": "job-1", "Company": "Acme", "Review Status": "User changed"}]})
        repo = GoogleRepository(service, "fixture", min_request_interval=0)
        with self.assertRaisesRegex(RepositoryError, "changed since planning"):
            repo.commit([operation(values={"Review Notes": "reviewed"}, expected={"Review Status": "Needs Review"})])
        self.assertEqual(service.batches, [])
        self.assertGreaterEqual(repo.metrics["read_requests"], 4)


if __name__ == "__main__":
    unittest.main()
