"""SQLite review outcomes reach the compact Sheet without general publication."""
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from job_search_helper.repository import MemoryRepository, GoogleRepository, SCHEMAS
from job_search_helper.sqlite_repository import SQLiteRepository
from job_search_helper.sheet_profile import COMPACT_PROFILE, COMPACT_SCHEMAS
from job_search_helper.review_runtime import Runtime, main, atomic_json
from job_search_helper.review_writeback import sync_pending
from job_search_helper.review_publication import publish_reviews, publication_counts
import test_review_auto_writeback as delivery_fixtures
from test_concurrent_review import publish, response
from sheets_fixture import RangeSheets


class ReviewPublicationTests(unittest.TestCase):
    claim = delivery_fixtures.ReviewDeliveryTests.claim
    assess = delivery_fixtures.ReviewDeliveryTests.assess
    repository = delivery_fixtures.ReviewDeliveryTests.repository

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.queue = Path(self.temp.name) / 'queue'
        publish(self.queue)
        self.runtime = Runtime(self.queue); self.addCleanup(self.runtime.close)
        self.path = Path(self.temp.name) / 'jobs.sqlite3'
        self.local = SQLiteRepository(self.path, 'fixture', initialize=True)
        self.addCleanup(self.local.close)
        self.local.ensure_columns('Opportunities', ['Opportunity ID'])

    def stores(self, keys):
        full = self.repository(keys)
        for tab in SCHEMAS:
            self.local.import_rows(tab, enumerate(full.read(tab), 2))
        with self.local.transaction():
            self.local.set_meta('ready', 'yes')
            self.local.set_meta('sheets_profile', COMPACT_PROFILE)
        self.service = RangeSheets(full.tables, schemas=COMPACT_SCHEMAS)
        self.remote = GoogleRepository(self.service, 'fixture', schemas=COMPACT_SCHEMAS,
                                       min_request_interval=0)

    def save(self, stage, keys, decisions):
        owner, items = self.claim(stage, keys)
        if stage == 3:
            self.assess(owner, items, decisions)
        else:
            outcomes = dict(zip(keys, decisions))
            self.runtime.submit(stage, owner, [response(item, stage, outcomes[item['job_key']])
                for item in items])
        result = sync_pending(self.runtime, stage, owner, repo=self.local,
                              lock_path=Path(self.temp.name) / 'local.lock')
        self.assertEqual(result['counts'], {'Written': len(keys)})
        return owner, items

    def deliver(self, stage, owner=None, **kwargs):
        return publish_reviews(self.runtime, stage, owner, local=self.local,
            remote=self.remote, lock_path=Path(self.temp.name) / 'writer.lock', **kwargs)

    def test_mixed_sqlite_outcomes_publish_only_review_fields(self):
        self.stores(['reject', 'manual', 'unrelated'])
        owner, _ = self.save(2, ['reject', 'manual'], ['CLEAR_REJECT', 'NEEDS_INFO'])
        self.local.commit([
            {'tab': 'Job History', 'identity': {'Job Key': key},
             'values': {'Last Checked': 'future'}} for key in ['reject', 'unrelated']])
        result = self.deliver(2, owner)
        self.assertEqual(result['counts'], {'Written': 2})
        rows = {row['Job Key']: row for row in self.remote.read('Job History')}
        self.assertEqual(rows['reject']['Added to Opportunities?'], 'No')
        self.assertEqual(rows['manual']['Added to Opportunities?'], 'Manual Review')
        self.assertEqual(rows['unrelated']['Added to Opportunities?'], 'Pending')
        self.assertNotEqual(rows['reject']['Last Checked'], 'future')
        self.assertNotEqual(rows['unrelated']['Last Checked'], 'future')
        self.assertEqual(self.local.status()['pending_cells'], 2)
        self.assertEqual(self.runtime.status(2)['passes']['2']['pending_publication'], 0)

    def test_maintenance_recovers_prior_written_without_a_new_review_run(self):
        self.stores(['old'])
        owner, _ = self.save(2, ['old'], ['CLEAR_REJECT'])
        before = list(self.runtime.db.execute('SELECT run_id,state FROM review_runs'))
        result = self.deliver(2)
        self.assertEqual(result['counts'], {'Written': 1})
        self.assertEqual(list(self.runtime.db.execute('SELECT run_id,state FROM review_runs')), before)
        self.assertEqual(self.deliver(2)['selected'], 0)
        self.assertEqual(self.runtime.run_status(2, owner)['saved_assessments'], 1)

    def test_failed_remote_delivery_stays_pending_and_finish_cannot_drain(self):
        self.stores(['reject'])
        owner, _ = self.save(2, ['reject'], ['CLEAR_REJECT'])
        with patch.object(self.remote, 'commit', side_effect=RuntimeError('offline')):
            result = self.deliver(2, owner)
        self.assertEqual(result['counts'], {'Pending': 1})
        self.assertEqual(self.runtime.finish(2, owner)['state'], 'WRITEBACK_PENDING')
        self.assertEqual(self.deliver(2, owner)['counts'], {'Written': 1})
        self.assertEqual(publication_counts(self.runtime, 2, owner), {'Written': 1})

    def test_equal_manual_no_protects_human_choice_and_notes(self):
        self.stores(['reject'])
        owner, _ = self.save(2, ['reject'], ['CLEAR_REJECT'])
        self.service.set_cell('Job History', 1, 'Added to Opportunities?', 'No')
        self.service.set_cell('Job History', 1, 'Review Notes', 'Human decision')
        result = self.deliver(2, owner)
        self.assertEqual(result['counts'], {'Conflict': 1})
        row = self.remote.read('Job History')[0]
        self.assertEqual(row['Review Notes'], 'Human decision')
        self.assertEqual(row['Review Status'], 'Needs Review')

    def test_accept_publishes_yes_then_opportunity_without_duplicate(self):
        self.stores(['accept'])
        owner, _ = self.save(3, ['accept'], ['Accept'])
        result = self.deliver(3, owner)
        self.assertEqual(result['counts'], {'Written': 1})
        self.assertEqual(self.remote.read('Job History')[0]['Added to Opportunities?'], 'Yes')
        self.assertEqual(len(self.remote.read('Opportunities')), 1)
        self.assertEqual(self.deliver(3, owner)['selected'], 0)
        self.assertEqual(len(self.remote.read('Opportunities')), 1)

    def test_lost_response_is_reconciled_by_live_readback(self):
        self.stores(['reject'])
        owner, _ = self.save(2, ['reject'], ['CLEAR_REJECT'])
        commit = self.remote.commit
        def lost(operations):
            commit(operations)
            raise RuntimeError('response lost')
        with patch.object(self.remote, 'commit', side_effect=lost):
            result = self.deliver(2, owner)
        self.assertEqual(result['counts'], {'Written': 1})

    def test_changed_source_is_not_published(self):
        self.stores(['reject'])
        owner, _ = self.save(2, ['reject'], ['CLEAR_REJECT'])
        self.local.commit([{'tab': 'Job History', 'identity': {'Job Key': 'reject'},
                            'values': {'Source Hash': 'new-source'}}])
        self.assertEqual(self.deliver(2, owner)['counts'], {'Conflict': 1})
        self.assertEqual(self.remote.read('Job History')[0]['Added to Opportunities?'], 'Pending')

    def test_unreceipted_sqlite_delivery_counts_pending_and_cannot_drain(self):
        self.stores(['reject'])
        owner, _ = self.save(2, ['reject'], ['CLEAR_REJECT'])
        with self.runtime.transaction():
            self.runtime.db.execute("INSERT INTO metadata VALUES('sheet_controls',?)",
                (json.dumps({'delivery_target': 'local_database'}),))
        self.assertEqual(publication_counts(self.runtime, 2, owner), {'Pending': 1})
        self.assertEqual(self.runtime.finish(2, owner)['state'], 'WRITEBACK_PENDING')

    def test_maintenance_limit_keeps_remaining_deliveries_pending(self):
        self.stores(['one', 'two'])
        self.save(2, ['one', 'two'], ['CLEAR_REJECT', 'CLEAR_REJECT'])
        result = self.deliver(2, limit=1)
        self.assertEqual(result['counts'], {'Written': 1})
        self.assertEqual(result['pending'], 1)
        result = self.deliver(2, limit=1)
        self.assertEqual(result['counts'], {'Written': 1})
        self.assertEqual(result['pending'], 0)

    def test_prior_publisher_acknowledgement_is_not_republished(self):
        self.stores(['reject'])
        owner, _ = self.save(2, ['reject'], ['CLEAR_REJECT'])
        self.assertEqual(self.deliver(2, owner)['counts'], {'Written': 1})
        with self.runtime.transaction():
            self.runtime.db.execute('DELETE FROM review_publications')
        with patch.object(self.remote, 'commit', side_effect=AssertionError('already acknowledged')):
            result = self.deliver(2, owner)
        self.assertEqual(result['selected'], 0)
        self.assertEqual(publication_counts(self.runtime, 2, owner), {'Acknowledged': 1})

    def test_malformed_legacy_identity_does_not_block_valid_saved_reviews(self):
        self.stores(['bad', 'good'])
        owner, _ = self.save(2, ['bad', 'good'], ['CLEAR_REJECT', 'CLEAR_REJECT'])
        # Reproduce a legacy accepted intent whose authoritative job URL is
        # invalid. Baseline acknowledgement used to raise before batch selection.
        with self.runtime.transaction():
            saved = self.runtime.db.execute("SELECT payload FROM writeback WHERE job_key='bad'").fetchone()
            intent = json.loads(saved[0]); intent['decision'] = 'Accept'
            self.runtime.db.execute("UPDATE writeback SET payload=? WHERE job_key='bad'", (json.dumps(intent),))
        rid, row = self.local.matches('Job History', {'Job Key': 'bad'})[0]
        row['Official Job URL'] = 'legacy-invalid-url'
        # Give the bad intent a historically acknowledged History projection so
        # acknowledgement reaches the invalid Opportunity URL lookup.
        base = self.local.baseline('Job History', rid)
        base.update(intent['history_values'])
        base['Review Notes'] = intent['marker']
        with self.local.transaction():
            self.local.db.execute("UPDATE records SET data=? WHERE tab='Job History' AND row_id=?",
                                  (json.dumps(row), rid))
            self.local._baseline('Job History', rid, base)
        result = self.deliver(2)
        self.assertEqual(result['counts'], {'Conflict': 1, 'Written': 1})
        rows = {row['Job Key']: row for row in self.remote.read('Job History')}
        self.assertEqual(rows['good']['Added to Opportunities?'], 'No')
        self.assertEqual(rows['bad']['Added to Opportunities?'], 'Pending')
        self.assertEqual(self.deliver(2)['selected'], 0)

    def test_unrelated_malformed_opportunity_url_is_not_an_identity_match(self):
        self.stores(['good'])
        owner, _ = self.save(2, ['good'], ['CLEAR_REJECT'])
        # This is a legacy/manual placeholder from the same employer, not the
        # reviewed job. Exact URL comparison must fail closed without throwing.
        self.service.set_cell('Opportunities', 1, 'Company', 'Fixture')
        self.service.set_cell('Opportunities', 1, 'Job URL', 'not-yet-known')
        self.service.set_cell('Opportunities', 1, 'Application Status', 'Applied')
        result = self.deliver(2, owner)
        self.assertEqual(result['counts'], {'Written': 1})
        self.assertEqual(self.remote.read('Job History')[0]['Added to Opportunities?'], 'No')
        self.assertEqual(self.remote.read('Opportunities')[0]['Application Status'], 'Applied')

    def test_bounded_retry_does_not_rewrite_receipts_for_the_remaining_backlog(self):
        keys = [f'job-{n}' for n in range(10)]
        self.stores(keys)
        owner, _ = self.save(2, keys, ['CLEAR_REJECT'] * len(keys))
        with patch.object(self.remote, 'commit', side_effect=RuntimeError('offline')):
            self.deliver(2, owner, limit=1)
            with patch.object(self.runtime, 'transaction', wraps=self.runtime.transaction) as transactions, \
                 patch.object(self.runtime, 'event', wraps=self.runtime.event) as events:
                result = self.deliver(2, owner, limit=1)
        self.assertEqual(result['pending'], 10)
        # Only the selected retry changes admission/failure detail. Repeated
        # identical receipts for the rest of the backlog cause no writes/events.
        self.assertLessEqual(transactions.call_count, 2)
        self.assertLessEqual(events.call_count, 2)

    def test_cli_sqlite_submit_automatically_publishes(self):
        self.stores(['reject'])
        owner, items = self.claim(2, ['reject'])
        answer = Path(self.temp.name) / 'answers.jsonl'
        atomic_json(answer, [response(items[0], 2, 'CLEAR_REJECT')], lines=True)
        output = io.StringIO()
        def repository(**kwargs):
            return SQLiteRepository(self.path, 'fixture', readonly=not kwargs.get('write'))
        with patch('job_search_helper.runner._load_environment'), \
             patch('job_search_helper.cli.get_repository', side_effect=repository), \
             patch('job_search_helper.cli.get_remote_repository', return_value=self.remote), \
             patch('job_search_helper.cli.state_path', return_value=Path(self.temp.name) / 'state.db'), \
             patch('job_search_helper.cli.storage_backend', return_value='sqlite'), redirect_stdout(output):
            code = main(['submit', '--pass', '2', '--run-id', owner, '--file', str(answer),
                         '--queue-dir', str(self.queue)])
        self.assertEqual(code, 0, output.getvalue())
        result = json.loads(output.getvalue())
        self.assertEqual(result['writeback']['counts'], {'Saved Locally': 1})
        self.assertEqual(result['publication']['counts'], {'Written': 1})
        self.assertEqual(self.remote.read('Job History')[0]['Added to Opportunities?'], 'No')

    def test_finish_publishes_saved_outcome_from_a_paused_worker(self):
        self.stores(['reject'])
        old_owner, _ = self.save(2, ['reject'], ['CLEAR_REJECT'])
        self.runtime.pause(2, old_owner)
        current = self.runtime.start(2)['run_id']
        output = io.StringIO()
        def repository(**kwargs):
            return SQLiteRepository(self.path, 'fixture', readonly=not kwargs.get('write'))
        with patch('job_search_helper.runner._load_environment'), \
             patch('job_search_helper.cli.get_repository', side_effect=repository), \
             patch('job_search_helper.cli.get_remote_repository', return_value=self.remote), \
             patch('job_search_helper.cli.state_path', return_value=Path(self.temp.name) / 'state.db'), \
             patch('job_search_helper.cli.storage_backend', return_value='sqlite'), \
             patch('job_search_helper.review_runtime.live_refresh'), redirect_stdout(output):
            code = main(['finish', '--pass', '2', '--run-id', current,
                         '--queue-dir', str(self.queue)])
        self.assertEqual(code, 0, output.getvalue())
        result = json.loads(output.getvalue())
        self.assertEqual(result['publication']['counts'], {'Written': 1})
        self.assertIsNone(result['publication']['run_id'])
        self.assertEqual(result['state'], 'DRAINED')
        self.assertEqual(self.runtime.run_status(2, old_owner)['state'], 'paused')
        self.assertEqual(self.runtime.run_status(2, current)['saved_assessments'], 0)
        self.assertEqual(self.remote.read('Job History')[0]['Added to Opportunities?'], 'No')


if __name__ == '__main__':
    unittest.main()
