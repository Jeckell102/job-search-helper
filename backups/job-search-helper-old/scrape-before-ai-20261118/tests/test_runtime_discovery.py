"""Terminal/app PATH parity and precise startup failures; no network or scans."""
import argparse
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from job_search_helper import scrape_first_pass as workflow, launcher


class RuntimeDiscoveryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.python = self.executable('project/.venv/bin/python')
        self.project = self.root/'project'
        self.desktop = self.executable('desktop/resources/codex')
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, {'PATH':str(self.root/'empty-path')}, clear=True).start()
        patch.object(workflow, 'DESKTOP_CODEX_PATHS', (self.desktop,)).start()

    def executable(self, name):
        path = self.root/name; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('#!/bin/sh\nexit 0\n'); path.chmod(0o755)
        return path

    def controller(self, command='run', codex=None):
        return workflow.Controller(argparse.Namespace(project=str(self.project), codex=codex, command=command))

    def test_terminal_without_codex_on_path_finds_installed_desktop_binary(self):
        self.assertEqual(workflow.resolve_codex(), str(self.desktop))
        self.assertEqual(self.controller().python, self.python)

    def test_path_installation_precedes_desktop_fallback(self):
        cli = self.executable('bin/codex')
        os.environ['PATH'] = str(cli.parent)
        self.assertEqual(workflow.resolve_codex(), str(cli))

    def test_explicit_option_precedes_environment_and_path(self):
        explicit = self.executable('explicit/codex')
        env = self.executable('environment/codex')
        cli = self.executable('bin/codex')
        os.environ.update(JOB_SEARCH_CODEX=str(env), PATH=str(cli.parent))
        self.assertEqual(workflow.resolve_codex(str(explicit)), str(explicit))
        self.assertEqual(workflow.resolve_codex(), str(env))

    def test_explicit_relative_path_is_fixed_before_changing_child_directory(self):
        with patch.object(workflow.shutil, 'which', return_value='relative/codex'):
            self.assertEqual(workflow.resolve_codex('relative/codex'), str(Path('relative/codex').absolute()))

    def test_invalid_override_does_not_silently_use_desktop(self):
        for override in (str(self.root/'missing'), str(self.root)):
            with self.subTest(override=override), self.assertRaisesRegex(workflow.Blocked, 'Configured Codex executable'):
                self.controller(codex=override).ai_preflight()
        os.environ['JOB_SEARCH_CODEX'] = str(self.root/'missing')
        with self.assertRaisesRegex(workflow.Blocked, 'JOB_SEARCH_CODEX'): self.controller().ai_preflight()

    def test_nonexecutable_or_broken_desktop_binary_is_rejected(self):
        self.desktop.chmod(0o644)
        with self.assertRaisesRegex(workflow.Blocked, 'Codex CLI was not found'): self.controller().ai_preflight()
        self.desktop.unlink(); self.desktop.symlink_to(self.root/'missing')
        with self.assertRaisesRegex(workflow.Blocked, 'Codex CLI was not found'): self.controller().ai_preflight()

    def test_python_failure_is_distinguished_from_codex_failure(self):
        for missing in (False, True):
            if missing: self.python.unlink()
            else: self.python.chmod(0o644)
            with self.assertRaisesRegex(workflow.Blocked, 'Scraper Python is missing or not executable'):
                self.controller()

    def test_status_still_reads_saved_workflow_without_codex(self):
        self.desktop.unlink()
        ctl = self.controller(command='status')
        ctl.probe = Mock(return_value={'state_dir':str(self.root), 'scraper_busy':False, 'cycles':[]})
        output = io.StringIO()
        with redirect_stdout(output): self.assertEqual(ctl.run(), 0)
        result = json.loads(output.getvalue())
        self.assertIsNone(result['runtime']['codex'])
        self.assertEqual(result['runtime']['python'], str(self.python))

    def test_normal_public_start_defers_codex_and_preserves_worker_options(self):
        with patch.object(workflow, 'HERE', self.project/'src/job_search_helper'), \
             patch.object(workflow.Controller, 'run', autospec=True, return_value=0) as run:
            self.assertEqual(launcher.main(['start', '--fetch-workers', '15']), 0)
        ctl = run.call_args.args[0]
        self.assertIsNone(ctl.codex)
        self.assertEqual(ctl.args.scraper_args, ['--fetch-workers', '15'])
        self.assertEqual(workflow.MODEL, 'gpt-5.6-luna')
        self.assertEqual(workflow.EFFORT, 'medium')

    def test_review_recovery_does_not_replace_a_different_unfinished_workflow(self):
        ctl = self.controller()
        ctl.args.resume = False
        ctl.args.command = 'review'; ctl.args.cycle = 'finished'
        ctl.probe = Mock(return_value={'state_dir':str(self.root), 'scraper_busy':False,
                                      'cycles':[{'id':'finished', 'status':'Complete'}]})
        base = self.root/'scrape-first-pass'; previous = base/'run-previous/workflow.json'
        state = {'stage':'REVIEWING', 'status':'PAUSED_NOT_COMPLETE', 'cycle_id':'older'}
        workflow.atomic(previous, state)
        workflow.atomic(base/'latest.json', {'workflow':str(previous)})
        with self.assertRaisesRegex(workflow.Blocked, r'job-search-helper resume'):
            ctl.run()
        self.assertEqual(json.loads(previous.read_text()), state)
        self.assertEqual(list(base.glob('run-*')), [previous.parent])
