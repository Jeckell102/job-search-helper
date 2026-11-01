"""Fenced maintenance for prior third-pass manual outcomes, entirely offline."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from job_search_helper.review_runtime import Runtime, digest, encoded
from job_search_helper.review_question_migration import (EVENT, promote_questions,
                                                        question_assessment_signature)
from job_search_helper.review_writeback import sync_pending, verified
from job_search_helper.repository import MemoryRepository, GoogleRepository, SCHEMAS
from job_search_helper.review_publication import publish_reviews
from job_search_helper.sheet_profile import COMPACT_PROFILE, COMPACT_SCHEMAS
from sheets_fixture import RangeSheets
from job_search_helper.sqlite_repository import SQLiteRepository
from test_concurrent_review import publish, response
import test_review_auto_writeback as fixtures


class QuestionMigrationTests(unittest.TestCase):
    claim = fixtures.ReviewDeliveryTests.claim
    repository = fixtures.ReviewDeliveryTests.repository

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.queue = Path(self.temp.name) / 'queue'; publish(self.queue)
        self.runtime = Runtime(self.queue); self.addCleanup(self.runtime.close)
        self.environment = patch('job_search_helper.runner._load_environment')
        self.environment.start(); self.addCleanup(self.environment.stop)
        self.owner, items = self.claim(3, ['question'])
        answer = response(items[0], 3, 'Needs Info')
        answer['reason'] = 'Clarify whether this assignment requires future clearance eligibility.'
        self.runtime.submit(3, self.owner, [answer])
        self.repo = self.repository(['question'])
        self.marker = '[third-pass ' + digest(['question', 'h1'])[:16] + ']'
        self.repo.commit([{'tab': 'Job History', 'identity': {'Job Key': 'question'},
                          'values': {'Added to Opportunities?': 'Manual Review', 'Review Status': 'Manual Review',
                                     'Decision': 'Needs Info', 'Description Hash': 'prior-source',
                                     'Reconsideration Count': 1},
                          'append_notes': {'Review Notes': self.marker + ' ' + answer['reason']}}])
        self.prior = self.saved(); self.prior['writeback_status'] = 'Written'
        self.old_intent = {'job_key': 'question', 'source_hash': 'h1', 'decision': 'Needs Info',
                           'marker': self.marker, 'history_values': {'Added to Opportunities?': 'Manual Review',
                           'Review Status': 'Manual Review', 'Decision': 'Needs Info'},
                           'opportunity_values': {}, 'operations': []}
        with self.runtime.transaction():
            self.runtime.db.execute("UPDATE decisions SET payload=? WHERE stage=3", (encoded(self.prior),))
            self.runtime.db.execute('INSERT INTO writeback VALUES(?,?,?)', ('question', 'h1', encoded(self.old_intent)))
            for stage in [2, 3]:
                self.runtime.db.execute('INSERT INTO review_publications VALUES(?,?,?,?,?,?)',
                                        (stage, 'question', 'h1', 'Written', 'Prior verified receipt', self.runtime.clock()))
            self.runtime.db.execute("UPDATE tasks SET active=0,owner=NULL WHERE stage=3")
        self.request = {'job_key': 'question', 'source_hash': 'h1',
                        'expected_assessment_signature': question_assessment_signature(self.prior),
                        'migration_id': 'explicit-user-question-promotion-1',
                        'user_instruction': 'Move all third-pass unresolved questions into Opportunities.'}
        self.lock = Path(self.temp.name) / 'migration.lock'

    def saved(self):
        row = self.runtime.db.execute("SELECT payload FROM decisions WHERE stage=3 AND job_key='question'").fetchone()
        return json.loads(row[0])

    def events(self):
        return [json.loads(row[0]) for row in self.runtime.db.execute('SELECT detail FROM events WHERE event=?', (EVENT,))]

    def snapshot(self):
        return {name: [tuple(row) for row in self.runtime.db.execute('SELECT * FROM ' + name)]
                for name in ['decisions', 'writeback', 'review_publications', 'events', 'review_runs']}

    def promote(self, requests=None, repo=None):
        return promote_questions(self.runtime, self.owner, requests or [self.request],
                                 repo=repo or self.repo, lock_path=self.lock)

    def refused(self, requests=None, repo=None):
        before = self.snapshot()
        with self.assertRaises((ValueError, RuntimeError)):
            self.promote(requests, repo)
        self.assertEqual(self.snapshot(), before)

    def test_prepares_audited_intent_without_changing_assessment_or_sheet(self):
        before = self.repo.tables
        self.assertEqual(self.promote()['prepared'], 1)
        self.assertEqual(self.repo.tables, before)
        saved = self.saved()
        for name in ['decision', 'reason', 'reviewed_at', 'run_id']:
            self.assertEqual(saved.get(name), self.prior.get(name))
        self.assertEqual(saved['writeback_status'], 'Pending')
        audit = self.events()[0]
        self.assertEqual(audit['prior_assessment'], self.prior)
        self.assertEqual(audit['prior_intent'], self.old_intent)
        self.assertEqual(audit['prior_publication']['state'], 'Written')
        self.assertTrue(audit['intent']['requires_opportunity'])
        self.assertEqual(self.runtime.db.execute('SELECT stage FROM review_publications').fetchall()[0][0], 2)
        self.assertEqual(self.runtime.db.execute('SELECT COUNT(*) FROM review_publications').fetchone()[0], 1)
        self.assertEqual(sync_pending(self.runtime, 3, self.owner, repo=self.repo)['counts'], {'Written': 1})
        row = self.repo.read('Job History')[0]
        self.assertEqual((row['Added to Opportunities?'], row['Review Status'], row['Decision']), ('Yes', 'Reviewed', 'Needs Info'))
        self.assertEqual((row['Description Hash'], row['Reconsideration Count']), ('prior-source', 1))
        opp = self.repo.read('Opportunities')[0]
        self.assertEqual((opp['Fit Review'], opp['Notes'], opp['Application Status']), ('', '', 'Not Reviewed'))
        self.assertIn(self.prior['reason'], opp['Review Questions'])
        self.assertTrue(verified(self.repo, audit['intent']))
        self.assertEqual(self.runtime.run_status(3, self.owner)['saved_assessments'], 1)

    def test_repeat_after_delivery_preserves_later_publication_and_single_audit(self):
        self.promote(); sync_pending(self.runtime, 3, self.owner, repo=self.repo)
        with self.runtime.transaction():
            self.runtime.db.execute('INSERT INTO review_publications VALUES(?,?,?,?,?,?)',
                                    (3, 'question', 'h1', 'Written', 'New verified receipt', self.runtime.clock()))
        result = self.promote()
        self.assertEqual((result['prepared'], result['reused']), (0, 1))
        self.assertEqual(len(self.events()), 1)
        self.assertEqual(self.runtime.db.execute('SELECT detail FROM review_publications WHERE stage=3').fetchone()[0], 'New verified receipt')
        self.assertEqual(len(self.repo.read('Opportunities')), 1)

    def test_lost_response_after_transaction_resumes_same_migration(self):
        with patch.object(self.runtime, 'export', side_effect=RuntimeError('Response lost')):
            with self.assertRaisesRegex(RuntimeError, 'Response lost'):
                self.promote()
        self.assertEqual(self.promote()['reused'], 1)
        self.assertEqual(len(self.events()), 1)

    def test_stale_signature_refused_before_any_mutation(self):
        changed = {**self.request, 'expected_assessment_signature': '0' * 64}
        self.refused([changed])

    def test_changed_source_missing_history_and_duplicate_history_refused(self):
        for rows in [[], [{**self.repo.read('Job History')[0], 'Source Hash': 'h2'}],
                     self.repo.read('Job History') * 2]:
            with self.subTest(rows=len(rows)):
                self.refused(repo=MemoryRepository({'Job History': rows}))

    def test_manual_no_yes_closed_and_frozen_are_preserved(self):
        original = self.repo.read('Job History')[0]
        for edits in [{'Added to Opportunities?': 'No'}, {'Added to Opportunities?': 'Yes'},
                      {'Job Status': 'Closed'}, {'Reconsideration Count': 2},
                      {'Reconsideration Status': 'Frozen after 2'}]:
            with self.subTest(edits=edits):
                self.refused(repo=MemoryRepository({'Job History': [{**original, **edits}]}))

    def test_second_pass_provenance_and_missing_original_marker_refused(self):
        with self.runtime.transaction():
            self.runtime.db.execute("DELETE FROM decisions WHERE stage=3")
        self.refused()
        with self.runtime.transaction():
            self.runtime.db.execute("INSERT INTO decisions VALUES(?,?,?,?,?,?)", (3, "question", "h1", encoded(self.prior), "managed", self.runtime.clock()))
            wrong = {**self.old_intent, 'marker': '[second-pass wrong]'}
            self.runtime.db.execute('UPDATE writeback SET payload=?', (encoded(wrong),))
        self.refused()
        with self.runtime.transaction():
            self.runtime.db.execute('UPDATE writeback SET payload=?', (encoded(self.old_intent),))
        self.repo.commit([{'tab': 'Job History', 'identity': {'Job Key': 'question'}, 'values': {'Review Notes': 'Human notes only'}}])
        self.refused()

    def test_existing_personal_fields_and_questions_survive_delivery(self):
        original = {'Company': 'Fixture', 'Job URL': 'https://example.com/jobs/question',
                    'Job Title': 'Existing title', 'Application Status': 'Applied', 'Date Applied': '2026-10-01',
                    'Date Found': '2026-09-01', 'Fit Review': 'Strong Potential Fit', 'Notes': 'Personal text',
                    'Review Questions': 'Existing open question'}
        self.repo = MemoryRepository({**self.repo.tables, 'Opportunities': [original]})
        self.promote(); sync_pending(self.runtime, 3, self.owner, repo=self.repo)
        opp = self.repo.read('Opportunities')[0]
        for name in ['Application Status', 'Date Applied', 'Date Found', 'Fit Review', 'Notes']:
            self.assertEqual(opp[name], original[name])
        self.assertTrue(opp['Review Questions'].startswith('Existing open question\n\n'))

    def test_protected_same_value_manual_choice_refused(self):
        local = SQLiteRepository(Path(self.temp.name) / 'local.sqlite3', 'fixture', initialize=True)
        self.addCleanup(local.close)
        for tab in SCHEMAS:
            local.import_rows(tab, enumerate(self.repo.read(tab), 2))
        with local.transaction():
            local.set_meta('ready', 'yes')
            rid = local.matches('Job History', {'Job Key': 'question'})[0][0]
            local.db.execute('INSERT INTO manual_choices VALUES(?,?,?,?)', ('Job History', rid, 'Manual Review', 'now'))
        self.refused(repo=local)

    def test_all_requests_validate_before_first_mutation_and_id_reuse_is_fenced(self):
        invalid = {**self.request, 'job_key': 'missing', 'migration_id': 'other'}
        self.refused([self.request, invalid])
        self.promote()
        changed = {**self.request, 'user_instruction': 'A different instruction'}
        self.refused([changed])
        self.refused([{**self.request, 'migration_id': 'different-id'}])

    def test_prior_remote_manual_becomes_verified_question_opportunity(self):
        local = SQLiteRepository(Path(self.temp.name) / 'publication.sqlite3', 'fixture', initialize=True)
        self.addCleanup(local.close)
        for tab in SCHEMAS:
            local.import_rows(tab, enumerate(self.repo.read(tab), 2))
        with local.transaction():
            local.set_meta('ready', 'yes')
            local.set_meta('sheets_profile', COMPACT_PROFILE)
        service = RangeSheets(self.repo.tables, schemas=COMPACT_SCHEMAS)
        remote = GoogleRepository(service, 'fixture', schemas=COMPACT_SCHEMAS, min_request_interval=0)
        self.promote(repo=local)
        self.assertEqual(sync_pending(self.runtime, 3, self.owner, repo=local)['counts'], {'Written': 1})
        commit = remote.commit
        def lost(operations):
            result = commit(operations)
            if any(op.get('tab') == 'Opportunities' for op in operations):
                raise RuntimeError('Lost remote response')
            return result
        with patch.object(remote, 'commit', side_effect=lost):
            result = publish_reviews(self.runtime, 3, local=local, remote=remote,
                                     lock_path=Path(self.temp.name) / 'remote-writer.lock')
        self.assertEqual(result['counts'], {'Written': 1})
        row = remote.read('Job History')[0]
        self.assertEqual((row['Added to Opportunities?'], row['Review Status']), ('Yes', 'Reviewed'))
        self.assertEqual(local.read('Job History')[0]['Decision'], 'Needs Info')
        self.assertEqual(len(remote.read('Opportunities')), 1)
        self.assertIn(self.prior['reason'], remote.read('Opportunities')[0]['Review Questions'])
        self.assertEqual(self.promote(repo=local)['reused'], 1)
        self.assertEqual(self.runtime.db.execute('SELECT state FROM review_publications WHERE stage=3').fetchone()[0], 'Written')
        self.assertEqual(self.runtime.db.execute('SELECT state FROM review_publications WHERE stage=2').fetchone()[0], 'Written')

    def test_duplicate_opportunities_and_expired_maintenance_run_refused(self):
        duplicate = {'Company': 'Fixture', 'Job URL': 'https://example.com/jobs/question'}
        self.refused(repo=MemoryRepository({**self.repo.tables, 'Opportunities': [duplicate, duplicate]}))
        with self.runtime.transaction():
            self.runtime.db.execute('UPDATE review_runs SET lease_until=0 WHERE run_id=?', (self.owner,))
        self.refused()


if __name__ == '__main__':
    unittest.main()
