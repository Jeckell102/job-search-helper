"""Restart preserves legacy state and only closes a real, resolved session."""
from contextlib import contextmanager
import json
import tempfile
import unittest
from unittest.mock import patch

from coordinator_store import Store
import test_inference_store as inference_fixture


def database_snapshot(store):
    """Include exact stored JSON and all table contents, without normalization."""
    with store.connect() as db:
        tables = [row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        return {table: db.execute('SELECT * FROM "' + table.replace('"', '""') + '" ORDER BY rowid').fetchall()
                for table in tables}


class StartupSessionNoopTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = Store(temporary.name)

    def insert(self, index=0, **fields):
        state = dict(id=f'WRAP-{index:010x}', status='PAUSED', **fields)
        with self.store.connect() as db:
            db.execute('INSERT INTO tasks VALUES (?,?)', (state['id'], json.dumps(state, indent=2)))
        return state['id']

    def assert_no_update(self, operation):
        before = database_snapshot(self.store)
        statements = []
        connect = self.store.connect

        @contextmanager
        def traced_connect():
            with connect() as db:
                db.set_trace_callback(statements.append)
                yield db

        with patch.object(self.store, 'connect', traced_connect):
            operation()
        self.assertEqual(database_snapshot(self.store), before)
        self.assertFalse([sql for sql in statements if sql.lstrip().upper().startswith('UPDATE')])

    def test_absent_empty_mismatched_and_closed_sessions_are_noops(self):
        cases = [({}, None), ({}, ''), ({}, 'caller'),
                 ({'inference_session_id': None, 'inference_session_open': True}, None),
                 ({'inference_session_id': '', 'inference_session_open': True}, ''),
                 ({'inference_session_id': 'real', 'inference_session_open': True}, 'other'),
                 ({'inference_session_id': 'real'}, 'real'),
                 ({'inference_session_id': 'real', 'inference_session_open': False}, 'real'),
                 ({'inference_session_id': 'real', 'inference_session_open': 1}, 'real')]
        for index, (fields, supplied) in enumerate(cases):
            with self.subTest(fields=fields, supplied=supplied):
                task = self.insert(index, **fields)
                self.assert_no_update(lambda: self.store.end_inference_session(task, supplied))

    def test_pending_receipts_protect_open_session(self):
        for index, status in enumerate(('DISPATCHING', 'UNCERTAIN')):
            task = self.insert(index, inference_session_id='real', inference_session_open=True)
            with self.store.connect() as db:
                db.execute('INSERT INTO inference_receipts VALUES (?,?,?,?)',
                           (str(index), task, status, json.dumps({'status': status})))
            self.assert_no_update(lambda: self.store.end_inference_session(task, 'real'))

    def test_resolved_open_session_closes_once_across_recovery(self):
        task = self.insert(inference_session_id='real', inference_session_open=True)
        before = self.store.get(task)
        self.store.recover()
        self.assertEqual(self.store.get(task), dict(before, inference_session_open=False))
        self.assert_no_update(self.store.recover)

    def test_111_legacy_tasks_and_closed_session_unchanged_on_two_recoveries(self):
        for index in range(111):
            self.insert(index, reason='Preserved legacy pause', sessions=0, calls=0, tokens=0)
        self.insert(111, inference_session_id='old', inference_session_open=False)
        with self.store.connect() as db:
            for key, value in [('queue_enabled', False), ('campaign_enabled', False),
                               ('autopilot_enabled', False), ('pilot_task', None)]:
                db.execute('INSERT INTO settings VALUES (?,?)', (key, json.dumps(value)))
        self.assert_no_update(self.store.recover)
        self.assert_no_update(self.store.recover)


class StartupPendingRecoveryTests(unittest.TestCase):
    setUp = inference_fixture.InferenceStoreTests.setUp
    task = inference_fixture.InferenceStoreTests.task
    reserve = inference_fixture.InferenceStoreTests.reserve

    def test_dispatch_becomes_uncertain_and_stays_open_without_replay(self):
        task, receipt = self.reserve()
        store = self.co.store
        counters = {key: store.get(task)[key] for key in ('sessions', 'calls', 'tokens')}
        for _ in range(2):
            store.recover()
            state = store.get(task)
            self.assertTrue(state['inference_session_open'])
            self.assertEqual(state['status'], 'PAUSED_RECOVERY')
            self.assertEqual({key: state[key] for key in counters}, counters)
            receipts = store.inference_receipts(task)
            self.assertEqual(len(receipts), 1)
            self.assertEqual(receipts[0]['status'], 'UNCERTAIN')
            self.assertEqual(receipts[0]['request_id'], receipt['request_id'])
            self.assertIsNone(store.start_inference_session(task))
        self.assertEqual(self.history, [])


if __name__ == '__main__':
    unittest.main()
