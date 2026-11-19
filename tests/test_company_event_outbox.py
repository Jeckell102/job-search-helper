import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from job_search_helper.company_events import canonical_company_fact, source_revision
from job_search_helper.repository import RepositoryError, SCHEMAS
from job_search_helper.sqlite_repository import SQLiteRepository


def company(**changes):
    row = {'Company': 'Acme', 'Company ID': 'COMP-1', 'Company Status': 'Active',
           'Official Careers URL': 'https://jobs.example.test/acme?utm_source=ignored',
           'ATS / Source': 'Greenhouse'}
    row.update(changes)
    return row


class CompanyEventOutboxTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = SQLiteRepository(Path(self.temp.name) / 'jobs.sqlite3', 'test-sheet', initialize=True)
        self.addCleanup(self.repo.close)
        for tab in SCHEMAS:
            self.repo.import_rows(tab, enumerate([company()] if tab == 'Companies' else [], 2))
        with self.repo.transaction():
            self.repo.set_meta('ready', 'yes')

    def mutation(self, **values):
        return self.repo.mutate_company_with_event({
            'tab': 'Companies', 'identity': {'Company ID': 'COMP-1'}, 'values': values,
        })

    def test_canonical_revision_ignores_cosmetic_fields_and_normalizes_url(self):
        before = company(Notes='first', **{'Official Careers URL': 'https://JOBS.example.test/acme?utm_campaign=x'})
        after = company(Notes='second', **{'Official Careers URL': 'https://jobs.example.test/acme'})
        self.assertEqual(source_revision(before), source_revision(after))
        self.assertTrue(canonical_company_fact(before)['eligible'])

    def test_supported_mutation_commits_company_and_eligible_event_together(self):
        result = self.mutation(**{'ATS / Source': 'Lever'})
        event = result['company_event']
        self.assertEqual(event['kind'], 'company.eligible')
        self.assertEqual(event['company_id'], 'COMP-1')
        self.assertEqual(event['revision'], 1)
        self.assertEqual(self.repo.read('Companies')[0]['ATS / Source'], 'Lever')
        self.assertEqual(self.repo.pending_company_events('intake'), [event])

    def test_duplicate_and_cosmetic_mutations_do_not_duplicate_work(self):
        first = self.mutation(**{'ATS / Source': 'Lever'})['company_event']
        duplicate = self.mutation(**{'ATS / Source': 'Lever'})
        cosmetic = self.mutation(**{'Notes': 'Human note'})
        self.assertIsNone(duplicate['company_event'])
        self.assertIsNone(cosmetic['company_event'])
        self.assertEqual(self.repo.pending_company_events('intake'), [first])

    def test_meaningful_revisions_and_delivery_ack_are_durable_and_ordered(self):
        first = self.mutation(**{'ATS / Source': 'Lever'})['company_event']
        second = self.mutation(**{'Company Status': 'Paused'})['company_event']
        self.assertEqual((first['revision'], second['revision']), (1, 2))
        self.assertEqual(second['kind'], 'company.ineligible')
        self.repo.acknowledge_company_event(first['event_id'], 'intake', source_revision=first['source_revision'])
        self.assertEqual(self.repo.pending_company_events('intake'), [second])
        with self.assertRaisesRegex(RepositoryError, 'stale source revision'):
            self.repo.acknowledge_company_event(second['event_id'], 'intake', source_revision=first['source_revision'])
        self.repo.close()
        self.repo = SQLiteRepository(Path(self.temp.name) / 'jobs.sqlite3', 'test-sheet')
        self.addCleanup(self.repo.close)
        self.assertEqual(self.repo.pending_company_events('intake'), [second])

    def test_newer_ack_sets_company_high_watermark_and_rejects_stale_ack(self):
        first = self.mutation(**{'ATS / Source': 'Lever'})['company_event']
        second = self.mutation(**{'Company Status': 'Paused'})['company_event']
        # Consumers may receive r2 after a crash/reconnect before r1.  Taking
        # r2 is a deliberate supersession, not permission to replay r1 later.
        self.repo.acknowledge_company_event(second['event_id'], 'intake', source_revision=second['source_revision'])
        self.assertEqual(self.repo.pending_company_events('intake'), [])
        with self.assertRaisesRegex(RepositoryError, 'stale for this consumer revision'):
            self.repo.acknowledge_company_event(first['event_id'], 'intake', source_revision=first['source_revision'])
        # Retrying the r2 acknowledgement is idempotent.
        self.assertTrue(self.repo.acknowledge_company_event(
            second['event_id'], 'intake', source_revision=second['source_revision'])['acknowledged'])

    def test_failed_event_write_rolls_back_company_mutation(self):
        with patch.object(self.repo, '_record_company_event', side_effect=RuntimeError('event disk failure')):
            with self.assertRaisesRegex(RuntimeError, 'event disk failure'):
                self.mutation(**{'ATS / Source': 'Lever'})
        self.assertEqual(self.repo.read('Companies')[0]['ATS / Source'], 'Greenhouse')
        self.assertEqual(self.repo.pending_company_events('intake'), [])

    def test_incomplete_company_waits_without_event(self):
        result = self.mutation(**{'Official Careers URL': ''})
        self.assertIsNone(result['company_event'])
        self.assertEqual(self.repo.pending_company_events('intake'), [])

    def test_removing_source_from_eligible_company_emits_withdrawal(self):
        eligible = self.mutation(**{'ATS / Source': 'Lever'})['company_event']
        withdrawal = self.mutation(**{'Official Careers URL': ''})['company_event']
        self.assertEqual(withdrawal['kind'], 'company.withdrawn')
        self.assertFalse(withdrawal['fact']['eligible'])
        self.assertEqual(withdrawal['fact']['official_careers_url'], '')
        self.assertEqual(self.repo.pending_company_events('intake'), [eligible, withdrawal])

    def test_explicit_company_import_emits_once_but_plain_bootstrap_does_not(self):
        # Plain bootstrap deliberately remains non-live, so enabling M2 cannot
        # queue every historical Company as a newly added Company.
        self.repo.import_rows('Companies', [(2, company(**{'ATS / Source': 'Lever'}))])
        self.assertEqual(self.repo.pending_company_events('intake'), [])
        receipt = self.repo.import_companies_with_events(
            [(2, company(**{'ATS / Source': 'Ashby'}))], origin='sheets-reconciliation')
        self.assertEqual(receipt['imported'], 1)
        self.assertEqual(len(receipt['company_events']), 1)
        replay = self.repo.import_companies_with_events(
            [(2, company(**{'ATS / Source': 'Ashby'}))], origin='sheets-reconciliation')
        self.assertEqual(replay['company_events'], [])

    def test_external_reconciliation_seeds_once_then_emits_only_later_changes(self):
        initial = self.repo.bootstrap_company_event_reconciliation()
        self.assertEqual(initial, {'bootstrapped': True, 'seeded': 1})
        self.assertEqual(self.repo.pending_company_events('intake'), [])
        self.assertEqual(self.repo.bootstrap_company_event_reconciliation(), {'bootstrapped': False, 'seeded': 0})

        # This models an authoritative Sheets pull using the legacy safe
        # importer.  The follow-up reconciliation is what creates intake work.
        self.repo.import_rows('Companies', [(2, company(**{'ATS / Source': 'Lever'}))])
        changed = self.repo.reconcile_external_company_events()
        self.assertEqual(changed['reconciled'], 1)
        self.assertEqual(changed['company_events'][0]['kind'], 'company.eligible')
        self.assertEqual(self.repo.reconcile_external_company_events()['company_events'], [])

    def test_external_reconciliation_rejects_use_before_safe_baseline(self):
        with self.assertRaisesRegex(RepositoryError, 'requires a completed baseline'):
            self.repo.reconcile_external_company_events()

    def test_readonly_open_does_not_require_or_modify_event_schema(self):
        self.repo.close()
        self.repo = SQLiteRepository(Path(self.temp.name) / 'jobs.sqlite3', 'test-sheet', readonly=True)
        self.addCleanup(self.repo.close)
        self.assertEqual(self.repo.pending_company_events('intake'), [])
        with self.assertRaisesRegex(RepositoryError, 'read-only'):
            self.repo.mutate_company_with_event({'tab': 'Companies', 'identity': {'Company ID': 'COMP-1'},
                                                 'values': {'ATS / Source': 'Lever'}})
