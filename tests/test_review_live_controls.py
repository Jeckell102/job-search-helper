"""Manual sheet changes must fence live reviews without losing other work."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from job_search_helper.review_controls import refresh_sheet_controls, FIELDS
from job_search_helper.review_runtime import Runtime, main, atomic_json, LOGS
from job_search_helper.repository import MemoryRepository, SCHEMAS, _encoded, RepositoryError
from job_search_helper.sqlite_repository import SQLiteRepository
from job_search_helper.sheet_profile import COMPACT_PROFILE
from test_concurrent_review import job as queued_job, publish, response
from test_sqlite_migration import job


class LiveControlsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name); self.queue=self.root/'queue'
        self.local=SQLiteRepository(self.root/'jobs.sqlite3','fixture',initialize=True)
        self.addCleanup(self.local.close)
        self.remote=MemoryRepository({'Job History':[job('a'),job('b')],
                                     'Job Evidence':[{'Job Key':k,'Source Hash':'source-1','Job Description':'Complete description'} for k in ('a','b')]})
        self.remote.spreadsheet_id='fixture'
        for tab in SCHEMAS: self.local.import_rows(tab,enumerate(self.remote.read(tab),2))
        with self.local.transaction():
            self.local.set_meta('ready','yes')
            self.local.set_meta('sheets_profile',COMPACT_PROFILE)
        publish(self.queue,second=[queued_job(k,'source-1',description='Complete description') for k in ('a','b')])
        self.rt=Runtime(self.queue); self.addCleanup(self.rt.close)
        self.rt.sync(); self.owner=self.rt.start(2)['run_id']

    def edit(self,key,choice):
        index=next(i for i,r in enumerate(self.remote.read('Job History'),1) if r['Job Key']==key)
        sheet=self.remote._sheets['Job History']
        cell=sheet.cells.setdefault((index,sheet.headers.index('Added to Opportunities?')),{})
        cell['userEnteredValue']=cell['effectiveValue']=_encoded(choice)

    def pull(self):
        return refresh_sheet_controls(self.rt,local=self.local,remote=self.remote)

    def test_no_while_claimed_cancels_only_changed_job_and_saves_rest(self):
        self.pull(); batch=self.rt.next(2,self.owner)['items']
        self.edit('a','No'); report=self.pull()
        self.assertEqual(report['cancelled_claims'],1)
        result=self.rt.submit(2,self.owner,[response(i,2,'CLEAR_REJECT') for i in batch])
        self.assertEqual(result['saved'],1)
        self.assertEqual([r['job_key'] for r in result['skipped_manual']],['a'])
        self.assertEqual(self.local.matches('Job History',{'Job Key':'a'})[0][1]['Added to Opportunities?'],'No')
        self.assertEqual(self.rt.db.execute("SELECT COUNT(*) FROM decisions WHERE job_key='a'").fetchone()[0],0)

    def test_yes_manual_review_and_blank_also_remove_jobs(self):
        for choice in ('Yes','Manual Review',''):
            with self.subTest(choice=choice):
                self.edit('a',choice); self.pull()
                self.assertNotIn('a',[x['job_key'] for x in self.rt.next(2,self.owner)['items']])

    def test_off_sheet_audit_never_claimed_and_history_preserved(self):
        hidden=queued_job('hidden','source-1',description='Full off-sheet evidence'); hidden['row_number']=None
        publish(self.queue,second=[queued_job('a','source-1',description='Complete description'),hidden])
        self.pull()
        self.assertEqual([x['job_key'] for x in self.rt.next(2,self.owner)['items']],['a'])
        self.assertIn('hidden',(self.queue/'second-pass.jsonl').read_text())

    def test_change_back_to_pending_reopens_and_archives_completed_decision(self):
        self.pull(); batch=self.rt.next(2,self.owner)['items']
        item=next(x for x in batch if x['job_key']=='a')
        self.rt.submit(2,self.owner,[response(item,2,'CLEAR_REJECT')])
        self.edit('a','No'); self.pull()
        self.edit('a','Pending'); report=self.pull()
        self.assertEqual(report['reopened_jobs'],1)
        fresh=next(x for x in self.rt.next(2,self.owner)['items'] if x['job_key']=='a')
        self.assertNotEqual(fresh['claim_token'],item['claim_token'])
        event=json.loads(self.rt.db.execute("SELECT detail FROM events WHERE event='manual_review_requested' AND job_key='a'").fetchone()[0])
        self.assertEqual(len(event['prior_decisions']),1)
        self.assertEqual(self.rt.submit(2,self.owner,[response(fresh,2,'ESCALATE')])['saved'],1)

    def test_pending_reopen_does_not_reimport_old_legacy_assessment(self):
        atomic_json(self.queue/LOGS[2],[{'job_key':'a','source_hash':'source-1','triage_decision':'CLEAR_REJECT','reason':'Old decision'}],lines=True)
        self.rt.sync(); self.pull(); self.edit('a','No'); self.pull()
        self.edit('a','Pending'); self.pull()
        self.assertIn('a',[x['job_key'] for x in self.rt.next(2,self.owner)['items']])
        self.assertEqual(self.rt.db.execute("SELECT COUNT(*) FROM decisions WHERE job_key='a'").fetchone()[0],0)

    def test_partial_merge_does_not_flag_other_sheet_rows_as_missing(self):
        self.edit('a','No'); self.pull()
        self.assertEqual(self.local.db.execute("SELECT COUNT(*) FROM conflicts WHERE header='__missing__'").fetchone()[0],0)
        self.assertEqual(self.local.matches('Job History',{'Job Key':'b'})[0][1]['Added to Opportunities?'],'Pending')

    def test_poll_reads_only_control_columns_and_never_publishes(self):
        with patch.object(self.remote,'read_columns',wraps=self.remote.read_columns) as reads, patch.object(self.remote,'commit',side_effect=AssertionError('Must not publish')):
            first=self.pull(); second=self.pull()
        self.assertEqual(reads.call_count,2)
        self.assertEqual(reads.call_args.args,('Job History',FIELDS))
        self.assertEqual(second['changed_fields'],0)
        self.assertEqual(first['delivery_target'],'local_database')

    def test_failed_live_read_cannot_publish_an_empty_snapshot(self):
        self.pull(); before=self.rt.status()['sheet_controls']
        with patch.object(self.remote,'read_columns',side_effect=RuntimeError('offline')):
            with self.assertRaisesRegex(RuntimeError,'offline'): self.pull()
        self.assertEqual(self.rt.status()['sheet_controls'],before)

    def test_cli_pulls_before_claiming(self):
        self.edit('a','No')
        with patch('job_search_helper.review_controls.refresh_sheet_controls',side_effect=lambda runtime:self.pull()) as refresh, redirect_stdout(io.StringIO()) as out:
            code=main(['next','--pass','2','--run-id',self.owner,'--queue-dir',str(self.queue)])
        self.assertEqual(code,0,out.getvalue())
        self.assertEqual([x['job_key'] for x in json.loads(out.getvalue())['items']],['b'])
        self.assertEqual(refresh.call_count,1)

    def test_no_return_to_pending_fences_old_claim_even_without_changed_source(self):
        self.pull(); old=self.rt.next(2,self.owner)['items'][0]
        self.edit(old['job_key'],'No'); self.pull()
        self.edit(old['job_key'],'Pending'); self.pull()
        self.rt.next(2,self.owner)
        with self.assertRaisesRegex(RuntimeError,'Stale/unowned'):
            self.rt.submit(2,self.owner,[response(old,2,'CLEAR_REJECT')])

    def test_cli_blocks_claims_when_sheet_is_unavailable(self):
        with patch('job_search_helper.review_controls.refresh_sheet_controls',side_effect=RuntimeError('Sheet unavailable')), patch.object(Runtime,'next',side_effect=AssertionError('Must not claim')):
            from contextlib import redirect_stderr
            with redirect_stderr(io.StringIO()) as error:
                code=main(['next','--pass','2','--run-id',self.owner,'--queue-dir',str(self.queue)])
        self.assertEqual(code,1)
        self.assertIn('Sheet unavailable',error.getvalue())

    def test_live_no_is_imported_before_cli_submission(self):
        self.pull(); batch=self.rt.next(2,self.owner)['items']
        path=self.root/'results.jsonl'
        atomic_json(path,[response(i,2,'ESCALATE') for i in batch],lines=True)
        self.edit('a','No')
        with patch('job_search_helper.review_controls.refresh_sheet_controls',side_effect=lambda runtime:self.pull()), patch('job_search_helper.review_writeback.sync_pending',return_value={'counts':{}}), redirect_stdout(io.StringIO()) as out:
            code=main(['submit','--pass','2','--run-id',self.owner,'--queue-dir',str(self.queue),'--file',str(path)])
        result=json.loads(out.getvalue())
        self.assertEqual(code,0)
        self.assertEqual(result['saved'],1)
        self.assertEqual(result['skipped_manual'][0]['job_key'],'a')

    def test_manual_notes_are_merged_without_losing_local_review_notes(self):
        sheet=self.remote._sheets['Job History']
        cell=sheet.cells.setdefault((1,sheet.headers.index('Review Notes')), {})
        cell['userEnteredValue']=cell['effectiveValue']=_encoded('My new note')
        self.local.commit([{'tab':'Job History','identity':{'Job Key':'a'},'append_notes':{'Review Notes':'Saved review note'}}])
        self.pull()
        notes=self.local.matches('Job History',{'Job Key':'a'})[0][1]['Review Notes']
        self.assertIn('My new note',notes)
        self.assertIn('Saved review note',notes)

    def test_runtime_status_labels_local_delivery_honestly(self):
        self.pull(); item=self.rt.next(2,self.owner)['items'][0]
        self.rt.submit(2,self.owner,[response(item,2,'CLEAR_REJECT')])
        from job_search_helper.review_writeback import sync_pending
        sync_pending(self.rt,2,self.owner,repo=self.local,lock_path=self.root/'local-writer.lock')
        status=self.rt.status(2,self.owner)
        self.assertEqual(status['run']['delivery'],{'Saved Locally':1})
        self.assertEqual(self.remote.read('Job History')[0]['Added to Opportunities?'],'Pending')


if __name__=='__main__': unittest.main()
