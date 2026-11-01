from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from job_search_helper.ats import HTTPResponse
from job_search_helper.kontron import fetch_kontron


ROOT = "https://www.kontron.com"
SOURCE = ROOT + "/en/group/careers"
SOFTGARDEN = ROOT + "/api/cms/softgarden/jobs?locale=en"
PAYLOCITY = ROOT + "/api/paylocity/jobs"
CHANNELS = ROOT + "/api/cms/softgarden/channels"
FIXTURES = Path(__file__).parent / "fixtures" / "kontron"


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class Transport:
    """Replay the two observed public JSON endpoints; reject detail/apply fetches."""
    def __init__(self, softgarden=None, paylocity=None, softgarden_recheck=None, paylocity_recheck=None):
        self.softgarden = softgarden or fixture("softgarden-en.json")
        self.paylocity = paylocity or fixture("paylocity.json")
        self.softgarden_recheck = softgarden_recheck if softgarden_recheck is not None else self.softgarden
        self.paylocity_recheck = paylocity_recheck if paylocity_recheck is not None else self.paylocity
        self.calls = []
        self._reads = {SOFTGARDEN: 0, PAYLOCITY: 0, CHANNELS: 0}

    def _payload(self, url):
        if url == CHANNELS:
            self._reads[url] += 1
            return {"success": True, "data": [{"id": "147418_extern", "accessible": True, "name": "Default Channel"}]}
        if url == SOFTGARDEN:
            self._reads[url] += 1
            return self.softgarden if self._reads[url] == 1 else self.softgarden_recheck
        if url == PAYLOCITY:
            self._reads[url] += 1
            return self.paylocity if self._reads[url] == 1 else self.paylocity_recheck
        raise AssertionError(f"unexpected non-feed request: {url}")

    def get(self, url):
        self.calls.append(url)
        return HTTPResponse(200, json.dumps(self._payload(url)).encode(), {"content-type": "application/json"})

    def get_json(self, url):
        self.calls.append(url)
        return self._payload(url)


