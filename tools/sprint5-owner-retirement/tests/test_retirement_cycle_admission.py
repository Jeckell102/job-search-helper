import copy
from contextlib import redirect_stdout
from datetime import datetime, timezone
from io import StringIO
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from job_search_helper.scan_request import (
    _cycle_views, _unfinished_cycle_ids, _unfinished_from_views,
    company_event_timing, company_only_intake_start_measurement,
    company_only_queue_status,
    requested_scan, request_fingerprint,
)


RETIRED = "CYC-B639C6D864EC"
VERIFIER = "job_search_helper.retained_cycle_retirement_control.verified_retired_cycle_ids"


def local_cycle(cycle_id, **values):
    return {"id": cycle_id, "status": "In Progress", "companies": {"COMP-0054": {}},
            "started_at": "2026-11-20T12:00:00Z", **values}


def mirror(cycle):
    return {"Cycle ID": cycle["id"], "Cycle Status": cycle["status"],
            "Started At": cycle.get("started_at", ""),
            "Completed At": cycle.get("completed_at", ""),
            "Notes": json.dumps({key: value for key, value in cycle.items()
                                 if key in ("supersedes", "companies")})}


class ReadOnlyState:
    def __init__(self, cycles):
        self.records = cycles

    def cycles(self):
        return self.records


class ReadOnlyRepository:
    def __init__(self, rows):
        self.records = rows
        self.read_count = 0

    def read_columns(self, tab, headers):
        assert tab == "Scan Cycles"
        self.read_count += 1
        return list(enumerate(self.records, 2))


