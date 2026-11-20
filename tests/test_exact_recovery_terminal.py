import copy
import tempfile
import unittest
from pathlib import Path

from job_search_helper.engine import State
from job_search_helper.inbox import InventoryInbox
from job_search_helper.exact_recovery_terminal import qualify_terminal_holds, revalidate_terminal_manifest, MANIFEST_VERSION
from job_search_helper.publication_receipts import record_fingerprints
from job_search_helper.exact_cycle_planner import _receipt


class TerminalHoldTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.state = State(root / 'state.db'); self.addCleanup(self.state.close)
        self.inbox = InventoryInbox(root / 'inbox.db', 'fixture'); self.addCleanup(self.inbox.close)
        self.cycle = 'CYCLE'; self.cid = 'COMP-1'
        self.state.save_cycle({'id': self.cycle, 'status': 'In Progress',
                               'companies': {self.cid: {'stage': 'blocked'}}})
        self.payload = {'inventory_status': 'blocked', 'jobs': [], 'requested_url': 'https://example.test'}
        self.inbox.save(self.cycle, self.cid, self.payload); self.inbox.block(self.cycle, self.cid)

    def test_blocked_inventory_without_plan_qualifies_without_mutation(self):
        before = copy.deepcopy(self.state.cycle(self.cycle))
        report = qualify_terminal_holds(self.state, self.inbox, self.cycle, [self.cid])
        self.assertEqual(report['version'], MANIFEST_VERSION)
        self.assertEqual(len(report['qualified']), 1); self.assertEqual(report['held'], [])
        self.assertEqual(self.state.cycle(self.cycle), before)
        self.assertTrue(report['qualified'][0]['manifest_digest'])

    def test_rejects_unblocked_or_nonterminal_or_other_cycle(self):
        self.inbox.unblock(self.cycle, self.cid)
        self.assertEqual(qualify_terminal_holds(self.state, self.inbox, self.cycle, [self.cid])['held'][0]['reason'], 'inbox_not_blocked_hold')
        self.inbox.block(self.cycle, self.cid)
        cycle = self.state.cycle(self.cycle); cycle['companies'][self.cid]['stage'] = 'queued'; self.state.save_cycle(cycle)
        self.assertEqual(qualify_terminal_holds(self.state, self.inbox, self.cycle, [self.cid])['held'][0]['reason'], 'checkpoint_not_terminal_hold')
        with self.assertRaises(ValueError): qualify_terminal_holds(self.state, self.inbox, 'OTHER', [self.cid])

    def test_no_plan_rejects_any_company_receipt(self):
        receipt = {'binding': {'request_id': 'other-cycle', 'company_id': self.cid,
                               'source_revision': 'x', 'release_id': 'y'},
                   'records': {'Companies:{"Company ID":"COMP-1"}': 'f'},
                   'schedule': {'boundary': 'idle', 'enqueued_at': 'now'}, 'timestamp': 'now'}
        self.inbox.ensure_receipt(receipt)
        report = qualify_terminal_holds(self.state, self.inbox, self.cycle, [self.cid])
        self.assertEqual(report['held'][0]['reason'], 'receipt_exists_without_frozen_plan')

    def test_plan_requires_end_cursor_and_durable_confirmed_receipt(self):
        plan = {'operations': [{'tab': 'Companies', 'identity': {'Company ID': self.cid}, 'values': {'Scan State': 'Blocked'}}]}
        self.inbox.save_plan(self.cycle, self.cid, plan)
        self.assertEqual(qualify_terminal_holds(self.state, self.inbox, self.cycle, [self.cid])['held'][0]['reason'], 'frozen_plan_not_complete')
        self.inbox.advance(self.cycle, {self.cid: 1})
        self.assertEqual(qualify_terminal_holds(self.state, self.inbox, self.cycle, [self.cid])['held'][0]['reason'], 'confirmed_receipt_missing')
        receipt = _receipt(self.state.cycle(self.cycle), self.cid, self.payload, plan, 'terminal-hold-proof')
        self.inbox.ensure_receipt(receipt)
        self.inbox.mark_receipt_pending(receipt, timestamp='fixture-pending')
        self.inbox.reconcile_receipt(receipt, receipt['records'], 'fixture-ack', timestamp='fixture-time')
        good = qualify_terminal_holds(self.state, self.inbox, self.cycle, [self.cid])
        self.assertEqual(len(good['qualified']), 1)
        self.assertEqual(good['qualified'][0]['receipt']['state'], 'SYNC_CONFIRMED')

    def test_pending_receipt_is_not_confirmed(self):
        plan = {'operations': [{'tab': 'Companies', 'identity': {'Company ID': self.cid}, 'values': {'Scan State': 'Blocked'}}]}
        records = record_fingerprints(plan['operations'])
        receipt = _receipt(self.state.cycle(self.cycle), self.cid, self.payload, plan, 'terminal-hold-proof')
        self.inbox.save_plan(self.cycle, self.cid, plan, receipt); self.inbox.advance(self.cycle, {self.cid: 1})
        self.inbox.mark_receipt_pending(receipt, timestamp='later')
        report = qualify_terminal_holds(self.state, self.inbox, self.cycle, [self.cid])
        self.assertEqual(report['held'][0]['reason'], 'receipt_evidence_not_confirmed_or_mismatched')

    def test_manifest_revalidation_rejects_payload_and_cursor_changes(self):
        plan = {'operations': [{'tab': 'Companies', 'identity': {'Company ID': self.cid}, 'values': {'Scan State': 'Blocked'}}]}
        receipt = _receipt(self.state.cycle(self.cycle), self.cid, self.payload, plan, 'terminal-hold-proof')
        self.inbox.save_plan(self.cycle, self.cid, plan, receipt); self.inbox.advance(self.cycle, {self.cid: 1})
        self.inbox.mark_receipt_pending(receipt, timestamp='fixture-pending')
        self.inbox.reconcile_receipt(receipt, receipt['records'], 'fixture-ack', timestamp='fixture-time')
        manifest = qualify_terminal_holds(self.state, self.inbox, self.cycle, [self.cid])['qualified'][0]
        self.assertEqual(revalidate_terminal_manifest(self.state, self.inbox, manifest)['manifest_digest'], manifest['manifest_digest'])
        with self.inbox.connection:
            self.inbox.connection.execute('UPDATE inventories SET payload=? WHERE cycle=? AND company=?',
                                        ('{"inventory_status":"blocked","jobs":[],"requested_url":"https://changed.test"}', self.cycle, self.cid))
        with self.assertRaises(ValueError): revalidate_terminal_manifest(self.state, self.inbox, manifest)
