import copy
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from job_search_helper.engine import Engine, State
from job_search_helper.inbox import InventoryInbox
from job_search_helper.repository import MemoryRepository
from job_search_helper.runner import active_inbox_cycles, resolve_cycle
from job_search_helper.scan_request import requested_scan, superseded_cycle_ids
from test_fetch_pool import company, inventory


class FreshScanRequestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.database = self.root/'state.db'
        self.state = State(self.database)
        self.addCleanup(self.state.close)
        self.repo = MemoryRepository({'Companies':[company(i) for i in range(6)]})
        self.inbox = InventoryInbox(self.root/'inventories.sqlite3','fixture')
        self.addCleanup(self.inbox.close)
        self.engine = Engine(self.repo,self.state,inbox=self.inbox)
        self.old = self.engine.start_cycle()
        self.original = copy.deepcopy(self.state.cycle(self.old))
        self.request = {'mode':'fresh-full-scan','request_id':'fixture-request',
                        'start_last':['C-0','C-3'],'comparison_baseline_id':'CYC-BASELINE'}
        (self.root/'next-scan.json').write_text(json.dumps(self.request))
        self.output = redirect_stdout(StringIO()); self.output.__enter__()
        self.addCleanup(self.output.__exit__,None,None,None)

    def test_new_full_scan_preserves_old_checkpoint_and_orders_slow_companies_last(self):
        cycle_id = requested_scan(self.engine,self.state,self.database)
        cycle = self.state.cycle(cycle_id)
        self.assertNotEqual(cycle_id,self.old)
        self.assertTrue(cycle['all'])
        self.assertEqual(list(cycle['companies']),['C-1','C-2','C-4','C-5','C-0','C-3'])
        self.assertEqual(cycle['supersedes'],[self.old])
        self.assertEqual(self.state.cycle(self.old),self.original)
        self.assertTrue((self.root/'last-scan-request.json').exists())
        self.assertFalse((self.root/'next-scan.json').exists())
        self.assertEqual(resolve_cycle(self.engine,self.state,self.repo)[0],cycle_id)

    def test_repeat_request_id_recovers_same_cycle_and_does_not_duplicate(self):
        first = requested_scan(self.engine,self.state,self.database)
        (self.root/'next-scan.json').write_text(json.dumps(self.request))
        second = requested_scan(self.engine,self.state,self.database)
        self.assertEqual(first,second)
        self.assertEqual(len(self.state.cycles()),2)

    def test_old_inbox_is_preserved_but_not_replayed_by_normal_start(self):
        self.inbox.save(self.old,'C-0',{'jobs':[],'inventory_status':'blocked'})
        cycle_id = requested_scan(self.engine,self.state,self.database)
        self.inbox.save(cycle_id,'C-1',{'jobs':[],'inventory_status':'blocked'})
        self.assertEqual(active_inbox_cycles(self.inbox,self.state),[cycle_id])
        self.assertIsNotNone(self.inbox.get(self.old,'C-0'))

    def test_normal_new_cycle_allowed_after_replacement_finishes(self):
        cycle_id = requested_scan(self.engine,self.state,self.database)
        cycle = self.state.cycle(cycle_id)
        for item in cycle['companies'].values(): item['stage']='complete'
        self.engine._sync_cycle(cycle)
        new_id = self.engine.start_cycle()
        self.assertNotEqual(new_id,cycle_id)
        self.assertEqual(self.state.cycle(self.old),self.original)

    def test_recovery_retains_replacement_metadata_and_order(self):
        cycle_id = requested_scan(self.engine,self.state,self.database)
        recovered_state = State()
        self.addCleanup(recovered_state.close)
        engine = Engine(self.repo,recovered_state)
        recovered = engine._recover(cycle_id)
        self.assertEqual(recovered['supersedes'],[self.old])
        self.assertEqual(list(recovered['companies'])[-2:],['C-0','C-3'])
        self.assertEqual(superseded_cycle_ids(self.repo.read('Scan Cycles')),{self.old})

    def test_without_explicit_request_unfinished_cycle_still_blocks_new_scan(self):
        with self.assertRaisesRegex(ValueError,'unfinished local'):
            self.engine.start_cycle()

    def test_invalid_request_is_preserved_and_creates_no_cycle(self):
        (self.root/'next-scan.json').write_text('{"mode":"skip everything"}')
        with self.assertRaisesRegex(ValueError,'Invalid next-scan'):
            requested_scan(self.engine,self.state,self.database)
        self.assertEqual(len(self.state.cycles()),1)
        self.assertTrue((self.root/'next-scan.json').exists())

    def test_worker_assignment_order_follows_cycle_order_without_skipping_any_company(self):
        cycle_id = requested_scan(self.engine,self.state,self.database)
        fetched = []
        def fetch(source,url,cid,name):
            fetched.append(cid)
            return inventory(cid,name,url)
        self.engine.fetcher = fetch
        self.engine.resume_local(cycle_id,fetch_workers=1,defer_sync=True)
        self.assertEqual(fetched,['C-1','C-2','C-4','C-5','C-0','C-3'])


if __name__ == '__main__':
    unittest.main()
