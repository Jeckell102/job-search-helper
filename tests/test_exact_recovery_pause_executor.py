import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from job_search_helper.cli import WriterLockBusy, scraper_lock_name, writer_lock
from job_search_helper.engine import State
from job_search_helper.exact_recovery_pause import (
    PauseJournalStore, freeze_exact_pause_journal,
)
from job_search_helper.exact_recovery_pause_apply import COMPLETE, PauseApplyStore
from job_search_helper.exact_recovery_pause_executor import (
    MAX_CHUNK_BYTES, _chunks, execute_exact_recovery_pause,
)
from job_search_helper.exact_recovery_terminal import (
    qualify_terminal_holds, revalidate_terminal_manifest,
)
from job_search_helper.inbox import InventoryInbox
from job_search_helper.repository import MemoryRepository, SCHEMAS, UncertainWriteError


class RecordingRemote(MemoryRepository):
    def __init__(self, companies, cycle):
        super().__init__({
            "Companies": companies,
            "Scan Cycles": [cycle],
        }, schemas=copy.deepcopy(SCHEMAS))
        self.commits = []
        self.fail_before_tab = None
        self.lose_after_tab = None

    def commit(self, operations):
        operations = copy.deepcopy(list(operations))
        tab = operations[0]["tab"]
        self.commits.append(operations)
        if self.fail_before_tab == tab:
            self.fail_before_tab = None
            raise OSError("request not issued")
        result = super().commit(operations)
        if self.lose_after_tab == tab:
            self.lose_after_tab = None
            raise UncertainWriteError("response lost")
        return result

    def snapshot(self, tab):
        return copy.deepcopy(super().read(tab))


