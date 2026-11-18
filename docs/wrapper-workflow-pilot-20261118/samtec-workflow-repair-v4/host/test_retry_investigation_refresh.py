"""Explicit retry evidence refresh cannot broaden the pinned company scope."""
import copy
import tempfile
import unittest
from coordinator_store import Store, task_state_digest
from coordinator_identity import validate_bound_identity

class RetryInvestigationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)
        self.store.configure_queue(False)
        requirements = {'required_files': ['tests/test_a.py', 'src/a.py'],
            'source_targets': [{'url': 'https://example.com/careers',
                'allowed_urls': ['https://example.com/careers', 'https://jobs.example.com/a'],
                'identity_terms': ['Company A']}], 'read_hints': {'src/a.py': [9]}, 'sentinel': 'preserve'}
        spec = dict(objective='Repair Company A', tests=['tests/test_a.py'], mode='develop',
            max_sessions=10, authorization_version=1, evidence_requirements=requirements,
            workflow_version=2, integration=dict(company_id='COMP-0001', company='Company A',
                configured_url='https://example.com/careers', tests=['tests/test_a.py'], source_targets=['src/a.py']))
        self.task = self.store.enqueue_batch('refresh', [spec], held=True)[0][0]
        self.store.update(self.task, calls=4, tokens=23100, sessions=2)
        self.before = self.store.get(self.task)
        self.target = {'url': 'https://jobs.example.com/a', 'allowed_urls': ['https://jobs.example.com/a'],
            'identity_terms': ['Company A'], 'purpose': 'configured_listing'}

    def retry(self, targets=None, digest=None):
        return self.store.retry_campaign_task(self.task,
            investigation_targets=[self.target] if targets is None else targets,
            expected_state_digest=task_state_digest(self.before) if digest is None else digest)

    def test_valid_refresh_rebinds_successor_preserving_history_and_original_requirements(self):
        receipts = self.store.receipts(self.task)
        successor = self.retry()
        self.assertEqual(self.store.get(self.task), self.before)
        self.assertEqual(self.store.receipts(self.task), receipts)
        self.assertEqual([self.before[k] for k in ('calls', 'tokens', 'sessions')], [4, 23100, 2])
        expected = copy.deepcopy(self.before['evidence_requirements'])
        expected['investigation_targets'] = [self.target]
        self.assertEqual(successor['evidence_requirements'], expected)
        self.assertNotEqual(successor['evidence_requirements_digest'], self.before['evidence_requirements_digest'])
        for key in ('assignment_baseline', 'acceptance_baseline_manifest', 'integration', 'tests', 'max_sessions'):
            self.assertEqual(successor[key], self.before[key])
        self.assertEqual(successor['retry_of'], self.task)
        self.assertEqual(successor['calls'], 0)  # Existing explicit successor budget policy.
        validate_bound_identity(successor)
        with self.store.connect() as db:
            self.store._require_current_identity(db, successor)

    def test_unknown_url_identity_fields_and_duplicate_rejected_atomically(self):
        for update in ({'url': 'https://evil.example/a', 'allowed_urls': ['https://evil.example/a']},
                       {'identity_terms': ['Other company']}, {'extra': True},
                       {'allowed_urls': ['https://jobs.example.com/a', 'https://evil.example']},
                       {'purpose': 'anything'}, {'url': 'http://jobs.example.com/a'},
                       {'url': 'https://127.0.0.1/a'}):
            target = dict(self.target, **update)
            with self.subTest(update=update), self.assertRaises(ValueError):
                self.retry([target])
            self.assertEqual(self.store.get(self.task), self.before)
            self.assertEqual(len(self.store.all()), 1)
        with self.assertRaises(ValueError):
            self.retry([self.target, self.target])

    def test_stale_or_missing_digest_rejected(self):
        with self.assertRaises(ValueError):
            self.retry(digest='0' * 64)
        with self.assertRaises(ValueError):
            self.store.retry_campaign_task(self.task, investigation_targets=[self.target])
        self.store.update(self.task, tokens=23101)
        with self.assertRaises(ValueError):
            self.retry()
        self.assertEqual(len(self.store.all()), 1)

    def test_active_controls_still_reject_refresh(self):
        self.store.configure_queue(True)
        with self.assertRaisesRegex(ValueError, 'Stop queue'):
            self.retry()
        self.assertEqual(len(self.store.all()), 1)

    def test_default_retry_preserves_requirements(self):
        successor = self.store.retry_campaign_task(self.task)
        self.assertEqual(successor['evidence_requirements'], self.before['evidence_requirements'])
        self.assertEqual(self.store.get(self.task), self.before)

if __name__ == '__main__':
    unittest.main()
