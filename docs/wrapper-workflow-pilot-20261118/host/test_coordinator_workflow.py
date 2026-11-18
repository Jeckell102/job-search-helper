"""Version-2 workflow acceptance: actual tools, isolated files, simulated inference."""
import copy
import json
import time
import unittest
from unittest.mock import patch

import coordinator as c
import coordinator_workflow as w
from coordinator_evidence import source_receipts
import test_coordinator as fixture


class WorkflowTests(unittest.TestCase):
    checkpoint = fixture.CoordinatorTests.checkpoint

    def setUp(self):
        fixture.CoordinatorTests.setUp(self)
        self.co.workflow_version = 2

    def task(self, mode='review', source=''):
        return self.co.command({'action': 'start', 'mode': mode,
                                'objective': f'Inspect src/a.py. Run tests/test_a.py. {source}'})['id']

    def collect(self, task):
        self.co.step(task)
        for _ in range(30):
            state = self.co.store.get(task)
            if not w.plan(state, self.co.store.receipts(task), c.manifest(), self.root)['next']:
                return
            self.co.step(task)
            self.assertEqual(self.co.store.get(task)['status'], 'QUEUED')
        self.fail('Host preparation did not terminate')

    def test_host_collects_files_without_model_then_review_and_tests(self):
        task = self.task()
        self.collect(task)
        state = self.co.store.get(task)
        self.assertEqual((state['calls'], state['tokens'], state['sessions']), (0, 0, 0))
        self.assertEqual(self.history, [])
        self.answers = [self.checkpoint('phase_done')]
        self.co.step(task)
        self.co.step(task)
        self.assertEqual(self.co.store.get(task)['status'], 'REVIEW_COMPLETE_LIVE_NOT_VALIDATED')
        self.assertEqual(sum(r['name'] == 'code_test' for r in self.co.store.receipts(task)), 2)

    def test_host_renders_shell_once_and_blocks_without_model_loop(self):
        task = self.task(source='https://example.org/careers')
        shell = {'ok': True, 'result': {'status': 200, 'url': 'https://example.org/careers', 'text': 'Enable JavaScript to run this app.'}}
        with patch.object(c.web, 'execute', return_value=shell) as web:
            for _ in range(8):
                self.co.step(task)
                if self.co.store.get(task)['status'] == 'PAUSED_BLOCKED':
                    break
        self.assertEqual(self.co.store.get(task)['status'], 'PAUSED_BLOCKED')
        self.assertEqual(web.call_count, 2)
        self.assertEqual(self.history, [])

    def test_development_uses_guarded_edit_and_host_diff_before_verification(self):
        task = self.task('develop')
        self.collect(task)
        self.answers = [self.checkpoint('phase_done')]
        self.co.step(task)
        self.co.step(task)  # Python collects implementation read.
        self.answers = [fixture.response('code_edit', {'path': 'src/a.py', 'sha256': c.manifest()['src/a.py'], 'old': '1', 'new': '2'}), self.checkpoint('phase_done')]
        self.co.step(task)
        self.assertEqual(self.co.store.get(task)['phase'], 'implement')
        self.co.step(task)  # reread changed implementation file
        self.git.return_value = 'diff --git a/src/a.py b/src/a.py\n+value = 2\n'
        self.co.step(task)  # host diff
        self.assertEqual(self.co.store.get(task)['phase'], 'verify')
        self.co.step(task)
        self.assertEqual(self.co.store.get(task)['status'], 'AWAITING_LIVE_VALIDATION')
        self.assertEqual((self.root / 'src/a.py').read_text(), 'value = 2\n')
        self.assertTrue(all(len(h) == 2 for h in self.history))

    def test_development_empty_diff_cannot_reach_verification(self):
        task = self.task('develop')
        self.collect(task)
        self.answers = [self.checkpoint('phase_done')]
        self.co.step(task)
        self.co.step(task)  # implementation read
        self.answers = [self.checkpoint('phase_done')]
        self.co.step(task)
        self.co.step(task)  # host diff gate
        state = self.co.store.get(task)
        self.assertEqual(state['status'], 'PAUSED_BLOCKED')
        self.assertEqual(state['phase'], 'implement')
        self.assertIn('No development change exists', state['reason'])

    def test_repeated_cached_reads_stop_without_new_receipts(self):
        task = self.task()
        self.collect(task)
        before = len(self.co.store.receipts(task))
        read = fixture.response('code_read', {'path': 'src/a.py', 'start_line': 1})
        self.answers = [read, read, self.checkpoint()]
        self.co.step(task)
        self.answers = [read]
        self.co.step(task)
        self.assertEqual(self.co.store.get(task)['status'], 'PAUSED_BLOCKED')
        self.assertEqual(len(self.co.store.receipts(task)), before)
        packet = json.loads(self.history[1][1]['content'])
        self.assertEqual(packet['evidence'][0]['arguments']['path'], 'src/a.py')

    def test_restart_reuses_completed_actions_and_preserves_counters(self):
        task = self.task()
        self.co.step(task)
        self.co.step(task)
        receipts = self.co.store.receipts(task)
        old = self.co.store.get(task)
        self.co = c.Coordinator(self.co.store.base, self.co.model, self.co.budget)
        self.co.step(task)
        new = self.co.store.receipts(task)
        self.assertEqual(new[:len(receipts)], receipts)
        self.assertNotEqual(new[-1]['arguments'], receipts[-1]['arguments'])
        self.assertEqual(self.co.store.get(task)['created'], old['created'])

    def test_external_changes_invalidate_reads_without_resetting_action_budget(self):
        task = self.task()
        self.collect(task)
        old = self.co.store.get(task)
        (self.root / 'src/a.py').write_text('value = 3\n')
        self.co.step(task)
        self.assertEqual(self.co.store.get(task)['status'], 'PAUSED_FILES_CHANGED')
        self.co.command({'action': 'resume', 'id': task})
        new = self.co.store.get(task)
        self.assertEqual(new['workflow']['automatic_actions'], old['workflow']['automatic_actions'])
        for name in ('tokens', 'calls', 'created', 'sessions'):
            self.assertEqual(new[name], old[name])
        self.co.step(task)
        next_step = w.plan(self.co.store.get(task), self.co.store.receipts(task), c.manifest(), self.root)['next']
        self.assertEqual(next_step['arguments']['path'], 'src/a.py')

    def test_pending_action_survives_restart_without_replay(self):
        task = self.task('develop')
        self.co.store.update(task, status='RUNNING')
        self.co.store.intent(task, 'implement', 'code_edit', {'path': 'src/a.py'})
        recovered = c.Coordinator(self.co.store.base, self.co.model, self.co.budget)
        self.assertEqual(recovered.store.get(task)['status'], 'PAUSED_RECOVERY')

    def test_multiple_returned_tools_are_never_partially_executed(self):
        task = self.task()
        self.collect(task)
        answer = fixture.response('code_read', {'path': 'src/a.py'})
        answer['message']['tool_calls'] *= 2
        self.answers = [answer]
        before = len(self.co.store.receipts(task))
        self.co.step(task)
        self.assertEqual(self.co.store.get(task)['status'], 'PAUSED_BLOCKED')
        self.assertEqual(len(self.co.store.receipts(task)), before)

    def test_total_token_limit_is_preserved_across_fresh_contexts(self):
        task = self.task()
        self.collect(task)
        self.co.store.update(task, tokens=c.MAX_TOKENS - 100)
        self.co.step(task)
        self.assertEqual(self.co.store.get(task)['status'], 'PAUSED_BUDGET')
        self.assertEqual(self.history, [])

    def test_auto_action_limit_and_expired_deadline_prevent_dispatch(self):
        task = self.task()
        self.co.step(task)
        self.co.store.update(task, workflow={'automatic_actions': w.MAX_AUTOMATIC_ACTIONS})
        count = len(self.co.store.receipts(task))
        self.co.step(task)
        self.assertEqual(self.co.store.get(task)['status'], 'PAUSED_BUDGET')
        self.assertEqual(len(self.co.store.receipts(task)), count)
        self.co.store.update(task, activated_at=time.time() - c.MAX_SECONDS - 1, workflow={})
        self.co.step(task)
        self.assertEqual(len(self.co.store.receipts(task)), count)


class ProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.now = time.time()
        self.target = {'url': 'https://old.example/jobs/scythe', 'allowed_urls': ['https://old.example/jobs/scythe'], 'identity_terms': ['Scythe Robotics']}
        self.old = self.receipt(1, 'web_read', self.target['url'], 'https://new.example/scythe', 'Enable JavaScript to run this app.')
        self.render = self.receipt(2, 'rendered_web_read', 'https://new.example/scythe', 'https://new.example/scythe', 'Scythe Robotics Careers. No positions available at this time.')

    def receipt(self, ident, name, requested, final, text):
        return {'id': ident, 'created': self.now, 'phase': 'inspect', 'name': name,
                'arguments': {'url': requested}, 'result': {'ok': True, 'result': {'url': final, 'status': 200, 'text': text}}}

    def test_observed_redirect_links_two_real_results(self):
        self.assertEqual(source_receipts(self.target, [self.old, self.render], self.now), [1, 2])
        self.assertEqual(source_receipts(self.target, [self.render], self.now), [])

    def test_identity_shell_failure_unrelated_stale_and_future_fail_closed(self):
        for key, value in [('text', 'Another Employer Careers. No positions available at this time.'), ('text', 'Enable JavaScript to run this app.'), ('status', 503), ('url', 'https://elsewhere.example/other')]:
            bad = copy.deepcopy(self.render); bad['result']['result'][key] = value
            self.assertEqual(source_receipts(self.target, [self.old, bad], self.now), [])
        for offset in (-1801, 60):
            bad = copy.deepcopy(self.old); bad['created'] += offset
            self.assertEqual(source_receipts(self.target, [bad, self.render], self.now), [])

    def test_overlapping_lines_are_not_new_progress(self):
        def read(ident, start, text):
            return {'id': ident, 'name': 'code_read', 'arguments': {'path': 'src/a.py', 'start_line': start},
                    'result': {'ok': True, 'result': {'sha256': 'hash', 'text': text}}}
        a = read(1, 1, '1: a\n2: b\n3: c')
        b = read(2, 2, '2: b\n3: c')
        self.assertEqual(w.progress_key([a], {'src/a.py': 'hash'}), w.progress_key([a, b], {'src/a.py': 'hash'}))


if __name__ == '__main__':
    unittest.main()
