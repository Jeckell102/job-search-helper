"""Combined acceptance tests for the independently repaired controls."""
import unittest
import coordinator as c
import test_coordinator as fixture


class IntegrationTests(unittest.TestCase):
    setUp = fixture.CoordinatorTests.setUp
    checkpoint = fixture.CoordinatorTests.checkpoint

    def task(self, mode='review'):
        return self.co.command({'action': 'start', 'mode': mode,
                                'objective': 'Inspect and fix src/a.py. Run tests/test_a.py.'})['id']

    def reads(self):
        return [fixture.response('code_read', {'path': 'src/a.py'}),
                fixture.response('code_read', {'path': 'tests/test_a.py'})]

    def test_keyword_fix_never_promotes_default_review_to_develop(self):
        task = self.co.command({'action': 'start', 'objective': 'Review proposed fix in src/a.py; run tests/test_a.py.'})['id']
        self.assertEqual(self.co.store.get(task)['mode'], 'review')

    def test_fresh_worker_after_restart_consumes_saved_evidence(self):
        task = self.task()
        self.co.step(task)
        self.answers = [self.reads()[0], self.checkpoint()]
        self.co.step(task)
        self.assertEqual(self.co.store.get(task)['phase'], 'inspect')
        self.co = c.Coordinator(self.co.store.base, self.co.model, self.co.budget)
        self.answers = [self.reads()[1], self.checkpoint('phase_done')]
        self.co.step(task)
        self.assertEqual(self.co.store.get(task)['phase'], 'verify')
        self.co.step(task)
        state = self.co.store.get(task)
        self.assertEqual(state['status'], 'REVIEW_COMPLETE_LIVE_NOT_VALIDATED')
        self.assertEqual(state['sessions'], 2)
        self.assertEqual(sum(r['name'] == 'code_test' for r in self.co.store.receipts(task)), 2)
        self.assertTrue((self.co.store.base / task / 'HANDOFF.md').exists())

    def test_legacy_develop_task_without_explicit_authorization_stops(self):
        task = self.co.store.create('Fix src/a.py using tests/test_a.py', ['tests/test_a.py'], 'develop')['id']
        self.co.step(task)
        self.assertEqual(self.co.store.get(task)['status'], 'PAUSED_AUTHORIZATION')
        self.assertEqual(self.history, [])

    def test_development_needs_current_diff_after_edit(self):
        task = self.task('develop')
        self.co.step(task)
        self.answers = [*self.reads(), self.checkpoint('phase_done')]
        self.co.step(task)
        self.assertEqual(self.co.store.get(task)['phase'], 'implement')
        self.answers = [*self.reads(), fixture.response('code_diff', {}),
                        fixture.response('code_edit', {'path': 'src/a.py', 'sha256': c.manifest()['src/a.py'], 'old': '1', 'new': '2'}),
                        self.checkpoint('phase_done')]
        self.co.step(task)
        self.assertEqual(self.co.store.get(task)['phase'], 'implement')
        self.answers = [*self.reads(), fixture.response('code_diff', {}), self.checkpoint('phase_done')]
        self.co.step(task)
        self.assertEqual(self.co.store.get(task)['phase'], 'verify')
        self.co.step(task)
        self.assertEqual(self.co.store.get(task)['status'], 'AWAITING_LIVE_VALIDATION')

    def test_resume_after_external_change_requires_new_baseline_and_current_read(self):
        task = self.task()
        self.co.step(task)
        self.answers = [*self.reads(), self.checkpoint('phase_done')]
        self.co.step(task)
        self.assertEqual(self.co.store.get(task)['phase'], 'verify')
        (self.root / 'src/a.py').write_text('value = 3\n')
        self.co.step(task)
        self.assertEqual(self.co.store.get(task)['status'], 'PAUSED_FILES_CHANGED')
        before = self.co.store.get(task)
        self.co.command({'action': 'resume', 'id': task})
        state = self.co.store.get(task)
        self.assertEqual(state['phase'], 'baseline')
        for counter in ('sessions', 'calls', 'tokens', 'created'):
            self.assertEqual(state[counter], before[counter])
        self.co.step(task)
        self.answers = [self.checkpoint('phase_done')]
        self.co.step(task)
        self.assertEqual(self.co.store.get(task)['phase'], 'inspect')
        self.answers = [self.reads()[0], self.checkpoint('phase_done')]
        self.co.step(task)
        self.assertEqual(self.co.store.get(task)['phase'], 'verify')
        self.co.step(task)
        self.assertEqual(self.co.store.get(task)['status'], 'REVIEW_COMPLETE_LIVE_NOT_VALIDATED')


if __name__ == '__main__':
    unittest.main()
