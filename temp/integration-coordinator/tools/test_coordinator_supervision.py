from collections import namedtuple
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest

from coordinator_store import Store
from coordinator_supervision import (CoordinatorSupervision, POLICY,
                                     external_retention_snapshot, support_matrix,
                                     watchdog)
from test_coordinator_workflow import WorkflowTests


Usage = namedtuple("Usage", "total used free")


class FakeCoordinator:
    def __init__(self, base):
        self.store = Store(base)
        self.stop = threading.Event()
        self.wake = threading.Event()


class CoordinatorSupervisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name) / "tasks"
        self.coordinator = FakeCoordinator(self.base)
        self.usage = Usage(1000, 100, 900)

    def supervisor(self, catch_up=lambda: {"accepted": 0}):
        return CoordinatorSupervision(
            self.coordinator, catch_up, disk_usage=lambda _: self.usage,
            min_free_bytes=100, min_free_ratio=0.05, clock=lambda: 123.0)

    def test_boot_catch_up_and_retention_status_are_durable(self):
        seen = []
        supervisor = self.supervisor(lambda: seen.append(True) or {"accepted": 3})
        result = supervisor.tick()
        self.assertEqual(seen, [True])
        self.assertEqual(result["state"], "ACTIVE")
        self.assertEqual(result["catch_up"], {"accepted": 3})
        self.assertEqual(result["retention"]["policy"], POLICY)
        self.assertFalse(result["retention"]["automatic_cleanup"])
        self.assertEqual(supervisor.status(), result)

    def test_external_retention_counts_are_visible_and_never_cleaned(self):
        supervisor = CoordinatorSupervision(
            self.coordinator, lambda: {"accepted": 0},
            disk_usage=lambda _: self.usage, min_free_bytes=100,
            min_free_ratio=0.05, clock=lambda: 123.0,
            retention_probe=lambda: {
                "unacknowledged_company_events": 2,
                "active_release_records": 1,
                "invalid": -1,
            })
        retention = supervisor.tick()["retention"]
        self.assertEqual(retention["external_protected_counts"], {
            "unacknowledged_company_events": 2,
            "active_release_records": 1,
        })
        self.assertFalse(retention["automatic_cleanup"])

    def test_external_retention_probe_failure_is_visible_not_destructive(self):
        supervisor = CoordinatorSupervision(
            self.coordinator, lambda: {"accepted": 0},
            disk_usage=lambda _: self.usage, min_free_bytes=100,
            min_free_ratio=0.05, clock=lambda: 123.0,
            retention_probe=lambda: (_ for _ in ()).throw(OSError("offline")))
        retention = supervisor.tick()["retention"]
        self.assertIn("OSError", retention["external_probe_error"])
        self.assertFalse(retention["automatic_cleanup"])

    def test_scraper_release_and_publication_evidence_is_counted_read_only(self):
        database = Path(self.temp.name) / "jobs.sqlite3"
        db = sqlite3.connect(database)
        db.executescript("""
            CREATE TABLE company_event_outbox(event_id TEXT PRIMARY KEY);
            CREATE TABLE company_event_deliveries(event_id TEXT, consumer TEXT);
            CREATE TABLE scrape_outcomes(outcome_id TEXT PRIMARY KEY);
            CREATE TABLE scrape_outcome_deliveries(outcome_id TEXT, consumer TEXT);
            INSERT INTO company_event_outbox VALUES('E1');
            INSERT INTO company_event_outbox VALUES('E2');
            INSERT INTO company_event_deliveries VALUES('E2','bridge');
            INSERT INTO scrape_outcomes VALUES('O1');
        """)
        db.commit()
        db.close()
        inventory = sqlite3.connect(database.parent / "inventories.sqlite3")
        inventory.execute("CREATE TABLE publication_receipts(state TEXT)")
        inventory.executemany("INSERT INTO publication_receipts VALUES(?)",
                              [("LOCAL_COMMITTED",), ("SYNC_CONFIRMED",)])
        inventory.commit()
        inventory.close()
        record = database.parent / "release-record"
        record.mkdir()
        (database.parent / "integration-release-journal.json").write_text(
            json.dumps({"state": "INSTALLING", "record": str(record)}))

        counts = external_retention_snapshot(
            database, company_consumer="bridge", outcome_consumer="coordinator")
        self.assertEqual(counts, {
            "unacknowledged_company_events": 1,
            "unacknowledged_scrape_outcomes": 1,
            "unconfirmed_publication_receipts": 1,
            "nonterminal_release_journals": 1,
            "active_release_records": 1,
        })

    def test_disk_pressure_pauses_all_work_without_catch_up_or_cleanup(self):
        self.coordinator.store.configure_queue(True)
        self.usage = Usage(1000, 990, 10)
        seen = []
        result = self.supervisor(lambda: seen.append(True)).tick()
        self.assertEqual(result["state"], "DISK_PRESSURE_HOLD")
        self.assertFalse(self.coordinator.store.queue_enabled())
        self.assertEqual(seen, [])
        self.assertFalse(result["retention"]["automatic_cleanup"])

    def test_disk_pressure_retains_existing_uncommitted_evidence_byte_for_byte(self):
        self.coordinator.store.configure_queue(True)
        with self.coordinator.store.connect() as db:
            db.execute("INSERT INTO tasks VALUES('T1','{}')")
            db.execute("INSERT INTO receipts VALUES(1,'T1','inspect','code_read','{}',NULL,'sig',1.0)")
            db.execute("INSERT INTO inference_receipts VALUES('R1','T1','UNCERTAIN','{}')")
            db.execute("INSERT INTO scrape_outcome_intake VALUES('O1','C1','S1','HELD','{}',1.0)")
            before = {
                table: db.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
                for table in ("tasks", "receipts", "inference_receipts",
                              "scrape_outcome_intake")
            }
        self.usage = Usage(1000, 999, 1)
        result = self.supervisor().tick()
        with self.coordinator.store.connect() as db:
            after = {
                table: db.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
                for table in before
            }
        self.assertEqual(after, before)
        self.assertEqual(result["state"], "DISK_PRESSURE_HOLD")
        self.assertFalse(self.coordinator.store.queue_enabled())
        self.assertEqual(result["retention"]["protected_counts"]["tasks"], 1)
        self.assertEqual(result["retention"]["protected_counts"]["receipts"], 1)
        self.assertEqual(result["retention"]["protected_counts"]["inference_receipts"], 1)
        self.assertEqual(result["retention"]["protected_counts"]["scrape_outcome_intake"], 1)

    def test_catch_up_failure_is_retryable_and_does_not_enable_work(self):
        self.coordinator.store.configure_queue(False)
        result = self.supervisor(lambda: (_ for _ in ()).throw(OSError("offline"))).tick()
        self.assertEqual(result["state"], "CATCHUP_RETRY")
        self.assertIn("OSError", result["error"])
        self.assertFalse(self.coordinator.store.queue_enabled())

    def test_only_one_supervision_owner_exists(self):
        first, second = self.supervisor(), self.supervisor()
        first.acquire()
        self.addCleanup(first.release)
        with self.assertRaisesRegex(RuntimeError, "owns supervision"):
            second.acquire()

    def test_shutdown_persists_pause_and_wakes_scheduler(self):
        self.coordinator.store.configure_queue(True)
        result = self.supervisor().shutdown("test shutdown")
        self.assertEqual(result["state"], "SHUTDOWN_PAUSED")
        self.assertFalse(self.coordinator.store.queue_enabled())
        self.assertTrue(self.coordinator.stop.is_set())
        self.assertTrue(self.coordinator.wake.is_set())
        self.assertFalse(result["recovery_required"])

    def test_support_matrix_does_not_invent_automatic_families(self):
        self.assertEqual(support_matrix()["automatic_profiles"], [])
        self.assertIn("unqualified", support_matrix()["engineering_review"])


