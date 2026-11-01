"""Larger complete-evidence batches, bounded text, and independent ownership."""
import json
import multiprocessing
from pathlib import Path
from contextlib import redirect_stdout
import io
import tempfile
import unittest
from unittest.mock import patch

from job_search_helper.review_runtime import Runtime, local_evidence, TRIAGE_BATCH_CHARACTERS, main
from job_search_helper.sqlite_repository import SQLiteRepository
from test_concurrent_review import job, publish, response
from test_multi_worker_review import process_worker


class BatchEfficiencyTests(unittest.TestCase):
    def setUp(self):
        directory=tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        self.root=Path(directory.name); self.queue=self.root/'queue'
        publish(self.queue,second=[job(f'j{i:03}',description='Complete description') for i in range(20)])
        self.rt=Runtime(self.queue); self.addCleanup(self.rt.close)
        self.rt.sync(); self.owner=self.rt.start(2)['run_id']
        self.repo=SQLiteRepository(self.root/'jobs.sqlite3','fixture',initialize=True)
        self.addCleanup(self.repo.close)

    def evidence(self, count=20, text='Complete saved description'):
        self.repo.import_rows('Job Evidence',enumerate(
            [{'Job Key':f'j{i:03}','Source Hash':'h1','Job Description':text} for i in range(count)],2))

    def test_default_returns_ten_short_descriptions(self):
        batch=self.rt.next(2,self.owner)
        self.assertEqual(len(batch['items']),10)
        self.assertFalse(batch['batch']['over_budget'])
        self.assertEqual(batch['batch']['missing_descriptions'],0)

    def test_explicit_smaller_limit_and_invalid_limits(self):
        self.assertEqual(len(self.rt.next(2,self.owner,3)['items']),3)
        for limit in (0,-1,11):
            with self.assertRaises(ValueError): self.rt.next(2,self.owner,limit)

    def test_long_descriptions_reduce_batch_without_truncation_or_extra_claims(self):
        text='A'*20000
        publish(self.queue,second=[job(f'j{i:03}',description=text) for i in range(10)])
        batch=self.rt.next(2,self.owner)
        self.assertEqual(len(batch['items']),2)
        self.assertTrue(all(i['job_description']==text for i in batch['items']))
        self.assertEqual(self.rt.status(2)['passes']['2']['claimed'],2)

    def test_one_oversized_job_is_not_starved(self):
        text='A'*(TRIAGE_BATCH_CHARACTERS+1)
        publish(self.queue,second=[job('a',description=text),job('b',description='Small')])
        batch=self.rt.next(2,self.owner)
        self.assertEqual(len(batch['items']),1)
        self.assertEqual(batch['items'][0]['job_description'],text)
        self.assertTrue(batch['batch']['over_budget'])

    def test_uncertain_evidence_reserves_space(self):
        publish(self.queue,second=[job(f'j{i:03}') for i in range(10)])
        batch=self.rt.next(2,self.owner)
        self.assertLess(len(batch['items']),10)
        self.assertEqual(batch['batch']['missing_descriptions'],len(batch['items']))

    def test_missing_descriptions_are_loaded_by_index_before_sizing(self):
        publish(self.queue,second=[job(f'j{i:03}') for i in range(10)])
        text='B'*20000; self.evidence(text=text)
        with patch.object(self.repo,'read_columns',side_effect=AssertionError('Full scan')):
            batch=self.rt.next(2,self.owner,repo=self.repo)
        self.assertEqual(len(batch['items']),2)
        self.assertTrue(all(i['job_description']==text for i in batch['items']))
        self.assertEqual(batch['batch']['missing_descriptions'],0)

    def test_exact_source_required_and_duplicate_identity_fails_closed(self):
        self.evidence(1)
        self.assertIsNone(local_evidence(self.repo,'j000','different'))
        self.assertIsNone(local_evidence(self.repo,'different','h1'))
        row={'Job Key':'j000','Source Hash':'h1','Job Description':'Ambiguous'}
        with self.repo.transaction(): self.repo._put('Job Evidence',99,row)
        evidence=local_evidence(self.repo,'j000','h1')
        self.assertTrue(evidence['evidence_conflict'])
        self.assertEqual(evidence['job_description'],'')

    def test_truncated_or_blank_local_evidence_is_not_complete(self):
        for text in ('','   ','Opening [truncated for export]'):
            with self.repo.transaction(): self.repo._put('Job Evidence',1,{'Job Key':'j000','Source Hash':'h1','Job Description':text})
            self.assertIsNone(local_evidence(self.repo,'j000','h1'))

    def test_single_recovery_avoids_snapshot_and_inventory_scans(self):
        self.evidence(1)
        with patch('job_search_helper.review_runtime.read_snapshot',side_effect=AssertionError('Queue scan')), patch('job_search_helper.title_audit.load_title_audits',side_effect=AssertionError('Inventory scan')):
            evidence=self.rt.hydrate('j000','h1',repo=self.repo)
        self.assertEqual(evidence['job_description'],'Complete saved description')
        self.assertEqual(self.rt.hydrate('j000','h1'),evidence)

    def test_cached_evidence_is_included_in_size_and_resume_keeps_held_claims(self):
        self.rt.next(2,self.owner)
        # Evidence can grow after a previous (older) worker claimed a batch.
        publish(self.queue,second=[job(f'j{i:03}') for i in range(20)])
        self.rt.sync()
        held=self.rt.next(2,self.owner,1)['items'][0]
        with self.rt.transaction():
            self.rt.db.execute('INSERT INTO evidence VALUES(?,?,?)',('j000','h1',json.dumps({'job_description':'A'*70000})))
        resumed=self.rt.next(2,self.owner)['items']
        self.assertEqual(len(resumed),1)
        self.assertEqual(resumed[0]['claim_token'],held['claim_token'])
        self.assertEqual(len(resumed[0]['job_description']),70000)

    def test_existing_claims_survive_budget_growth(self):
        publish(self.queue,second=[job(f'j{i:03}') for i in range(10)])
        held=self.rt.next(2,self.owner,2)['items']
        with self.rt.transaction():
            for item in held:
                self.rt.db.execute('INSERT INTO evidence VALUES(?,?,?)',(item['job_key'],'h1',json.dumps({'job_description':'A'*40000})))
        batch=self.rt.next(2,self.owner)
        self.assertEqual([r['claim_token'] for r in batch['items']],[r['claim_token'] for r in held])
        self.assertTrue(batch['batch']['over_budget'])

    def test_cli_opens_local_evidence_readonly_after_controls_and_closes_it(self):
        publish(self.queue,second=[job('j000')]); self.evidence(1)
        output=io.StringIO()
        with patch('job_search_helper.runner._load_environment'), patch('job_search_helper.review_controls.refresh_sheet_controls',return_value={'reopened_jobs':0,'delivery_target':'local_database'}) as controls, patch('job_search_helper.cli.storage_backend',return_value='sqlite'), patch('job_search_helper.cli.get_repository',return_value=self.repo) as getter, patch.object(self.repo,'close') as close, redirect_stdout(output):
            result=main(['next','--pass','2','--run-id',self.owner,'--queue-dir',str(self.queue)])
        self.assertEqual(result,0)
        controls.assert_called_once(); getter.assert_called_once_with(write=False,interactive=False)
        close.assert_called_once()
        self.assertEqual(json.loads(output.getvalue())['items'][0]['job_description'],'Complete saved description')

    def test_manual_no_fences_one_in_larger_batch(self):
        self.rt.set_sheet_controls([(f'j{i:03}','Pending',1,'h1') for i in range(20)])
        items=self.rt.next(2,self.owner)['items']
        self.rt.set_sheet_controls([(f'j{i:03}','No' if i==0 else 'Pending',int(i!=0),'h1') for i in range(20)])
        result=self.rt.submit(2,self.owner,[response(i,2,'ESCALATE') for i in items])
        self.assertEqual(result['saved'],9)
        self.assertEqual(len(result['skipped_manual']),1)

    def test_ten_process_workers_claim_one_hundred_distinct_jobs(self):
        publish(self.queue,second=[job(f'j{i:03}',description='Complete description') for i in range(100)])
        ctx=multiprocessing.get_context('spawn'); barrier=ctx.Barrier(10); reports=ctx.Queue()
        workers=[ctx.Process(target=process_worker,args=(self.queue,barrier,reports)) for _ in range(10)]
        try:
            for worker in workers: worker.start()
            results=[reports.get(timeout=30) for _ in workers]
            for worker in workers: worker.join(10)
            self.assertTrue(all(w.exitcode==0 for w in workers))
            self.assertFalse([r for r in results if 'error' in r],results)
            keys=[key for result in results for key in result['keys']]
            self.assertEqual(len(keys),100); self.assertEqual(len(set(keys)),100)
            self.assertEqual(len({r['owner'] for r in results}),10)
            self.assertEqual(sum(r['saved'] for r in results),100)
        finally:
            for worker in workers:
                if worker.is_alive(): worker.terminate(); worker.join(5)
            reports.close(); reports.join_thread()


if __name__=='__main__': unittest.main()
