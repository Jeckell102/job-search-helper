"""Offline refresh caching, publication isolation and live-control invalidation."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from job_search_helper.sqlite_repository import SQLiteRepository
from job_search_helper.repository import SCHEMAS
from job_search_helper.review_queue import export_review_queues, build_review_queues
from job_search_helper.review_refresh import fingerprint
from job_search_helper.review_revisions import revision
from job_search_helper.review_runtime import read_snapshot
from test_review_queue import ReviewQueueTests
from test_review_live_controls import LiveControlsTests


class SharedRefreshTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name); self.queue = self.root / 'queue'
        self.repo = SQLiteRepository(self.root / 'jobs.sqlite3', 'fixture', initialize=True)
        self.addCleanup(self.repo.close)
        fixture = ReviewQueueTests().make_repo()
        for tab in SCHEMAS:
            self.repo.import_rows(tab, enumerate(fixture.read(tab), 2))
        self.repo.set_meta('ready', 'yes')

    def export(self, **kwargs):
        return export_review_queues(self.repo, self.queue, overwrite=True, reuse_if_current=True, **kwargs)

    def raw_change(self, tab, field, value, row_id=None):
        if row_id is None: row_id = self.repo.matches(tab, {'Job Key':'a'})[0][0]
        row = self.repo.row(tab, row_id); row[field] = value
        with self.repo.transaction():
            self.repo.db.execute('UPDATE records SET data=? WHERE tab=? AND row_id=?',
                                 (json.dumps(row), tab, row_id))

    def test_second_worker_reuses_verified_generation(self):
        first = self.export()
        with patch('job_search_helper.review_queue.build_review_queues', side_effect=AssertionError('Repeated full build')):
            second = self.export()
        self.assertFalse(first['refresh']['reused']); self.assertTrue(second['refresh']['reused'])
        self.assertEqual(first['generated_at'], second['generated_at'])

    def test_raw_sql_evidence_change_with_same_source_hash_invalidates(self):
        self.export(); self.raw_change('Job Evidence', 'Job Description', 'Customer field deployment hardware integration and training')
        self.assertFalse(self.export()['refresh']['reused'])
        _, files = read_snapshot(self.queue)
        self.assertIn('Customer field deployment', files['second-pass.jsonl'][0]['job_description'])

    def test_title_salary_source_and_status_changes_invalidate(self):
        self.export()
        for field, value in [('Job Title','Field Integration Lead'), ('Salary / Range','$190,000 base'),
                             ('Source Hash','new-source'), ('Job Status','Closed'),
                             ('Reconsideration Status','Frozen after 2')]:
            with self.subTest(field=field):
                self.raw_change('Job History', field, value)
                self.assertFalse(self.export()['refresh']['reused'])

    def test_review_removal_and_notes_do_not_force_rescore_but_reopen_does(self):
        self.export()
        before = revision(self.repo, 'controls')
        self.raw_change('Job History', 'Added to Opportunities?', 'No')
        self.raw_change('Job History', 'Review Notes', 'Personal note')
        self.assertTrue(self.export()['refresh']['reused'])
        self.assertNotEqual(before, revision(self.repo, 'controls'))
        self.raw_change('Job History', 'Added to Opportunities?', 'Pending')
        self.assertFalse(self.export()['refresh']['reused'])

    def test_delete_and_insert_and_rollbacks_track_revision(self):
        self.export(); before = revision(self.repo, 'queue')
        self.repo.db.execute('BEGIN IMMEDIATE')
        self.repo.db.execute("DELETE FROM baseline WHERE tab='Job Evidence'")
        self.repo.db.execute("DELETE FROM records WHERE tab='Job Evidence'")
        self.assertNotEqual(before, revision(self.repo, 'queue'))
        self.repo.db.execute('ROLLBACK')
        self.assertEqual(before, revision(self.repo, 'queue'))
        self.assertTrue(self.export()['refresh']['reused'])
        self.repo.db.execute("INSERT INTO records(tab,row_id,data) VALUES('Job Evidence',999,?)",
                             (json.dumps({'Job Key':'new','Source Hash':'s','Job Description':'Full source'}),))
        self.assertFalse(self.export()['refresh']['reused'])

    def test_corrupted_files_rebuild_instead_of_reuse(self):
        self.export(); (self.queue / 'second-pass.jsonl').write_text('corrupt')
        self.assertFalse(self.export()['refresh']['reused']); read_snapshot(self.queue)

    def test_threshold_and_policy_changes_invalidate(self):
        self.export(); self.assertFalse(self.export(threshold=20)['refresh']['reused'])
        from job_search_helper import efficiency
        rules = self.root / 'blacklist.txt'; rules.write_text(efficiency.BLACKLIST_PATH.read_text())
        with patch.object(efficiency, 'BLACKLIST_PATH', rules):
            self.assertFalse(self.export()['refresh']['reused'])
            self.assertTrue(self.export()['refresh']['reused'])
            rules.write_text(rules.read_text() + '\nSome New Excluded Title\n')
            self.assertFalse(self.export()['refresh']['reused'])
        efficiency.load_title_blacklist.cache_clear()

    def test_inventory_wal_and_database_replacement_invalidate(self):
        path = self.root / 'inventory.sqlite3'; path.write_bytes(b'one')
        first = fingerprint(self.repo, 17, path)
        Path(str(path)+'-wal').write_bytes(b'change')
        self.assertNotEqual(first, fingerprint(self.repo, 17, path))

    def test_failure_keeps_previous_generation(self):
        first = self.export(); self.raw_change('Job History','Job Title','Field Support Engineer')
        with patch('job_search_helper.review_queue.build_review_queues', side_effect=RuntimeError('failed')):
            with self.assertRaisesRegex(RuntimeError,'failed'): self.export()
        self.assertEqual(read_snapshot(self.queue)[0]['generated_at'],first['generated_at'])

    def test_source_change_during_build_retries_fresh_snapshot(self):
        first = self.export(); self.raw_change('Job History','Job Title','New Field Support Engineer')
        other = SQLiteRepository(self.repo.path, 'fixture'); self.addCleanup(other.close)
        builds = []
        def changing(*args, **kwargs):
            result = build_review_queues(*args, **kwargs)
            builds.append(1)
            if len(builds) == 1:
                rid, row = other.matches('Job History', {'Job Key':'a'})[0]; row['Job Title']='Latest Field Support Engineer'
                other.db.execute("UPDATE records SET data=? WHERE tab='Job History' AND row_id=?",(json.dumps(row),rid))
            return result
        def waiting(delay):
            self.assertFalse(self.repo.db.in_transaction)
            self.assertEqual(read_snapshot(self.queue)[0]['generated_at'],first['generated_at'])
        with patch('job_search_helper.review_queue.build_review_queues',side_effect=changing), \
             patch('job_search_helper.review_queue.time.sleep',side_effect=waiting) as sleep, \
             self.assertLogs('job_search_helper.review_queue', level='WARNING'):
            result = self.export()
        self.assertEqual(len(builds), 2)
        sleep.assert_called_once_with(0.5)
        self.assertEqual(result['refresh']['attempts'], 2)
        self.assertEqual(result['refresh']['retries'], 1)
        summary, files = read_snapshot(self.queue)
        self.assertEqual(summary['source_fingerprint'], fingerprint(self.repo,17,None))
        rows = files['first-pass.jsonl'] + files['second-pass.jsonl']
        self.assertEqual(next(row['job_title'] for row in rows if row['job_key']=='a'),
                         'Latest Field Support Engineer')

    def test_continuous_source_changes_exhaust_three_attempts_and_preserve_files(self):
        self.export(); self.raw_change('Job History','Job Title','New Field Support Engineer')
        names = ('first-pass.jsonl','second-pass.jsonl','deterministic-filtered.jsonl','summary.json')
        prior = {name:(self.queue/name).read_bytes() for name in names}
        other = SQLiteRepository(self.repo.path, 'fixture'); self.addCleanup(other.close)
        builds = []
        def changing(*args, **kwargs):
            result = build_review_queues(*args, **kwargs)
            builds.append(1)
            row = other.row('Job History',2); row['Source Hash']=f'changed-during-build-{len(builds)}'
            other.db.execute("UPDATE records SET data=? WHERE tab='Job History' AND row_id=2",(json.dumps(row),))
            return result
        with patch('job_search_helper.review_queue.build_review_queues',side_effect=changing), \
             patch('job_search_helper.review_queue.time.sleep') as sleep, \
             self.assertLogs('job_search_helper.review_queue', level='WARNING'), \
             self.assertRaisesRegex(RuntimeError,'after 3 attempts; prior queue preserved'):
            self.export()
        self.assertEqual(len(builds),3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list],[0.5,1.0])
        self.assertEqual({name:(self.queue/name).read_bytes() for name in names},prior)
        self.assertFalse(self.repo.db.in_transaction)
        self.assertEqual(list(self.queue.glob('.refresh-*')),[])

    def test_unrelated_build_error_is_not_retried(self):
        self.export(); self.raw_change('Job History','Job Title','Field Support Engineer')
        with patch('job_search_helper.review_queue.build_review_queues',side_effect=RuntimeError('different error')) as build, \
             patch('job_search_helper.review_queue.time.sleep') as sleep:
            with self.assertRaisesRegex(RuntimeError,'different error'):
                self.export()
        self.assertEqual(build.call_count,1)
        sleep.assert_not_called()

    def test_concurrent_starters_share_build_and_readers_are_not_blocked(self):
        self.export(); self.raw_change('Job History','Job Title','Field Support Engineer')
        entered=threading.Event(); release=threading.Event(); read_done=threading.Event()
        results=[]; errors=[]; builds=[]
        def slow(*args,**kwargs):
            builds.append(1); entered.set()
            if not release.wait(5): raise RuntimeError('test timeout')
            return build_review_queues(*args,**kwargs)
        def starter():
            repo=SQLiteRepository(self.repo.path,'fixture',readonly=True)
            try: results.append(export_review_queues(repo,self.queue,overwrite=True,reuse_if_current=True))
            except BaseException as exc: errors.append(exc)
            finally: repo.close()
        def reader():
            try: read_snapshot(self.queue); read_done.set()
            except BaseException as exc: errors.append(exc)
        with patch('job_search_helper.review_queue.build_review_queues',side_effect=slow):
            a=threading.Thread(target=starter); b=threading.Thread(target=starter)
            a.start(); self.assertTrue(entered.wait(2)); b.start()
            r=threading.Thread(target=reader); r.start()
            try: self.assertTrue(read_done.wait(2),'Reader blocked by queue construction')
            finally:
                release.set(); a.join(5); b.join(5); r.join(5)
        self.assertFalse(errors,errors); self.assertEqual(len(builds),1)
        self.assertEqual(sorted(x['refresh']['reused'] for x in results),[False,True])


class FastLiveControlsTests(LiveControlsTests):
    def test_unchanged_pull_reads_remote_but_skips_local_merge(self):
        from job_search_helper import review_controls
        with patch.object(self.remote,'read_columns',wraps=self.remote.read_columns) as reads, \
             patch.object(review_controls,'_local_rows',wraps=review_controls._local_rows) as scans:
            first=self.pull(); second=self.pull()
        self.assertEqual(reads.call_count,2); self.assertEqual(scans.call_count,1)
        self.assertFalse(first['local_processing_skipped']); self.assertTrue(second['local_processing_skipped'])
        self.assertNotEqual(first['checked_at'],second['checked_at'])

    def test_local_change_invalidates_unchanged_remote_fast_path(self):
        self.pull(); self.assertTrue(self.pull()['local_processing_skipped'])
        self.local.commit([{'tab':'Job History','identity':{'Job Key':'a'},
                            'values':{'Added to Opportunities?':'No'}}])
        result=self.pull(); self.assertFalse(result['local_processing_skipped'])
        self.assertNotIn('a',[x['job_key'] for x in self.rt.next(2,self.owner)['items']])

    def test_remote_edit_after_cached_check_still_cancels_claim(self):
        self.pull(); self.pull(); items=self.rt.next(2,self.owner)['items']
        self.edit('a','No'); result=self.pull()
        self.assertFalse(result['local_processing_skipped']); self.assertEqual(result['cancelled_claims'],1)
        from test_concurrent_review import response
        saved=self.rt.submit(2,self.owner,[response(x,2,'ESCALATE') for x in items])
        self.assertEqual(saved['saved'],1); self.assertEqual(saved['skipped_manual'][0]['job_key'],'a')

    def test_unchanged_poll_does_not_repeat_reopen(self):
        self.pull(); self.edit('a','No'); self.pull(); self.edit('a','Pending')
        self.assertEqual(self.pull()['reopened_jobs'],1)
        cached=self.pull(); self.assertTrue(cached['local_processing_skipped'])
        self.assertEqual(cached['reopened_jobs'],0)


if __name__=='__main__': unittest.main()