class ExactRecoveryPauseExecutorTests(unittest.TestCase):
    def fixture(self, candidate_count=2):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        cycle_id = "CYCLE"
        state = State(root / "state.db")
        inbox = InventoryInbox(root / "inbox.db", "fixture")
        journal_store = PauseJournalStore(root / "pause-journal.db")
        apply_store = PauseApplyStore(root / "pause-apply.db")
        self.addCleanup(state.close)
        self.addCleanup(inbox.close)
        self.addCleanup(journal_store.close)
        self.addCleanup(apply_store.close)

        companies = {}
        remote_companies = []
        for index in range(candidate_count):
            company_id = "COMP-%03d" % index
            stage = "queued" if index % 2 == 0 else "inventory"
            companies[company_id] = {"company": company_id, "stage": stage}
            remote_companies.append({
                "Company ID": company_id,
                "Company": company_id,
                "Company Status": "Active",
                "Active Cycle ID": cycle_id,
                "Scan State": "Queued" if stage == "queued" else "In Progress",
                "Automatic Retry?": "Yes",
            })
        companies["HOLD"] = {"company": "Held", "stage": "blocked", "evidence": "keep"}
        companies["PARTIAL"] = {"company": "Partial", "stage": "partial"}
        remote_companies.extend([
            {"Company ID": "HOLD", "Company": "Held", "Company Status": "Active",
             "Active Cycle ID": cycle_id, "Scan State": "Blocked / Manual Review"},
            {"Company ID": "PARTIAL", "Company": "Partial", "Company Status": "Active",
             "Active Cycle ID": cycle_id, "Scan State": "Complete"},
            {"Company ID": "UNRELATED", "Company": "Other", "Company Status": "Active",
             "Active Cycle ID": "OTHER", "Scan State": "Queued", "Notes": "untouched"},
        ])
        cycle = {
            "id": cycle_id,
            "status": "In Progress",
            "started_at": "2026-11-18T00:00:00Z",
            "all": True,
            "companies": companies,
        }
        state.save_cycle(cycle)
        inbox.save(cycle_id, "HOLD", {"jobs": [], "evidence": "keep"})
        inbox.block(cycle_id, "HOLD")
        manifests = qualify_terminal_holds(
            state, inbox, cycle_id, ["HOLD"],
        )["qualified"]

        notes = '{"all":true,"company_ids":' + __import__("json").dumps(
            list(companies), separators=(",", ":"),
        ) + "}"
        remote = RecordingRemote(remote_companies, {
            "Cycle ID": cycle_id,
            "Started At": cycle["started_at"],
            "Cycle Status": "In Progress",
            "Companies in Scope": len(companies),
            "Companies Complete": 0,
            "Companies Partial": 1,
            "Companies Blocked": 1,
            "Companies Remaining": candidate_count,
            "Notes": notes,
        })
        request = root / "next-scan.json"
        request.write_bytes(b"preserve-request")

        def revalidator(manifest):
            return revalidate_terminal_manifest(state, inbox, manifest)

        freeze_exact_pause_journal(
            state, inbox, journal_store, cycle_id, manifests,
            manifest_revalidator=revalidator,
            reason="operator boundary",
            timestamp="2026-11-19T12:00:00Z",
            next_scan_path=request,
        )
        arguments = dict(
            state=state, inbox=inbox, journal_store=journal_store,
            apply_store=apply_store, remote=remote, cycle_id=cycle_id,
            manifests=manifests, manifest_revalidator=revalidator,
            next_scan_path=request,
        )
        return root, arguments

    def test_full_apply_is_bounded_exact_and_preserves_holds_and_unrelated_data(self):
        root, arguments = self.fixture(candidate_count=51)
        remote = arguments["remote"]
        unrelated_before = remote.snapshot("Companies")[-1]
        hold_before = copy.deepcopy(arguments["inbox"].get("CYCLE", "HOLD"))

        result = execute_exact_recovery_pause(**arguments)

        self.assertEqual(result["status"], COMPLETE)
        company_commits = [call for call in remote.commits if call[0]["tab"] == "Companies"]
        self.assertEqual([len(call) for call in company_commits], [50, 1])
        self.assertTrue(all(
            len(__import__("json").dumps({"companies": call}).encode()) <= 500_000
            for call in company_commits
        ))
        self.assertEqual(remote.snapshot("Companies")[-1], unrelated_before)
        self.assertEqual(arguments["inbox"].get("CYCLE", "HOLD"), hold_before)
        self.assertEqual((root / "next-scan.json").read_bytes(), b"preserve-request")

        cycle = arguments["state"].cycle("CYCLE")
        self.assertEqual(cycle["companies"]["HOLD"]["stage"], "blocked")
        self.assertEqual(cycle["companies"]["HOLD"]["evidence"], "keep")
        self.assertEqual(cycle["companies"]["PARTIAL"]["stage"], "partial")
        self.assertTrue(all(cycle["companies"][company_id]["stage"] == "paused"
                            for company_id in result["paused_company_ids"]))
        scan = remote.snapshot("Scan Cycles")[0]
        self.assertEqual(scan["Cycle Status"], "Complete with exceptions")
        self.assertEqual(scan["Companies Remaining"], 0)
        self.assertEqual(scan["Companies Partial"], 1)
        self.assertEqual(scan["Companies Blocked"], 52)

    def test_lost_company_response_recovers_by_readback_without_replay(self):
        _root, arguments = self.fixture()
        remote = arguments["remote"]
        remote.lose_after_tab = "Companies"
        with self.assertRaises(UncertainWriteError):
            execute_exact_recovery_pause(**arguments)
        company_calls = len([call for call in remote.commits if call[0]["tab"] == "Companies"])

        result = execute_exact_recovery_pause(**arguments)

        self.assertEqual(result["status"], COMPLETE)
        self.assertEqual(
            len([call for call in remote.commits if call[0]["tab"] == "Companies"]),
            company_calls,
        )

    def test_frozen_run_before_first_intent_revalidates_and_resumes(self):
        _root, arguments = self.fixture()
        store = arguments["apply_store"]
        with patch.object(store, "begin", side_effect=OSError("crash before intent")):
            with self.assertRaises(OSError):
                execute_exact_recovery_pause(**arguments)
        self.assertIsNotNone(store.run("CYCLE"))
        self.assertEqual(arguments["remote"].commits, [])

        result = execute_exact_recovery_pause(**arguments)

        self.assertEqual(result["status"], COMPLETE)

    def test_confirmed_company_chunk_crash_resumes_without_replay(self):
        _root, arguments = self.fixture()
        store = arguments["apply_store"]
        remote = arguments["remote"]
        original = store.confirm

        def confirm_then_crash(cycle_id, kind, ordinal, digest, acknowledgement):
            result = original(cycle_id, kind, ordinal, digest, acknowledgement)
            if kind == "CHUNK":
                raise OSError("crash after chunk confirmation")
            return result

        with patch.object(store, "confirm", side_effect=confirm_then_crash):
            with self.assertRaises(OSError):
                execute_exact_recovery_pause(**arguments)
        company_calls = len([call for call in remote.commits if call[0]["tab"] == "Companies"])

        result = execute_exact_recovery_pause(**arguments)

        self.assertEqual(result["status"], COMPLETE)
        self.assertEqual(
            len([call for call in remote.commits if call[0]["tab"] == "Companies"]),
            company_calls,
        )

    def test_pending_company_intent_that_did_not_write_is_never_replayed(self):
        _root, arguments = self.fixture()
        remote = arguments["remote"]
        remote.fail_before_tab = "Companies"
        with self.assertRaises(OSError):
            execute_exact_recovery_pause(**arguments)
        calls = len(remote.commits)

        with self.assertRaisesRegex(ValueError, "pending_chunk_intent_readback_mismatch"):
            execute_exact_recovery_pause(**arguments)
        self.assertEqual(len(remote.commits), calls)

    def test_crash_after_state_save_recovers_without_company_replay(self):
        _root, arguments = self.fixture()
        state = arguments["state"]
        remote = arguments["remote"]
        original = state.save_cycle

        def save_then_crash(cycle):
            original(cycle)
            raise OSError("crash after atomic state save")

        with patch.object(state, "save_cycle", side_effect=save_then_crash):
            with self.assertRaises(OSError):
                execute_exact_recovery_pause(**arguments)
        company_calls = len([call for call in remote.commits if call[0]["tab"] == "Companies"])

        result = execute_exact_recovery_pause(**arguments)

        self.assertEqual(result["status"], COMPLETE)
        self.assertEqual(
            len([call for call in remote.commits if call[0]["tab"] == "Companies"]),
            company_calls,
        )

    def test_state_intent_without_state_write_is_never_replayed(self):
        _root, arguments = self.fixture()
        state = arguments["state"]
        with patch.object(state, "save_cycle", side_effect=OSError("not written")):
            with self.assertRaises(OSError):
                execute_exact_recovery_pause(**arguments)
        calls = len(arguments["remote"].commits)

        with self.assertRaisesRegex(ValueError, "pending_state_intent_readback_mismatch"):
            execute_exact_recovery_pause(**arguments)
        self.assertEqual(len(arguments["remote"].commits), calls)

    def test_confirmed_state_crash_resumes_at_scan_only(self):
        _root, arguments = self.fixture()
        store = arguments["apply_store"]
        remote = arguments["remote"]
        original = store.confirm

        def confirm_then_crash(cycle_id, kind, ordinal, digest, acknowledgement):
            result = original(cycle_id, kind, ordinal, digest, acknowledgement)
            if kind == "STATE_FINALIZATION":
                raise OSError("crash after state confirmation")
            return result

        with patch.object(store, "confirm", side_effect=confirm_then_crash):
            with self.assertRaises(OSError):
                execute_exact_recovery_pause(**arguments)
        company_calls = len([call for call in remote.commits if call[0]["tab"] == "Companies"])

        result = execute_exact_recovery_pause(**arguments)

        self.assertEqual(result["status"], COMPLETE)
        self.assertEqual(
            len([call for call in remote.commits if call[0]["tab"] == "Companies"]),
            company_calls,
        )

    def test_lost_scan_response_finishes_by_exact_readback_without_replay(self):
        _root, arguments = self.fixture()
        remote = arguments["remote"]
        remote.lose_after_tab = "Scan Cycles"
        with self.assertRaises(UncertainWriteError):
            execute_exact_recovery_pause(**arguments)
        scan_calls = len([call for call in remote.commits if call[0]["tab"] == "Scan Cycles"])

        result = execute_exact_recovery_pause(**arguments)

        self.assertEqual(result["status"], COMPLETE)
        self.assertEqual(
            len([call for call in remote.commits if call[0]["tab"] == "Scan Cycles"]),
            scan_calls,
        )

    def test_pending_scan_intent_that_did_not_write_is_never_replayed(self):
        _root, arguments = self.fixture()
        remote = arguments["remote"]
        remote.fail_before_tab = "Scan Cycles"
        with self.assertRaises(OSError):
            execute_exact_recovery_pause(**arguments)
        calls = len(remote.commits)

        with self.assertRaisesRegex(ValueError, "pending_scan_intent_readback_mismatch"):
            execute_exact_recovery_pause(**arguments)
        self.assertEqual(len(remote.commits), calls)

    def test_completed_rerun_is_readback_only(self):
        _root, arguments = self.fixture()
        execute_exact_recovery_pause(**arguments)
        calls = len(arguments["remote"].commits)

        result = execute_exact_recovery_pause(**arguments)

        self.assertEqual(result["status"], COMPLETE)
        self.assertEqual(len(arguments["remote"].commits), calls)

    def test_real_writer_lock_contention_prevents_any_apply_access(self):
        root, arguments = self.fixture()
        remote = arguments["remote"]
        exact_lock = Path(arguments["state"].path).parent / scraper_lock_name()
        with patch.object(arguments["state"], "cycle") as state_cycle, \
             patch.object(arguments["inbox"], "pending") as inbox_pending, \
             patch.object(arguments["journal_store"], "read") as journal_read, \
             patch.object(arguments["apply_store"], "run") as apply_run, \
             writer_lock(exact_lock):
            with self.assertRaises(TypeError):
                execute_exact_recovery_pause(
                    **arguments, lock_path=root / "attacker-selected.lock",
                )
            with self.assertRaises(WriterLockBusy):
                execute_exact_recovery_pause(**arguments)
        state_cycle.assert_not_called()
        inbox_pending.assert_not_called()
        journal_read.assert_not_called()
        apply_run.assert_not_called()
        self.assertEqual(remote.commits, [])

    def test_non_file_backed_state_is_rejected_before_protected_access(self):
        for path in (":memory:", "/definitely/missing/pause-state.db"):
            with self.subTest(path=path):
                state = MagicMock()
                state.path = path
                inbox = MagicMock()
                journal = MagicMock()
                apply = MagicMock()
                remote = MagicMock()
                with self.assertRaisesRegex(ValueError, "file_backed_state_required"):
                    execute_exact_recovery_pause(
                        state, inbox, journal, apply, remote, "CYCLE", [],
                        manifest_revalidator=lambda manifest: manifest,
                    )
                state.cycle.assert_not_called()
                inbox.pending.assert_not_called()
                journal.read.assert_not_called()
                apply.run.assert_not_called()
                remote.read_columns.assert_not_called()

    def test_chunks_reject_small_then_oversized_and_every_payload_is_bounded(self):
        small = {"company_id": "SMALL", "operation": {}, "readback": {}}
        oversized = {
            "company_id": "LARGE", "operation": {"value": "x" * MAX_CHUNK_BYTES},
            "readback": {},
        }
        with self.assertRaisesRegex(ValueError, "operation_exceeds_chunk_limit"):
            list(_chunks([small, oversized]))

        entries = [
            {"company_id": "C-%03d" % index,
             "operation": {"value": "x" * 20_000}, "readback": {}}
            for index in range(75)
        ]
        payloads = list(_chunks(entries))
        self.assertEqual(sum(len(payload["companies"]) for payload in payloads), 75)
        for payload in payloads:
            encoded = json.dumps(
                payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ).encode("utf-8")
            self.assertLessEqual(len(encoded), MAX_CHUNK_BYTES)
            self.assertLessEqual(len(payload["companies"]), 50)

    def test_control_or_journal_drift_stops_before_first_intent(self):
        _root, arguments = self.fixture()
        remote = arguments["remote"]
        remote.commit([{
            "tab": "Companies", "identity": {"Company ID": "COMP-000"},
            "values": {"Claimed By": "other", "Claim Token": "claim"},
        }])
        remote.commits.clear()
        with self.assertRaisesRegex(ValueError, "pause_company_claimed"):
            execute_exact_recovery_pause(**arguments)
        self.assertEqual(arguments["apply_store"].run("CYCLE"), None)
        self.assertEqual(remote.commits, [])


if __name__ == "__main__":
    unittest.main()
