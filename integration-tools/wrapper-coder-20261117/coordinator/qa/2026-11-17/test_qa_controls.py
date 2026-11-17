"""Adversarial QA of installed coordinator controls. No live tasks or inference.

Run: python3 -B test_qa_controls.py --tools /path/to/wrapper-coder/tools
These assertions express required behavior; failures reproduce the QA findings.
All files, tasks, edits and receipts use TemporaryDirectory fixtures.
"""
import argparse
import json
from pathlib import Path
import sys
import threading
import time
import types
import unittest
from unittest.mock import patch

parser = argparse.ArgumentParser()
parser.add_argument('--tools', required=True)
options, remaining = parser.parse_known_args()
sys.path.insert(0, str(Path(options.tools).resolve()))
import coordinator as c
import test_coordinator as fixture


class QAControls(unittest.TestCase):
    setUp = fixture.CoordinatorTests.setUp
    task = fixture.CoordinatorTests.task
    checkpoint = fixture.CoordinatorTests.checkpoint

    def test_explicit_do_not_modify_must_not_enable_or_perform_edits(self):
        task = self.task('Review src/a.py; do not modify any files. Run tests/test_a.py.')
        self.co.step(task)
        self.answers = [fixture.response('code_read', {'path': 'src/a.py'}), self.checkpoint('phase_done')]
        self.co.step(task)
        self.answers = [fixture.response('code_read', {'path': 'src/a.py'}),
                        fixture.response('code_edit', {'path': 'src/a.py', 'sha256': c.manifest()['src/a.py'], 'old': '1', 'new': '2'}),
                        fixture.response('code_diff', {}), self.checkpoint('phase_done')]
        self.co.step(task)
        observed = {'mode': self.co.store.get(task)['mode'], 'file': (self.root / 'src/a.py').read_text()}
        self.assertEqual(observed, {'mode': 'review', 'file': 'value = 1\n'})

    def test_empty_unrelated_search_and_protocol_read_cannot_satisfy_inspection(self):
        task = self.task('Review src/a.py using https://example.com/company. Run tests/test_a.py.')
        self.co.step(task)
        self.answers = [fixture.response('code_read', {'path': 'docs/wrapper-development-test-protocol.md'}),
                        fixture.response('web_search', {'query': 'unrelated weather'}), self.checkpoint('phase_done')]
        with patch.object(c.web, 'execute', return_value={'ok': True, 'result': {'results': []}}):
            self.co.step(task)
        phase = self.co.store.get(task)['phase']
        if phase == 'verify':
            self.co.step(task)
        state = self.co.store.get(task)
        self.assertEqual((state['phase'], state['status']), ('inspect', 'QUEUED'))

    def test_snapshot_write_error_must_not_kill_scheduler_thread(self):
        task = self.task()
        uncaught = []
        with patch.object(self.co.store, 'export', side_effect=OSError('QA simulated snapshot write failure')):
            with patch.object(threading, 'excepthook', side_effect=lambda args: uncaught.append(type(args.exc_value).__name__)):
                self.co.start()
                self.co.thread.join(timeout=1)
                alive = self.co.thread.is_alive()
                state = self.co.store.get(task)
                self.co.stop.set()
                self.co.wake.set()
                self.co.thread.join(timeout=2)
        self.assertEqual({'alive': alive, 'uncaught': uncaught, 'status': state['status']},
                         {'alive': True, 'uncaught': [], 'status': 'QUEUED'})

    def test_render_timing_alone_must_not_count_as_progress(self):
        task = self.task('Review src/a.py at https://example.com/company. Run tests/test_a.py.')
        self.co.step(task)
        for seconds in (1.0, 1.1, 1.2, 1.3):
            self.answers = [fixture.response('rendered_web_read', {'url': 'https://example.com/company'}), self.checkpoint()]
            with patch.object(c.web, 'execute', return_value={'ok': True, 'result': {
                    'url': 'https://example.com/company', 'status': 200, 'text': 'same evidence',
                    'links': [], 'render_seconds': seconds}}):
                self.co.step(task)
        state = self.co.store.get(task)
        self.assertEqual((state['status'], state['no_progress']), ('PAUSED_NO_PROGRESS', 3))

    def test_dispatch_must_reserve_remaining_total_tokens(self):
        task = self.task()
        self.co.step(task)
        self.co.store.update(task, tokens=c.MAX_TOKENS - 1)
        self.co.budget = lambda m, s: types.SimpleNamespace(available_generation_tokens=6000, prompt_tokens=500)
        self.answers = [self.checkpoint()]
        self.co.step(task)
        state = self.co.store.get(task)
        self.assertEqual({'model_calls': len(self.history), 'tokens': state['tokens']},
                         {'model_calls': 0, 'tokens': c.MAX_TOKENS - 1})

    def test_elapsed_deadline_must_stop_next_call_inside_a_session(self):
        task = self.task()
        self.co.step(task)
        created = self.co.store.get(task)['created']
        now = [created + 1]
        calls = []
        def model(messages, schemas, limit):
            calls.append(1)
            if len(calls) == 1:
                now[0] = created + c.MAX_SECONDS + 1
                return fixture.response('code_read', {'path': 'src/a.py'})
            return self.checkpoint()
        self.co.model = model
        with patch.object(c.time, 'time', side_effect=lambda: now[0]):
            self.co.step(task)
        self.assertEqual(len(calls), 1, 'No further inference should start after the deadline.')


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0], *remaining], verbosity=2)
