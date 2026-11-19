"""Synthetic adoption/crash probes; remaining-gap tests assert observed defects."""
import copy
import json
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

import reviewer_probes as prior_probes
from reviewer_probes import CYCLE, COMPANY, build
from job_search_helper.exact_cycle_planner import _digest, _exact_plan_digest
from job_search_helper.exact_local_plan import exact_local_plan, _validate_plan
from job_search_helper.inbox import InventoryInbox
from job_search_helper.publication_receipts import record_fingerprints
from job_search_helper.repository import MemoryRepository
from job_search_helper.sheet_profile import COMPACT_SCHEMAS
from job_search_helper.sheets_sync import SheetsSynchronizer
from job_search_helper.sqlite_repository import SQLiteRepository


class AdoptionChecks(unittest.TestCase):
    setUp = prior_probes.SQLiteMigrationProbes.setUp

    def reopen(self):
        self.local.close(); self.inbox.close()
        self.local = SQLiteRepository(Path(self.tmp.name) / 'jobs.sqlite3', 'synthetic-review')
        self.inbox = InventoryInbox(Path(self.tmp.name) / 'inbox.sqlite3', 'synthetic-review')
        self.addCleanup(self.local.close); self.addCleanup(self.inbox.close)

    def begin(self):
        self.inbox.save_plan(CYCLE, COMPANY, self.legacy)
        self.inbox.advance(CYCLE, {COMPANY: 3}, expected={COMPANY: 0})
        self.approved = self.inbox._legacy_migration_binding(self.plan)
        return self.inbox.begin_exact_legacy_migration(
            CYCLE, COMPANY, self.plan, self.approved, timestamp='t0')

    def adopt(self):
        with patch.object(self.local, '_commit_in_transaction',
                          side_effect=AssertionError('legacy replay forbidden')):
            return self.local.adopt_verified_legacy_local_plan(
                CYCLE, COMPANY, self.plan, timestamp_value='t1')

    def mark(self):
        return self.inbox.mark_exact_legacy_local_complete(
            CYCLE, COMPANY, self.plan, self.local, timestamp='t2')

    def freeze(self):
        return self.inbox.freeze_exact_legacy_successor(
            CYCLE, COMPANY, self.plan, self.local, timestamp='t3')

    def local_complete(self):
        self.begin(); self.adopt(); self.mark()

    def test_each_durable_boundary_reopens_and_retries_without_replay(self):
        data_before = self.local.db.execute('SELECT * FROM records ORDER BY tab,row_id').fetchall()
        dirty_before = self.local.db.execute('SELECT * FROM dirty ORDER BY tab,row_id,header').fetchall()
        self.assertEqual(self.begin()['state'], 'FROZEN')
        self.reopen()
        self.assertFalse(self.inbox.begin_exact_legacy_migration(
            CYCLE, COMPANY, self.plan, self.approved, timestamp='t0b')['created'])
        self.assertFalse(self.adopt()['recovered'])
        self.reopen()
        self.assertTrue(self.adopt()['recovered'])
        self.assertEqual(self.mark()['state'], 'LOCAL_COMPLETE')
        self.reopen()
        self.assertTrue(self.mark()['recovered'])
        self.assertEqual(self.freeze()['state'], 'REMOTE_PLAN_FROZEN')
        self.reopen()
        self.assertTrue(self.adopt()['recovered'])
        self.assertTrue(self.freeze()['recovered'])
        self.assertEqual(self.local.db.execute('SELECT * FROM records ORDER BY tab,row_id').fetchall(), data_before)
        self.assertEqual(self.local.db.execute('SELECT * FROM dirty ORDER BY tab,row_id,header').fetchall(), dirty_before)
        self.assertEqual(self.inbox.plan(CYCLE, COMPANY), (self.plan, 3))
        row = self.inbox.connection.execute(
            'SELECT legacy_plan,successor_plan FROM exact_legacy_plan_migrations').fetchone()
        self.assertEqual(json.loads(row[0]), self.legacy)
        self.assertEqual(json.loads(row[1]), self.plan)
        for table in ('publication_receipts', 'exact_remote_plans', 'exact_sync_chunks'):
            self.assertEqual(self.inbox.connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0], 0)
        self.assertEqual(self.local.db.execute('SELECT COUNT(*) FROM exact_local_apply_chunks').fetchone()[0], 1)

    def test_local_journal_fault_rolls_back_parent_and_retries(self):
        self.begin()
        self.local.db.execute("CREATE TEMP TRIGGER fail_chunk BEFORE INSERT ON exact_local_apply_chunks "
                              "BEGIN SELECT RAISE(ABORT, 'injected chunk failure'); END")
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'injected chunk failure'):
            self.adopt()
        self.assertIsNone(exact_local_plan(self.local, CYCLE, COMPANY))
        self.assertEqual(self.inbox.plan(CYCLE, COMPANY), (self.legacy, 3))
        self.local.db.execute('DROP TRIGGER fail_chunk')
        self.reopen()
        self.assertFalse(self.adopt()['recovered'])

    def test_successor_fault_rolls_back_old_plan_and_retries(self):
        self.local_complete()
        self.inbox.connection.execute("CREATE TEMP TRIGGER fail_mirror BEFORE INSERT ON exact_plan_local_state "
                                      "BEGIN SELECT RAISE(ABORT, 'injected mirror failure'); END")
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'injected mirror failure'):
            self.freeze()
        self.assertEqual(self.inbox.plan(CYCLE, COMPANY), (self.legacy, 3))
        self.assertEqual(self.inbox.exact_legacy_migration_state(CYCLE, COMPANY)['state'], 'LOCAL_COMPLETE')
        self.assertIsNone(self.inbox.exact_local_state(CYCLE, COMPANY))
        self.inbox.connection.execute('DROP TRIGGER fail_mirror')
        self.reopen()
        self.assertFalse(self.freeze()['recovered'])

    def test_changed_local_snapshot_before_adoption_refuses(self):
        self.begin()
        self.local.commit([{'tab': 'Job History', 'identity': {'Job Key': 'job-1'},
                            'values': {'Review Notes': 'new note'}}])
        with self.assertRaisesRegex(ValueError, 'snapshot changed'):
            self.adopt()
        self.assertIsNone(exact_local_plan(self.local, CYCLE, COMPANY))
        self.assertEqual(self.inbox.plan(CYCLE, COMPANY), (self.legacy, 3))

    def test_cleanup_refuses_frozen_migration_without_publication(self):
        self.begin()
        with self.assertRaisesRegex(ValueError, 'before successor freeze'):
            self.inbox.acknowledge(CYCLE, COMPANY, local=self.local)
        self.assertIsNotNone(self.inbox.get(CYCLE, COMPANY))
        self.assertEqual(self.inbox.plan(CYCLE, COMPANY), (self.legacy, 3))
        self.assertEqual(self.inbox.exact_legacy_migration_state(CYCLE, COMPANY)['state'], 'FROZEN')
        self.assertEqual(self.inbox.connection.execute('SELECT COUNT(*) FROM exact_legacy_plan_migration_archive').fetchone()[0], 0)

    def test_cleanup_refuses_local_complete_migration(self):
        self.local_complete()
        with self.assertRaisesRegex(ValueError, 'before successor freeze'):
            self.inbox.acknowledge(CYCLE, COMPANY, local=self.local)
        self.assertEqual(self.inbox.plan(CYCLE, COMPANY), (self.legacy, 3))
        self.assertIsNotNone(exact_local_plan(self.local, CYCLE, COMPANY))
        self.assertEqual(self.inbox.connection.execute('SELECT COUNT(*) FROM publication_receipts').fetchone()[0], 0)

    def test_inventory_block_and_discard_refuse_during_migration(self):
        self.local_complete()
        with self.assertRaisesRegex(ValueError, 'inventory state is immutable'):
            self.inbox.block(CYCLE, COMPANY)
        with self.assertRaisesRegex(ValueError, 'plans are immutable'):
            self.inbox.discard_plan(CYCLE, COMPANY)
        self.assertFalse(self.inbox.get(CYCLE, COMPANY)[1])
        self.assertEqual(self.inbox.plan(CYCLE, COMPANY), (self.legacy, 3))

    def test_freeze_refuses_unrelated_local_drift_after_adoption(self):
        self.local_complete()
        self.local.commit([{'tab': 'Job History', 'identity': {'Job Key': 'job-1'},
                            'values': {'Review Notes': 'changed after local adoption'}}])
        with self.assertRaisesRegex(ValueError, 'snapshot changed before freeze'):
            self.freeze()
        self.assertEqual(self.inbox.plan(CYCLE, COMPANY), (self.legacy, 3))
        self.assertEqual(self.inbox.exact_legacy_migration_state(CYCLE, COMPANY)['state'], 'LOCAL_COMPLETE')

    def test_v1_fingerprint_and_plan_validation_preserve_legacy_semantics(self):
        op = {'tab': 'Job History', 'identity': {'Job Key': 'job-1'},
              'values': {'Last Checked': 'now'}, 'expected': {'Review Status': 'Human Reviewed'}}
        label = 'Job History:' + json.dumps(op['identity'], sort_keys=True, separators=(',', ':'))
        historical = {label: _digest({'tab': 'Job History', 'identity': op['identity'],
                                      'fields': op['values'], 'notes': {}})}
        self.assertEqual(record_fingerprints([op]), historical)
        self.assertNotEqual(record_fingerprints([op], include_guard_only=True), historical)
        v1 = copy.deepcopy(self.plan)
        v1.pop('record_fingerprint_version')
        for operations, records in (('local_operations', 'local_expected_records'),
                                    ('remote_projection', 'remote_records')):
            v1[records] = record_fingerprints(v1[operations])
            v1[records + '_digest'] = _digest(v1[records])
        v1['plan_digest'] = _exact_plan_digest(v1)
        _validate_plan(v1, CYCLE, COMPANY)
        self.inbox.save_exact_plan(CYCLE, COMPANY, v1, timestamp='t0')
        self.assertEqual(self.inbox.plan(CYCLE, COMPANY), (v1, 0))


if __name__ == '__main__':
    unittest.main(verbosity=2)
