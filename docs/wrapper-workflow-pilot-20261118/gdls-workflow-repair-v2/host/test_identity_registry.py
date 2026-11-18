"""Registry import integrity and immutable assignment regression tests."""
import json
import tempfile
import unittest
from coordinator_store import Store


class IdentityRegistryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)
        self.store.configure_queue(False)

    def spec(self, number=1):
        return dict(objective=f'Historic assignment {number}', tests=['tests/test_a.py'],
                    mode='develop', max_sessions=10, authorization_version=1,
                    evidence_requirements={}, workflow_version=2,
                    integration=dict(company_id=f'COMP-{number:04}', company=f'Company {number}',
                                     configured_url=f'https://example.com/{number}',
                                     tests=['tests/test_a.py'], source_targets=['src/a.py']))

    def test_late_duplicate_rolls_back_earlier_new_company_and_batch(self):
        first = self.store.enqueue_batch('old', [self.spec()], held=True)[0]
        with self.assertRaises(ValueError):
            self.store.enqueue_batch('changed', [self.spec(2), self.spec()], held=True)
        self.assertEqual([s['id'] for s in self.store.all()], first)
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM batches').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM campaign_company_registry').fetchone()[0], 1)

    def test_batch_replay_cannot_redefine_spec_under_same_provenance(self):
        ids = self.store.enqueue_batch('same', [self.spec()], held=True)[0]
        changed = self.spec()
        changed['objective'] = 'Different audited instruction'
        with self.assertRaises(ValueError):
            self.store.enqueue_batch('same', [changed], held=True)
        self.assertEqual([s['id'] for s in self.store.all()], ids)

    def test_superseded_task_cannot_resume_and_replay_cannot_reset_retry(self):
        task = self.store.enqueue_batch('same', [self.spec()], held=True)[0][0]
        self.store.update(task, calls=7, tokens=95)
        before = self.store.get(task)
        retry = self.store.retry_campaign_task(task)
        self.assertEqual(self.store.get(task), before)
        self.assertEqual(retry['retry_of'], task)
        with self.assertRaises(ValueError):
            self.store.resume_campaign_task(task)
        with self.assertRaises(ValueError):
            self.store.enqueue_batch('same', [self.spec()], held=True)
        self.store.configure_campaign(True)
        self.assertEqual(self.store.activate_next_campaign()['id'], retry['id'])
        self.assertEqual(self.store.claim_campaign()['id'], retry['id'])

    def test_mutated_identity_cannot_claim_or_emit_intent(self):
        task = self.store.enqueue_batch('same', [self.spec()], held=True)[0][0]
        self.store.configure_campaign(True)
        self.store.activate_next_campaign()
        state = self.store.get(task)
        state['worker_assignment'] += ' Changed instructions'
        with self.store.connect() as db:
            db.execute('UPDATE tasks SET state=? WHERE id=?', (json.dumps(state), task))
        with self.assertRaises(ValueError):
            self.store.claim_campaign()
        with self.assertRaises(ValueError):
            self.store.active_intent(task, 'inspect', 'code_read', {'path': 'src/a.py'})
        self.assertEqual(self.store.receipts(task), [])


if __name__ == '__main__':
    unittest.main()
