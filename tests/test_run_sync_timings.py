"""Deterministic attribution checks; no Google calls or live job data."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from job_search_helper.run_sync import RunSheetsSync, publish_pending
from test_run_scoped_sync import FakeSync


class BatchTimingTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.sync = FakeSync(pending=2)
        self.metrics = dict(read_seconds=100.0, write_seconds=50.0,
                            throttle_seconds=20.0, read_requests=10,
                            write_requests=5, read_response_bytes=1000)
        # Evidence archives expose the shared counters on their main repository.
        self.sync.remote = SimpleNamespace(main=SimpleNamespace(metrics=self.metrics))
        self.original_publish = self.sync.publish_batch
        self.logs = []
        self.session = RunSheetsSync(lambda: None, log=self.logs.append)

    def publish(self):
        self.metrics['read_seconds'] += 2.0
        self.metrics['write_seconds'] += 3.0
        self.metrics['throttle_seconds'] += 1.0
        self.metrics['read_requests'] += 2
        self.metrics['write_requests'] += 1
        self.metrics['read_response_bytes'] += 4096
        self.now += 10.0  # Four seconds outside API calls and pacing.
        return self.original_publish()

    def test_periodic_batches_log_and_accumulate_nonoverlapping_costs(self):
        with patch('job_search_helper.run_sync.time.monotonic', side_effect=lambda: self.now), \
             patch.object(self.sync, 'publish_batch', side_effect=self.publish):
            self.session._publish(self.sync, 'periodic')
        totals = self.session.totals
        for name, expected in [('read_seconds', 4), ('write_seconds', 6),
                               ('throttle_seconds', 2), ('processing_seconds', 8),
                               ('total_seconds', 20), ('read_requests', 4),
                               ('write_requests', 2), ('read_response_bytes', 8192)]:
            self.assertEqual(totals['sheets_publish_' + name], expected)
        self.assertEqual(totals['sheets_published_row_updates'], 2)
        batch_logs = [line for line in self.logs if 'batch ' in line]
        self.assertEqual(len(batch_logs), 2)
        self.assertTrue(all('Sheets periodic:' in line for line in batch_logs))
        self.assertIn('read=2.00s, processing=4.00s, write=3.00s, pacing=1.00s', batch_logs[0])

    def test_failed_attempt_is_measured_without_acknowledging_work(self):
        def publish():
            if self.sync.local.pending == 2:
                return self.publish()
            self.metrics['read_seconds'] += 2
            self.metrics['read_requests'] += 1
            self.now += 3
            raise OSError('read failed')
        with patch('job_search_helper.run_sync.time.monotonic', side_effect=lambda: self.now), \
             patch.object(self.sync, 'publish_batch', side_effect=publish), \
             self.assertRaisesRegex(OSError, 'read failed'):
            self.session._publish(self.sync, 'periodic')
        self.assertEqual(self.session.totals['sheets_publish_read_seconds'], 4)
        self.assertEqual(self.session.totals['sheets_publish_processing_seconds'], 5)
        self.assertEqual(self.session.totals['sheets_publish_total_seconds'], 13)
        self.assertEqual(self.session.totals['sheets_published_row_updates'], 1)
        self.assertEqual(self.sync.local.pending, 1)
        self.assertTrue(any('batch failed; read=2.00s' in line for line in self.logs))

    def test_startup_periodic_and_final_totals_accumulate(self):
        with patch('job_search_helper.run_sync.time.monotonic', side_effect=lambda: self.now), \
             patch.object(self.sync, 'publish_batch', side_effect=self.publish):
            for phase in ('startup', 'periodic', 'final'):
                self.sync.local.pending = 1
                self.session._publish(self.sync, phase, final=phase == 'final')
        self.assertEqual(self.session.totals['sheets_publish_read_seconds'], 6)
        self.assertEqual(self.session.totals['sheets_publish_total_seconds'], 30)

    def test_budget_prevents_any_attempt_or_timing_callback(self):
        timings = []
        result = publish_pending(self.sync, max_seconds=0,
                                 batch_progress=lambda *args: timings.append(args))
        self.assertEqual(result['stop_reason'], 'time_budget')
        self.assertEqual(timings, [])
        self.assertEqual(self.sync.local.pending, 2)


if __name__ == '__main__':
    unittest.main()
