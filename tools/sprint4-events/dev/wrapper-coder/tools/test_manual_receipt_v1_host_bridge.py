"""Focused isolated-only proof for the manual receipt-v1 host bridge."""
import hashlib
import importlib.util
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from coordinator import Coordinator
from coordinator_outcome_delivery import drain as legacy_drain
from coordinator_receipt_host_bridge import ManualReceiptV1HostBridge, legacy_production_drain
from job_search_helper.sqlite_repository import SQLiteRepository


def facts(**changes):
    value = {
        'request_id': 'REQ-1', 'company_id': 'COMP-0001', 'source_revision': 'rev-1',
        'cycle_id': 'CYC-1', 'provider': 'greenhouse', 'adapter_version': 'v1',
        'source_current': True, 'company_status': 'Active', 'storage_status': 'confirmed',
        'inventory_status': 'partial', 'capability': 'unknown',
        'failure': {'category': 'unknown'},
    }
    value.update(changes)
    return value


class ManualReceiptV1HostBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'sender.sqlite3'
        self.sender = SQLiteRepository(self.path, 'sheet', initialize=True)
        self.addCleanup(self.sender.close)
        self.coordinator = Coordinator(base=Path(self.temp.name) / 'coordinator')

    def record(self, **changes):
        return self.sender.record_scrape_outcome(facts(**changes))['outcome']

    def bridge(self, *, enabled=True, coordinator=None, factory=None):
        return ManualReceiptV1HostBridge(
            coordinator or self.coordinator, factory or (lambda: self.sender), enabled=enabled)

    def test_default_off_never_opens_sender_or_calls_receiver(self):
        opened = []
        bridge = self.bridge(enabled=False, factory=lambda: opened.append(True))
        self.assertEqual(bridge.status()['state'], 'DISABLED')
        self.assertEqual(bridge.manual_drain()['results'], [])
        self.assertEqual(opened, [])
        self.assertEqual(self.coordinator.store.all(), [])

    def test_exact_manual_target_ignores_other_sender_records(self):
        other = self.record(request_id='REQ-OTHER')
        selected = self.record(request_id='REQ-SELECTED')
        bridge = self.bridge()
        self.assertEqual(bridge.manual_drain(outcome_id=selected['outcome_id'])['results'],
                         [{'outcome_id': selected['outcome_id'], 'disposition': 'ACCEPTED'}])
        self.assertEqual(bridge.manual_drain(outcome_id=selected['outcome_id'])['results'], [])
        self.assertEqual(self.sender.pending_scrape_outcomes('repair-coordinator'), [other])
        with self.coordinator.store.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM scrape_outcome_intake').fetchone()[0], 1)
        self.assertEqual(self.coordinator.store.all(), [])

    def test_live_shaped_host_holds_catchup_and_delivers_only_pinned_outcome(self):
        from job_search_helper import cli

        entry = Path(__file__).with_name('host_server.py')
        spec = importlib.util.spec_from_file_location('isolated_receipt_host', entry)
        host = importlib.util.module_from_spec(spec)
        with patch.object(Path, 'read_text', return_value='disposable-token'):
            spec.loader.exec_module(host)
        host.COORDINATOR = self.coordinator
        other = self.record(request_id='REQ-OTHER')
        selected = self.record(request_id='REQ-SELECTED')
        self.sender.set_meta('ready', 'yes')
        with (
            patch.dict('os.environ', {'WRAPPER_SELECTED_OUTCOME_ID': selected['outcome_id'],
                                      'SPREADSHEET_ID': 'sheet'}),
            patch.object(cli, 'load_environment') as load,
            patch.object(cli, 'storage_backend', return_value='sqlite'),
            patch.object(cli, 'job_database_path', return_value=self.path),
            patch.object(cli, 'state_path', return_value=self.path.with_name('state.db')),
        ):
            self.assertEqual(host.drain_scrape_outcomes()['state'], 'HELD_EXACT_OPERATOR_SCOPE_REQUIRED')
            self.assertEqual(host.drain_scrape_outcomes(outcome_id=other['outcome_id'])['state'],
                             'HELD_EXACT_OPERATOR_SCOPE_REQUIRED')
            load.assert_not_called()
            self.assertEqual(host.drain_scrape_outcomes(outcome_id=selected['outcome_id'])['results'],
                             [{'outcome_id': selected['outcome_id'], 'disposition': 'ACCEPTED'}])
            self.assertEqual(host.drain_scrape_outcomes(outcome_id=selected['outcome_id'])['results'], [])
        self.assertEqual(self.sender.pending_scrape_outcomes('repair-coordinator'), [other])
        self.assertEqual(self.coordinator.store.all(), [])

    def test_unicode_record_uses_fixed_v1_action_and_has_no_task_or_f6_effect(self):
        record = self.record(provider='grünhaus')
        before = tuple(self.sender.db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]
                       for table in ('records', 'dirty'))
        result = self.bridge().manual_drain()
        self.assertEqual(result['results'], [{'outcome_id': record['outcome_id'], 'disposition': 'ACCEPTED'}])
        self.assertEqual(self.coordinator.store.all(), [])
        self.assertEqual(tuple(self.sender.db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]
                               for table in ('records', 'dirty')), before)
        with self.coordinator.store.connect() as db:
            receipt = json.loads(db.execute('SELECT receipt FROM scrape_outcome_delivery_receipts').fetchone()[0])
        raw = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        self.assertEqual(receipt['record_sha256'], hashlib.sha256(raw.encode('utf-8')).hexdigest())

    def test_lost_response_replays_frozen_receiver_receipt_once(self):
        record = self.record()

        class LoseResponse:
            def __init__(self, real): self.real, self.calls = real, 0
            def command(self, value):
                self.calls += 1
                result = self.real.command(value)
                if self.calls == 1:
                    raise RuntimeError('simulated response loss')
                return result

        proxy = LoseResponse(self.coordinator)
        self.assertEqual(self.bridge(coordinator=proxy).manual_drain()['results'][0]['disposition'], 'WAITING')
        self.sender.db.execute('UPDATE scrape_outcome_delivery_attempts SET next_attempt_at=0')
        self.sender.db.commit()
        self.assertEqual(self.bridge(coordinator=proxy).manual_drain()['results'],
                         [{'outcome_id': record['outcome_id'], 'disposition': 'ACCEPTED'}])
        self.assertEqual(proxy.calls, 2)
        with self.coordinator.store.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM scrape_outcome_intake').fetchone()[0], 1)

    def test_stale_is_suppressed_sender_side_without_receiver_contact(self):
        record = self.record(source_current=False, current_source_revision='rev-now')

        class NeverCall:
            def command(self, _value): raise AssertionError('stale reached receiver')

        result = self.bridge(coordinator=NeverCall()).manual_drain()
        self.assertEqual(result['results'], [{'outcome_id': record['outcome_id'], 'disposition': 'STALE_SUPPRESSED'}])
        self.assertEqual(self.coordinator.store.all(), [])

    def test_invalid_receipt_and_storage_failure_leave_work_unacknowledged(self):
        self.record()

        class Invalid:
            def command(self, _value): return {'ok': True, 'receipt': {'bad': 'receipt'}}

        self.assertEqual(self.bridge(coordinator=Invalid()).manual_drain()['results'][0]['disposition'], 'WAITING')
        self.assertEqual(self.sender.db.execute('SELECT COUNT(*) FROM scrape_outcome_deliveries').fetchone()[0], 0)
        self.assertEqual(self.coordinator.store.all(), [])
        held = self.bridge(factory=lambda: (_ for _ in ()).throw(OSError('storage unavailable'))).manual_drain()
        self.assertEqual(held['state'], 'HELD_SOURCE_STORAGE_UNAVAILABLE')
        self.assertEqual(held['results'], [])
        self.assertNotIn('storage unavailable', json.dumps(held))
        self.assertEqual(self.coordinator.store.all(), [])

    def test_source_read_oserror_is_sanitized_before_receiver_or_delivery_mutation(self):
        record = self.record()
        before = tuple(self.sender.db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]
                       for table in ('scrape_outcome_deliveries', 'scrape_outcome_delivery_attempts'))

        class NeverCall:
            def command(self, _value): raise AssertionError('source read reached receiver')

        original = self.sender._outcome_delivery_rows
        self.sender._outcome_delivery_rows = lambda _consumer: (_ for _ in ()).throw(
            OSError('private sqlite read detail'))
        self.addCleanup(setattr, self.sender, '_outcome_delivery_rows', original)
        held = self.bridge(coordinator=NeverCall()).manual_drain()
        self.assertEqual(held['state'], 'HELD_SOURCE_STORAGE_UNAVAILABLE')
        self.assertEqual(held['results'], [])
        self.assertNotIn('private sqlite read detail', json.dumps(held))
        self.assertEqual(tuple(self.sender.db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]
                               for table in ('scrape_outcome_deliveries', 'scrape_outcome_delivery_attempts')), before)
        self.assertEqual(record['outcome_id'], self.sender.scrape_outcomes()[0]['outcome_id'])

    def test_attempt_cap_and_legacy_production_drain_are_hard_rejected(self):
        record = self.record()
        raw = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        self.sender.db.execute('INSERT INTO scrape_outcome_delivery_attempts VALUES (?,?,?,?,?,?,?,?)',
                               ('repair-coordinator', record['outcome_id'],
                                hashlib.sha256(raw.encode()).hexdigest(), 16, 'IN_FLIGHT', 0,
                                None, 'test'))
        self.sender.db.commit()

        class Down:
            def command(self, _value): raise RuntimeError('down')

        self.assertEqual(self.bridge(coordinator=Down()).manual_drain()['results'][0]['disposition'],
                         'HELD_RETRY_CAP')
        with self.assertRaisesRegex(RuntimeError, 'Legacy production'):
            legacy_drain(self.sender, self.coordinator, consumer='repair-coordinator')
        with self.assertRaisesRegex(RuntimeError, 'Legacy production'):
            legacy_production_drain()

    def test_concurrent_manual_calls_create_one_receiver_intake_and_no_worker(self):
        record = self.record()
        local, results, errors = threading.local(), [], []

        def factory():
            repo = SQLiteRepository(self.path, 'sheet', require_ready=False)
            local.repo = repo
            return repo

        bridge = self.bridge(factory=factory)
        def run():
            try:
                results.append(bridge.manual_drain())
            except Exception as exc:
                errors.append(exc)
            finally:
                if hasattr(local, 'repo'):
                    local.repo.close()
        first, second = threading.Thread(target=run), threading.Thread(target=run)
        first.start(); second.start(); first.join(); second.join()
        self.assertEqual(errors, [])
        self.assertEqual(sum(len(item['results']) for item in results), 1)
        with self.coordinator.store.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM scrape_outcome_intake').fetchone()[0], 1)
        self.assertEqual(self.coordinator.store.all(), [])
        self.assertEqual(self.sender.db.execute('SELECT COUNT(*) FROM scrape_outcome_deliveries').fetchone()[0], 1)
        self.assertEqual(record['outcome_id'], self.sender.scrape_outcomes()[0]['outcome_id'])


