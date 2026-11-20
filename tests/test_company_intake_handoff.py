import json
from pathlib import Path
import tempfile
import unittest

from job_search_helper.company_events import _json_digest
from job_search_helper.scrape_first_pass import Blocked, company_intake_handoff


def request():
    return {"mode": "company-only", "request_id": "company-event:CEV-1", "company_ids": ["COMP-1"], "source_revision": "rev", "enqueued_at": "2026-11-19T00:00:00Z", "start_last": [], "company_event": {"schema": "company-event-scan-request-v1", "event_id": "CEV-1", "company_id": "COMP-1", "revision": 1, "source_revision": "rev"}}


class CompanyIntakeHandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name) / ".state"; self.state.mkdir()
        self.work = self.state / "scrape-first-pass"; self.work.mkdir()

    def write(self, candidate=None, handoff=None):
        candidate = candidate or request()
        (self.state / "next-scan.json").write_text(json.dumps(candidate))
        handoff = handoff or {"request_id": candidate["request_id"], "request_digest": _json_digest(candidate)}
        (self.work / "company-intake-handoff.json").write_text(json.dumps(handoff))

    def test_exact_sidecar_is_accepted(self):
        self.write()
        self.assertEqual(company_intake_handoff(self.work)["request_id"], "company-event:CEV-1")

    def test_stale_or_forged_sidecar_blocks_before_workflow_creation(self):
        self.write(handoff={"request_id": "company-event:CEV-OLD", "request_digest": "wrong"})
        with self.assertRaisesRegex(Blocked, "does not match"):
            company_intake_handoff(self.work)
        (self.state / "next-scan.json").unlink()
        with self.assertRaisesRegex(Blocked, "unreadable"):
            company_intake_handoff(self.work)

    def test_matching_forged_sidecar_cannot_bypass_event_identity(self):
        forged = request(); forged["request_id"] = "not-company-event"
        self.write(candidate=forged, handoff={"request_id": forged["request_id"], "request_digest": _json_digest(forged)})
        with self.assertRaisesRegex(Blocked, "does not match"):
            company_intake_handoff(self.work)
