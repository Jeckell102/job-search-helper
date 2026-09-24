"""Offline end-to-end comparison, runnable against pre-change src via PYTHONPATH.

No credentials or network calls; API pacing is disabled only in this fixture.
24 small companies expose overhead hidden by benchmarks of full-size batches.
"""
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import time

import job_search_helper.engine as engine_module
from job_search_helper.ats import Inventory
from job_search_helper.engine import Engine, State
from job_search_helper.inbox import InventoryInbox
from job_search_helper.repository import GoogleRepository
from sheets_fixture import RangeSheets
from test_fetch_pool import company, inventory


def benchmark():
    engine_module.now = lambda: '2026-09-24T12:00:00+00:00'
    companies = [company(i) for i in range(24)]
    service = RangeSheets({'Companies': companies, 'Job History': [
        {'Company': 'Old company', 'Job Key': f'old-{i}', 'Job Title': 'Existing job',
         'Job Description': 'Evidence text. ' * 140} for i in range(600)]})
    repo = GoogleRepository(service, 'offline-fixture', min_request_interval=0)
    def fetch(source, url, cid, name):
        base = inventory(cid, name, url).jobs[0]
        return Inventory('complete', [{**base, 'posting_id': str(i), 'url': f'{url}/jobs/{i}',
            'description': 'Integrate physical products with customers. ' * 25} for i in range(8)],
            source_url=url, ats='Greenhouse')
    with tempfile.TemporaryDirectory() as directory:
        state = State(Path(directory) / 'state.db')
        inbox = InventoryInbox(Path(directory) / 'inbox.db', 'offline-fixture')
        engine = Engine(repo, state, fetcher=fetch, batch_size=200, inbox=inbox, error_log_path=None)
        started = time.perf_counter()
        with redirect_stdout(StringIO()):
            cycle = engine.start_cycle([c['Company ID'] for c in companies])
            resume = getattr(engine, 'resume_local', engine.resume_parallel)
            resume(cycle, fetch_workers=5, assignment_window=100)
        result = {**repo.metrics, **engine.performance,
                  'elapsed_seconds': time.perf_counter() - started,
                  'checkpoint_seconds': state.checkpoint_seconds + inbox.checkpoint_seconds,
                  'checkpoint_payload_bytes': state.checkpoint_bytes + inbox.payload_bytes,
                  'update_entries': sum(len(b['body']['requests']) for b in service.batches)}
        rows = repo.read('Job History')
        assert len(rows) == 792, len(rows)
        assert len({row['Job Key'] for row in rows}) == 792
        assert inbox.cycles(include_blocked=True) == []
        assert state.cycle(cycle)['status'] == 'Complete'
        inbox.close()
        state.close()
    return result


if __name__ == '__main__':
    print(json.dumps(benchmark(), indent=2, sort_keys=True))
