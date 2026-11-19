"""Offline recovery tests for the Company-event to scoped-request bridge."""
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from job_search_helper.company_events import CompanyEventBridge
from job_search_helper.repository import SCHEMAS
from job_search_helper.sqlite_repository import SQLiteRepository


def company(**changes):
    row = {
        "Company": "Acme", "Company ID": "COMP-1", "Company Status": "Active",
        "Official Careers URL": "https://jobs.example.test/acme", "ATS / Source": "Greenhouse",
    }
    row.update(changes)
    return row


class CompanyEventBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = SQLiteRepository(self.root / "jobs.sqlite3", "test-sheet", initialize=True)
        self.addCleanup(self.repo.close)
        for tab in SCHEMAS:
            self.repo.import_rows(tab, enumerate([company()] if tab == "Companies" else [], 2))
        self.clock = lambda: datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)
        self.bridge = CompanyEventBridge(self.repo, self.root / "state", now=self.clock)

    def event(self, **values):
        return self.repo.mutate_company_with_event({
            "tab": "Companies", "identity": {"Company ID": "COMP-1"}, "values": values,
        })["company_event"]

    def test_eligible_event_creates_exactly_one_immutable_company_only_request(self):
        event = self.event(**{"ATS / Source": "Lever"})
        delivered = self.bridge.process_pending()
        self.assertEqual(delivered[0]["state"], "REQUEST_WRITTEN")
        request = json.loads(self.bridge.request_path.read_text())
        self.assertEqual(request["mode"], "company-only")
        self.assertEqual(request["company_ids"], ["COMP-1"])
        self.assertEqual(request["source_revision"], event["source_revision"])
        self.assertEqual(request["company_event"]["event_id"], event["event_id"])
        self.assertEqual(self.repo.pending_company_events(self.bridge.consumer), [])

    def test_standalone_bridge_takes_the_normal_scraper_writer_lock(self):
        self.event(**{"ATS / Source": "Lever"})
        with patch("job_search_helper.company_events.writer_lock") as lock:
            lock.return_value.__enter__.return_value = None
            delivered = self.bridge.process_pending()
        self.assertEqual(delivered[0]["state"], "REQUEST_WRITTEN")
        lock.assert_called_once_with(self.root / "state" / "scraper.lock")

    def test_crash_after_durable_write_before_ack_recovers_without_second_request(self):
        event = self.event(**{"ATS / Source": "Lever"})
        original_ack = self.repo.acknowledge_company_event

        def crash(*args, **kwargs):
            raise RuntimeError("simulated process death before acknowledgement")

        self.repo.acknowledge_company_event = crash
        with self.assertRaisesRegex(RuntimeError, "process death"):
            self.bridge.process_pending()
        original = self.bridge.request_path.read_bytes()
        self.repo.acknowledge_company_event = original_ack
        recovered = CompanyEventBridge(self.repo, self.root / "state", now=self.clock)
        self.assertEqual(recovered.process_pending()[0]["state"], "REQUEST_CONFIRMED")
        self.assertEqual(recovered.request_path.read_bytes(), original)
        self.assertEqual(self.repo.pending_company_events(recovered.consumer), [])
        receipt = json.loads((recovered.evidence_directory / "receipts" / (event["event_id"] + ".json")).read_text())
        self.assertEqual(receipt["event_id"], event["event_id"])

    def test_duplicate_delivery_is_idempotent(self):
        self.event(**{"ATS / Source": "Lever"})
        self.bridge.process_pending()
        request = self.bridge.request_path.read_bytes()
        event = self.repo.mutate_company_with_event({
            "tab": "Companies", "identity": {"Company ID": "COMP-1"},
            "values": {"ATS / Source": "Lever"},
        })["company_event"]
        self.assertIsNone(event)
        self.assertEqual(self.bridge.process_pending(), [])
        self.assertEqual(self.bridge.request_path.read_bytes(), request)

    def test_newest_revision_supersedes_older_unacknowledged_delivery(self):
        first = self.event(**{"ATS / Source": "Lever"})
        original_ack = self.repo.acknowledge_company_event
        self.repo.acknowledge_company_event = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("ack lost"))
        with self.assertRaisesRegex(RuntimeError, "ack lost"):
            self.bridge.process_pending()
        self.repo.acknowledge_company_event = original_ack
        second = self.event(**{"ATS / Source": "Ashby"})
        delivered = self.bridge.process_pending()
        self.assertEqual(len(delivered), 1)
        self.assertEqual(delivered[0]["event_id"], second["event_id"])
        request = json.loads(self.bridge.request_path.read_text())
        self.assertEqual(request["company_event"]["event_id"], second["event_id"])
        self.assertNotEqual(request["company_event"]["event_id"], first["event_id"])
        self.assertEqual(self.repo.pending_company_events(self.bridge.consumer), [])

    def test_page_limit_selects_the_newest_durable_revision_before_delivery(self):
        # More revisions than one bridge page must not briefly schedule an
        # older fact merely because it was encountered first in the outbox.
        latest = None
        for value in range(101):
            latest = self.event(**{"ATS / Source": f"Source-{value}"})
        delivered = self.bridge.process_pending(limit=1)
        self.assertEqual(delivered, [{
            "event_id": latest["event_id"], "company_id": "COMP-1",
            "revision": latest["revision"], "state": "REQUEST_WRITTEN",
        }])
        request = json.loads(self.bridge.request_path.read_text())
        self.assertEqual(request["company_event"]["revision"], latest["revision"])
        self.assertEqual(self.repo.pending_company_events(self.bridge.consumer), [])

    def test_withdrawal_cancels_only_pending_bridge_request_and_never_a_cycle(self):
        self.event(**{"ATS / Source": "Lever"})
        self.bridge.process_pending()
        active_cycle = self.root / "state" / "active-cycle-fixture.json"
        active_cycle.write_text('{"id":"CYC-ACTIVE","status":"Running"}')
        withdrawn = self.event(**{"Company Status": "Paused"})
        delivered = self.bridge.process_pending()
        self.assertEqual(delivered[0]["state"], "PENDING_REQUEST_CANCELLED")
        self.assertFalse(self.bridge.request_path.exists())
        self.assertTrue(active_cycle.exists())
        cancelled = list((self.bridge.evidence_directory / "cancelled-requests").glob("*.json"))
        self.assertEqual(len(cancelled), 1)
        directives = list((self.bridge.evidence_directory / "cancellations").glob("*.json"))
        self.assertEqual(len(directives), 1)
        self.assertEqual(json.loads(directives[0].read_text())["event_id"], withdrawn["event_id"])
        self.assertEqual(self.repo.pending_company_events(self.bridge.consumer), [])

    def test_other_company_request_is_a_safe_boundary_and_is_not_acknowledged(self):
        self.bridge.request_path.parent.mkdir(parents=True)
        self.bridge.request_path.write_text(json.dumps({
            "mode": "company-only", "company_ids": ["OTHER"], "source_revision": "other",
            "company_event": {"event_id": "CEV-other", "company_id": "OTHER", "revision": 1,
                              "source_revision": "other"},
        }))
        event = self.event(**{"ATS / Source": "Lever"})
        delivered = self.bridge.process_pending()
        self.assertEqual(delivered[0]["state"], "WAITING_FOR_SAFE_REQUEST_BOUNDARY")
        self.assertEqual(self.repo.pending_company_events(self.bridge.consumer), [event])

    def test_normal_start_admits_event_request_through_the_shared_writer_boundary(self):
        """The real runner must bridge then admit exactly the declared Company."""
        from unittest.mock import patch
        from job_search_helper import runner
        from job_search_helper.engine import Engine, State
        from test_fetch_pool import inventory

        event = self.event(**{"ATS / Source": "Lever"})
        database = self.root / "state" / "state.db"

        def make_engine(repo, state, **kwargs):
            return Engine(
                repo, state,
                fetcher=lambda source, url, company_id, name: inventory(company_id, name, url),
                **kwargs,
            )

        with patch.object(runner, "_load_environment"), \
             patch.object(runner, "load_title_blacklist"), \
             patch.object(runner, "load_title_review_list"), \
             patch.object(runner, "state_path", return_value=database), \
             patch.object(runner, "get_repository", return_value=self.repo), \
             patch.object(runner, "Engine", side_effect=make_engine), \
             patch.object(runner, "_refresh_review_queue"):
            self.assertEqual(
                runner.run_start(fetch_workers=1, browser_fallback=False, defer_sync=True), 0,
            )

        self.assertFalse((database.parent / "next-scan.json").exists())
        receipt = json.loads((database.parent / "last-scan-request.json").read_text())
        self.assertEqual(receipt["company_event"]["event_id"], event["event_id"])
        self.assertEqual(self.repo.pending_company_events(self.bridge.consumer), [])
        state = State(database, readonly=True)
        self.addCleanup(state.close)
        cycles = state.cycles()
        self.assertEqual(len(cycles), 1)
        self.assertEqual(set(cycles[0]["companies"]), {"COMP-1"})


if __name__ == "__main__":
    unittest.main()
