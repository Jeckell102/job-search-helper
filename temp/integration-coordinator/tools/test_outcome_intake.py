"""M3 outcomes enter the existing coordinator without dispatching work."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'src'))
from coordinator_store import Store, canonical_scrape_outcome
from coordinator import Coordinator
import test_coordinator as coordinator_fixture


def outcome(**changes):
    identity = {
        'request_id': 'company-event:CEV-1', 'company_id': 'COMP-0001',
        'source_revision': 'rev-1', 'provider': 'greenhouse', 'adapter_version': 'adapter-1',
    }
    identity.update(changes.pop('identity', {}))
    identity = {key: value for key, value in identity.items() if value is not None}
    result = {
        'outcome': 'QUALIFIED_INTEGRATION_REPAIR', 'action': 'upsert_qualified_repair',
        'identity': identity, 'failure_fingerprint': 'a' * 64,
    }
    result.update(changes)
    immutable = {key: result[key] for key in ('identity', 'failure_fingerprint', 'outcome')}
    result['outcome_id'] = 'OUT-' + hashlib.sha256(
        json.dumps(immutable, sort_keys=True, separators=(',', ':')).encode()).hexdigest()[:24]
    return result


def facts(**changes):
    result = {
        'request_id': 'company-event:CEV-1', 'company_id': 'COMP-0001',
        'source_revision': 'rev-1', 'provider': 'greenhouse', 'adapter_version': 'adapter-1',
        'source_current': True, 'company_status': 'Active', 'storage_status': 'confirmed',
        'inventory_status': 'partial', 'capability': 'qualified',
        'failure': {'category': 'adapter_regression'},
    }
    result.update(changes)
    return result


class OutcomeIntakeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        self.coordinator = Coordinator(base=self.temp.name)

    def test_qualified_outcome_creates_one_held_repair_without_a_task(self):
        item = facts()
        first = self.store.ingest_scrape_outcome(item)
        self.assertTrue(first['recorded'])
        self.assertEqual(first['status'], 'HELD_FOR_REPAIR_TRIAGE')
        self.assertFalse(self.store.ingest_scrape_outcome(item)['recorded'])
        held = self.store.held_repair_intake()
        self.assertEqual(len(held), 1)
        self.assertEqual(held[0]['outcome']['outcome'], 'QUALIFIED_INTEGRATION_REPAIR')
        self.assertEqual(self.store.all(), [])

    def test_untrusted_fields_or_identifier_are_rejected(self):
        item = outcome()
        item['identity']['raw_private'] = 'should never enter coordinator storage'
        with self.assertRaisesRegex(ValueError, 'invalid identity'):
            canonical_scrape_outcome(item)
        with self.assertRaisesRegex(ValueError, 'Invalid trusted'):
            self.store.ingest_scrape_outcome(outcome())
        accepted = self.store.ingest_scrape_outcome({
            **facts(), 'outcome': 'FORGED', 'action': 'dispatch-everything',
            'identity': {}, 'outcome_id': 'OUT-forged',
        })
        self.assertEqual(accepted['status'], 'HELD_FOR_REPAIR_TRIAGE')
        self.assertNotEqual(accepted['outcome_id'], 'OUT-forged')

    def test_missing_provider_or_adapter_holds_without_a_repair_key(self):
        item = facts(provider=None)
        result = self.store.ingest_scrape_outcome(item)
        self.assertEqual(result['status'], 'HELD_MISSING_REPAIR_CAPABILITY')
        self.assertIsNone(result['repair_key'])
        self.assertEqual(self.store.held_repair_intake(), [])

    def test_repeated_attempts_attach_evidence_to_one_held_repair(self):
        first = self.store.ingest_scrape_outcome(facts(attempt_id='ATT-1'))
        second = self.store.ingest_scrape_outcome(facts(attempt_id='ATT-2'))
        self.assertTrue(first['recorded'])
        self.assertTrue(second['recorded'])
        self.assertEqual(first['repair_key'], second['repair_key'])
        held = self.store.held_repair_intake()
        self.assertEqual(len(held), 1)
        self.assertEqual(held[0]['evidence_outcome_ids'], sorted([first['outcome_id'], second['outcome_id']]))

    def test_pre_evidence_relation_repair_reads_as_no_attached_evidence(self):
        item = facts()
        result = self.store.ingest_scrape_outcome(item)
        with self.store.connect() as db:
            db.execute('DELETE FROM repair_intake_evidence WHERE repair_key=?', (result['repair_key'],))
        held = self.store.held_repair_intake()
        self.assertEqual(held[0]['evidence_outcome_ids'], [])

    def test_command_intake_holds_a_qualified_repair_without_starting_worker(self):
        result = self.coordinator.command({'action': 'ingest-scrape-outcome', 'facts': facts()})

        self.assertTrue(result['ok'])
        self.assertEqual(result['status'], 'HELD_FOR_REPAIR_TRIAGE')
        self.assertTrue(result['repair_key'])
        self.assertEqual(self.coordinator.store.all(), [])
        self.assertEqual(len(self.coordinator.store.held_repair_intake()), 1)
        self.assertIn('no worker was started', result['text'])

    def test_command_intake_rejects_extra_untrusted_wrapper_fields(self):
        with self.assertRaisesRegex(ValueError, 'exactly action and facts'):
            self.coordinator.command({'action': 'ingest-scrape-outcome', 'facts': facts(), 'start': True})
        self.assertEqual(self.coordinator.store.all(), [])


class HeldRepairPromotionTests(coordinator_fixture.CoordinatorTests):
    def promoted(self):
        repair = self.co.store.ingest_scrape_outcome(facts())
        response = self.co.command({
            'action': 'promote-repair', 'repair_key': repair['repair_key'], 'source_revision': 'rev-1', 'mode': 'develop',
            'objective': 'Develop the bounded Acme wrapper using src/a.py and run tests/test_a.py.',
            'integration': {
                'company_id': 'COMP-0001', 'company': 'Acme', 'configured_url': 'https://jobs.example.test/acme',
                'tests': ['tests/test_a.py'], 'source_targets': ['src/a.py'], 'ats': 'Greenhouse',
            },
        })
        return repair, response

    def test_promotion_creates_one_paused_task_not_a_runnable_task(self):
        repair, response = self.promoted()
        state = self.co.store.get(response['id'])
        self.assertEqual(state['status'], 'PAUSED')
        self.assertTrue(state['stop_requested'])
        self.assertEqual(state['held_repair_key'], repair['repair_key'])
        self.assertEqual(state['repair_provenance']['source_revision'], 'rev-1')
        self.assertIsNone(self.co.store.claim_queued())
        self.assertEqual(self.co.store.held_repair_intake()[0]['task_id'], state['id'])
        self.assertEqual(self.promoted()[1]['id'], state['id'])
        self.assertEqual(len(self.co.store.all()), 1)
        restarted = Store(self.co.store.base)
        restarted.recover()
        self.assertEqual(restarted.get(state['id'])['status'], 'PAUSED')
        self.assertEqual(restarted.held_repair_intake()[0]['task_id'], state['id'])

    def test_promotion_refuses_an_assignment_for_another_company(self):
        repair = self.co.store.ingest_scrape_outcome(facts())
        with self.assertRaisesRegex(ValueError, 'does not match'):
            self.co.command({
                'action': 'promote-repair', 'repair_key': repair['repair_key'], 'source_revision': 'rev-1', 'mode': 'develop',
                'objective': 'Develop another wrapper using src/a.py and run tests/test_a.py.',
                'integration': {
                    'company_id': 'COMP-0002', 'company': 'Other', 'configured_url': 'https://jobs.example.test/other',
                    'tests': ['tests/test_a.py'], 'source_targets': ['src/a.py'], 'ats': 'Greenhouse',
                },
            })

    def test_promotion_refuses_a_stale_source_revision(self):
        repair = self.co.store.ingest_scrape_outcome(facts())
        with self.assertRaisesRegex(ValueError, 'does not match'):
            self.co.command({
                'action': 'promote-repair', 'repair_key': repair['repair_key'], 'source_revision': 'rev-stale', 'mode': 'develop',
                'objective': 'Develop the bounded Acme wrapper using src/a.py and run tests/test_a.py.',
                'integration': {
                    'company_id': 'COMP-0001', 'company': 'Acme', 'configured_url': 'https://jobs.example.test/acme',
                    'tests': ['tests/test_a.py'], 'source_targets': ['src/a.py'], 'ats': 'Greenhouse',
                },
            })
        self.assertEqual(self.co.store.all(), [])

    def test_repeat_promotion_still_refuses_wrong_company_or_revision(self):
        repair, response = self.promoted()
        base = {
            'action': 'promote-repair', 'repair_key': repair['repair_key'], 'mode': 'develop',
            'objective': 'Develop the bounded Acme wrapper using src/a.py and run tests/test_a.py.',
            'integration': {
                'company_id': 'COMP-0001', 'company': 'Acme', 'configured_url': 'https://jobs.example.test/acme',
                'tests': ['tests/test_a.py'], 'source_targets': ['src/a.py'], 'ats': 'Greenhouse',
            },
        }
        with self.assertRaisesRegex(ValueError, 'does not match'):
            self.co.command({**base, 'source_revision': 'rev-stale'})
        with self.assertRaisesRegex(ValueError, 'does not match'):
            self.co.command({**base, 'source_revision': 'rev-1', 'integration': {
                **base['integration'], 'company_id': 'COMP-0002', 'company': 'Other',
            }})
        self.assertEqual(self.co.store.get(response['id'])['status'], 'PAUSED')

    def test_promoted_repair_needs_authoritative_current_company_revision_before_resume(self):
        repair, response = self.promoted()
        with self.assertRaisesRegex(ValueError, 'authoritative current Company revision'):
            self.co.command({'action': 'resume', 'id': response['id']})
        self.assertEqual(self.co.store.get(response['id'])['status'], 'PAUSED')
        self.co.store.company_revision_resolver = lambda company_id: 'rev-1'
        self.co.command({'action': 'resume', 'id': response['id']})
        self.assertEqual(self.co.store.get(response['id'])['status'], 'QUEUED')

    def test_stale_promoted_repair_cannot_resume_or_be_claimed(self):
        repair, response = self.promoted()
        self.co.store.company_revision_resolver = lambda company_id: 'rev-newer'
        with self.assertRaisesRegex(ValueError, 'authoritative current Company revision'):
            self.co.command({'action': 'resume', 'id': response['id']})
        self.co.store.update(response['id'], status='QUEUED', stop_requested=False)
        self.assertIsNone(self.co.store.claim_queued(response['id']))
        state = self.co.store.get(response['id'])
        self.assertEqual(state['status'], 'PAUSED')
        self.assertTrue(state['stop_requested'])
        self.assertIn('no longer current', state['reason'])

    def test_stale_promoted_repair_cannot_bypass_freshness_with_direct_step(self):
        repair, response = self.promoted()
        self.co.store.company_revision_resolver = lambda company_id: 'rev-newer'
        self.co.store.update(response['id'], status='QUEUED', stop_requested=False)
        self.co.step(response['id'])
        state = self.co.store.get(response['id'])
        self.assertEqual(state['status'], 'PAUSED')
        self.assertTrue(state['stop_requested'])
        self.assertEqual(self.co.store.receipts(response['id']), [])


if __name__ == '__main__':
    unittest.main()
