"""Exercise new public adoption wrappers using only temporary synthetic databases."""
import unittest
import copy
import json
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

    def test_wrapper_retry_after_successor_freeze_is_unchanged_noop(self):
        approved = self.prepare()
        with patch.object(SQLiteRepository, '_commit_in_transaction',
                          side_effect=AssertionError('must not replay')):
            first = adopt_retained_legacy_migration(*self.args, approved)
            self.assertEqual(first['successor_state'], 'REMOTE_PLAN_FROZEN')
            before = self.snapshot()
            retry = adopt_retained_legacy_migration(*self.args, approved)
            self.assertEqual(retry['successor_state'], 'REMOTE_PLAN_FROZEN')
            self.assertFalse(retry['receipt_created'])
            self.assertFalse(retry['remote_write_performed'])
            self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.inbox.exact_legacy_migration_state(CYCLE, COMPANY)['state'], 'REMOTE_PLAN_FROZEN')
        self.assertEqual(self.inbox.connection.execute('SELECT COUNT(*) FROM publication_receipts').fetchone()[0], 0)

    def snapshot(self):
        result = {}
        for label, db, tables in (
            ('local', self.local.db, ('records', 'dirty', 'exact_local_applications',
                                     'exact_local_apply_chunks', 'exact_local_acknowledgements')),
            ('inbox', self.inbox.connection, ('inventories', 'sync_plans',
                'exact_legacy_plan_migrations', 'exact_plan_local_state',
                'exact_remote_plans', 'exact_sync_chunks', 'publication_receipts'))):
            for table in tables:
                result[label + ':' + table] = db.execute('SELECT * FROM ' + table).fetchall()
        return result

    def changed_retry_refuses(self, change, expected):
        approved = self.prepare()
        adopt_retained_legacy_migration(*self.args, approved)
        approved = copy.deepcopy(approved)
        change(self, approved)
        before = self.snapshot()
        with patch.object(SQLiteRepository, '_commit_in_transaction',
                          side_effect=AssertionError('must not replay')):
            with self.assertRaisesRegex(ValueError, expected):
                adopt_retained_legacy_migration(*self.args, approved)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.inbox.connection.execute('SELECT COUNT(*) FROM publication_receipts').fetchone()[0], 0)


def sql_change(which, statement, params=()):
    def change(case, approved):
        db = case.local.db if which == 'local' else case.inbox.connection
        db.execute(statement, params)
        db.commit()
    return change


def change_local_note(case, approved):
    case.local.commit([{'tab': 'Job History', 'identity': {'Job Key': 'job-1'},
                        'values': {'Review Notes': 'new note after successor'}}])


def change_approval(case, approved):
    approved['current_local_snapshot_digest'] = '0' * 64


def change_successor(case, approved):
    plan, cursor = case.inbox.plan(CYCLE, COMPANY)
    plan['reviewer_tamper'] = True
    case.inbox.connection.execute('UPDATE sync_plans SET payload=?', (json.dumps(plan),))
    case.inbox.connection.commit()


CASES = (
    ('approval', change_approval, 'approval pins no longer match'),
    ('full_local_row', change_local_note, 'approval pins no longer match'),
    ('successor_payload', change_successor, 'frozen successor changed'),
    ('successor_cursor', sql_change('inbox', 'UPDATE sync_plans SET cursor=2'), 'frozen successor changed'),
    ('mirror_apply_id', sql_change('inbox', "UPDATE exact_plan_local_state SET local_apply_id='changed'"), 'frozen successor changed'),
    ('mirror_record_digest', sql_change('inbox', "UPDATE exact_plan_local_state SET local_records_digest='changed'"), 'frozen successor changed'),
    ('mirror_state', sql_change('inbox', "UPDATE exact_plan_local_state SET state='FROZEN'"), 'frozen successor changed'),
    ('local_parent', sql_change('local', "UPDATE exact_local_applications SET plan_digest='changed'"), 'adoption conflicts with its journal'),
    ('local_chunk', sql_change('local', "UPDATE exact_local_apply_chunks SET operations_digest='changed'"), 'adopted chunk evidence changed'),
    ('inventory_block', sql_change('inbox', 'UPDATE inventories SET blocked=1'), 'missing or blocked'),
    ('migration_successor', sql_change('inbox', "UPDATE exact_legacy_plan_migrations SET successor_plan_digest='changed'"), 'journal conflicts with retry'),
)


def make_test(change, expected):
    def test(self):
        self.changed_retry_refuses(change, expected)
    return test


for name, change, expected in CASES:
    setattr(RunnerChecks, 'test_changed_retry_refuses_' + name, make_test(change, expected))


if __name__ == '__main__':
    unittest.main(verbosity=2)
