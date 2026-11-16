import argparse
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import controller as c


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
        ctl.state = {'stage': 'REVIEWING', 'review_run_id': 'owned-run'}
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

    def test_claim_tokens_are_copied_from_actual_claim(self):
        output = c.validate_assessments({'assessments': [decision()]}, [claim()])
        self.assertEqual(output[0]['claim_token'], 'token-1')
        self.assertEqual(output[0]['input_version'], 1)

    def test_model_identity_corruption_is_blocked(self):
        bad_batches = [[], [decision('invented')], [decision(), decision()],
                       [{**decision(), 'decision': 'Accept'}], [{**decision(), 'reason': ''}]]
        for rows in bad_batches:
            with self.assertRaises(c.Blocked):
                c.validate_assessments({'assessments': rows}, [claim()])

    def test_changed_or_manual_withdrawn_claim_never_submitted(self):
        rows = c.validate_assessments({'assessments': [decision()]}, [claim()])
        self.assertEqual(c.reconcile(rows, []), [])
        self.assertEqual(c.reconcile(rows, [claim(token='replacement')]), [])
        self.assertEqual(c.reconcile(rows, [claim()]), rows)

    def test_title_input_omits_descriptions_and_practical_fields(self):
        row = {**claim(), 'job_description': 'secret', 'company': 'irrelevant',
               'location': 'irrelevant', 'pay': 123, 'url': 'https://example.com'}
        self.assertEqual(c.title_input(row), {k: v for k, v in claim().items()
                                            if k not in ('claim_token', 'input_version')})

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

    def test_failed_scraper_never_advances_to_review(self):
        ctl = self.controller()
        ctl.project = self.root
        ctl.state = {'stage': 'SCRAPE_PENDING', 'before_cycles': ['old']}
        ctl.probe = Mock(side_effect=[{'scraper_busy': False}, {'scraper_busy': False,
            'cycles': [{'id': 'old'}, {'id': 'new', 'status': 'In Progress'}]}])
        ctl.command = Mock(return_value=(1, self.root / 'log'))
        with self.assertRaises(c.Blocked):
            ctl.scrape()
        self.assertEqual(ctl.state['stage'], 'SCRAPING')

    def test_full_review_requires_managed_finish(self):
        ctl = self.controller()
        ctl.fetch_prompt = Mock(return_value=('live policy', 'hash'))
        rows = c.validate_assessments({'assessments': [decision()]}, [claim()])
        ctl.assess = Mock(return_value=rows)
        ctl.review_command = Mock(side_effect=[{}, {'items': [claim()]}, {'items': [claim()]},
                                              {'saved': 1}, {'items': []}, {}, {'state': 'DRAINED'}])
        ctl.review()
        self.assertEqual(ctl.state['stage'], 'COMPLETE')
        self.assertEqual([x.args[0] for x in ctl.review_command.call_args_list],
                         ['start', 'next', 'next', 'submit', 'next', 'status', 'finish'])

    def test_manual_change_before_submit_skips_the_job(self):
        ctl = self.controller()
        ctl.fetch_prompt = Mock(return_value=('policy', 'hash'))
        ctl.assess = Mock(return_value=c.validate_assessments({'assessments': [decision()]}, [claim()]))
        ctl.review_command = Mock(side_effect=[{}, {'items': [claim()]}, {'items': []},
                                              {'items': []}, {}, {'state': 'DRAINED'}])
        ctl.review()
        self.assertNotIn('submit', [x.args[0] for x in ctl.review_command.call_args_list])

    def test_empty_queue_with_pending_publication_is_not_complete(self):
        ctl = self.controller()
        ctl.fetch_prompt = Mock(return_value=('policy', 'hash'))
        ctl.review_command = Mock(side_effect=[{}, {'items': []}, {}, {'state': 'WRITEBACK_PENDING'}])
        with self.assertRaises(c.Blocked):
            ctl.review()
        self.assertNotEqual(ctl.state['stage'], 'COMPLETE')

    def test_lost_start_response_never_launches_a_second_worker(self):
        ctl = self.controller()
        ctl.state = {'stage': 'REVIEWING', 'start_attempted': True}
        ctl.fetch_prompt = Mock(return_value=('policy', 'hash'))
        ctl.review_command = Mock()
        with self.assertRaises((OSError, c.Blocked)):
            ctl.review()
        ctl.review_command.assert_not_called()

    def test_saved_start_receipt_recovers_same_run(self):
        ctl = self.controller()
        ctl.state = {'stage': 'REVIEWING', 'start_attempted': True}
        (self.root / 'managed-start.stdout').write_text('{"run_id":"recovered","pass":1}')
        ctl.fetch_prompt = Mock(return_value=('policy', 'hash'))
        ctl.review_command = Mock(side_effect=[{}, {'items': []}, {}, {'state': 'DRAINED_WITH_EXCEPTIONS'}])
        ctl.review()
        self.assertEqual(ctl.state['review_run_id'], 'recovered')
        self.assertEqual(ctl.state['status'], 'DRAINED_WITH_EXCEPTIONS')

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


if __name__ == '__main__':
    unittest.main()
