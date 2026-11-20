"""Offline proof that the accepted sender and isolated receiver interoperate."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from coordinator import Coordinator
from coordinator_store import OUTCOME_DELIVERY_CONSUMER
from job_search_helper.scrape_outcome_delivery import OutcomeDelivery
from job_search_helper.sqlite_repository import SQLiteRepository


def facts(**changes):
    value = {
        'request_id': 'REQ-1', 'company_id': 'COMP-0001',
        'source_revision': 'rev-1', 'cycle_id': 'CYC-1',
        'provider': 'greenhouse', 'adapter_version': 'adapter-v1',
        'source_current': True, 'company_status': 'Active',
        'storage_status': 'confirmed', 'inventory_status': 'partial',
        'capability': 'qualified',
        'failure': {'category': 'adapter_regression'},
    }
    value.update(changes)
    return value


class ReceiverSink:
    def __init__(self, coordinator, *, lose_first_response=False):
        self.coordinator = coordinator
        self.lose_first_response = lose_first_response
        self.calls = 0

    def ingest_immutable(self, record):
        self.calls += 1
        response = self.coordinator.command({
            'action': 'ingest-scrape-outcome-delivery-v1',
            'consumer': OUTCOME_DELIVERY_CONSUMER,
            'record': record,
        })
        if self.lose_first_response and self.calls == 1:
            raise ConnectionError('simulated lost response after durable receiver commit')
        return response['receipt']


class TwoSidedOutcomeDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.sender = SQLiteRepository(root / 'sender.sqlite3', 'sheet', initialize=True)
        self.addCleanup(self.sender.close)
        self.receiver = Coordinator(base=root / 'receiver')
        self.now = [1000.0]

    def record(self, **changes):
        return self.sender.record_scrape_outcome(facts(**changes))['outcome']

    def mapping_record(self, **changes):
        source = facts(
            provider='rippling', adapter_version='shared-v1', capability='sealed',
            failure={'category': 'same_provider_source_mapping'},
            capability_id='rippling-shared-v1', capability_digest='a' * 64,
            mapping_digest='b' * 64, configuration_digest='c' * 64)
        source.update(changes)
        return self.sender._record_scrape_outcome(source)['outcome']

    def test_exact_sender_record_is_received_and_acknowledged_once(self):
        record = self.record(provider='grünhaus')
        sink = ReceiverSink(self.receiver)
        result = OutcomeDelivery(
            self.sender, sink, clock=lambda: self.now[0]).drain(limit=1)
        self.assertEqual(result, [{
            'outcome_id': record['outcome_id'], 'disposition': 'ACCEPTED'}])
        raw = json.dumps(record, ensure_ascii=False, sort_keys=True,
                         separators=(',', ':'))
        digest = hashlib.sha256(raw.encode('utf-8')).hexdigest()
        with self.sender.db:
            sender_receipt = json.loads(self.sender.db.execute(
                'SELECT receipt FROM scrape_outcome_delivery_receipts').fetchone()[0])
        self.assertEqual(sender_receipt['record_sha256'], digest)
        with self.receiver.store.connect() as db:
            receiver_receipt = json.loads(db.execute(
                'SELECT receipt FROM scrape_outcome_delivery_receipts').fetchone()[0])
        self.assertEqual(receiver_receipt, sender_receipt)
        self.assertEqual(len(self.receiver.store.held_repair_intake()), 1)
        self.assertEqual(self.receiver.store.all(), [])

    def test_lost_response_replays_same_receiver_receipt_then_source_acks(self):
        record = self.record()
        sink = ReceiverSink(self.receiver, lose_first_response=True)
        delivery = OutcomeDelivery(self.sender, sink, clock=lambda: self.now[0])
        self.assertEqual(delivery.drain(), [{
            'outcome_id': record['outcome_id'], 'disposition': 'WAITING'}])
        self.assertEqual(self.sender.db.execute(
            'SELECT count(*) FROM scrape_outcome_deliveries').fetchone()[0], 0)
        with self.receiver.store.connect() as db:
            first = db.execute(
                'SELECT receipt FROM scrape_outcome_delivery_receipts').fetchone()[0]
            self.assertEqual(db.execute(
                'SELECT count(*) FROM scrape_outcome_intake').fetchone()[0], 1)
        self.now[0] += 31
        self.assertEqual(delivery.drain(), [{
            'outcome_id': record['outcome_id'], 'disposition': 'ACCEPTED'}])
        with self.receiver.store.connect() as db:
            second = db.execute(
                'SELECT receipt FROM scrape_outcome_delivery_receipts').fetchone()[0]
            self.assertEqual(db.execute(
                'SELECT count(*) FROM scrape_outcome_intake').fetchone()[0], 1)
            self.assertEqual(db.execute(
                'SELECT count(*) FROM repair_intake_evidence').fetchone()[0], 1)
        self.assertEqual(second, first)
        self.assertEqual(sink.calls, 2)

    def test_stale_is_suppressed_locally_and_never_reaches_receiver(self):
        record = self.record(source_current=False, current_source_revision='rev-new')
        sink = ReceiverSink(self.receiver)
        self.assertEqual(OutcomeDelivery(
            self.sender, sink, clock=lambda: self.now[0]).drain(), [{
                'outcome_id': record['outcome_id'],
                'disposition': 'STALE_SUPPRESSED'}])
        self.assertEqual(sink.calls, 0)
        with self.receiver.store.connect() as db:
            self.assertEqual(db.execute(
                'SELECT count(*) FROM scrape_outcome_intake').fetchone()[0], 0)
            self.assertEqual(db.execute(
                'SELECT count(*) FROM scrape_outcome_delivery_receipts').fetchone()[0], 0)

    def test_mapping_tuple_is_top_level_and_distinct_end_to_end_identity(self):
        first = self.mapping_record(request_id='REQ-map-1')
        second = self.mapping_record(request_id='REQ-map-2', configuration_digest='d' * 64)
        sink = ReceiverSink(self.receiver)
        result = OutcomeDelivery(
            self.sender, sink, clock=lambda: self.now[0]).drain(limit=2)
        self.assertEqual({item['outcome_id'] for item in result},
                         {first['outcome_id'], second['outcome_id']})
        for record in (first, second):
            for key in ('capability_id', 'capability_digest', 'mapping_digest',
                        'configuration_digest'):
                self.assertIn(key, record)
                self.assertNotIn(key, record['identity'])
        with self.receiver.store.connect() as db:
            self.assertEqual(db.execute(
                'SELECT count(*) FROM scrape_outcome_delivery_receipts').fetchone()[0], 2)
            keys = [row[0] for row in db.execute(
                'SELECT repair_key FROM repair_intake ORDER BY repair_key').fetchall()]
        self.assertEqual(len(keys), 2)
        self.assertNotEqual(keys[0], keys[1])


if __name__ == '__main__':
    unittest.main()
