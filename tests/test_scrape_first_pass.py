import argparse
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from job_search_helper import scrape_first_pass as c


def claim(key='job-1', token='token-1'):
    return dict(job_key=key, source_hash='hash', claim_token=token, input_version=1,
                job_title='Field Applications Engineer', score=3, evidence_missing=True)


def decision(key='job-1'):
    return dict(job_key=key, source_hash='hash', decision='RESCUE',
                reason='Field applications engineering aligns with customer technical work.', policy_conflicts=[])


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def controller(self):
        ctl = object.__new__(c.Controller)
        ctl.work = self.root
        ctl.state = {'stage': 'REVIEWING', 'review_run_id': 'owned-run', 'workflow_id': 'fixture-workflow'}
        ctl.project = self.root
        ctl.python = self.root / ".venv/bin/python"
        ctl.args = argparse.Namespace(batch_size=25, max_wait_checks=1, fetch_workers=5,
                                      scrape_timeout=1, command='run', resume=False)
        ctl.announce = Mock()
        return ctl

    def test_pending_publication_never_passes(self):
        good = dict(configured_backend='sqlite', ready=True, pending_cells=0,
                    pending_rows=0, last_error='', conflicts=4)
        self.assertTrue(c.publication_ready(good))
        for change in ({'pending_cells': 1}, {'pending_rows': 1}, {'last_error': 'failed'},
                       {'ready': False}, {'configured_backend': 'sheets'}):
            self.assertFalse(c.publication_ready({**good, **change}))
        self.assertFalse(c.publication_ready({}))





    def test_live_prompt_requires_actual_successful_connector_result(self):
        content = 'FIRST PASS RESCUE PASS ' + ('policy text ' * 150)
        item = {'type': 'mcp_tool_call', 'tool': 'google_drive.get_document', 'status': 'completed',
                'result': {'structured_content': {'documentId': c.PROMPT_ID,
                    'tabs': [{'body': {'content': [{'paragraph': {'elements': [
                        {'textRun': {'content': content}}]}}]}}]}}}
        self.assertEqual(c.extract_prompt([{'type': 'item.completed', 'item': item}]), content)
        for changed in ({**item, 'status': 'failed'},
                        {**item, 'result': {'structured_content': {'documentId': 'wrong'}}},
                        {'type': 'agent_message', 'text': content}):
            with self.assertRaises(c.Blocked):
                c.extract_prompt([{'type': 'item.completed', 'item': changed}])

    def test_receipt_parser_rejects_partial_or_trailing_garbage(self):
        path = self.root / 'stdout'
        path.write_text('Progress\n{"pass":1,"run_id":"id"}\n')
        self.assertEqual(c.parse_json_file(path)['run_id'], 'id')
        for text in ('{"pass":', '{"pass":1}\nerror'):
            path.write_text(text)
            with self.assertRaises(c.Blocked):
                c.parse_json_file(path)

    def test_cycle_binding_rejects_old_ambiguous_or_superseded_cycle(self):
        ctl = self.controller()
        ctl.state = {'before_cycles': ['old']}
        with self.assertRaises(c.Blocked):
            ctl.select_cycle({'cycles': [{'id': 'old'}]})
        self.assertEqual(ctl.select_cycle({'cycles': [{'id': 'old'}, {'id': 'new'}]})['id'], 'new')
        with self.assertRaises(c.Blocked):
            ctl.select_cycle({'cycles': [{'id': 'new'}, {'id': 'extra'}]})
        ctl.state['cycle_id'] = 'new'
        with self.assertRaises(c.Blocked):
            ctl.select_cycle({'cycles': [{'id': 'new'}, {'id': 'extra'}]})

    def test_finished_scrape_recovery_skips_rescrape(self):
        ctl = self.controller()
        ctl.state = {'stage': 'SCRAPING', 'before_cycles': ['old']}
        ctl.probe = Mock(return_value={'scraper_busy': False,
            'cycles': [{'id': 'old'}, {'id': 'new', 'status': 'Complete with exceptions'}]})
        ctl.command = Mock()
        ctl.scrape()
        ctl.command.assert_not_called()
        self.assertEqual(ctl.state['stage'], 'PUBLISHING')
        self.assertEqual(ctl.state['cycle_id'], 'new')

    def test_active_scraper_prevents_duplicate(self):
        ctl = self.controller()
        ctl.probe = Mock(return_value={'scraper_busy': True})
        ctl.command = Mock()
        with self.assertRaises(c.Blocked):
            ctl.scrape()
        ctl.command.assert_not_called()

    def test_user_options_reach_internal_worker_without_public_start_recursion(self):
        ctl = self.controller()
        ctl.state = {'stage': 'SCRAPE_PENDING', 'before_cycles': ['old'],
                     'scraper_args': ['--fetch-workers', '15', '--no-browser-fallback']}
        ctl.probe = Mock(side_effect=[{'scraper_busy': False, 'cycles': [{'id': 'old'}]},
            {'scraper_busy': False, 'cycles': [{'id': 'old'}, {'id': 'new', 'status': 'Complete'}]}])
        ctl.command = Mock(return_value=(0, self.root/'scrape.stdout'))
        ctl.scrape()
        self.assertEqual(ctl.command.call_args.args[0], [str(ctl.python), '-m',
            'job_search_helper.scrape_worker', 'start', '--fetch-workers', '15', '--no-browser-fallback'])
        self.assertEqual(ctl.state['stage'], 'PUBLISHING')

    def test_only_final_sync_error_can_advance_completed_scan_to_publication(self):
        for text, accepted in [('ERROR: Final Sheets sync incomplete; pending changes remain saved locally: 2 cells', True),
                               ('ERROR: unrelated error', False)]:
            ctl = self.controller()
            ctl.state = {'stage':'SCRAPE_PENDING', 'before_cycles':['old']}
            ctl.probe = Mock(side_effect=[{'scraper_busy':False,'cycles':[{'id':'old'}]},
                {'scraper_busy':False,'cycles':[{'id':'old'},{'id':'new','status':'Complete'}]}])
            (self.root/'scrape.stderr').write_text(text)
            ctl.command = Mock(return_value=(1,self.root/'scrape.stdout'))
            if accepted:
                ctl.scrape()
                self.assertEqual(ctl.state['stage'], 'PUBLISHING')
            else:
                with self.assertRaises(c.Blocked): ctl.scrape()

    def test_recovery_binds_exact_cycle_and_never_scrapes_or_reviews_twice(self):
        ctl = self.controller()
        ctl.state = None
        ctl.args.command = 'review'; ctl.args.cycle = 'finished'
        ctl.probe = Mock(return_value={'state_dir':str(self.root), 'scraper_busy':False,
                                      'cycles':[{'id':'finished','status':'Complete'}]})
        ctl.preflight = Mock(); ctl.scrape = Mock()
        ctl.publish_gate = Mock(side_effect=lambda: ctl.save(stage='REVIEWING'))
        ctl.review = Mock(side_effect=lambda: ctl.save(stage='COMPLETE'))
        self.assertEqual(ctl.run(),0)
        ctl.scrape.assert_not_called(); ctl.review.assert_called_once()
        self.assertEqual(ctl.state['cycle_id'],'finished')
        self.assertEqual(ctl.run(),0)
        ctl.review.assert_called_once()

    def test_recovery_rejects_wrong_cycle_and_active_scraper(self):
        for busy, requested in [(False,'old'),(True,'finished')]:
            ctl=self.controller(); ctl.state=None
            ctl.args.command='review'; ctl.args.cycle=requested
            ctl.probe=Mock(return_value={'state_dir':str(self.root),'scraper_busy':busy,
                                       'cycles':[{'id':'finished','status':'Complete'}]})
            ctl.preflight=Mock(); ctl.review=Mock()
            with self.assertRaises(c.Blocked): ctl.run()
            ctl.preflight.assert_not_called(); ctl.review.assert_not_called()

    def test_failed_scraper_never_advances_to_review(self):
        ctl = self.controller()
        ctl.project = self.root
        ctl.python = self.root / ".venv/bin/python"
        ctl.state = {'stage': 'SCRAPE_PENDING', 'before_cycles': ['old']}
        ctl.probe = Mock(side_effect=[{'scraper_busy': False}, {'scraper_busy': False,
            'cycles': [{'id': 'old'}, {'id': 'new', 'status': 'In Progress'}]}])
        ctl.command = Mock(return_value=(1, self.root / 'log'))
        with self.assertRaises(c.Blocked):
            ctl.scrape()
        self.assertEqual(ctl.state['stage'], 'SCRAPING')






    def test_codex_configuration_pins_requested_model_and_effort(self):
        ctl = self.controller()
        ctl.codex = '/codex'
        log = self.root / 'events'
        log.write_text('{"type":"turn.completed"}\n')
        ctl.command = Mock(return_value=(0, log))
        ctl.codex_command('test', 'test')
        argv = ctl.command.call_args.args[0]
        self.assertEqual(argv[argv.index('-m') + 1], 'gpt-5.6-luna')
        self.assertIn('model_reasoning_effort="medium"', argv)
        self.assertIn('read-only', argv)
        self.assertNotIn('--dangerously-bypass-approvals-and-sandbox', argv)

    def test_new_external_cycle_after_preflight_blocks_fresh_launch(self):
        ctl = self.controller()
        ctl.state = {'stage': 'SCRAPE_PENDING', 'before_cycles': ['old']}
        ctl.probe = Mock(return_value={'scraper_busy': False, 'cycles': [{'id': 'old'}, {'id': 'external'}]})
        ctl.command = Mock()
        with self.assertRaises(c.Blocked):
            ctl.scrape()
        ctl.command.assert_not_called()

    def test_pending_uploads_prevent_review_after_bounded_retries(self):
        ctl = self.controller()
        ctl.state = {'stage': 'PUBLISHING', 'cycle_id': 'new'}
        ctl.probe = Mock(return_value={'scraper_busy': False, 'cycles': [{'id': 'new', 'status': 'Complete'}]})
        ctl.helper = Mock(return_value=dict(configured_backend='sqlite', ready=True,
                                           pending_cells=2, pending_rows=2, last_error='', conflicts=4))
        with patch.object(c.time, 'sleep'), self.assertRaises(c.Blocked):
            ctl.publish_gate()
        self.assertEqual(ctl.state['stage'], 'PUBLISHING')
        self.assertEqual(ctl.helper.call_count, 5)

    def test_resolved_uploads_allow_review_and_preserve_conflict_report(self):
        ctl = self.controller()
        ctl.state = {'stage': 'PUBLISHING', 'cycle_id': 'new'}
        ctl.probe = Mock(return_value={'scraper_busy': False, 'cycles': [{'id': 'new', 'status': 'Complete'}]})
        good = dict(configured_backend='sqlite', ready=True, pending_cells=0,
                    pending_rows=0, last_error='', conflicts=4)
        ctl.helper = Mock(side_effect=[{**good, 'pending_cells': 1}, {}, good])
        with patch.object(c.time, 'sleep'):
            ctl.publish_gate()
        self.assertEqual(ctl.state['stage'], 'REVIEWING')
        self.assertEqual(ctl.state['scrape_publication']['conflicts'], 4)

    def proof(self):
        return {'run': {'run_id': 'owned-run', 'stage': 1, 'state': 'drained'},
                'started_at': 101,
                'checkpoint': {'run_id': 'owned-run', 'run': {'state': 'drained'},
                    'passes': {'1': {'ready': 0, 'claimed': 0, 'pending_writeback': 0,
                                     'pending_publication': 0, 'upstream_active': [],
                                     'conflicts': 0, 'deferred': 0, 'publication': {}}}}}

    def test_handoff_tells_ai_to_read_live_prompt_and_manage_review(self):
        ctl = self.controller()
        prompt = ctl.handoff_prompt()
        self.assertIn('Read "AI Prompt" in my Google Drive and do a FIRST PASS', prompt)
        self.assertIn(c.PROMPT_ID, prompt)
        self.assertIn('GPT-5.6 Luna with medium reasoning', prompt)
        self.assertIn('You manage the review yourself', prompt)
        self.assertIn('immediately before starting or resuming', prompt)
        self.assertNotIn('<claimed_titles>', prompt)
        self.assertFalse(hasattr(ctl, 'assess'))

    def test_agent_launch_is_one_persistent_task_with_google_tools(self):
        ctl = self.controller(); ctl.codex = '/codex'
        argv = ctl.agent_argv(self.root/'result', self.root/'schema')
        self.assertEqual(argv[argv.index('-m')+1], 'gpt-5.6-luna')
        self.assertIn('model_reasoning_effort="medium"', argv)
        self.assertIn('sandbox_mode="workspace-write"', argv)
        self.assertNotIn('--ignore-user-config', argv)
        self.assertNotIn('--ephemeral', argv)
        self.assertNotIn('--dangerously-bypass-approvals-and-sandbox', argv)

    def test_resume_uses_exact_saved_codex_session(self):
        ctl = self.controller(); ctl.codex='/codex'
        argv = ctl.agent_argv(self.root/'result', self.root/'schema', 'exact-session')
        self.assertIn('resume', argv)
        self.assertEqual(argv[-2:], ['exact-session', '-'])
        self.assertNotIn('--last', argv)
        resume_options = argv[argv.index('resume')+1:]
        for setting in ('sandbox_mode="workspace-write"',
                        'sandbox_workspace_write.network_access=true',
                        'approval_policy="never"', 'model_reasoning_effort="medium"'):
            self.assertIn(setting, resume_options)

    def test_session_recovery_refuses_ambiguous_logs(self):
        self.assertEqual(c.session_id([{'type':'thread.started','thread_id':'one'}]), 'one')
        for events in ([], [{'type':'thread.started','thread_id':i} for i in ('one','two')]):
            with self.assertRaises(c.Blocked): c.session_id(events)

    def test_ai_claim_of_completion_requires_runtime_proof(self):
        result={'state':'DRAINED','run_id':'owned-run','summary':'Finished'}
        owner={'workflow_id':'fixture-workflow','run_id':'owned-run'}
        self.assertEqual(c.verify_completion(result,owner,self.proof(),'fixture-workflow',100), 'DRAINED')
        for key in ('ready','claimed','pending_writeback','pending_publication'):
            proof=self.proof(); proof['checkpoint']['passes']['1'][key]=1
            with self.assertRaises(c.Blocked):
                c.verify_completion(result,owner,proof,'fixture-workflow',100)
        proof=self.proof(); proof['run']['state']='active'
        with self.assertRaises(c.Blocked): c.verify_completion(result,owner,proof,'fixture-workflow',100)

    def test_old_or_wrong_worker_cannot_supply_completion(self):
        result={'state':'DRAINED','run_id':'owned-run','summary':'Finished'}
        owner={'workflow_id':'fixture-workflow','run_id':'owned-run'}
        with self.assertRaises(c.Blocked): c.verify_completion(result,owner,self.proof(),'other-workflow',100)
        with self.assertRaises(c.Blocked): c.verify_completion(result,owner,self.proof(),'fixture-workflow',102)

    def test_exceptions_must_be_reported(self):
        result={'state':'DRAINED','run_id':'owned-run','summary':'Finished'}
        owner={'workflow_id':'fixture-workflow','run_id':'owned-run'}
        proof=self.proof(); proof['checkpoint']['passes']['1']['conflicts']=1
        with self.assertRaises(c.Blocked): c.verify_completion(result,owner,proof,'fixture-workflow',100)
        result['state']='DRAINED_WITH_EXCEPTIONS'
        self.assertEqual(c.verify_completion(result,owner,proof,'fixture-workflow',100), result['state'])

    def test_review_launches_ai_once_and_checks_proof_without_python_batches(self):
        ctl=self.controller(); ctl.codex='/codex'; ctl.python=Path('/python')
        ctl.args.review_timeout=60
        ctl.state={'stage':'REVIEWING','workflow_id':'fixture-workflow','agent_started_at':100}
        prompt_text='FIRST PASS RESCUE PASS '+('policy '*300)
        def command(argv,name,**kwargs):
            if name=='codex-first-pass':
                response=Path(argv[argv.index('-o')+1])
                c.atomic(response,{'state':'DRAINED','run_id':'owned-run','summary':'Finished'})
                c.atomic(ctl.work/'review-owner.json',{'workflow_id':'fixture-workflow','run_id':'owned-run'})
                events=[{'type':'thread.started','thread_id':'session-1'},
                    {'type':'item.completed','item':{'type':'mcp_tool_call','status':'completed',
                        'tool':'google_drive.get_document','result':{'structured_content':{
                            'documentId':c.PROMPT_ID,'body':{'content':[{'textRun':{'content':prompt_text}}]}}}}},
                    {'type':'turn.completed'}]
                kwargs['fixed_output'].write_text('\n'.join(json.dumps(e) for e in events))
                return 0,kwargs['fixed_output']
            self.assertEqual(name,'verify-ai-finish')
            path=ctl.work/'proof.json';c.atomic(path,self.proof());return 0,path
        ctl.command=Mock(side_effect=command)
        ctl.review_command=Mock(side_effect=AssertionError('Python must not drive review batches'))
        ctl.review()
        self.assertEqual(ctl.state['status'],'DRAINED')
        self.assertEqual(ctl.state['codex_session_id'],'session-1')
        self.assertEqual(ctl.command.call_count,2)
        ctl.review_command.assert_not_called()


if __name__ == '__main__':
    unittest.main()