if __name__ == '__main__':
    unittest.main()


def test_signed_company_event_to_exact_coordinator_receipt(tmp_path, monkeypatch):
    from contextlib import closing
    from test_retained_operator_run import OperatorFixture

    fixture = OperatorFixture(tmp_path, monkeypatch, company_event=True)
    fixture.sign()
    result = fixture.command('execute')
    outcome_id = result['outcome_id']
    coordinator = Coordinator(base=tmp_path / 'coordinator')
    with closing(fixture.local(write=True)) as sender:
        bridge = ManualReceiptV1HostBridge(coordinator, lambda: sender, enabled=True)
        assert bridge.manual_drain(outcome_id=outcome_id)['results'] == [
            {'outcome_id': outcome_id, 'disposition': 'ACCEPTED'},
        ]
        assert bridge.manual_drain(outcome_id=outcome_id)['results'] == []
        row = sender.db.execute(
            'SELECT record_sha256,receipt FROM scrape_outcome_delivery_receipts WHERE outcome_id=?',
            (outcome_id,),
        ).fetchone()
    with coordinator.store.connect() as db:
        receiver = db.execute(
            'SELECT record_sha256,receipt,sink_status FROM scrape_outcome_delivery_receipts WHERE outcome_id=?',
            (outcome_id,),
        ).fetchone()
        tasks = db.execute('SELECT COUNT(*) FROM repair_intake WHERE outcome_id=?', (outcome_id,)).fetchone()[0]
    assert receiver[:2] == row
    assert receiver[2] == 'RECORDED_NO_REPAIR'
    assert tasks == 0
