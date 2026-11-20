"""Offline behavior checks: reuse work without weakening source or write guards."""
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from job_search_helper import shared_boards as boards, title_audit, review_queue
from job_search_helper.browser_progress import BrowserProgress
from job_search_helper.derived_cache import DerivedCache
from job_search_helper.inbox import InventoryInbox
from job_search_helper.run_sync import PublishWindow, publish_pending
from job_search_helper.review_refresh import policy_fingerprint
import test_review_queue as queue_fixture
import test_run_scoped_sync as sync_fixture


class DetailReuseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'inbox.sqlite3'
        self.inbox = InventoryInbox(self.path, 'fixture'); self.addCleanup(lambda:self.inbox.close())
        self.board = boards.Board('SmartRecruiters', 'https://api.smartrecruiters.com', 'Example', '/Example')
        self.entries = [{'id':str(i), 'title':'Field Engineer', 'revision':1} for i in range(100)]
        self.calls = []
        self.failures = {'2', '4', '7'}

    def detail(self, board, transport, entry, cid, company):
        self.calls.append(entry['id'])
        if entry['id'] in self.failures:
            raise boards.FetchError('partial', 'Missing full description')
        return {'posting_id':entry['id'], 'title':entry['title'], 'description':'Full validated source', 'revision':entry['revision']}

    def fetch(self, cycle='cycle', entries=None, **kwargs):
        progress = BrowserProgress(self.inbox, cycle, 'company', self.board.url)
        with patch.object(boards, 'listing', return_value=self.entries if entries is None else entries), \
             patch.object(boards, 'posting', side_effect=self.detail):
            return boards._fetch(self.board, object(), 'company', 'Example', self.board.url, progress=progress, **kwargs)

    def test_retry_after_restart_fetches_only_failed_details(self):
        first = self.fetch(); self.assertEqual(first.status, 'partial'); self.assertEqual(len(first.jobs), 97)
        self.inbox.close(); self.inbox = InventoryInbox(self.path, 'fixture')
        self.calls.clear(); self.failures.clear()
        second = self.fetch()
        self.assertEqual(second.status, 'complete'); self.assertEqual(len(second.jobs), 100)
        self.assertEqual(set(self.calls), {'2', '4', '7'})
        self.assertIn('Reused 97', second.reason)

    def test_changed_new_removed_and_restricted_entries_use_current_listing(self):
        self.failures.clear(); self.fetch(); self.calls.clear()
        entries = [dict(e) for e in self.entries if e['id'] != '1']
        entries[0]['revision'] = 2
        entries.append({'id':'new', 'title':'Field Engineer', 'revision':1})
        result = self.fetch(entries=entries)
        self.assertEqual(set(self.calls), {'0','new'})
        self.assertNotIn('1', {job['posting_id'] for job in result.jobs})
        self.calls.clear()
        scoped = self.fetch(entries=entries, ids={'0'})
        self.assertEqual(scoped.status, 'partial')
        self.assertEqual([job['posting_id'] for job in scoped.jobs], ['0'])

    def test_new_cycle_and_changed_adapter_policy_fetch_fresh_details(self):
        self.failures.clear(); self.fetch(); self.calls.clear()
        self.fetch(cycle='next-cycle'); self.assertEqual(len(self.calls), 100)
        self.calls.clear()
        with patch.object(boards, '_detail_policy', return_value='changed-code'):
            self.fetch()
        self.assertEqual(len(self.calls), 100)

    def test_expired_details_and_smaller_cap(self):
        self.failures.clear()
        with patch('job_search_helper.browser_progress.time.time', return_value=1): self.fetch()
        self.calls.clear()
        result = self.fetch(max_jobs=2)
        self.assertEqual(len(self.calls), 2); self.assertEqual(len(result.jobs), 2)
        self.assertEqual(result.status, 'partial')
        self.calls.clear(); result = self.fetch(max_jobs=1)
        self.assertEqual(self.calls, []); self.assertEqual(len(result.jobs), 1)
        self.assertEqual(result.status, 'partial')

    def test_interrupt_preserves_each_completed_posting(self):
        self.entries = self.entries[:2]; self.failures.clear()
        original = self.detail
        def interrupted(*args):
            if args[2]['id'] == '1': raise KeyboardInterrupt()
            return original(*args)
        with patch.object(self, 'detail', side_effect=interrupted), self.assertRaises(KeyboardInterrupt): self.fetch()
        self.calls.clear(); result = self.fetch()
        self.assertEqual(self.calls, ['1']); self.assertEqual(result.status, 'complete')

    def test_listing_recheck_still_invalidates_details_within_attempt(self):
        self.entries = self.entries[:2]; self.failures.clear(); self.fetch(); self.calls.clear()
        changed = [dict(self.entries[0], revision=2), self.entries[1]]
        progress = BrowserProgress(self.inbox, 'cycle', 'company', self.board.url)
        with patch.object(boards, 'listing', side_effect=[self.entries, changed, changed]), \
             patch.object(boards, 'posting', side_effect=self.detail):
            result = boards._fetch(self.board, object(), 'company', 'Example', self.board.url, progress=progress)
        self.assertEqual(self.calls, ['0']); self.assertEqual(result.status, 'complete')


class CalculationReuseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cache = DerivedCache(self.root/'cache.sqlite3'); self.addCleanup(self.cache.close)
        self.repo = queue_fixture.ReviewQueueTests().make_repo()

    def test_warm_build_identical_and_changed_evidence_with_same_hash_recomputes_one(self):
        cold = review_queue.build_review_queues(self.repo, cache=self.cache)
        with patch.object(review_queue, 'score_posting', side_effect=AssertionError('Repeated scoring')):
            warm = review_queue.build_review_queues(self.repo, cache=self.cache)
        self.assertEqual(cold, warm)
        rows = self.repo.tables
        rows['Job Evidence'][0]['Job Description'] = 'Completely changed source description.'
        self.repo = type(self.repo)(rows)
        with patch.object(review_queue, 'score_posting', wraps=review_queue.score_posting) as score:
            changed = review_queue.build_review_queues(self.repo, cache=self.cache)
            self.assertEqual(score.call_count, 1)
        self.assertEqual(changed, review_queue.build_review_queues(self.repo))

    def test_changed_decision_is_excluded_even_with_warm_cache(self):
        review_queue.build_review_queues(self.repo, cache=self.cache)
        rows = self.repo.tables
        rows['Job History'][0]['Added to Opportunities?'] = 'No'
        self.repo = type(self.repo)(rows)
        result = review_queue.build_review_queues(self.repo, cache=self.cache)
        self.assertNotIn('a', {r['job_key'] for key in ('first_pass','second_pass') for r in result[key]})
        self.assertEqual(result, review_queue.build_review_queues(self.repo))

    def test_policy_change_invalidates_and_threshold_reroutes_without_rescoring(self):
        review_queue.build_review_queues(self.repo, cache=self.cache)
        with patch.object(review_queue, 'score_posting', side_effect=AssertionError('Repeated scoring')):
            changed = review_queue.build_review_queues(self.repo, threshold=30, cache=self.cache)
        self.assertEqual(changed, review_queue.build_review_queues(self.repo, threshold=30))
        with patch('job_search_helper.review_refresh.policy_fingerprint', return_value={'new-policy':'1'}), \
             patch.object(review_queue, 'score_posting', wraps=review_queue.score_posting) as score:
            review_queue.build_review_queues(self.repo, cache=self.cache)
            self.assertEqual(score.call_count, 5)

    def test_duplicate_evidence_cannot_be_rescued_by_cached_score(self):
        review_queue.build_review_queues(self.repo, cache=self.cache)
        rows = self.repo.tables
        rows['Job Evidence'].append(dict(rows['Job Evidence'][0]))
        self.repo = type(self.repo)(rows)
        self.assertEqual(review_queue.build_review_queues(self.repo, cache=self.cache), review_queue.build_review_queues(self.repo))

    def test_missing_corrupt_or_unwritable_cache_recomputes(self):
        expected = review_queue.build_review_queues(self.repo, cache=self.cache)
        self.cache.db.execute("UPDATE calculations SET payload='{}'")
        self.assertEqual(review_queue.build_review_queues(self.repo, cache=self.cache), expected)
        bad = self.root/'bad'; bad.write_bytes(b'invalid database')
        broken = DerivedCache(bad); self.addCleanup(broken.close)
        self.assertEqual(review_queue.build_review_queues(self.repo, cache=broken), expected)
        disabled = DerivedCache(self.root); self.addCleanup(disabled.close)
        self.assertEqual(review_queue.build_review_queues(self.repo, cache=disabled), expected)

    def test_pruning_discards_only_unused_derived_records(self):
        self.cache.calculate('review', 'old', ['input'], lambda:{'value':1})
        self.cache.used.clear()
        self.cache.calculate('review', 'current', ['input'], lambda:{'value':2})
        self.cache.prune()
        self.assertEqual(self.cache.db.execute('SELECT identity FROM calculations').fetchall(), [('current',)])

    def test_company_cache_preserves_partial_sightings_and_rebuilds_only_changed_company(self):
        inbox = InventoryInbox(self.root/'inbox.sqlite3', 'fixture'); self.addCleanup(inbox.close)
        def payload(ident, date, status='complete'):
            return {'inventory_status':status, 'fetched_at':date, 'ats':'Greenhouse', 'jobs':[
                {'posting_id':ident, 'title':'Software Engineer', 'description':'Engineering work.',
                 'url':f'https://boards.greenhouse.io/example/jobs/{ident}', 'ats':'Greenhouse'}]}
        inbox.save('old', 'a', payload('1', '2026-01-01'))
        inbox.save('old', 'b', payload('2', '2026-01-01'))
        load = lambda: title_audit.load_title_audits(inbox.path, 'fixture', cache=self.cache)
        first = load()
        with patch.object(title_audit, '_replay_company', side_effect=AssertionError('Repeated replay')):
            self.assertEqual(load(), first)
        inbox.save('new', 'a', payload('3', '2026-01-02', 'partial'))
        with patch.object(title_audit, '_replay_company', wraps=title_audit._replay_company) as replay:
            result = load(); self.assertEqual(replay.call_count, 1)
        self.assertEqual(len(result[0]), 3)
        self.assertEqual(result, title_audit.load_title_audits(inbox.path, 'fixture'))
        inbox.save('latest', 'a', payload('4', '2026-01-03'))
        self.assertEqual({r['posting']['posting_id'] for r in load()[0]}, {'4','2'})
        with self.assertRaises(ValueError): title_audit.load_title_audits(inbox.path, 'other', cache=self.cache)


