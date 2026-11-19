import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from coordinator_outcome_delivery import drain
from coordinator import Coordinator as LiveCoordinator
from coordinator_repair_profiles import select_profile
from job_search_helper.sqlite_repository import SQLiteRepository


class Repository:
    def __init__(self, records):
        self.records = list(records)
        self.acknowledged = []

    def pending_scrape_outcomes(self, consumer, *, limit):
        return self.records[:limit]

    def acknowledge_scrape_outcome(self, outcome_id, consumer):
        self.acknowledged.append((outcome_id, consumer))
        self.records = [item for item in self.records if item['outcome_id'] != outcome_id]


class Coordinator:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, []

    def command(self, value):
        self.calls.append(value)
        if self.error:
            raise self.error
        return self.result


class OutcomeDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.record = {'outcome_id': 'OUT-1', 'outcome': 'QUALIFIED_INTEGRATION_REPAIR'}

    def test_acknowledges_only_matching_successful_receipt(self):
        repository = Repository([self.record])
        coordinator = Coordinator({'ok': True, 'outcome_id': 'OUT-1', 'status': 'HELD_FOR_REPAIR_TRIAGE'})
        result = drain(repository, coordinator, consumer='test-consumer')
        self.assertEqual(repository.acknowledged, [('OUT-1', 'test-consumer')])
        self.assertEqual(result['remaining'], 0)

    def test_rejection_or_exception_leaves_record_pending(self):
        for coordinator in (Coordinator({'ok': False, 'outcome_id': 'OUT-1'}),
                            Coordinator({'ok': True, 'outcome_id': 'OUT-other'}),
                            Coordinator(error=RuntimeError('unavailable'))):
            with self.subTest(coordinator=coordinator.result):
                repository = Repository([self.record])
                with self.assertRaises(RuntimeError):
                    drain(repository, coordinator, consumer='test-consumer')
                self.assertEqual(repository.acknowledged, [])
                self.assertEqual(repository.records, [self.record])

    def test_rejects_boolean_limit(self):
        with self.assertRaisesRegex(ValueError, 'limit'):
            drain(Repository([]), Coordinator({}), consumer='test-consumer', limit=True)


class DurableQualifiedDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repository = SQLiteRepository(Path(self.temp.name) / 'jobs.sqlite3', 'test-sheet', initialize=True)
        self.addCleanup(self.repository.close)
        self.facts = {
            'request_id': 'company-event:CEV-1', 'company_id': 'COMP-0001',
            'source_revision': 'rev-1', 'provider': 'greenhouse', 'adapter_version': 'adapter-1',
            'source_current': True, 'company_status': 'Active', 'storage_status': 'confirmed',
            'inventory_status': 'partial', 'capability': 'qualified',
            'failure': {'category': 'adapter_regression'},
        }

    def test_normal_durable_delivery_preserves_category_for_profile_selection(self):
        self.repository.record_scrape_outcome(self.facts)
        seen = []
        coordinator = LiveCoordinator(base=Path(self.temp.name) / 'coordinator',
            repair_profile_selector=lambda held: seen.append(held['outcome'].get('repair_category')) or None)
        receipt = drain(self.repository, coordinator, consumer='test-consumer')
        self.assertEqual(receipt['remaining'], 0)
        self.assertEqual(seen, [])  # Selection is a separate explicit M4 action.
        held = coordinator.store.held_repair_intake()[0]
        self.assertEqual(held['outcome']['repair_category'], 'adapter_regression')
        proposal = select_profile(held, {
            'company_id': 'COMP-0001', 'source_revision': 'rev-1', 'company': 'Acme',
            'official_careers_url': 'https://jobs.example.test/acme'}, profiles=({
                'profile_id': 'acme-greenhouse-v1', 'company_id': 'COMP-0001',
                'provider': 'greenhouse', 'adapter_version': 'adapter-1',
                'failure_category': 'adapter_regression', 'configured_url': 'https://jobs.example.test/acme',
                'tests': ['tests/test_a.py'], 'source_targets': ['src/a.py'], 'max_sessions': 2,
            },))
        self.assertEqual(proposal['profile_id'], 'acme-greenhouse-v1')

    def test_legacy_category_less_record_remains_held_and_readable(self):
        identity = {'request_id': 'REQ-1', 'company_id': 'COMP-0001', 'source_revision': 'rev-1',
                    'provider': 'greenhouse', 'adapter_version': 'adapter-1'}
        fingerprint = 'b' * 64
        outcome_id = 'OUT-' + hashlib.sha256(json.dumps({
            'identity': identity, 'failure_fingerprint': fingerprint,
            'outcome': 'QUALIFIED_INTEGRATION_REPAIR'}, sort_keys=True,
            separators=(',', ':')).encode()).hexdigest()[:24]
        record = {
            'outcome_id': outcome_id, 'outcome': 'QUALIFIED_INTEGRATION_REPAIR',
            'action': 'upsert_qualified_repair',
            'identity': identity, 'failure_fingerprint': fingerprint,
        }
        # This fixture uses the coordinator's historical category-less format;
        # it must stay a safe held record rather than becoming unreadable.
        coordinator = LiveCoordinator(base=Path(self.temp.name) / 'legacy')
        result = coordinator.command({'action': 'ingest-scrape-outcome-record', 'record': record})
        self.assertEqual(result['status'], 'HELD_FOR_REPAIR_TRIAGE')
        self.assertNotIn('repair_category', coordinator.store.held_repair_intake()[0]['outcome'])


if __name__ == '__main__':
    unittest.main()
