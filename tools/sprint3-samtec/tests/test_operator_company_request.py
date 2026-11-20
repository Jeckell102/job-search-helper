from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from job_search_helper.operator_company_request import queue_operator_company_request
from job_search_helper.repository import SCHEMAS
from job_search_helper.sqlite_repository import SQLiteRepository
from job_search_helper.scan_request import _read_request, request_fingerprint, requested_scan
from job_search_helper.engine import Engine, State


def company(**changes):
    row = {
        'Company': 'Fixture Co', 'Company ID': 'COMP-1', 'Company Status': 'Active',
        'Official Careers URL': 'https://jobs.example.test/fixture', 'ATS / Source': 'Fixture',
    }
    row.update(changes)
    return row


class OperatorCompanyRequestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = SQLiteRepository(self.root / 'jobs.sqlite3', 'test-sheet', initialize=True)
        self.addCleanup(self.repo.close)
        for tab in SCHEMAS:
            self.repo.import_rows(tab, enumerate([company()] if tab == 'Companies' else [], 2))
        self.now = datetime(2026, 11, 19, 20, 0, tzinfo=timezone.utc)

    def queue(self, request_id='operator-samtec-m1'):
        return queue_operator_company_request(
            self.repo, self.root / 'state', 'COMP-1', request_id, now=self.now)

    def test_writes_exact_one_company_request_and_receipt(self):
        result = self.queue()
        self.assertEqual(result['state'], 'REQUEST_WRITTEN')
        request = json.loads((self.root / 'state' / 'next-scan.json').read_text())
        self.assertEqual(request['company_ids'], ['COMP-1'])
        self.assertEqual(request['operator_request']['request_id'], 'operator-samtec-m1')
        self.assertEqual(len(list((self.root / 'state' / 'operator-company-requests' / 'receipts').glob('*.json'))), 1)

    def test_same_request_id_is_idempotent_and_other_request_is_held(self):
        self.queue()
        first = (self.root / 'state' / 'next-scan.json').read_bytes()
        self.now += timedelta(minutes=1)
        self.assertEqual(self.queue()['state'], 'REQUEST_ALREADY_DURABLE')
        self.assertEqual((self.root / 'state' / 'next-scan.json').read_bytes(), first)
        held = self.queue('operator-other-company')
        self.assertEqual(held['state'], 'WAITING_FOR_SAFE_REQUEST_BOUNDARY')
        self.assertEqual((self.root / 'state' / 'next-scan.json').read_bytes(), first)

    def test_existing_receipt_prevents_requeue_and_id_collision_before_writing(self):
        self.queue()
        path = self.root / 'state' / 'next-scan.json'
        path.unlink()
        self.now += timedelta(minutes=1)
        self.assertEqual(self.queue()['state'], 'REQUEST_PREVIOUSLY_RESERVED')
        self.assertFalse(path.exists())
        self.repo.import_rows('Companies', enumerate([
            company(**{'Official Careers URL': 'https://jobs.example.test/changed'})], 2))
        with self.assertRaisesRegex(ValueError, 'receipt_collision'):
            self.queue()
        self.assertFalse(path.exists())

    def test_recovers_request_written_before_receipt_with_original_enqueue_time(self):
        self.queue()
        path = self.root / 'state' / 'next-scan.json'
        original = path.read_bytes()
        receipt, = (self.root / 'state' / 'operator-company-requests' / 'receipts').glob('*.json')
        receipt.unlink()
        self.now += timedelta(minutes=1)
        self.assertEqual(self.queue()['state'], 'REQUEST_ALREADY_DURABLE')
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(json.loads(receipt.read_text())['state'], 'REQUEST_ALREADY_DURABLE')

    def test_rejects_ineligible_or_claimed_company_without_request(self):
        for changes in ({'Company Status': 'Paused'}, {'Claim Token': 'claim'}):
            self.repo.import_rows('Companies', enumerate([company(**changes)], 2))
            with self.assertRaisesRegex(ValueError, 'company_(ineligible|claimed)'):
                self.queue()
            self.assertFalse((self.root / 'state' / 'next-scan.json').exists())

    def test_operator_provenance_is_immutable_request_identity(self):
        self.queue()
        path = self.root / 'state' / 'next-scan.json'
        request, company_ids = _read_request(path)
        fingerprint = request_fingerprint(request, company_ids)
        request['operator_request']['company_id'] = 'COMP-2'
        path.write_text(json.dumps(request))
        with self.assertRaisesRegex(ValueError, 'operator request does not bind'):
            _read_request(path)
        self.assertTrue(fingerprint)

    def test_normal_admission_keeps_bound_operator_provenance_and_rejects_stale_source(self):
        self.queue()
        database = self.root / 'state' / 'state.db'
        state = State(database)
        self.addCleanup(state.close)
        cycle_id = requested_scan(Engine(self.repo, state), state, database)
        cycle = state.cycle(cycle_id)
        self.assertEqual(cycle['operator_request']['company_id'], 'COMP-1')
        self.assertFalse(cycle['all'])
        recovered_state = State()
        self.addCleanup(recovered_state.close)
        recovered = Engine(self.repo, recovered_state)._recover(cycle_id)
        self.assertEqual(recovered['operator_request'], cycle['operator_request'])
        cycle['companies']['COMP-1']['stage'] = 'complete'
        Engine(self.repo, state)._sync_cycle(cycle)

        self.queue('operator-stale')
        path = self.root / 'state' / 'next-scan.json'
        stale = json.loads(path.read_text())
        stale['source_revision'] = 'stale-revision'
        stale['operator_request']['source_revision'] = 'stale-revision'
        path.write_text(json.dumps(stale))
        with self.assertRaisesRegex(ValueError, 'source revision is stale'):
            requested_scan(Engine(self.repo, state), state, database)


if __name__ == '__main__':
    unittest.main()