class PublicationWindowTests(unittest.TestCase):
    def test_small_updates_wait_but_continuous_updates_do_not_extend_deadline(self):
        local = sync_fixture.FakeLocal(); local.pending = 1
        window = PublishWindow(max_wait=15, target_rows=100)
        with patch('job_search_helper.run_sync.time.monotonic', return_value=0): self.assertFalse(window.ready(local))
        local.pending = 20
        with patch('job_search_helper.run_sync.time.monotonic', return_value=14): self.assertFalse(window.ready(local))
        with patch('job_search_helper.run_sync.time.monotonic', return_value=15): self.assertTrue(window.ready(local))
        local.pending = 100
        self.assertTrue(window.ready(local))
        local.pending = 0; self.assertFalse(window.ready(local)); self.assertIsNone(window.first_pending)

    def test_threshold_counts_rows_instead_of_cells(self):
        import sqlite3
        from types import SimpleNamespace
        db = sqlite3.connect(':memory:'); self.addCleanup(db.close)
        db.execute('CREATE TABLE dirty(tab TEXT,row_id INTEGER,header TEXT)')
        db.executemany('INSERT INTO dirty VALUES (?,?,?)', [('History',1,str(i)) for i in range(100)])
        self.assertFalse(PublishWindow(target_rows=100).ready(SimpleNamespace(db=db)))

    def test_final_drain_bypasses_gathering_and_no_progress_is_preserved(self):
        sync = sync_fixture.FakeSync(pending=3)
        window = PublishWindow(max_wait=15)
        held = publish_pending(sync, ready=window.ready)
        self.assertEqual(held['stop_reason'], 'gathering'); self.assertEqual(sync.events, [])
        drained = publish_pending(sync)
        self.assertEqual(drained['stop_reason'], 'drained'); self.assertEqual(sync.local.pending, 0)
        sync.local.pending = 1; sync.zero_progress = True
        self.assertEqual(publish_pending(sync)['stop_reason'], 'no_progress')

    def test_startup_and_exit_never_wait_for_small_batch(self):
        sync = sync_fixture.FakeSync(pending=1)
        session = sync_fixture.RunScopedSyncTests().session(sync, interval=60, coalesce_seconds=15)
        with session:
            self.assertEqual(sync.local.pending, 0)
            sync.local.pending = 3
        self.assertEqual(sync.local.pending, 0)
        self.assertFalse(session.thread.is_alive())
