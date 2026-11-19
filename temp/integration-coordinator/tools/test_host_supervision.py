from collections import namedtuple
import importlib
from pathlib import Path
import tempfile
import threading
import types
import unittest
from unittest.mock import patch

from coordinator_store import Store


Usage = namedtuple("Usage", "total used free")


class FakeCoordinator:
    def __init__(self, base):
        self.store = Store(base)
        self.stop = threading.Event()
        self.wake = threading.Event()


class HostSupervisionWiringTests(unittest.TestCase):
    def import_host(self):
        with patch.object(Path, "read_text", return_value="fixture-token"):
            return importlib.import_module("host_server")

    def test_existing_health_entry_point_still_fails_a_dead_scheduler(self):
        host = self.import_host()
        exits = []
        coordinator = types.SimpleNamespace(
            thread=types.SimpleNamespace(is_alive=lambda: False))
        host.supervise(coordinator, exit_process=exits.append, interval=0)
        self.assertEqual(exits, [75])

    def test_bounded_environment_thresholds_support_live_disk_hold_exercise(self):
        host = self.import_host()
        with patch.dict(host.os.environ, {
                "WRAPPER_SUPERVISION_MIN_FREE_BYTES": "987654321",
                "WRAPPER_SUPERVISION_MIN_FREE_RATIO": "0.25"}):
            supervision = host.build_supervision(
                FakeCoordinator(Path(tempfile.mkdtemp()) / "tasks"),
                catch_up=lambda: {"accepted": 0})
        self.assertEqual(supervision.min_free_bytes, 987654321)
        self.assertEqual(supervision.min_free_ratio, 0.25)

    def test_invalid_environment_threshold_fails_service_start_closed(self):
        host = self.import_host()
        with patch.dict(host.os.environ, {
                "WRAPPER_SUPERVISION_MIN_FREE_BYTES": "invalid"}):
            with self.assertRaisesRegex(ValueError, "disk threshold"):
                host.build_supervision(
                    FakeCoordinator(Path(tempfile.mkdtemp()) / "tasks"),
                    catch_up=lambda: {"accepted": 0})

    def test_host_persists_external_retention_counts_from_zero_argument_probe(self):
        # host_server reads its private bearer token at import. No service is
        # started by import, and this test substitutes a fixture token only.
        host = self.import_host()
        with tempfile.TemporaryDirectory() as temporary:
            coordinator = FakeCoordinator(Path(temporary) / "tasks")
            expected = {
                "unacknowledged_company_events": 2,
                "unacknowledged_scrape_outcomes": 1,
                "unconfirmed_publication_receipts": 3,
                "nonterminal_release_journals": 1,
                "active_release_records": 1,
            }
            with (patch("job_search_helper.cli.load_environment"),
                  patch("job_search_helper.cli.storage_backend", return_value="sqlite"),
                  patch("job_search_helper.cli.job_database_path",
                        return_value=Path(temporary) / "jobs.sqlite3"),
                  patch.object(host, "retention_counts", return_value=expected) as probe):
                supervision = host.build_supervision(
                    coordinator, catch_up=lambda: {"accepted": 0})
                supervision.disk_usage = lambda _: Usage(1000, 100, 900)
                supervision.min_free_bytes = 100
                supervision.min_free_ratio = 0.05
                result = supervision.tick()

            probe.assert_called_once_with(
                Path(temporary) / "jobs.sqlite3",
                company_consumer="company-scan-request-bridge",
                outcome_consumer="wrapper-coordinator")
            self.assertEqual(
                result["retention"]["external_protected_counts"], expected)
            self.assertEqual(supervision.status(), result)
            self.assertNotIn("external_probe_error", result["retention"])


if __name__ == "__main__":
    unittest.main()
