import copy
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from job_search_helper.repository import MemoryRepository, RepositoryError, SCHEMAS, _encoded
from job_search_helper.sqlite_repository import SQLiteRepository
from job_search_helper.sheets_sync import SheetsSynchronizer


def job(key='job-1', **changes):
    row = {'Job Key': key, 'Company': 'Acme', 'Job Title': 'Field Applications Engineer',
           'Official Job URL': 'https://jobs.example.com/' + key,
           'Source Hash': 'source-1', 'Added to Opportunities?': 'Pending',
           'Review Status': 'Needs Review', 'Job Status': 'Open and verified', 'Location': 'Ohio'}
    row.update(changes)
    return row


def operation(key='job-1', **values):
    return {'tab': 'Job History', 'identity': {'Job Key': key}, 'values': values}


def upgrade_operation():
    return {'tab': 'Job History',
            'identity': {'Company': 'Acme', 'Official Job URL': 'https://jobs.example.com/job-1'},
            'values': {'Job Key': 'provider-1', 'Prior Job Key': 'job-1'},
            'expected': {'Job Key': 'job-1'}}


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'jobs.sqlite3'
        self.remote = MemoryRepository({'Companies': [{'Company': 'Acme', 'Company ID': 'COMP-1',
             'Company Status': 'Active', 'Official Careers URL': 'https://jobs.example.com'}],
             'Job History': [job()], 'Job Evidence': [{'Job Key': 'job-1', 'Source Hash': 'source-1',
             'Company': 'Acme', 'Job Title': 'Field Applications Engineer', 'Job Description': 'Original evidence'}]})
        self.remote.spreadsheet_id = 'test-sheet'
        self.local = SQLiteRepository(self.path, 'test-sheet', initialize=True)
        self.addCleanup(self.local.close)
        for tab in SCHEMAS:
            self.local.import_rows(tab, enumerate(self.remote.read(tab), 2))
        with self.local.transaction(): self.local.set_meta('ready', 'yes')
        self.sync = SheetsSynchronizer(self.local, self.remote)

    def edit(self, tab, field, value, index=1):
        sheet = self.remote._sheets[tab]
        cell = sheet.cells.setdefault((index, sheet.headers.index(field)), {})
        cell['userEnteredValue'] = cell['effectiveValue'] = _encoded(value)

    def test_bootstrap_has_no_pending_writes(self):
        self.assertEqual(self.local.status()['pending_cells'], 0)
        self.assertEqual(self.local.read('Job History'), self.remote.read('Job History'))

    def test_changes_are_local_and_outbox_coalesces(self):
        with patch.object(self.remote, 'commit', side_effect=AssertionError('network used')):
            self.local.commit([operation(**{'Last Checked': 'one'})])
            self.local.commit([operation(**{'Last Checked': 'two'})])
        self.assertEqual(self.local.status()['pending_cells'], 1)
        self.assertEqual(self.remote.read('Job History')[0]['Last Checked'], '')
        self.sync.publish_batch()
        self.assertEqual(self.remote.read('Job History')[0]['Last Checked'], 'two')
        self.assertEqual(self.local.status()['pending_cells'], 0)

    def test_pending_key_upgrade_pulls_manual_edits_and_publishes_same_row(self):
        self.local.commit([upgrade_operation()])
        self.edit('Job History', 'Added to Opportunities?', 'No')
        self.edit('Job History', 'Review Notes', 'Keep my decision')
        self.sync.pull()
        row = self.local.read('Job History')[0]
        self.assertEqual(row['Job Key'], 'provider-1')
        self.assertEqual(row['Added to Opportunities?'], 'No')
        self.assertEqual(row['Review Notes'], 'Keep my decision')
        self.assertEqual(self.local.status()['conflicts'], 0)
        plan = self.sync._operations()[0][4]
        self.assertEqual(plan['identity'], {'Company': 'Acme', 'Official Job URL': 'https://jobs.example.com/job-1'})
        self.assertEqual(plan['values']['Job Key'], 'provider-1')
        self.assertEqual(plan['expected']['Job Key'], 'job-1')
        self.sync.publish_batch(); self.sync.pull(); self.sync.publish_batch()
        rows = self.remote.read('Job History')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['Job Key'], 'provider-1')
        self.assertEqual(rows[0]['Added to Opportunities?'], 'No')
        self.assertEqual(rows[0]['Review Notes'], 'Keep my decision')
        self.assertEqual(self.local.status()['pending_cells'], 0)

    def test_key_upgrade_recovers_lost_publication_ack(self):
        self.local.commit([upgrade_operation()])
        original = self.remote.commit
        def lost(ops):
            original(ops)
            raise TimeoutError('lost acknowledgement')
        with patch.object(self.remote, 'commit', side_effect=lost):
            with self.assertRaises(TimeoutError):
                self.sync.publish_batch()
        self.sync.pull(); self.sync.publish_batch()
        self.assertEqual(len(self.remote.read('Job History')), 1)
        self.assertEqual(self.remote.read('Job History')[0]['Job Key'], 'provider-1')
        self.assertEqual(self.local.status()['pending_cells'], 0)

    def test_old_and_new_remote_keys_cannot_merge_into_one_record(self):
        self.local.commit([upgrade_operation()])
        with self.assertRaisesRegex(RepositoryError, 'multiple remote identities'):
            self.sync.merge_remote('Job History', [(2, {'Job Key': 'job-1'}), (3, {'Job Key': 'provider-1'})])
        self.assertEqual(self.local.read('Job History')[0]['Job Key'], 'provider-1')

    def test_unknown_remote_key_still_requires_reconciliation(self):
        with self.assertRaisesRegex(RepositoryError, 'unrecognized remote row'):
            self.sync.merge_remote('Job History', [(8761, {'Job Key': 'unknown'})])

    def test_baseline_alias_cannot_shadow_another_current_record(self):
        self.local.commit([upgrade_operation()])
        op = operation('job-1', **job('job-1', **{'Official Job URL': 'https://jobs.example.com/different'}))
        op['append_if_missing'] = True
        self.local.commit([op])
        with self.assertRaisesRegex(RepositoryError, 'ambiguous local identity'):
            self.sync.merge_remote('Job History', [(2, {'Job Key': 'job-1'})])

    def test_batch_failure_rolls_back_records_and_outbox(self):
        before = self.local.read('Job History')
        with self.assertRaises(RepositoryError):
            self.local.commit([operation(**{'Last Checked': 'bad'}), operation('missing', **{'Last Checked': 'bad'})])
        self.assertEqual(before, self.local.read('Job History'))
        self.assertEqual(self.local.status()['pending_cells'], 0)

    def test_stale_expected_values_rejected(self):
        self.local.commit([operation(**{'Review Notes': 'user note'})])
        op = operation(**{'Decision': 'Reject'}); op['expected'] = {'Review Notes': ''}
        with self.assertRaises(RepositoryError): self.local.commit([op])

    def test_insert_replay_does_not_duplicate(self):
        op = operation('job-2', **job('job-2')); op['append_if_missing'] = True
        self.local.commit([op]); self.local.commit([op])
        self.sync.publish_batch(); self.sync.publish_batch()
        self.assertEqual(len(self.local.read('Job History')), 2)
        self.assertEqual(len(self.remote.read('Job History')), 2)
        self.assertEqual(self.local.status()['pending_cells'], 0)

    def test_unknown_fields_rejected(self):
        with self.assertRaises(RepositoryError): self.local.commit([operation(Bogus='bad')])

    def test_url_alias_prevents_duplicate_job(self):
        op = operation('different', **job('different', **{'Official Job URL': 'https://jobs.example.com/job-1?utm_source=x'}))
        op['append_if_missing'] = True
        with self.assertRaises(RepositoryError): self.local.commit([op])

    def test_formula_preserved(self):
        rows = list(enumerate(self.remote.read('Job History'), 2))
        self.local.import_rows('Job History', rows, policies={2: {'Review Notes': {'userEnteredValue': {'formulaValue': '=1+1'}}}})
        with self.assertRaises(RepositoryError): self.local.commit([operation(**{'Review Notes': 'replace'})])

    def test_source_text_beginning_equals_stays_literal(self):
        self.local.commit([operation(**{'Job Title': '=IMPORTXML("bad")'})])
        self.sync.publish_batch()
        sheet = self.remote._sheets['Job History']
        cell = sheet.cells[(1, sheet.headers.index('Job Title'))]
        self.assertEqual(cell['userEnteredValue'], {'stringValue': '=IMPORTXML("bad")'})

    def test_manual_yes_creates_opportunity_once(self):
        self.edit('Job History', 'Added to Opportunities?', 'Yes')
        self.sync.pull(); self.sync.pull()
        self.assertEqual(len(self.local.read('Opportunities')), 1)
        self.assertEqual(self.local.read('Job History')[0]['Decision'], 'Accept')
        self.sync.publish_batch(); self.sync.publish_batch()
        self.assertEqual(len(self.remote.read('Opportunities')), 1)
        self.assertEqual(self.local.status()['pending_cells'], 0)

    def test_manual_no_blocks_stale_acceptance(self):
        self.edit('Job History', 'Added to Opportunities?', 'No')
        self.sync.pull()
        with self.assertRaises(RepositoryError):
            self.local.commit([operation(**{'Added to Opportunities?': 'Yes', 'Decision': 'Accept', 'Review Status': 'Reviewed'})])
        self.assertEqual(self.local.read('Job History')[0]['Added to Opportunities?'], 'No')

    def test_source_refresh_does_not_reset_manual_no(self):
        self.edit('Job History', 'Added to Opportunities?', 'No'); self.sync.pull()
        self.local.commit([operation(**{'Added to Opportunities?': 'Pending', 'Review Status': 'Needs Review', 'Decision': '', 'Last Checked': 'today'})])
        row = self.local.read('Job History')[0]
        self.assertEqual(row['Added to Opportunities?'], 'No')
        self.assertEqual(row['Last Checked'], 'today')

    def test_pending_releases_override(self):
        self.edit('Job History', 'Added to Opportunities?', 'No'); self.sync.pull(); self.sync.publish_batch()
        self.edit('Job History', 'Added to Opportunities?', 'Pending'); self.sync.pull()
        self.assertEqual(self.local.read('Job History')[0]['Review Status'], 'Needs Review')
        self.local.commit([operation(**{'Added to Opportunities?': 'Yes', 'Decision': 'Accept', 'Review Status': 'Reviewed'})])
        self.assertEqual(self.local.read('Job History')[0]['Added to Opportunities?'], 'Yes')

    def test_new_company_receives_stable_id_and_publishes_without_duplicate(self):
        self.remote.commit([{'tab': 'Companies', 'identity': {'Company': 'New Company'}, 'values': {'Website': 'https://new.example'}, 'append_if_missing': True}])
        self.sync.pull(); self.sync.publish_batch(); self.sync.pull()
        rows = [r for r in self.remote.read('Companies') if r['Company'] == 'New Company']
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]['Company ID'].startswith('COMP-'))

    def test_application_status_and_dates_are_imported_and_never_reset(self):
        self.remote.commit([{'tab': 'Opportunities', 'identity': {'Company': 'Acme', 'Job URL': 'https://jobs.example.com/job-1'},
                            'values': {'Application Status': 'Applied', 'Date Applied': 46300.25, 'Notes': 'My note'}, 'append_if_missing': True}])
        self.sync.pull()
        op = {'tab': 'Opportunities', 'identity': {'Company': 'Acme', 'Job URL': 'https://jobs.example.com/job-1'}, 'values': {'Application Status': 'Not Reviewed'}}
        with self.assertRaises(RepositoryError): self.local.commit([op])
        self.edit('Opportunities', 'Application Status', 'Interviewing'); self.sync.pull()
        row = self.local.read('Opportunities')[0]
        self.assertEqual(row['Application Status'], 'Interviewing'); self.assertEqual(row['Date Applied'], 46300.25)

    def test_no_keeps_existing_applied_opportunity(self):
        self.remote.commit([{'tab': 'Opportunities', 'identity': {'Company': 'Acme', 'Job URL': 'https://jobs.example.com/job-1'},
                            'values': {'Application Status': 'Applied'}, 'append_if_missing': True}])
        self.sync.pull(); self.edit('Job History', 'Added to Opportunities?', 'No'); self.sync.pull(); self.sync.publish_batch()
        self.assertEqual(self.remote.read('Opportunities')[0]['Application Status'], 'Applied')

    def test_newer_local_edit_is_not_cleared_by_older_ack(self):
        self.local.commit([operation(**{'Last Checked': 'first'})])
        original = self.remote.commit
        def concurrent(operations):
            result = original(operations)
            self.local.commit([operation(**{'Last Checked': 'second'})])
            return result
        with patch.object(self.remote, 'commit', side_effect=concurrent): self.sync.publish_batch()
        self.assertEqual(self.local.status()['pending_cells'], 1)
        self.sync.publish_batch()
        self.assertEqual(self.remote.read('Job History')[0]['Last Checked'], 'second')
        self.assertEqual(self.local.status()['pending_cells'], 0)

    def test_lost_remote_ack_reconciles_without_duplicate(self):
        op = operation('job-2', **job('job-2')); op['append_if_missing'] = True
        self.local.commit([op]); original = self.remote.commit
        def lost(operations): original(operations); raise TimeoutError('response lost')
        with patch.object(self.remote, 'commit', side_effect=lost):
            with self.assertRaises(TimeoutError): self.sync.publish_batch()
        self.assertGreater(self.local.status()['pending_cells'], 0)
        self.sync.pull(); self.sync.publish_batch()
        self.assertEqual(len(self.remote.read('Job History')), 2)
        self.assertEqual(self.local.status()['pending_cells'], 0)

    def test_remote_machine_conflict_is_visible_and_not_overwritten(self):
        self.local.commit([operation(**{'Source Hash': 'local-new'})])
        self.edit('Job History', 'Source Hash', 'other-new')
        self.sync.pull(); self.sync.publish_batch()
        self.assertGreater(self.local.status()['conflicts'], 0)
        self.assertEqual(self.remote.read('Job History')[0]['Source Hash'], 'other-new')

    def test_duplicate_remote_identity_stops_merge(self):
        rows = [(2, job()), (3, job())]
        with self.assertRaises(RepositoryError): self.sync.merge_remote('Job History', rows)
        self.assertEqual(len(self.local.read('Job History')), 1)

    def test_missing_remote_row_is_not_automatically_recreated(self):
        self.local.commit([operation(**{'Last Checked': 'today'})])
        self.remote._sheets['Job History'].cells = {}
        self.sync.pull(); self.sync.publish_batch()
        self.assertEqual(self.remote.read('Job History'), [])
        self.assertGreater(self.local.status()['conflicts'], 0)

    def test_automatic_published_choice_does_not_become_manual_pin(self):
        self.local.commit([operation(**{'Added to Opportunities?': 'No', 'Decision': 'Reject', 'Review Status': 'Reviewed'})])
        self.sync.publish_batch(); self.sync.pull()
        self.assertEqual(self.local.db.execute('SELECT COUNT(*) FROM manual_choices').fetchone()[0], 0)

    def test_identity_survives_remote_reordering(self):
        self.remote.commit([{'tab': 'Companies', 'identity': {'Company': 'Other'}, 'values': {'Company ID': 'COMP-2'}, 'append_if_missing': True}])
        self.sync.pull()
        sheet = self.remote._sheets['Companies']
        sheet.cells = {(3-r if r in {1,2} else r, c): value for (r,c),value in sheet.cells.items()}
        self.edit('Companies', 'Company Status', 'Paused', index=2)
        self.sync.pull()
        self.assertEqual(self.local.matches('Companies', {'Company ID': 'COMP-1'})[0][1]['Company Status'], 'Paused')

    def test_readonly_connection_cannot_write(self):
        repo = SQLiteRepository(self.path, 'test-sheet', readonly=True)
        try:
            with self.assertRaises(RepositoryError): repo.commit([operation(**{'Last Checked': 'bad'})])
        finally: repo.close()

    def test_incomplete_or_wrong_destination_is_refused(self):
        with self.assertRaises(RepositoryError): SQLiteRepository(self.path, 'wrong')
        with self.local.transaction(): self.local.set_meta('ready', 'no')
        with self.assertRaises(RepositoryError): SQLiteRepository(self.path, 'test-sheet')

    def test_consistent_backup(self):
        self.local.commit([operation(**{'Last Checked': 'durable'})])
        backup = Path(self.directory.name) / 'backup.sqlite3'
        self.local.backup(backup)
        other = SQLiteRepository(backup, 'test-sheet', readonly=True)
        try: self.assertEqual(other.read('Job History')[0]['Last Checked'], 'durable')
        finally: other.close()

    def test_concurrent_connections_preserve_all_appended_notes(self):
        def writer(number):
            repo = SQLiteRepository(self.path, 'test-sheet')
            try:
                repo.commit([{'tab': 'Job History', 'identity': {'Job Key': 'job-1'}, 'append_notes': {'Review Notes': f'unique-note-{number}.'}}])
            finally: repo.close()
        with ThreadPoolExecutor(max_workers=6) as pool: list(pool.map(writer, range(12)))
        notes = self.local.read('Job History')[0]['Review Notes']
        for n in range(12): self.assertEqual(notes.count(f'unique-note-{n}.'), 1)

    def test_evidence_is_published_before_dependent_history(self):
        self.local.commit([{'tab': 'Job Evidence', 'identity': {'Job Key': 'job-1', 'Source Hash': 'source-2'},
                           'values': {'Job Description': 'New evidence'}, 'append_if_missing': True},
                           operation(**{'Source Hash': 'source-2'})])
        plans = self.sync._operations()
        self.assertEqual([p[0] for p in plans], ['Job Evidence'])
        self.sync.publish_batch(); self.sync.publish_batch()
        self.assertEqual(self.remote.read('Job History')[0]['Source Hash'], 'source-2')
        self.assertEqual(self.local.status()['pending_cells'], 0)


    def test_unpublished_opportunity_is_held_after_manual_no_then_released(self):
        self.local.commit([operation(**{'Added to Opportunities?': 'Yes', 'Decision': 'Accept', 'Review Status': 'Reviewed'}),
            {'tab': 'Opportunities', 'identity': {'Company': 'Acme', 'Job URL': 'https://jobs.example.com/job-1'},
             'values': {'Job Title': 'Field Applications Engineer', 'Application Status': 'Not Reviewed'}, 'append_if_missing': True}])
        self.edit('Job History', 'Added to Opportunities?', 'No')
        self.sync.pull(); self.sync.publish_batch()
        self.assertEqual(self.remote.read('Opportunities'), [])
        self.assertEqual(self.local.status()['conflicts'], 1)
        self.edit('Job History', 'Added to Opportunities?', 'Yes')
        self.sync.pull(); self.sync.publish_batch()
        self.assertEqual(len(self.remote.read('Opportunities')), 1)
        self.assertEqual(self.local.status()['conflicts'], 0)

    def test_external_review_lock_does_not_report_false_publication(self):
        self.edit('Job History', 'Review Status', 'In Progress')
        self.sync.pull()
        self.local.commit([operation(**{'Last Checked': 'today'})])
        # The existing repository suppresses source writes under the lock.
        self.assertEqual(self.local.status()['pending_cells'], 0)

    def test_noop_readback_does_not_acknowledge_a_skipped_remote_row(self):
        self.local.commit([operation(**{'Last Checked': 'today'})])
        self.edit('Job History', 'Review Status', 'In Progress')
        self.sync.pull()
        result = self.sync.publish_batch()
        self.assertEqual(result['published_rows'], 0)
        self.assertEqual(self.local.status()['pending_cells'], 1)
        self.assertEqual(self.remote.read('Job History')[0]['Last Checked'], '')



    def test_manual_choice_matching_unpublished_ai_choice_is_still_protected(self):
        self.local.commit([operation(**{'Added to Opportunities?': 'No', 'Decision': 'Reject', 'Review Status': 'Reviewed'})])
        self.edit('Job History', 'Added to Opportunities?', 'No')
        self.sync.pull()
        self.assertEqual(self.local.db.execute('SELECT value FROM manual_choices').fetchone()[0], 'No')

    def test_personal_note_and_concurrent_automatic_note_are_both_retained(self):
        self.local.commit([{'tab': 'Job History', 'identity': {'Job Key': 'job-1'}, 'append_notes': {'Review Notes': 'Automatic review note'}}])
        self.edit('Job History', 'Review Notes', 'My personal note')
        self.sync.pull(); self.sync.publish_batch()
        notes = self.remote.read('Job History')[0]['Review Notes']
        self.assertIn('My personal note', notes)
        self.assertIn('Automatic review note', notes)
        self.assertEqual(self.local.status()['pending_cells'], 0)

    def test_correcting_remote_conflict_to_baseline_releases_held_update(self):
        self.local.commit([operation(**{'Source Hash': 'local-new'})])
        self.edit('Job History', 'Source Hash', 'external-conflict'); self.sync.pull()
        self.assertGreater(self.local.status()['conflicts'], 0)
        self.edit('Job History', 'Source Hash', 'source-1'); self.sync.pull()
        self.assertEqual(self.local.status()['conflicts'], 0)
        self.sync.publish_batch()
        self.assertEqual(self.remote.read('Job History')[0]['Source Hash'], 'local-new')

    def test_late_manual_no_blocks_unpublished_opportunity(self):
        self.edit('Job History', 'Added to Opportunities?', 'Yes'); self.sync.pull()
        self.edit('Job History', 'Added to Opportunities?', 'No')
        with self.assertRaises(RepositoryError): self.sync.publish_batch()
        self.assertEqual(self.remote.read('Opportunities'), [])
        self.sync.pull(); self.sync.publish_batch()
        self.assertEqual(self.remote.read('Opportunities'), [])


if __name__ == '__main__': unittest.main()
