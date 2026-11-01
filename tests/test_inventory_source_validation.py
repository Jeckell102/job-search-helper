"""Source validation must run before any provider tries to parse the URL."""

import unittest
import socket
from unittest.mock import MagicMock, patch

from job_search_helper.ats import Inventory, fetch_inventory
from job_search_helper.company_sources import repair_source
from job_search_helper.discovery import CareersTransport, DEFAULT_USER_AGENT


class InventorySourceValidationTests(unittest.TestCase):
    def test_missing_or_malformed_source_returns_inventory_instead_of_crashing(self):
        for url in (None, "", "   ", 42, {}):
            with self.subTest(url=url):
                result = fetch_inventory("Browser", url, "C-UNKNOWN", "Unknown")
                self.assertEqual(result.status, "unsupported")
                self.assertEqual(result.jobs, [])
                self.assertIn("Missing Official Careers URL", result.reason)

    def test_malformed_registered_source_does_not_crash_the_repair_layer(self):
        result = fetch_inventory("Browser", None, "COMP-0427", "Annapolis Micro Systems")
        self.assertEqual(result.status, "unsupported")

    def test_empty_registered_source_still_uses_verified_repair(self):
        with patch("job_search_helper.dayforce.fetch_dayforce", return_value=Inventory("complete")) as fetch:
            result = fetch_inventory("Browser", "", "COMP-0143", "MultiTech")
        self.assertEqual(result.status, "complete")
        self.assertIn("Verified company source repair", result.reason)
        self.assertEqual(fetch.call_args.args[1], "https://us231.dayforcehcm.com/CandidatePortal/en-US/multitech")

    def test_html_adapter_keeps_explicit_html_transport(self):
        class EmptyTransport:
            def __bool__(self):
                return False

        html_transport = EmptyTransport()
        api_transport = object()
        with patch("job_search_helper.kuka.fetch_kuka", return_value=Inventory("complete")) as fetch:
            fetch_inventory(
                "KUKA", "https://www.kuka.com/en-us/company/careers",
                "COMP-0246", "KUKA Robotics", api_transport,
                discovery_transport=html_transport,
            )
        self.assertIs(fetch.call_args.args[3], html_transport)

    def test_source_repair_never_replaces_a_user_changed_url(self):
        url = "https://example.com/new-careers/"
        self.assertEqual(
            repair_source("Browser", url, "COMP-0427", "Annapolis Micro Systems"),
            ("Browser", url, ""),
        )

    def test_html_transport_keeps_default_headers_and_allows_explicit_site_header(self):
        for user_agent in (None, "Mozilla/5.0"):
            with self.subTest(user_agent=user_agent):
                client = CareersTransport(sleep=lambda _: None, **(
                    {} if user_agent is None else {"user_agent": user_agent}
                ))
                client.context = MagicMock()
                addresses = [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 443))]
                with patch("job_search_helper.discovery._public_addresses", return_value=addresses), \
                        patch("job_search_helper.discovery.socket.socket"), \
                        patch("job_search_helper.discovery.HTTPSConnection") as connection:
                    response = connection.return_value.getresponse.return_value
                    response.status = 200
                    response.read.return_value = b"<html>Public page</html>"
                    response.getheaders.return_value = []
                    result = client.get("https://example.com/careers/")
                self.assertEqual(result.status, 200)
                request = connection.return_value.request.call_args
                self.assertEqual(request.args, ("GET", "/careers/"))
                self.assertEqual(request.kwargs["headers"]["User-Agent"], user_agent or DEFAULT_USER_AGENT)
                self.assertEqual(request.kwargs["headers"]["Accept-Encoding"], "identity")


if __name__ == "__main__":
    unittest.main()
