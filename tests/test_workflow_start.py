"""Start creates a new scrape; resume keeps the latest workflow identity."""
import fcntl
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from job_search_helper import launcher, scrape_first_pass as workflow


class WorkflowStartTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.project = self.root/'project'
        python = self.project/'.venv/bin/python'; python.parent.mkdir(parents=True)
        python.write_text('#!/bin/sh\nexit 0\n'); python.chmod(0o755)
        self.base = self.root/'state/scrape-first-pass'
        self.previous = self.base/'run-previous/workflow.json'
        self.saved = dict(workflow_id='run-previous', stage='REVIEWING',
                          status='PAUSED_NOT_COMPLETE', cycle_id='previous-cycle',
                          model=workflow.MODEL, reasoning_effort=workflow.EFFORT,
                          codex_session_id='previous-session', review_run_id='previous-review',
                          scraper_args=['--fetch-workers','5'])
        self.events = []
        self.controllers = []
        self.addCleanup(patch.stopall)
        patch.object(workflow, 'resolve_codex', return_value='/codex').start()
        patch.object(workflow, 'HERE', self.project/'src/job_search_helper').start()
        self.info = {'state_dir':str(self.base.parent), 'scraper_busy':False,
                     'cycles':[{'id':'previous-cycle','status':'Complete'}]}
        patch.object(workflow.Controller, 'probe', return_value=self.info).start()
        patch.object(workflow.Controller, 'announce').start()
        for name, stage in [('preflight', None), ('scrape', 'PUBLISHING'),
                            ('publish_gate', 'REVIEWING'), ('ai_preflight', None), ('review', 'COMPLETE')]:
            def step(ctl, name=name, stage=stage):
                self.events.append(name); self.controllers.append(ctl)
                if stage: ctl.save(stage=stage)
            patch.object(workflow.Controller, name, step).start()
        self.save_previous()

    def save_previous(self):
        workflow.atomic(self.previous, self.saved)
        workflow.atomic(self.base/'latest.json', {'workflow':str(self.previous)})

    def test_start_scrapes_before_review_and_keeps_old_progress(self):
        old = self.previous.read_bytes()
        self.assertEqual(launcher.main(['start','--fetch-workers','15']), 0)
        self.assertEqual(self.events, ['preflight','scrape','publish_gate','ai_preflight','review'])
        ctl = self.controllers[-1]
        self.assertNotEqual(ctl.state['workflow_id'], self.saved['workflow_id'])
        self.assertEqual(ctl.state['scraper_args'], ['--fetch-workers','15'])
        self.assertEqual(ctl.state['previous_workflow'], str(self.previous))
        self.assertNotIn('codex_session_id', ctl.state)
        self.assertNotIn('review_run_id', ctl.state)
        self.assertEqual(self.previous.read_bytes(), old)
        self.assertEqual(json.loads((self.base/'latest.json').read_text())['workflow'],
                         str(ctl.work/'workflow.json'))

    def test_resume_spellings_continue_the_saved_review_without_scraping(self):
        for args in (['resume'], ['-resume'], ['start','--resume']):
            with self.subTest(args=args):
                self.save_previous(); self.events.clear()
                self.assertEqual(launcher.main(args), 0)
                self.assertEqual(self.events, ['ai_preflight','review'])
                ctl = self.controllers[-1]
                for key in ('workflow_id','codex_session_id','review_run_id','cycle_id'):
                    self.assertEqual(ctl.state[key], self.saved[key])

    def test_resume_a_saved_scrape_runs_scan_before_review(self):
        self.saved['stage'] = 'SCRAPING'; self.save_previous()
        self.assertEqual(launcher.main(['resume']), 0)
        self.assertEqual(self.events, ['scrape','publish_gate','ai_preflight','review'])

    def test_start_after_completion_is_fresh_but_resume_is_noop(self):
        self.saved['stage'] = 'COMPLETE'; self.save_previous()
        self.assertEqual(launcher.main(['resume']), 0)
        self.assertEqual(self.events, [])
        self.assertEqual(launcher.main(['start']), 0)
        self.assertEqual(self.events, ['preflight','scrape','publish_gate','ai_preflight','review'])

    def test_active_controller_or_scraper_blocks_new_start_without_replacing_state(self):
        old = (self.base/'latest.json').read_bytes()
        with (self.base/'controller.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(launcher.main(['start']), 1)
        self.info['scraper_busy'] = True
        self.assertEqual(launcher.main(['start']), 1)
        self.assertEqual(self.events, [])
        self.assertEqual((self.base/'latest.json').read_bytes(), old)

    def test_failed_new_preflight_never_launches_or_resumes_a_review(self):
        with patch.object(workflow.Controller, 'preflight', side_effect=workflow.Blocked('preflight failed')):
            self.assertEqual(launcher.main(['start']), 1)
        self.assertEqual(self.events, [])
        self.assertEqual(json.loads(self.previous.read_text()), self.saved)
        latest = Path(json.loads((self.base/'latest.json').read_text())['workflow'])
        state = json.loads(latest.read_text())
        self.assertNotEqual(latest, self.previous)
        self.assertEqual(state['stage'], 'PREFLIGHT')
        self.assertEqual(state['status'], 'PAUSED_NOT_COMPLETE')
