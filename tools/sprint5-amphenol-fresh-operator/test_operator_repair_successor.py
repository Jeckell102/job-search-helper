"""Focused, disposable proof for the guarded operator-successor reservation."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


TOOLS = '/home/chris/job-search-helper_old/dev/wrapper-coder/tools'
SOURCE = Path(__file__).parents[1] / 'src/job_search_helper/coordinator_store.py'
sys.path.insert(0, TOOLS)
spec = importlib.util.spec_from_file_location('candidate_coordinator_store', SOURCE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
Store = module.Store
OUTCOME_DELIVERY_CONSUMER = module.OUTCOME_DELIVERY_CONSUMER
task_state_digest = module.task_state_digest


def outcome(request_id, *, fingerprint='a' * 64):
    identity = {
        'request_id': request_id, 'company_id': 'COMP-0490',
        'source_revision': 'rev-amphenol-current', 'provider': 'acquiretm',
        'adapter_version': 'normal-scraper-v1',
    }
    immutable = {'identity': identity, 'failure_fingerprint': fingerprint,
                 'outcome': 'QUALIFIED_INTEGRATION_REPAIR'}
    return {
        'outcome_id': 'OUT-' + hashlib.sha256(
            json.dumps(immutable, sort_keys=True, separators=(',', ':')).encode()).hexdigest()[:24],
        'outcome': 'QUALIFIED_INTEGRATION_REPAIR',
        'action': 'upsert_qualified_repair', 'identity': identity,
        'failure_fingerprint': fingerprint,
    }


class OperatorRepairSuccessorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)
        self.predecessor = outcome('company-event:CEV-old')
        self.successor = outcome('operator-request:OP-new')
        self.store.ingest_scrape_outcome_delivery_v1(OUTCOME_DELIVERY_CONSUMER, self.predecessor)
        self.store.ingest_scrape_outcome_delivery_v1(OUTCOME_DELIVERY_CONSUMER, self.successor)
        with self.store.connect() as db:
            self.repair_key = db.execute(
                'SELECT repair_key FROM repair_intake WHERE outcome_id=?',
                (self.predecessor['outcome_id'],)).fetchone()[0]
            self.task = {'id': 'WRAP-1234567890', 'status': 'PAUSED',
                         'stop_requested': True, 'sessions': 1,
                         'held_repair_key': self.repair_key}
            db.execute('INSERT INTO tasks VALUES (?,?)', (self.task['id'], json.dumps(self.task)))
            db.execute('UPDATE repair_intake SET task_id=?,status=? WHERE repair_key=?',
                       (self.task['id'], 'PROMOTED_PAUSED', self.repair_key))
            for key in ('queue_enabled', 'campaign_enabled', 'autopilot_enabled'):
                db.execute('INSERT INTO settings VALUES (?,?)', (key, 'false'))
            db.execute('INSERT INTO settings VALUES (?,?)', ('pilot_task', 'null'))
        self.pins = dict(
            predecessor_outcome_id=self.predecessor['outcome_id'], outcome_id=self.successor['outcome_id'],
            source_revision='rev-amphenol-current', predecessor_repair_key=self.repair_key,
            predecessor_task_id=self.task['id'],
            predecessor_task_state_sha256=task_state_digest(self.task), company_id='COMP-0490',
            failure_fingerprint='a' * 64)

    def test_reserves_acknowledged_distinct_operator_outcome_and_exact_replay(self):
        first = self.store.reserve_operator_repair_successor(**self.pins)
        replay = self.store.reserve_operator_repair_successor(**self.pins)
        self.assertFalse(first['replayed'])
        self.assertTrue(replay['replayed'])
        self.assertEqual(first['repair_key'], replay['repair_key'])
        self.assertEqual(first['owner_status'], 'HELD_FOR_REPAIR_TRIAGE')
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT outcome_id,status,task_id FROM repair_intake WHERE repair_key=?',
                                        (first['repair_key'],)).fetchone(),
                             (self.successor['outcome_id'], 'HELD_FOR_REPAIR_TRIAGE', None))
            self.assertEqual(db.execute('SELECT status,task_id FROM repair_intake WHERE repair_key=?',
                                        (self.repair_key,)).fetchone(),
                             ('PROMOTED_PAUSED', self.task['id']))
        promoted_id = 'WRAP-aaaaaaaaaa'
        self.store.new_state = lambda **ignored: {
            'id': promoted_id, 'integration_identity': {'company_id': 'COMP-0490'},
        }
        promoted = self.store.promote_held_repair(first['repair_key'], {'ignored': True},
                                                  source_revision='rev-amphenol-current')
        self.assertEqual(promoted['id'], promoted_id)
        self.assertEqual(self.store.get(promoted_id)['held_repair_key'], first['repair_key'])

    def test_second_distinct_successor_and_unstopped_controls_hold_without_mutation(self):
        self.store.reserve_operator_repair_successor(**self.pins)
        competing = outcome('operator-request:OP-other')
        self.store.ingest_scrape_outcome_delivery_v1(OUTCOME_DELIVERY_CONSUMER, competing)
        with self.assertRaisesRegex(ValueError, 'different operator successor'):
            self.store.reserve_operator_repair_successor(**{**self.pins, 'outcome_id': competing['outcome_id']})
        with self.store.connect() as db:
            db.execute("UPDATE settings SET value='true' WHERE key='queue_enabled'")
        # The second part is assessed on this store's reservation result, so a
        # changed global control cannot overwrite the existing reservation.
        with self.assertRaisesRegex(ValueError, 'scheduler'):
            self.store.reserve_operator_repair_successor(**self.pins)

    def test_rejects_unacknowledged_company_event_and_wrong_owner_pin(self):
        unacknowledged = outcome('operator-request:OP-unack')
        with self.assertRaisesRegex(ValueError, 'acknowledged'):
            self.store.reserve_operator_repair_successor(**{**self.pins, 'outcome_id': unacknowledged['outcome_id']})
        company_event = outcome('company-event:CEV-new')
        self.store.ingest_scrape_outcome_delivery_v1(OUTCOME_DELIVERY_CONSUMER, company_event)
        with self.assertRaisesRegex(ValueError, 'does not match'):
            self.store.reserve_operator_repair_successor(**{**self.pins, 'outcome_id': company_event['outcome_id']})
        with self.assertRaisesRegex(ValueError, 'pins'):
            self.store.reserve_operator_repair_successor(**{**self.pins, 'company_id': 'COMP-0000'})

    def test_accepts_the_verified_paused_error_shape_only_after_a_session(self):
        self.task.update(status='PAUSED_ERROR', stop_requested=False)
        with self.store.connect() as db:
            db.execute('UPDATE tasks SET state=? WHERE id=?',
                       (json.dumps(self.task), self.task['id']))
        pins = {**self.pins, 'predecessor_task_state_sha256': task_state_digest(self.task)}
        self.assertFalse(self.store.reserve_operator_repair_successor(**pins)['replayed'])

