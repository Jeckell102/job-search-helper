"""Verified-input shortcut must never bypass human choices or handoffs."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from job_search_helper import review_runtime as runner
from test_concurrent_review import job, publish, response


class SyncCacheTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.queue = Path(temp.name)
        publish(self.queue, second=[job(description="Complete description")])
        self.rt = runner.Runtime(self.queue)
        self.addCleanup(self.rt.close)
        self.rt.sync()

    def test_unchanged_inputs_skip_parsing_and_task_updates_across_process_connections(self):
        other = runner.Runtime(self.queue)
        self.addCleanup(other.close)
        statements = []
        other.db.set_trace_callback(statements.append)
        with patch.object(runner, 'parse_jsonl', side_effect=AssertionError('Unneeded parse')):
            result = other.sync()
        self.assertTrue(other.last_sync_reused)
        self.assertEqual(result['passes']['2']['ready'], 1)
        self.assertFalse(any(s.startswith('UPDATE tasks') for s in statements))

    def test_unchanged_live_poll_keeps_cache_but_no_cancels_claim(self):
        self.rt.set_sheet_controls([('j1', 'Pending', 1, 'h1')])
        self.rt.sync()
        owner = self.rt.start(2)['run_id']
        item = self.rt.next(2, owner)['items'][0]
        self.rt.set_sheet_controls([('j1', 'Pending', 1, 'h1')])
        self.rt.sync()
        self.assertTrue(self.rt.last_sync_reused)
        self.rt.set_sheet_controls([('j1', 'No', 0, 'h1')])
        result = self.rt.submit(2, owner, [response(item, 2, 'CLEAR_REJECT')])
        self.assertEqual(result['saved'], 0)
        self.assertEqual(len(result['skipped_manual']), 1)
        self.assertEqual(self.rt.status()['passes']['2']['claimed'], 0)

    def test_initial_empty_live_scope_invalidates_cache(self):
        self.rt.set_sheet_controls([])
        self.rt.sync()
        self.assertFalse(self.rt.last_sync_reused)
        self.assertEqual(self.rt.status()['passes']['2']['ready'], 0)

    def test_reopen_invalidates_even_with_fixed_clock(self):
        self.rt.clock = lambda: 100
        self.rt.set_sheet_controls([('j1', 'Pending', 1, 'h1')])
        owner = self.rt.start(2)['run_id']
        item = self.rt.next(2, owner)['items'][0]
        self.rt.submit(2, owner, [response(item, 2, 'CLEAR_REJECT')])
        self.rt.set_sheet_controls([('j1', 'No', 0, 'h1')])
        self.rt.sync()
        self.rt.set_sheet_controls([('j1', 'Pending', 1, 'h1')])
        new = self.rt.next(2, owner)['items'][0]
        self.assertNotEqual(item['claim_token'], new['claim_token'])

    def test_committed_decision_creates_handoff(self):
        owner = self.rt.start(2)['run_id']
        item = self.rt.next(2, owner)['items'][0]
        self.rt.submit(2, owner, [response(item, 2, 'ESCALATE')])
        self.assertEqual(self.rt.status()['passes']['3']['ready'], 1)
        self.rt.sync()
        self.assertTrue(self.rt.last_sync_reused)

    def test_direct_sql_decision_update_and_delete_invalidate(self):
        owner = self.rt.start(2)['run_id']
        item = self.rt.next(2, owner)['items'][0]
        self.rt.submit(2, owner, [response(item, 2, 'ESCALATE')])
        with self.rt.transaction():
            self.rt.db.execute("UPDATE decisions SET payload=json_set(payload,'$.evidence_packet.new','updated')")
        self.rt.sync()
        self.assertFalse(self.rt.last_sync_reused)
        payload = json.loads(self.rt.db.execute('SELECT payload FROM tasks WHERE stage=3').fetchone()[0])
        self.assertEqual(payload['evidence_packet']['new'], 'updated')
        with self.rt.transaction():
            self.rt.db.execute('DELETE FROM decisions')
        self.rt.sync()
        self.assertFalse(self.rt.last_sync_reused)
        self.assertEqual(self.rt.status()['passes']['3']['ready'], 0)

    def test_legacy_edit_with_same_size_and_timestamp_invalidates(self):
        path = self.queue / runner.LOGS[2]
        item = {'job_key':'j1','source_hash':'h1','triage_decision':'CLEAR_REJECT',
                'reason':'Reason A','description_complete':True}
        runner.atomic_json(path, [item], lines=True)
        self.rt.sync()
        stamp = path.stat()
        path.write_bytes(path.read_bytes().replace(b'Reason A', b'Reason B'))
        os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        self.rt.sync()
        self.assertFalse(self.rt.last_sync_reused)
        self.assertEqual(self.rt.status()['passes']['2']['conflicts'], 1)

    def test_corrupt_queue_still_fails_after_cached_sync(self):
        self.rt.sync()
        path = self.queue / 'second-pass.jsonl'
        path.write_bytes(path.read_bytes().replace(b'Complete', b'Changed!'))
        with self.assertRaisesRegex(RuntimeError, 'generation'):
            self.rt.sync()

    def test_new_queue_generation_invalidates(self):
        publish(self.queue, second=[job(source='h2')])
        self.rt.sync()
        self.assertFalse(self.rt.last_sync_reused)
        owner = self.rt.start(2)['run_id']
        self.assertEqual(self.rt.next(2, owner)['items'][0]['source_hash'], 'h2')

    def test_conflict_discovered_during_handoff_is_reconciled_before_cache_reuse(self):
        runner.atomic_json(self.queue / runner.LOGS[2],
                           [{'job_key':'j1','source_hash':'h1','triage_decision':'ESCALATE'}], lines=True)
        self.rt.sync()
        self.rt.sync()
        self.assertFalse(self.rt.last_sync_reused)
        result = self.rt.sync()
        self.assertTrue(self.rt.last_sync_reused)
        self.assertEqual(result['passes']['2']['conflicts'], 1)
        self.assertEqual(result['passes']['2']['done'], 0)
        self.assertEqual(result['passes']['3']['ready'], 0)

    def test_cached_sync_reads_current_claims_and_expires_lease_normally(self):
        now = [100]
        self.rt.clock = lambda: now[0]
        self.rt.lease_seconds = 10
        owner = self.rt.start(2)['run_id']
        item = self.rt.next(2, owner)['items'][0]
        result = self.rt.sync()
        self.assertTrue(self.rt.last_sync_reused)
        self.assertEqual(result['passes']['2']['claimed'], 1)
        now[0] += 11
        other = self.rt.start(2)['run_id']
        new = self.rt.next(2, other)['items'][0]
        self.assertNotEqual(item['claim_token'], new['claim_token'])

    def test_rolled_back_decision_does_not_invalidate_or_create_handoff(self):
        before = self.rt._sync_cache_key('fixture')
        with self.assertRaisesRegex(RuntimeError, 'rollback'):
            with self.rt.transaction():
                self.rt.db.execute("INSERT INTO decisions VALUES(2,'j1','h1','{}','test',100)")
                raise RuntimeError('rollback')
        self.assertEqual(before, self.rt._sync_cache_key('fixture'))
        self.rt.sync()
        self.assertTrue(self.rt.last_sync_reused)
        self.assertEqual(self.rt.status()['passes']['3']['ready'], 0)


if __name__ == '__main__':
    unittest.main()