class RetirementCycleAdmissionTests(unittest.TestCase):
    """Exercise admission consumers; archive/custody verification has its own owner."""

    def setUp(self):
        self.old = local_cycle(RETIRED)
        self.other = local_cycle("CYC-OTHER")
        self.state = ReadOnlyState([self.old, self.other])
        self.repo = ReadOnlyRepository([mirror(self.old), mirror(self.other)])
        self.engine = SimpleNamespace(repo=self.repo)

    def verified(self, value):
        # create=True permits this focused seam to run while the separate
        # author is finishing the durable verifier in the same source stage.
        return patch(VERIFIER, return_value=value, create=True)

    def test_no_marker_preserves_views_and_existing_unfinished_blockers(self):
        with self.verified(set()) as verified:
            local, remote = _cycle_views(self.repo, self.state)
        verified.assert_called_once_with(self.state)
        self.assertIs(local, self.state.records)
        self.assertEqual(remote, self.repo.records)
        self.assertEqual(_unfinished_from_views(local, remote), {RETIRED, "CYC-OTHER"})

    def test_exact_verified_retirement_excludes_both_views_without_storage_changes(self):
        before = copy.deepcopy((self.state.records, self.repo.records))
        with self.verified({RETIRED}):
            local, remote = _cycle_views(self.repo, self.state)
            self.assertEqual(_unfinished_cycle_ids(self.engine, self.state), {"CYC-OTHER"})
        self.assertEqual([row["id"] for row in local], ["CYC-OTHER"])
        self.assertEqual([row["Cycle ID"] for row in remote], ["CYC-OTHER"])
        self.assertEqual(before, (self.state.records, self.repo.records))
        self.assertEqual(self.old["status"], "In Progress")
        self.assertNotIn("completed_at", self.old)

    def test_unrelated_mirror_only_blocker_is_preserved(self):
        self.repo.records.append(mirror(local_cycle("CYC-MIRROR-ONLY")))
        with self.verified({RETIRED}):
            self.assertEqual(_unfinished_cycle_ids(self.engine, self.state),
                             {"CYC-OTHER", "CYC-MIRROR-ONLY"})

    def test_retirement_does_not_resurrect_previously_superseded_cycles(self):
        previous = local_cycle("CYC-PREVIOUS")
        self.old["supersedes"] = [previous["id"]]
        self.state.records.append(previous)
        self.repo.records = [mirror(row) for row in self.state.records]
        before = copy.deepcopy((self.state.records, self.repo.records))
        with self.verified(set()):
            self.assertEqual(_unfinished_cycle_ids(self.engine, self.state), {RETIRED, "CYC-OTHER"})
        with self.verified({RETIRED}):
            self.assertEqual(_unfinished_cycle_ids(self.engine, self.state), {"CYC-OTHER"})
        self.assertEqual(before, (self.state.records, self.repo.records))

    def test_local_only_view_never_reads_repository(self):
        with self.verified({RETIRED}):
            local, remote = _cycle_views(None, self.state, include_remote=False)
        self.assertEqual([row["id"] for row in local], ["CYC-OTHER"])
        self.assertEqual(remote, [])
        self.assertEqual(self.repo.read_count, 0)

    def test_missing_state_does_not_invent_remote_retirement_authority(self):
        with self.verified({RETIRED}) as verified:
            local, remote = _cycle_views(self.repo, None)
        verified.assert_not_called()
        self.assertEqual(local, [])
        self.assertEqual(_unfinished_from_views(local, remote), {RETIRED, "CYC-OTHER"})

    def test_verification_failure_and_malformed_result_fail_closed(self):
        before = copy.deepcopy((self.state.records, self.repo.records))
        with patch(VERIFIER, side_effect=ValueError("archive changed"), create=True):
            with self.assertRaisesRegex(ValueError, "archive changed"):
                _unfinished_cycle_ids(self.engine, self.state)
        for result in (None, [], RETIRED, {RETIRED: True}, {""}, {" padded"}, {1}):
            with self.subTest(result=result), self.verified(result):
                with self.assertRaisesRegex(ValueError, "retirement IDs"):
                    _cycle_views(self.repo, self.state)
        self.assertEqual(before, (self.state.records, self.repo.records))

    def test_repository_read_fallback_preserves_retirement_scope(self):
        repo = SimpleNamespace(read=lambda tab: self.repo.records)
        with self.verified({RETIRED}):
            self.assertEqual(_unfinished_from_views(*_cycle_views(repo, self.state)), {"CYC-OTHER"})

    def test_deferred_retirement_never_awards_completion_or_busy_timing_credit(self):
        observed = "2026-11-21T10:00:00Z"
        with self.verified({RETIRED}):
            local, remote = _cycle_views(self.repo, self.state)
        timing = company_event_timing(observed, [RETIRED], local, remote)
        self.assertEqual(timing["blocking_cycle_ids"], [RETIRED])
        self.assertEqual(timing["condition"], "unverified")
        request = {"mode": "company-only", "enqueued_at": "2026-11-21T10:01:00Z",
                   "company_event": {"event_id": "EVENT-NEW"},
                   "company_event_timing": timing}
        started = {"started_at": "2026-11-21T10:02:00Z"}
        measurement = company_only_intake_start_measurement(request, started, local, mirror_cycles=remote)
        self.assertEqual(measurement["condition"], "unverified")
        self.assertIsNone(measurement["target_met"])
        self.assertNotIn("safe_boundary_completed_at", measurement)

    def test_queue_status_becomes_ready_only_when_all_actual_blockers_are_gone(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = {"mode": "company-only", "request_id": "REQ-NEW", "company_ids": ["COMP-NEW"],
                       "source_revision": "revision-new", "enqueued_at": "2026-11-21T10:00:00Z",
                       "start_last": []}
            queue = root / "next-scan.json"
            queue.write_text(json.dumps(request))
            original_queue = queue.read_bytes()
            now = datetime(2026, 11, 21, 10, 2, tzinfo=timezone.utc)
            with self.verified({RETIRED}):
                held = company_only_queue_status(self.engine, self.state, root / "state.db", observed_at=now)
                self.assertEqual(held["state"], "WAITING_SAFE_BOUNDARY")
                self.assertEqual(held["blocking_cycle_ids"], ["CYC-OTHER"])
                self.state.records = [self.old]
                self.repo.records = [mirror(self.old)]
                ready = company_only_queue_status(self.engine, self.state, root / "state.db", observed_at=now)
            self.assertEqual(ready["state"], "READY_FOR_START")
            self.assertEqual(ready["blocking_cycle_ids"], [])
            self.assertEqual(queue.read_bytes(), original_queue)
            self.assertEqual(self.old["status"], "In Progress")

    def replay_fixture(self, mode, *, retired):
        from job_search_helper.engine import State
        from job_search_helper.retained_cycle_retirement import VERSION, _digest

        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        state = State()
        self.addCleanup(state.close)
        request = {"mode": mode, "request_id": "REQ-REPLAY", "start_last": []}
        company_ids = None
        if mode == "company-only":
            company_ids = ["COMP-0054"]
            request.update(company_ids=company_ids, source_revision="revision-old",
                           enqueued_at="2026-11-20T11:00:00Z")
        old = local_cycle(RETIRED, start_request_id=request["request_id"],
                          request_fingerprint=request_fingerprint(request, company_ids))
        state.save_cycle(old)
        state.save_cycle(self.other)
        if retired:
            # Exercise the real replay guard against a stored retirement record.
            # Archive verification itself remains covered by its owning suite.
            record = {"version": VERSION, "cycle_id": RETIRED,
                      "state": "RETIRED_UNPUBLISHED"}
            with state.connection:
                state.connection.execute(
                    "CREATE TABLE retained_cycle_retirements "
                    "(cycle TEXT PRIMARY KEY, record TEXT NOT NULL, sha256 TEXT NOT NULL)")
                state.connection.execute("INSERT INTO retained_cycle_retirements VALUES (?,?,?)",
                                         (RETIRED, json.dumps(record), _digest(record)))
        repo = ReadOnlyRepository([mirror(old), mirror(self.other)])
        engine = SimpleNamespace(repo=repo, start_cycle=Mock(), _sync_cycle=Mock())
        queue = root / "next-scan.json"
        queue.write_text(json.dumps(request))
        return root, state, engine, queue

    def test_exact_retired_request_replay_refuses_before_checkpoint_mirror_or_queue_change(self):
        for mode in ("company-only", "fresh-full-scan"):
            with self.subTest(mode=mode):
                root, state, engine, queue = self.replay_fixture(mode, retired=True)
                last = root / "last-scan-request.json"
                last.write_text('{"request_id":"unrelated-previous-request"}')
                before = (list(state.connection.iterdump()), copy.deepcopy(engine.repo.records),
                          queue.read_bytes(), last.read_bytes())
                with self.verified({RETIRED}), patch.object(state, "save_cycle", wraps=state.save_cycle) as save:
                    with self.assertRaisesRegex(ValueError, "saved scrape was retired"):
                        requested_scan(engine, state, root / "state.db")
                    save.assert_not_called()
                engine.start_cycle.assert_not_called()
                engine._sync_cycle.assert_not_called()
                self.assertEqual(before, (list(state.connection.iterdump()), engine.repo.records,
                                          queue.read_bytes(), last.read_bytes()))

    def test_exact_request_replay_without_retirement_keeps_existing_behavior(self):
        for mode in ("company-only", "fresh-full-scan"):
            with self.subTest(mode=mode):
                root, state, engine, queue = self.replay_fixture(mode, retired=False)
                original_queue = queue.read_bytes()
                unrelated = state.cycle("CYC-OTHER")
                with patch.object(state, "save_cycle", wraps=state.save_cycle) as save, redirect_stdout(StringIO()):
                    self.assertEqual(requested_scan(engine, state, root / "state.db"), RETIRED)
                engine.start_cycle.assert_not_called()
                self.assertEqual(save.call_count, int(mode == "company-only"))
                self.assertEqual(engine._sync_cycle.call_count, int(mode == "company-only"))
                self.assertFalse(queue.exists())
                self.assertEqual((root / "last-scan-request.json").read_bytes(), original_queue)
                self.assertEqual(state.cycle("CYC-OTHER"), unrelated)
                self.assertEqual(state.cycle(RETIRED)["status"], "In Progress")


if __name__ == "__main__":
    unittest.main()
