"""Exercise new public adoption wrappers using only temporary synthetic databases."""
import unittest
from pathlib import Path
from unittest.mock import patch

import reviewer_probes as prior
from job_search_helper.exact_legacy_migration_runner import (
    preview_retained_legacy_migration, adopt_retained_legacy_migration,
)
from job_search_helper.sqlite_repository import SQLiteRepository
from job_search_helper.inbox import InventoryInbox

CYCLE, COMPANY = prior.CYCLE, prior.COMPANY


class RunnerChecks(unittest.TestCase):
    setUp = prior.SQLiteMigrationProbes.setUp

    def prepare(self):
        self.inbox.save_plan(CYCLE, COMPANY, self.legacy)
        self.inbox.advance(CYCLE, {COMPANY: 3}, expected={COMPANY: 0})
        self.args = (Path(self.tmp.name) / 'inbox.sqlite3',
                     Path(self.tmp.name) / 'jobs.sqlite3', CYCLE, COMPANY)
        return preview_retained_legacy_migration(*self.args)['binding']

    def test_wrapper_recovers_after_local_application_without_replay(self):
        approved = self.prepare()
        with patch.object(InventoryInbox, 'mark_exact_legacy_local_complete',
                          side_effect=RuntimeError('injected interruption')):
            with self.assertRaisesRegex(RuntimeError, 'injected interruption'):
                adopt_retained_legacy_migration(*self.args, approved)
        with patch.object(SQLiteRepository, '_commit_in_transaction',
                          side_effect=AssertionError('must not replay')):
            result = adopt_retained_legacy_migration(*self.args, approved)
        self.assertEqual(result['successor_state'], 'REMOTE_PLAN_FROZEN')
        self.assertFalse(result['receipt_created'])
        self.assertFalse(result['remote_write_performed'])

    def test_remaining_gap_wrapper_cannot_retry_after_successor_freeze(self):
        approved = self.prepare()
        with patch.object(SQLiteRepository, '_commit_in_transaction',
                          side_effect=AssertionError('must not replay')):
            first = adopt_retained_legacy_migration(*self.args, approved)
            self.assertEqual(first['successor_state'], 'REMOTE_PLAN_FROZEN')
            with self.assertRaisesRegex(ValueError, 'retained evidence changed before migration'):
                adopt_retained_legacy_migration(*self.args, approved)
        self.assertEqual(self.inbox.exact_legacy_migration_state(CYCLE, COMPANY)['state'], 'REMOTE_PLAN_FROZEN')
        self.assertEqual(self.inbox.connection.execute('SELECT COUNT(*) FROM publication_receipts').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
