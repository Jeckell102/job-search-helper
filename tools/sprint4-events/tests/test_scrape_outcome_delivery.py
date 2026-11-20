import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from job_search_helper.repository import RepositoryError
from job_search_helper.sqlite_repository import SQLiteRepository
from job_search_helper.scrape_outcome_delivery import OutcomeDelivery, SCHEMA


def facts(**changes):
    value = {
        'request_id': 'REQ-1', 'company_id': 'COMP-1', 'source_revision': 'rev-1',
        'cycle_id': 'CYC-1', 'provider': 'test', 'adapter_version': 'v1',
        'source_current': True, 'company_status': 'Active', 'storage_status': 'confirmed',
        'inventory_status': 'partial', 'capability': 'unknown',
        'failure': {'category': 'unknown'},
    }
    value.update(changes)
    return value


class Sink:
    def __init__(self, receipt=None, exc=False): self.calls, self.receipt, self.exc = [], receipt, exc
    def ingest_immutable(self, record):
        self.calls.append(record)
        if self.exc: raise RuntimeError('private transport detail')
        return self.receipt(record) if callable(self.receipt) else self.receipt


class OutcomeDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.repo = SQLiteRepository(Path(self.temp.name) / 'jobs.db', 'sheet', initialize=True)
        self.addCleanup(self.repo.close)
        self.now = [1000.0]

    def _record(self, **changes):
        return self.repo.record_scrape_outcome(facts(**changes))['outcome']

    def _mapping_record(self, **changes):
        source = facts(
            capability='sealed', failure={'category': 'same_provider_source_mapping'},
            capability_id='rippling-shared-v1', capability_digest='a' * 64,
            mapping_digest='b' * 64, configuration_digest='c' * 64)
        source.update(changes)
        return self.repo._record_scrape_outcome(source)['outcome']

    def _receipt(self, record):
        raw = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        return {'schema': SCHEMA, 'consumer': 'repair-coordinator',
                'outcome_id': record['outcome_id'],
                'record_sha256': hashlib.sha256(raw.encode()).hexdigest(),
                'disposition': 'ACCEPTED', 'sink_receipt_id': 'sink:1',
                'sink_status': 'OBSERVED_HELD'}

    @staticmethod
    def _digest(record):
        raw = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(raw.encode()).hexdigest()

    def test_exact_selected_drain_preserves_the_other_pending_record(self):
        other = self._record(request_id='REQ-OTHER')
        selected = self._record(request_id='REQ-SELECTED')
        sink = Sink(self._receipt)
        delivery = OutcomeDelivery(self.repo, sink, clock=lambda: self.now[0])
        with self.assertRaisesRegex(ValueError, 'Selected outcome ID'):
            delivery.drain(outcome_id='')
        self.assertEqual(delivery.drain(outcome_id='OUT-' + '0' * 24), [])
        self.assertEqual(delivery.drain(outcome_id=selected['outcome_id']),
                         [{'outcome_id': selected['outcome_id'], 'disposition': 'ACCEPTED'}])
        self.assertEqual(delivery.drain(outcome_id=selected['outcome_id']), [])
        self.assertEqual(sink.calls, [selected])
        self.assertEqual(self.repo.pending_scrape_outcomes('repair-coordinator'), [other])

    def test_stale_comparison_is_suppressed_atomically_without_sink(self):
        record = self._record(source_current=False, current_source_revision='rev-now')
        sink = Sink()
        result = OutcomeDelivery(self.repo, sink, clock=lambda: self.now[0]).drain()
        self.assertEqual(result[0]['disposition'], 'STALE_SUPPRESSED')
        self.assertEqual(sink.calls, [])
        self.assertEqual(OutcomeDelivery(self.repo, sink, clock=lambda: self.now[0]).drain(), [])
        row = self.repo.db.execute('SELECT receipt FROM scrape_outcome_delivery_receipts').fetchone()[0]
        self.assertEqual(json.loads(row)['record_sha256'], hashlib.sha256(
            json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest())

    def test_ordinary_company_event_requires_the_current_acknowledged_revision(self):
        from job_search_helper.company_events import BRIDGE_CONSUMER

        self.repo.import_rows('Companies', [(2, {
            'Company ID': 'COMP-1', 'Company': 'Fixture', 'Company Status': 'Active',
        })])

        def update(url):
            return self.repo.mutate_company_with_event({
                'tab': 'Companies', 'identity': {'Company ID': 'COMP-1'},
                'values': {'Official Careers URL': url},
            })['company_event']

        def outcome(event, cycle_id):
            return self.repo._record_scrape_outcome(facts(
                request_id='company-event:' + event['event_id'], company_event_id=event['event_id'],
                cycle_id=cycle_id, source_revision=event['source_revision'],
            ), owned_company_event=True)['outcome']

        board = 'https://jobs.example.test/a'
        original = update(board)
        first = outcome(original, 'CYC-000000000001')
        sink = Sink(self._receipt)
        delivery = OutcomeDelivery(self.repo, sink, clock=lambda: self.now[0])
        held = [{'outcome_id': first['outcome_id'], 'disposition': 'HELD_STALE_COMPANY_EVENT_SOURCE'}]
        self.assertEqual(delivery.drain(outcome_id=first['outcome_id']), held)
        self.repo.acknowledge_company_event(original['event_id'], BRIDGE_CONSUMER)
        update('https://jobs.example.test/b')
        latest = update(board)
        self.assertEqual(original['source_revision'], latest['source_revision'])
        self.repo.acknowledge_company_event(latest['event_id'], BRIDGE_CONSUMER)
        self.assertEqual(delivery.drain(outcome_id=first['outcome_id']), held)
        self.assertEqual(sink.calls, [])
        second = outcome(latest, 'CYC-000000000002')
        self.assertEqual(delivery.drain(outcome_id=second['outcome_id']),
                         [{'outcome_id': second['outcome_id'], 'disposition': 'HELD_ORDINARY_EVENT_SETTLEMENT'}])
        self.assertEqual(sink.calls, [])

    def test_acceptance_is_idempotent_and_invalid_receipt_waits_without_ack(self):
        record = self._record()
        sink = Sink(lambda _record: {'ok': True})
        delivery = OutcomeDelivery(self.repo, sink, clock=lambda: self.now[0])
        self.assertEqual(delivery.drain()[0]['disposition'], 'WAITING')
        self.assertEqual(self.repo.db.execute('SELECT count(*) FROM scrape_outcome_deliveries').fetchone()[0], 0)
        self.now[0] += 31
        sink.receipt = self._receipt
        self.assertEqual(delivery.drain()[0]['disposition'], 'ACCEPTED')
        self.assertEqual(len(sink.calls), 2)
        changes = self.repo.db.total_changes
        self.assertEqual(delivery.drain(), [])
        self.assertEqual(self.repo.db.total_changes, changes)
        self.assertEqual(record['outcome_id'], self.repo.scrape_outcomes()[0]['outcome_id'])

    def test_unexpired_lease_skips_then_expiry_reclaims_same_attempt(self):
        record = self._record()
        sink = Sink(exc=True)
        delivery = OutcomeDelivery(self.repo, sink, clock=lambda: self.now[0])
        delivery.drain()
        row = self.repo.db.execute('SELECT attempt_count,state,next_attempt_at FROM scrape_outcome_delivery_attempts').fetchone()
        self.assertEqual(row[:2], (1, 'WAITING'))
        self.now[0] += 30
        sink.exc = False; sink.receipt = self._receipt
        self.assertEqual(delivery.drain()[0]['disposition'], 'ACCEPTED')
        self.assertEqual(len(sink.calls), 2)

    def test_unexpired_inflight_skips_and_expired_reclaims_without_increment(self):
        record = self._record()
        raw = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        digest = hashlib.sha256(raw.encode()).hexdigest()
        self.repo.db.execute('INSERT INTO scrape_outcome_delivery_attempts VALUES (?,?,?,?,?,?,?,?)',
                             ('repair-coordinator', record['outcome_id'], digest, 3, 'IN_FLIGHT',
                              self.now[0] + 300, None, 'x'))
        self.repo.db.commit()
        sink = Sink(self._receipt); delivery = OutcomeDelivery(self.repo, sink, clock=lambda: self.now[0])
        self.assertEqual(delivery.drain(), []); self.assertEqual(sink.calls, [])
        self.now[0] += 301
        self.assertEqual(delivery.drain()[0]['disposition'], 'ACCEPTED')
        self.assertEqual(len(sink.calls), 1)

    def test_malformed_stored_ack_without_receipt_fails_before_sink(self):
        record = self._record()
        self.repo.db.execute('INSERT INTO scrape_outcome_deliveries VALUES (?,?,?)',
                             (record['outcome_id'], 'repair-coordinator', 'x'))
        self.repo.db.commit()
        sink = Sink(self._receipt)
        with self.assertRaisesRegex(Exception, 'acknowledgement'):
            OutcomeDelivery(self.repo, sink, clock=lambda: self.now[0]).drain()
        self.assertEqual(sink.calls, [])

    def test_corrupt_mapping_record_fails_before_sink_or_acknowledgement(self):
        record = self._mapping_record()
        corrupt = dict(record, identity={**record['identity'],
                                        'configuration_digest': record['configuration_digest']})
        raw = json.dumps(corrupt, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        self.repo.db.execute('UPDATE scrape_outcomes SET payload=? WHERE outcome_id=?',
                             (raw, record['outcome_id']))
        self.repo.db.commit()
        sink = Sink(self._receipt)
        with self.assertRaisesRegex(RepositoryError, 'public outcome grammar'):
            OutcomeDelivery(self.repo, sink, clock=lambda: self.now[0]).drain()
        self.assertEqual(sink.calls, [])
        self.assertEqual(self.repo.db.execute(
            'SELECT count(*) FROM scrape_outcome_deliveries').fetchone()[0], 0)

    def test_private_completion_revalidates_mapping_payload_before_acknowledgement(self):
        record = self._mapping_record()
        digest = self._digest(record)
        reservation = self.repo._reserve_outcome_delivery(
            'repair-coordinator', record['outcome_id'], digest, self.now[0], 'x')
        receipt = self._receipt(record)
        receipt_raw = json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        corrupt = dict(record, configuration_digest='A' * 64)
        self.repo.db.execute('UPDATE scrape_outcomes SET payload=? WHERE outcome_id=?',
                             (json.dumps(corrupt, ensure_ascii=False, sort_keys=True,
                                         separators=(',', ':')), record['outcome_id']))
        self.repo.db.commit()
        with self.assertRaisesRegex(RepositoryError, 'changed before completion'):
            self.repo._complete_outcome_delivery(
                'repair-coordinator', record['outcome_id'], digest, receipt_raw,
                hashlib.sha256(receipt_raw.encode()).hexdigest(), 'x',
                expected_attempt_count=reservation['attempt_count'])
        self.assertEqual(self.repo.db.execute(
            'SELECT count(*) FROM scrape_outcome_deliveries').fetchone()[0], 0)

    def test_receipt_without_ack_and_stale_attempt_fail_before_sink(self):
        record = self._record()
        receipt = self._receipt(record)
        raw = json.dumps(receipt, sort_keys=True, separators=(',', ':'))
        digest = hashlib.sha256(json.dumps(record, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        self.repo.db.execute('INSERT INTO scrape_outcome_delivery_receipts VALUES (?,?,?,?,?,?)',
                             ('repair-coordinator', record['outcome_id'], digest, raw,
                              hashlib.sha256(raw.encode()).hexdigest(), 'x'))
        self.repo.db.commit()
        sink = Sink(self._receipt)
        with self.assertRaisesRegex(Exception, 'acknowledgement'):
            OutcomeDelivery(self.repo, sink, clock=lambda: self.now[0]).drain()
        self.assertEqual(sink.calls, [])

    def test_stale_attempt_is_zero_write_zero_call_corruption(self):
        record = self._record(source_current=False, current_source_revision='rev-now')
        self.repo.db.execute('INSERT INTO scrape_outcome_delivery_attempts VALUES (?,?,?,?,?,?,?,?)',
                             ('repair-coordinator', record['outcome_id'], self._digest(record), 1,
                              'WAITING', self.now[0], 'sink_unavailable', 'x'))
        self.repo.db.commit()
        changes = self.repo.db.total_changes
        sink = Sink(self._receipt)
        with self.assertRaisesRegex(RepositoryError, 'Stale outcome'):
            OutcomeDelivery(self.repo, sink, clock=lambda: self.now[0]).drain()
        self.assertEqual((sink.calls, self.repo.db.total_changes), ([], changes))

    def test_lost_completion_redelivers_only_after_same_lease_expires(self):
        self._record()
        sink = Sink(self._receipt)
        delivery = OutcomeDelivery(self.repo, sink, clock=lambda: self.now[0])
        with patch.object(self.repo, '_complete_outcome_delivery',
                          side_effect=RepositoryError('lost local completion')):
            with self.assertRaisesRegex(RepositoryError, 'lost local'):
                delivery.drain()
        self.assertEqual(len(sink.calls), 1)
        self.assertEqual(delivery.drain(), [])
        self.now[0] += 301
        self.assertEqual(delivery.drain()[0]['disposition'], 'ACCEPTED')
        self.assertEqual(len(sink.calls), 2)

    def test_stale_future_and_later_due_share_limit_without_head_of_line_block(self):
        stale = self._record(request_id='REQ-stale', source_current=False,
                             current_source_revision='rev-new')
        future = self._record(request_id='REQ-future')
        due = self._record(request_id='REQ-due')
        for position, record in enumerate((stale, future, due), 1):
            self.repo.db.execute('UPDATE scrape_outcomes SET recorded_at=? WHERE outcome_id=?',
                                 (str(position), record['outcome_id']))
        for record, next_at in ((future, self.now[0] + 500), (due, self.now[0])):
            self.repo.db.execute('INSERT INTO scrape_outcome_delivery_attempts VALUES (?,?,?,?,?,?,?,?)',
                                 ('repair-coordinator', record['outcome_id'], self._digest(record), 1,
                                  'WAITING', next_at, 'sink_unavailable', 'x'))
        self.repo.db.commit()
        sink = Sink(self._receipt)
        results = OutcomeDelivery(self.repo, sink, clock=lambda: self.now[0]).drain(limit=2)
        self.assertEqual(results, [
            {'outcome_id': stale['outcome_id'], 'disposition': 'STALE_SUPPRESSED'},
            {'outcome_id': due['outcome_id'], 'disposition': 'ACCEPTED'},
        ])
        self.assertEqual([record['outcome_id'] for record in sink.calls], [due['outcome_id']])

    def test_malformed_receipt_grammars_never_acknowledge(self):
        bad_values = [
            {'sink_receipt_id': 'bad space'},
            {'sink_status': 'FREE_FORM'},
            {'record_sha256': 'A' * 64},
            {'outcome_id': 'OUT-bad'},
            {'extra': 'field'},
        ]
        for number, change in enumerate(bad_values):
            record = self._record(request_id=f'REQ-bad-{number}')
            receipt = self._receipt(record)
            receipt.update(change)
            sink = Sink(receipt)
            result = OutcomeDelivery(self.repo, sink, clock=lambda: self.now[0]).drain()
            self.assertIn({'outcome_id': record['outcome_id'], 'disposition': 'WAITING'}, result)
        self.assertEqual(self.repo.db.execute(
            'SELECT count(*) FROM scrape_outcome_deliveries').fetchone()[0], 0)

    def test_private_completion_rejects_every_receipt_grammar_bypass_atomically(self):
        changes = [
            {'schema': 'wrong'},
            {'consumer': 'other-consumer'},
            {'outcome_id': 'OUT-' + '0' * 24},
            {'record_sha256': '0' * 64},
            {'disposition': 'STALE_SUPPRESSED'},
            {'sink_receipt_id': 'bad space'},
            {'sink_status': 'FREE_FORM'},
            {'extra': 'field'},
        ]
        for number, changed in enumerate(changes):
            with self.subTest(changed=changed):
                record = self._record(request_id=f'REQ-private-{number}')
                digest = self._digest(record)
                reservation = self.repo._reserve_outcome_delivery(
                    'repair-coordinator', record['outcome_id'], digest, self.now[0], 'x')
                receipt = self._receipt(record)
                receipt.update(changed)
                raw = json.dumps(receipt, sort_keys=True, separators=(',', ':'))
                before = tuple(self.repo.db.execute(
                    'SELECT count(*) FROM ' + table).fetchone()[0] for table in (
                        'scrape_outcome_delivery_receipts', 'scrape_outcome_deliveries'))
                attempt_before = self.repo.db.execute(
                    'SELECT * FROM scrape_outcome_delivery_attempts WHERE outcome_id=?',
                    (record['outcome_id'],)).fetchone()
                with self.assertRaises(RepositoryError):
                    self.repo._complete_outcome_delivery(
                        'repair-coordinator', record['outcome_id'], digest, raw,
                        hashlib.sha256(raw.encode()).hexdigest(), 'x',
                        expected_attempt_count=reservation['attempt_count'])
                after = tuple(self.repo.db.execute(
                    'SELECT count(*) FROM ' + table).fetchone()[0] for table in (
                        'scrape_outcome_delivery_receipts', 'scrape_outcome_deliveries'))
                self.assertEqual(after, before)
                self.assertEqual(self.repo.db.execute(
                    'SELECT * FROM scrape_outcome_delivery_attempts WHERE outcome_id=?',
                    (record['outcome_id'],)).fetchone(), attempt_before)

    def test_private_completion_rejects_arbitrary_canonical_json(self):
        record = self._record()
        digest = self._digest(record)
        reservation = self.repo._reserve_outcome_delivery(
            'repair-coordinator', record['outcome_id'], digest, self.now[0], 'x')
        raw = '{"not":"a delivery receipt"}'
        with self.assertRaises(RepositoryError):
            self.repo._complete_outcome_delivery(
                'repair-coordinator', record['outcome_id'], digest, raw,
                hashlib.sha256(raw.encode()).hexdigest(), 'x',
                expected_attempt_count=reservation['attempt_count'])
        self.assertEqual(self.repo.db.execute(
            'SELECT count(*) FROM scrape_outcome_deliveries').fetchone()[0], 0)

    def test_sixteenth_known_failure_holds_without_a_seventeenth_sink_call(self):
        record = self._record()
        raw = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        digest = hashlib.sha256(raw.encode()).hexdigest()
        self.repo.db.execute(
            'INSERT INTO scrape_outcome_delivery_attempts VALUES (?,?,?,?,?,?,?,?)',
            ('repair-coordinator', record['outcome_id'], digest, 15, 'WAITING', self.now[0],
             'sink_unavailable', 'x'))
        self.repo.db.commit()
        sink = Sink({'bad': 'receipt'})
        delivery = OutcomeDelivery(self.repo, sink, clock=lambda: self.now[0])
        self.assertEqual(delivery.drain()[0]['disposition'], 'HELD_RETRY_CAP')
        self.assertEqual(self.repo.db.execute(
            'SELECT attempt_count,state,next_attempt_at FROM scrape_outcome_delivery_attempts').fetchone(),
            (16, 'HELD_RETRY_CAP', None))
        self.assertEqual(delivery.drain(), [])
        self.assertEqual(len(sink.calls), 1)

    def test_sixteenth_attempt_may_succeed(self):
        record = self._record()
        raw = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        digest = hashlib.sha256(raw.encode()).hexdigest()
        self.repo.db.execute(
            'INSERT INTO scrape_outcome_delivery_attempts VALUES (?,?,?,?,?,?,?,?)',
            ('repair-coordinator', record['outcome_id'], digest, 15, 'WAITING', self.now[0],
             'sink_unavailable', 'x'))
        self.repo.db.commit()
        sink = Sink(self._receipt)
        self.assertEqual(OutcomeDelivery(self.repo, sink, clock=lambda: self.now[0]).drain()[0]['disposition'],
                         'ACCEPTED')
        self.assertEqual(self.repo.db.execute('SELECT count(*) FROM scrape_outcome_delivery_attempts').fetchone()[0], 0)

    def test_expired_sixteenth_reservation_reclaims_then_holds_on_known_failure(self):
        record = self._record()
        self.repo.db.execute(
            'INSERT INTO scrape_outcome_delivery_attempts VALUES (?,?,?,?,?,?,?,?)',
            ('repair-coordinator', record['outcome_id'], self._digest(record), 16, 'IN_FLIGHT',
             self.now[0] - 1, None, 'x'))
        self.repo.db.commit()
        sink = Sink({'bad': 'receipt'})
        result = OutcomeDelivery(self.repo, sink, clock=lambda: self.now[0]).drain()
        self.assertEqual(result[0]['disposition'], 'HELD_RETRY_CAP')
        self.assertEqual(self.repo.db.execute(
            'SELECT attempt_count,state FROM scrape_outcome_delivery_attempts').fetchone(),
            (16, 'HELD_RETRY_CAP'))

    def test_retry_identity_payload_is_unchanged_by_delivery(self):
        record = self._record(
            request_id='company-retry:RTRY-1', failed_request_id='company-event:CEV-1',
            attempt_id='RTRY-1', release_version='REL-1', release_binding_sha256='b' * 64,
            capability='qualified', failure={'category': 'adapter_regression'})
        before = self.repo.db.execute(
            'SELECT payload FROM scrape_outcomes WHERE outcome_id=?', (record['outcome_id'],)).fetchone()[0]
        sink = Sink(self._receipt)
        OutcomeDelivery(self.repo, sink, clock=lambda: self.now[0]).drain()
        after = self.repo.db.execute(
            'SELECT payload FROM scrape_outcomes WHERE outcome_id=?', (record['outcome_id'],)).fetchone()[0]
        self.assertEqual(after, before)
        self.assertFalse(any(name in {'tasks', 'repair_intake', 'repair_retry_lineage'}
                             for (name,) in self.repo.db.execute(
                                 "SELECT name FROM sqlite_master WHERE type='table'")))


if __name__ == '__main__':
    unittest.main()