class KontronTests(unittest.TestCase):
    def fetch(self, transport):
        return fetch_kontron(SOURCE, "COMP-0289", "Kontron", transport)

    def test_both_public_feeds_are_complete_and_reread(self):
        transport = Transport()
        result = self.fetch(transport)
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual(len(result.jobs), 79)
        self.assertEqual(len({j["posting_id"] for j in result.jobs}), 79)
        self.assertEqual(result.source_url, SOURCE)
        self.assertEqual(result.ats, "Kontron")
        self.assertEqual(sum(bool(j.get("description", "").strip()) for j in result.jobs), 79)
        self.assertEqual(transport.calls.count(SOFTGARDEN), 2)
        self.assertEqual(transport.calls.count(PAYLOCITY), 2)
        self.assertEqual(transport.calls.count(CHANNELS), 2)

    def test_feed_failure_is_partial_and_preserves_other_jobs(self):
        class Failing(Transport):
            def _payload(self, url):
                if url == PAYLOCITY:
                    raise OSError("paylocity unavailable")
                return super()._payload(url)
        result = self.fetch(Failing())
        self.assertEqual(result.status, "partial")
        self.assertEqual(len(result.jobs), 74)

    def test_blocked_feed_is_blocked_and_preserves_other_jobs(self):
        class BlockedPaylocity(Transport):
            def get(self, url):
                self.calls.append(url)
                if url == PAYLOCITY:
                    return HTTPResponse(403, b"forbidden", {"content-type": "text/plain"})
                return super().get(url)
        result = self.fetch(BlockedPaylocity())
        self.assertEqual(result.status, "blocked")
        self.assertEqual(len(result.jobs), 74)

    def test_missing_softgarden_body_is_partial(self):
        soft = fixture("softgarden-en.json")
        soft["data"][0]["jobAdText"] = ""
        result = self.fetch(Transport(softgarden=soft))
        self.assertEqual(result.status, "partial")

    def test_duplicate_public_ids_are_partial(self):
        soft = fixture("softgarden-en.json")
        soft["data"][1]["jobDbId"] = soft["data"][0]["jobDbId"]
        result = self.fetch(Transport(softgarden=soft))
        self.assertEqual(result.status, "partial")
        self.assertGreaterEqual(len(result.jobs), 73)

    def test_source_specific_ids_and_company_scope_are_enforced(self):
        soft = fixture("softgarden-en.json")
        soft["data"][0]["jobDbId"] = "pl-foreign"
        result = self.fetch(Transport(softgarden=soft))
        self.assertEqual(result.status, "partial")
        soft = fixture("softgarden-en.json")
        soft["data"][0]["company_name"] = None
        result = self.fetch(Transport(softgarden=soft))
        self.assertEqual(result.status, "partial")

    def test_malformed_company_metadata_is_partial(self):
        for value in (None, 17, [], {}):
            soft = fixture("softgarden-en.json")
            soft["data"][0]["company_name"] = value
            self.assertEqual(self.fetch(Transport(softgarden=soft)).status, "partial", value)

    def test_paylocity_source_metadata_is_pinned(self):
        pay = fixture("paylocity.json")
        pay["data"][0]["source"] = "softgarden"
        self.assertEqual(self.fetch(Transport(paylocity=pay)).status, "partial")

    def test_invalid_softgarden_ids_are_each_rejected(self):
        for bad in (None, 0, True, ""):
            soft = fixture("softgarden-en.json")
            soft["data"][0]["jobDbId"] = bad
            self.assertEqual(self.fetch(Transport(softgarden=soft)).status, "partial", bad)

    def test_invalid_paylocity_ids_are_each_rejected(self):
        for bad in (None, 0, True, ""):
            pay = fixture("paylocity.json")
            pay["data"][0]["jobDbId"] = bad
            self.assertEqual(self.fetch(Transport(paylocity=pay)).status, "partial", bad)

    def test_invalid_public_date_is_partial(self):
        soft = fixture("softgarden-en.json")
        soft["data"][0]["jobStartDate"] = "not-a-date"
        self.assertEqual(self.fetch(Transport(softgarden=soft)).status, "partial")

    def test_negative_public_timestamp_is_partial(self):
        soft = fixture("softgarden-en.json")
        soft["data"][0]["jobStartDate"] = -1
        self.assertEqual(self.fetch(Transport(softgarden=soft)).status, "partial")

    def test_channel_scope_and_api_source_are_pinned(self):
        class WrongChannel(Transport):
            def _payload(self, url):
                data = super()._payload(url)
                if url == CHANNELS:
                    data["data"][0]["id"] = "other_channel"
                return data
        self.assertEqual(self.fetch(WrongChannel()).status, "partial")
        transport = Transport()
        self.assertEqual(fetch_kontron("https://www.kontron.com/en/career", "COMP-0289", "Kontron", transport).status, "unsupported")
        self.assertEqual(transport.calls, [])

    def test_final_membership_or_body_change_is_partial(self):
        first = fixture("softgarden-en.json")
        final = copy.deepcopy(first)
        final["data"][-1]["jobAdText"] += " changed after detail fetch"
        result = self.fetch(Transport(softgarden=first, softgarden_recheck=final))
        self.assertEqual(result.status, "partial")

    def test_epoch_and_iso_dates_and_remote_mapping_are_retained(self):
        result = self.fetch(Transport())
        self.assertTrue(any(j.get("created_at") for j in result.jobs))
        pay = [j for j in result.jobs if str(j.get("posting_id", "")).startswith("pl-")]
        self.assertEqual(len(pay), 5)
        # The observed US feed has no remote_status field; its public location is
        # still retained and zero/blank compensation placeholders are not invented.
        self.assertTrue(any("Springfield" in j.get("location", "") for j in pay))
        self.assertIn("$120K", next(j.get("compensation", "") for j in pay if j["posting_id"] == "pl-4562403"))
        self.assertTrue(all("applyonline" not in j.get("url", "").lower() for j in result.jobs))

    def test_query_alias_on_configured_source_is_rejected_before_network(self):
        transport = Transport()
        result = fetch_kontron(SOURCE + "?locale=en", "COMP-0289", "Kontron", transport)
        self.assertEqual(result.status, "unsupported")
        self.assertEqual(transport.calls, [])

    def test_configured_row_dispatches_to_composite_provider_and_exact_allowlist(self):
        transport = Transport()
        from job_search_helper.ats import fetch_inventory
        result = fetch_inventory("Browser", SOURCE, "COMP-0289", "Kontron", transport)
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual(set(transport.calls), {CHANNELS, SOFTGARDEN, PAYLOCITY})
        self.assertEqual(transport.calls.count(CHANNELS), 2)
        self.assertEqual(transport.calls.count(SOFTGARDEN), 2)
        self.assertEqual(transport.calls.count(PAYLOCITY), 2)


if __name__ == "__main__":
    unittest.main()
