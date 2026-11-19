"""M3 outcomes enter the existing coordinator without dispatching work."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'src'))
from coordinator_store import Store, canonical_scrape_outcome


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


if __name__ == '__main__':
    unittest.main()