class LiveShutdownBoundaryTests(WorkflowTests):
    def test_planned_shutdown_waits_for_live_action_and_watchdog_stands_down(self):
        task = self.task()
        action_entered = threading.Event()
        action_release = threading.Event()

        def live_action(task_id):
            action_entered.set()
            self.assertTrue(action_release.wait(5))
            # Leave the scheduler-owned state active, exactly as an action
            # interrupted between its receipt and final boundary check could.
            self.assertEqual(task_id, task)

        self.co.step = live_action
        self.co.start()
        self.addCleanup(lambda: (self.co.stop.set(), self.co.wake.set()))
        self.assertTrue(action_entered.wait(5))

        supervisor = CoordinatorSupervision(
            self.co, lambda: {"accepted": 0},
            disk_usage=lambda _: Usage(1000, 100, 900),
            min_free_bytes=100, min_free_ratio=0.05, clock=time.time)
        supervisor.start(interval=3600)
        forced_exits = []
        monitor = threading.Thread(
            target=watchdog, args=(self.co, supervisor),
            kwargs={"exit_process": forced_exits.append, "interval": 0.01})
        monitor.start()

        result = {}
        stopping = threading.Thread(
            target=lambda: result.update(supervisor.shutdown(
                "integration test signal", boundary_timeout=5)))
        stopping.start()
        self.assertTrue(supervisor.planned_shutdown.wait(2))
        action_release.set()
        stopping.join(5)
        monitor.join(2)

        self.assertFalse(stopping.is_alive())
        self.assertFalse(monitor.is_alive())
        self.assertEqual(forced_exits, [])
        self.assertEqual(result["state"], "SHUTDOWN_PAUSED")
        self.assertFalse(result["recovery_required"])
        self.assertEqual(self.co.store.get(task)["status"], "PAUSED")
        self.assertFalse(self.co.thread.is_alive())

    def test_shutdown_timeout_records_recovery_required_without_false_pause(self):
        task = self.task()
        action_entered = threading.Event()
        action_release = threading.Event()

        def stuck_action(task_id):
            action_entered.set()
            action_release.wait(5)

        self.co.step = stuck_action
        self.co.start()
        self.addCleanup(action_release.set)
        self.assertTrue(action_entered.wait(5))
        supervisor = CoordinatorSupervision(
            self.co, lambda: {"accepted": 0},
            disk_usage=lambda _: Usage(1000, 100, 900),
            min_free_bytes=100, min_free_ratio=0.05, clock=time.time)
        result = supervisor.shutdown("timeout test", boundary_timeout=0.01)
        self.assertEqual(result["state"], "SHUTDOWN_RECOVERY_REQUIRED")
        self.assertTrue(result["recovery_required"])
        self.assertEqual(self.co.store.get(task)["status"], "RUNNING")
        action_release.set()
        self.co.thread.join(5)


if __name__ == "__main__":
    unittest.main()
