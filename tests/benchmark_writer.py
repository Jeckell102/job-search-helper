"""Offline writer benchmark. Run with PYTHONPATH=src:tests python tests/benchmark_writer.py.

RangeSheets is an in-memory service with real range selection and transactional
updateCells application. No credentials, network, ATS fetch, or spreadsheet ID.
API retry delays/network latency are NOT modeled; pacing is disabled only on
this fixture repository. Production defaults/backoff are unchanged.
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
from job_search_helper.repository import GoogleRepository
from sheets_fixture import RangeSheets
from test_fetch_pool import company, inventory


def benchmark():
    engine_module.now = lambda: "2026-09-24T12:00:00+00:00"
    companies = [company(i) for i in range(3)]
    history = [{'Company': 'Old company', 'Job Key': f'old-{i}',
                'Job Title': 'Existing job', 'Job Description': 'Evidence text. ' * 140}
               for i in range(600)]
    service = RangeSheets({'Companies': companies, 'Job History': history})
    repo = GoogleRepository(service, 'offline-fixture', min_request_interval=0)
    metrics = {'reading_seconds': 0.0, 'staging_seconds': 0.0, 'writing_seconds': 0.0,
               'checkpoint_seconds': 0.0, 'prepare_seconds': 0.0, 'build_requests_seconds': 0.0,
               'throttle_seconds': 0.0}
    execute = repo._execute
    def measured_execute(request, action):
        started = time.perf_counter()
        try:
            return execute(request, action)
        finally:
            metrics['reading_seconds' if action == 'read' else 'writing_seconds'] += time.perf_counter() - started
    repo._execute = measured_execute
    commit = repo.commit
    def measured_commit(operations):
        result = commit(operations)
        for key in ('prepare_seconds', 'build_requests_seconds'):
            metrics[key] += result.get('timings', {}).get(key, 0)
        return result
    repo.commit = measured_commit
    def fetch(source, url, cid, name):
        base = inventory(cid, name, url).jobs[0]
        jobs = [{**base, 'posting_id': str(i), 'url': f'{url}/jobs/{i}',
                 'description': 'Integrate physical products with customers. ' * 25} for i in range(200)]
        return Inventory('complete', jobs, source_url=url, ats='Greenhouse')
    with tempfile.TemporaryDirectory() as directory:
        state = State(Path(directory) / 'state.db')
        try:
            from job_search_helper.inbox import InventoryInbox
        except ImportError:
            inbox = None
        else:
            inbox = InventoryInbox(Path(directory) / 'inbox.db', 'offline-fixture')
        extra = {'inbox': inbox} if inbox is not None else {}
        engine = Engine(repo, state, fetcher=fetch, batch_size=200, error_log_path=None, **extra)
        for name in ('save_cycle', 'apply_buffer'):
            original = getattr(state, name)
            def measured_checkpoint(*args, _original=original, **kwargs):
                started = time.perf_counter()
                try:
                    return _original(*args, **kwargs)
                finally:
                    metrics['checkpoint_seconds'] += time.perf_counter() - started
            setattr(state, name, measured_checkpoint)
        stage = engine._stage_posting
        def measured_stage(*args, **kwargs):
            started = time.perf_counter()
            try:
                return stage(*args, **kwargs)
            finally:
                metrics['staging_seconds'] += time.perf_counter() - started
        engine._stage_posting = measured_stage
        started = time.perf_counter()
        with redirect_stdout(StringIO()):
            cycle = engine.start_cycle([c['Company ID'] for c in companies])
            engine.resume_parallel(cycle, fetch_workers=5, assignment_window=100)
        metrics['elapsed_seconds'] = time.perf_counter() - started
        metrics.update(read_requests=len(service.get_calls), write_requests=len(service.batches),
                       read_response_bytes=service.response_bytes, write_payload_bytes=service.request_bytes,
                       update_entries=sum(len(b['body']['requests']) for b in service.batches))
        rows = repo.read('Job History')
        assert len(rows) == 1200, len(rows)
        assert len({r['Job Key'] for r in rows}) == 1200
        if inbox is not None:
            metrics['checkpoint_seconds'] += inbox.checkpoint_seconds
            metrics['inventory_payload_bytes'] = inbox.payload_bytes
            inbox.close()
        state.close()
    print(json.dumps(metrics, indent=2, sort_keys=True))


if __name__ == '__main__':
    benchmark()
