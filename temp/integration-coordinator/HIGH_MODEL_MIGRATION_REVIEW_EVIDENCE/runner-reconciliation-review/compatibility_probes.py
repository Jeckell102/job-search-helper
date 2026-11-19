"""Disposable full-lifecycle version and historical acknowledgement probes."""
import copy
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

import reviewer_probes as prior_probes
from adoption_probes import AdoptionChecks as _AdoptionChecks
from job_search_helper.exact_cycle_planner import _digest, _exact_plan_digest
from job_search_helper.exact_cycle_sync import _fallback_receipt
from job_search_helper.exact_local_plan import exact_local_plan
from job_search_helper.publication_receipts import record_fingerprints
from job_search_helper.repository import MemoryRepository
from job_search_helper.sheet_profile import COMPACT_SCHEMAS
from job_search_helper.sheets_sync import SheetsSynchronizer

CYCLE, COMPANY = prior_probes.CYCLE, prior_probes.COMPANY


class CompatibilityChecks(unittest.TestCase):
    setUp = prior_probes.SQLiteMigrationProbes.setUp
    verified_local = prior_probes.SQLiteMigrationProbes.verified_local
    reopen = _AdoptionChecks.reopen
    begin = _AdoptionChecks.begin
    adopt = _AdoptionChecks.adopt
    mark = _AdoptionChecks.mark
    freeze = _AdoptionChecks.freeze
    local_complete = _AdoptionChecks.local_complete

    def prepare_remote(self, *, v1):
        if v1:
            self.plan = copy.deepcopy(self.plan)
            self.plan.pop('record_fingerprint_version')
            for operations, records in (('local_operations', 'local_expected_records'),
                                       ('remote_projection', 'remote_records')):
                self.plan[records] = record_fingerprints(self.plan[operations])
                self.plan[records + '_digest'] = _digest(self.plan[records])
            self.plan['plan_digest'] = _exact_plan_digest(self.plan)
            self.verified_local()
        else:
            self.local_complete()
            self.freeze()
        rows = {tab: [{key: row.get(key, '') for key in headers}
                      for row in self.local.read(tab)]
                for tab, headers in COMPACT_SCHEMAS.items()}
        self.remote = MemoryRepository(rows, schemas=COMPACT_SCHEMAS)
        self.remote.spreadsheet_id = 'synthetic-review'
        self.sync = SheetsSynchronizer(self.local, self.remote)
        authority = exact_local_plan(self.local, CYCLE, COMPANY)
        exact = self.sync.plan_exact_scope(authority['row_scope'], self.plan['remote_projection'])
        cycle = {'id': CYCLE, 'companies': {COMPANY: {}}, 'started_at': 't0'}
        self.receipt = _fallback_receipt(cycle, COMPANY, self.plan, self.payload)
        receipt_id = self.inbox.ensure_receipt(self.receipt)
        self.inbox.freeze_exact_remote_plan(
            CYCLE, COMPANY, local_plan_digest=self.plan['plan_digest'],
            projection=exact['operations'], projection_digest=exact['projection_digest'],
            receipt_id=receipt_id, intent_id='compatibility-intent', timestamp='t1')
        options = dict(inbox=self.inbox, cycle_id=CYCLE, company_id=COMPANY,
                       plan_digest=self.plan['plan_digest'], receipt_id=receipt_id,
                       intent_id='compatibility-intent')
        self.sync.publish_exact_scope(exact, **options)
        return options

    def test_v1_default_receipt_pending_restart_confirms_and_acknowledges(self):
        options = self.prepare_remote(v1=True)
        self.assertEqual(self.receipt['records'], self.plan['remote_records'])
        self.reopen()
        options['inbox'] = self.inbox
        self.sync = SheetsSynchronizer(self.local, self.remote)
        acknowledged = self.sync.confirm_and_acknowledge_exact_scope(**options)
        self.mark_acknowledged(options, acknowledged)
        self.assertEqual(self.inbox.receipt(self.receipt)['state'], 'SYNC_CONFIRMED')
        self.assertEqual(self.inbox.exact_remote_state(CYCLE, COMPANY)['state'], 'LOCAL_ACKNOWLEDGED')

    def test_pre_guard_v1_confirmation_resumes_acknowledgement(self):
        options = self.prepare_remote(v1=True)
        original_path = Path(__file__).parent.parent / 'migration-review/src/job_search_helper/sheets_sync.py'
        spec = importlib.util.spec_from_file_location('job_search_helper.historical_sheets_sync', original_path)
        old_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(old_module)
        # Execute the actual previous reader against the same genuine synthetic remote rows.
        historical_reader = old_module.SheetsSynchronizer.readback_exact_scope.__get__(self.sync)
        with patch.object(self.sync, 'readback_exact_scope', historical_reader):
            before = self.sync.confirm_exact_scope(**options)
        self.assertEqual(self.inbox.receipt(self.receipt)['state'], 'SYNC_CONFIRMED')
        self.assertFalse(any('remote_guards' in row for row in before['rows']))
        self.reopen()
        options['inbox'] = self.inbox
        self.sync = SheetsSynchronizer(self.local, self.remote)
        acknowledged = self.sync.confirm_and_acknowledge_exact_scope(**options)
        self.assertEqual(acknowledged['acknowledgement_id'], before['acknowledgement_id'])
        self.mark_acknowledged(options, acknowledged)
        self.assertEqual(self.inbox.exact_remote_state(CYCLE, COMPANY)['state'], 'LOCAL_ACKNOWLEDGED')
        self.assertEqual(self.local.db.execute('SELECT COUNT(*) FROM exact_local_acknowledgements').fetchone()[0], 1)

    def test_adopted_migration_archives_after_valid_publication_and_local_acknowledgement(self):
        options = self.prepare_remote(v1=False)
        acknowledged = self.sync.confirm_and_acknowledge_exact_scope(**options)
        self.mark_acknowledged(options, acknowledged)
        self.inbox.acknowledge(CYCLE, COMPANY, local=self.local)
        self.assertIsNone(self.inbox.plan(CYCLE, COMPANY))
        self.assertIsNone(self.inbox.exact_legacy_migration_state(CYCLE, COMPANY))
        self.assertEqual(self.inbox.connection.execute('SELECT COUNT(*) FROM exact_legacy_plan_migration_archive').fetchone()[0], 1)
        self.assertEqual(self.inbox.receipt(self.receipt)['state'], 'SYNC_CONFIRMED')

    def mark_acknowledged(self, options, acknowledged):
        self.inbox.mark_exact_remote_locally_acknowledged(
            CYCLE, COMPANY, local=self.local,
            local_plan_digest=self.plan['plan_digest'],
            projection_digest=self.plan['remote_projection_digest'],
            receipt_id=options['receipt_id'], intent_id=options['intent_id'],
            acknowledgement_id=acknowledged['acknowledgement_id'], timestamp='t4')


if __name__ == '__main__':
    unittest.main(defaultTest='CompatibilityChecks', verbosity=2)
