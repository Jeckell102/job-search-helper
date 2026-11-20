"""Every supported scraper path owns a stable, cycle-specific fetch context."""
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from job_search_helper.cooperative_fetch import current_scan_scope
from job_search_helper.engine import Engine, State
from job_search_helper.inbox import InventoryInbox
from job_search_helper.repository import MemoryRepository
from test_fetch_pool import company, inventory

class ScanScopeTests(unittest.TestCase):
    def test_serial_parallel_and_durable_paths_scope_each_fresh_cycle(self):
        for mode in ('serial', 'parallel', 'local'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as root, redirect_stdout(StringIO()):
                repo = MemoryRepository({'Companies': [company(0)]})
                state = State(Path(root) / 'state.db')
                inbox = InventoryInbox(Path(root) / 'inbox.db', 'fixture-id')
                seen = []
                def fetch(source, url, cid, name):
                    seen.append(current_scan_scope())
                    return inventory(cid, name, url)
                engine = Engine(repo, state, fetcher=fetch, inbox=inbox)
                try:
                    cycles = []
                    for _ in range(2):
                        cycle = engine.start_cycle(['C-0'])
                        cycles.append(cycle)
                        if mode == 'serial': engine.resume(cycle)
                        elif mode == 'parallel': engine.resume_parallel(cycle, fetch_workers=2)
                        else: engine.resume_local(cycle, fetch_workers=2)
                    self.assertEqual(seen, cycles)
                    self.assertNotEqual(*cycles)
                    self.assertEqual(current_scan_scope(), '')
                finally:
                    inbox.close()
                    state.close()
