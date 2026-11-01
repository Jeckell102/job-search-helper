"""Offline exact-identity final-review scoping; never contacts live services."""
from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from job_search_helper.review_runtime import Runtime, atomic_json, main, read_scope_file
from test_concurrent_review import job, publish, response


class FinalScopeTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name); self.queue=self.root/'queue'
        publish(self.queue,second=[job('old',score=100),job('pilot-a',score=20),job('pilot-b',score=10)])
        self.rt=Runtime(self.queue); self.addCleanup(self.rt.close)
        self.rt.sync(); triage=self.rt.start(2)['run_id']
        self.rt.submit(2,triage,[response(item,2,'ESCALATE') for item in self.rt.next(2,triage)['items']])
        self.owner=self.rt.start(3)['run_id']
        self.scope=[('pilot-a','h1'),('pilot-b','h1')]
        self.manifest=self.root/'scope.jsonl'
        atomic_json(self.manifest,[dict(job_key=key,source_hash=source) for key,source in self.scope],lines=True)

    def claim_state(self,key):
        return tuple(self.rt.db.execute('SELECT state,owner,token,lease_until FROM tasks WHERE stage=3 AND job_key=?',(key,)).fetchone())

    def test_scoped_claim_leaves_higher_priority_old_escalation_untouched(self):
        before=self.claim_state('old')
        items=self.rt.next(3,self.owner,3,identities=self.scope)['items']
        self.assertEqual([i['job_key'] for i in items],['pilot-a','pilot-b'])
        self.assertEqual(self.claim_state('old'),before)
        self.assertTrue(all(i['claim_token'] and i['input_version'] for i in items))

    def test_exact_source_mismatch_is_not_claimed(self):
        before=self.claim_state('pilot-a')
        self.assertEqual(self.rt.next(3,self.owner,identities=[('pilot-a','other-hash')])['items'],[])
        self.assertEqual(self.claim_state('pilot-a'),before)

    def test_normal_default_order_unchanged(self):
        self.assertEqual(self.rt.next(3,self.owner)['items'][0]['job_key'],'old')

    def test_refuses_to_strand_owned_out_of_scope_claim(self):
        self.rt.next(3,self.owner)
        before={key:self.claim_state(key) for key in ('old','pilot-a','pilot-b')}
        with self.assertRaisesRegex(RuntimeError,'outside supplied scope'):
            self.rt.next(3,self.owner,identities=self.scope)
        self.assertEqual({key:self.claim_state(key) for key in before},before)

    def test_resume_keeps_owned_token_within_scope(self):
        first=self.rt.next(3,self.owner,identities=self.scope)['items'][0]
        second=self.rt.next(3,self.owner,identities=self.scope)['items'][0]
        self.assertEqual(first['claim_token'],second['claim_token'])

    def test_multiple_workers_claim_disjoint_jobs_within_scope(self):
        barrier=threading.Barrier(2); claimed=[]; errors=[]
        def worker():
            runtime=Runtime(self.queue)
            try:
                owner=runtime.start(3)['run_id']; barrier.wait(timeout=10)
                claimed.extend(runtime.next(3,owner,identities=self.scope)['items'])
            except BaseException as error: errors.append(error)
            finally: runtime.close()
        workers=[threading.Thread(target=worker) for _ in range(2)]
        for worker in workers: worker.start()
        for worker in workers: worker.join(15)
        self.assertFalse(any(worker.is_alive() for worker in workers))
        self.assertFalse(errors,errors)
        self.assertEqual(sorted(item['job_key'] for item in claimed),['pilot-a','pilot-b'])
        self.assertEqual(len({item['claim_token'] for item in claimed}),2)
        self.assertEqual(self.claim_state('old')[0],'ready')

    def test_cli_still_imports_live_manual_no_before_claiming(self):
        def controls(runtime):
            runtime.set_sheet_controls([('old','Pending',1,'h1'),('pilot-a','No',0,'h1'),('pilot-b','Pending',1,'h1')])
            return {'reopened_jobs':0,'delivery_target':'local_database'}
        with patch('job_search_helper.review_controls.refresh_sheet_controls',side_effect=controls) as refresh, redirect_stdout(io.StringIO()) as output:
            code=main(['next','--pass','3','--run-id',self.owner,'--queue-dir',str(self.queue),'--scope-file',str(self.manifest)])
        self.assertEqual(code,0)
        refresh.assert_called_once()
        self.assertEqual([item['job_key'] for item in json.loads(output.getvalue())['items']],['pilot-b'])
        self.assertEqual(self.claim_state('old')[0],'ready')
        self.assertEqual(self.claim_state('pilot-a')[0],'withdrawn')

    def test_cli_live_control_failure_still_blocks_scoped_claim(self):
        with patch('job_search_helper.review_controls.refresh_sheet_controls',side_effect=RuntimeError('offline')), patch.object(Runtime,'next') as claim, redirect_stderr(io.StringIO()):
            code=main(['next','--pass','3','--run-id',self.owner,'--queue-dir',str(self.queue),'--scope-file',str(self.manifest)])
        self.assertEqual(code,1); claim.assert_not_called()

    def test_bad_manifests_fail_before_runtime_or_live_mutations(self):
        invalid=['','\n','{bad json}', '[]', '{}',
                 '{"job_key":"pilot-a","source_hash":"h1","extra":true}',
                 '{"job_key":"","source_hash":"h1"}',
                 '{"job_key":1,"source_hash":"h1"}',
                 '\n'.join([json.dumps({'job_key':'pilot-a','source_hash':'h1'})]*2),
                 '\n'.join(json.dumps({'job_key':str(i),'source_hash':'h1'}) for i in range(101))]
        for contents in invalid:
            with self.subTest(contents=contents[:100]):
                self.manifest.write_text(contents)
                with patch('job_search_helper.review_runtime.Runtime') as runtime, patch('job_search_helper.review_controls.refresh_sheet_controls') as controls, redirect_stderr(io.StringIO()):
                    code=main(['next','--pass','3','--run-id',self.owner,'--scope-file',str(self.manifest)])
                self.assertEqual(code,1); runtime.assert_not_called(); controls.assert_not_called()

    def test_scope_misuse_fails_before_runtime(self):
        for command,stage in [('next',1),('next',2),('start',3),('status',3),('submit',3),('writeback',3),('finish',3),('pause',3),('heartbeat',3),('evidence',3),('controls',3),('refresh',3),('amend-pending',3)]:
            with self.subTest(command=command,stage=stage), patch('job_search_helper.review_runtime.Runtime') as runtime, redirect_stderr(io.StringIO()):
                code=main([command,'--pass',str(stage),'--run-id',self.owner,'--scope-file',str(self.manifest)])
                self.assertEqual(code,1); runtime.assert_not_called()

    def test_runtime_invalid_scope_fails_before_sync(self):
        for stage,scope in [(2,self.scope),(3,[]),(3,[('pilot-a','h1')]*2),(3,[('a','')])]:
            with self.subTest(stage=stage,scope=scope), patch.object(self.rt,'sync') as sync:
                with self.assertRaises(ValueError): self.rt.next(stage,self.owner,identities=scope)
                sync.assert_not_called()

    def test_manifest_accepts_one_hundred_exact_identities(self):
        identities=[{'job_key':str(i),'source_hash':'h1'} for i in range(100)]
        atomic_json(self.manifest,identities,lines=True)
        self.assertEqual(len(read_scope_file(self.manifest)),100)


if __name__=='__main__': unittest.main()
