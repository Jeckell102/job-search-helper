"""Durable local planning with bounded, cross-company Sheets synchronization.

Inventories and frozen operations survive independently of cycle checkpoints.
Only this controller uses Sheets. Producers store payloads and queue IDs, so
slow uploads never bound the number of inventories safely held on disk.
"""
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import copy
import json
from queue import Empty, Full, Queue, SimpleQueue
from threading import Event
import time
from urllib.parse import urlsplit

from .ats import Inventory
from .browser_progress import BrowserProgress
from .batching import PlanningRepository, PendingState
from .dashboard import TerminalDashboard
from .engine import MAX_FETCH_WORKERS, inventory_payload, now
from .repository import RepositoryError, UncertainWriteError


def _stale_scoped_taleo_payload(company, payload):
    """Old Textron payloads used the shared Taleo board instead of its scoped page."""
    from .taleo_careers import supports_scoped_taleo_careers
    source_host = urlsplit(str(payload.get('source_url', ''))).hostname or ''
    return (supports_scoped_taleo_careers(
        str(company.get('ATS / Source', '')), str(company.get('Official Careers URL', ''))
    ) and source_host.endswith('.taleo.net'))


class LocalPipeline:
    def __init__(self, engine, cycle_id, sync_interval=60):
        if engine.inbox is None:
            raise ValueError("Local processing requires a durable inventory inbox")
        if not 1 <= sync_interval <= 3600:
            raise ValueError("Sync interval must be between 1 and 3600 seconds")
        self.engine = engine
        self.repo, self.state, self.inbox = engine.repo, engine.state, engine.inbox
        self.cycle = self.state.cycle(cycle_id) or engine._recover(cycle_id)
        self.cid = cycle_id
        self.interval = sync_interval
        self.planner = PlanningRepository(self.repo)
        self.companies = {r['Company ID']: r for r in self.planner.read('Companies') if r.get('Company ID')}
        self.pending = deque()
        self.ignored = set()
        self.last_sync = time.monotonic()
        self.last_cycle_sync = self.last_sync
        self.synced_stages = None
        self.dashboard = None

    def refresh_company_controls(self):
        headers = [
            'Company ID', 'Company', 'Company Status', 'Claimed By', 'Claim Token',
            'Automatic Retry?', 'Scan State', 'Official Careers URL', 'ATS / Source',
        ]
        try:
            read_columns = getattr(self.repo, 'read_cached_columns', self.repo.read_columns)
            numbered = read_columns('Companies', headers)
            rows = [row for _, row in numbered if row.get('Company ID')]
        except AttributeError:
            rows = [row for row in self.repo.read('Companies') if row.get('Company ID')]
        refreshed = {}
        for row in rows:
            current = self.companies.get(row['Company ID'], {})
            updated = copy.deepcopy(current)
            updated.update(row)
            refreshed.setdefault(row['Company ID'], []).append(updated)
        self.companies = {
            cid: matches[0]
            for cid, matches in refreshed.items()
            if len(matches) == 1
        }
        return refreshed

    def refresh_queue_status(self):
        if self.dashboard is None:
            return
        summary = self.inbox.summary(self.cid)
        self.dashboard.local_queue(summary['ready'], summary['planned'])

    def fail(self, cid, exc, context):
        self.ignored.add(cid)
        self.inbox.block(self.cid, cid)
        self.refresh_queue_status()
        self.engine._log_company_error(self.cycle, self.companies.get(cid, {'Company': cid}),
                                       self.cycle['companies'][cid], exc, context)
        # Error recording must not stop unrelated company results. The local
        # log + retained plan remain authoritative if this status write fails.
        try:
            self.repo.commit([self.engine._company_op({'Company ID': cid}, {
                'Scan State': 'Blocked / Manual Review', 'Blocked Reason': str(exc)[:900],
                'Automatic Retry?': 'No', 'Coverage Status': 'Incomplete inventory',
                'Next Action': 'Inspect scraper errors, resolve the issue, then sync --retry-blocked',
                'Record Updated': now()})])
        except Exception as status_error:
            self.engine._log_company_error(self.cycle, self.companies.get(cid, {'Company': cid}),
                                           self.cycle['companies'][cid], status_error, 'recording company error')

    def stage(self, cid):
        saved = self.inbox.get(self.cid, cid)
        if saved is None:
            raise ValueError('Durable inventory disappeared before planning')
        payload, blocked = saved
        if blocked or cid in self.ignored:
            return
        item = self.cycle['companies'][cid]
        plan = self.inbox.plan(self.cid, cid)
        if plan is not None:
            if plan[1] == len(plan[0]['operations']):
                self.finish(cid, plan[0])
            else:
                try:
                    self.planner.commit(plan[0]['operations'][plan[1]:])
                except RepositoryError as exc:
                    self.fail(cid, exc, 'restoring local plan')
                    return
                self.pending.append(cid)
            return
        # Older ADP MyJobs inventories assigned the board URL to every job.
        # Repair only unplanned payloads; frozen operations must replay exactly.
        from .adp_myjobs import repair_saved_urls
        payload = repair_saved_urls(payload)
        company = self.companies.get(cid)
        if company is None:
            self.fail(cid, ValueError('Company removed from workbook'), 'planning inventory')
            return
        started = time.monotonic()
        self.dashboard.writer_message('Processing locally', company['Company'])
        # Use a company transaction in the planning cache. Roll back a failed
        # plan, including newly inserted rows, without another Sheets download.
        lengths = {tab: len(rows) for tab, rows in self.planner.rows.items()}
        originals = {}
        commit = self.planner.commit
        def track(operations):
            for op in operations:
                for number, row in self.planner.indexes[op['tab']].matches(op['identity']):
                    originals.setdefault((op['tab'], number), copy.deepcopy(row))
            return commit(operations)
        self.planner.commit = track
        self.planner.begin()
        base_repo, base_state = self.engine.repo, self.engine.state
        local_cycle = copy.deepcopy(self.cycle)
        local_item = local_cycle['companies'][cid]
        local_item.update(payload, stage='inventory', staging_complete=True, next_job_index=0)
        self.engine.repo, self.engine.state = self.planner, PendingState(self.state)
        try:
            status = payload.get('inventory_status')
            if status in {'failed', 'blocked', 'unsupported'}:
                local_item['stage'] = status
                self.planner.commit([self.engine._company_op(company, {
                    'Scan State': 'Blocked / Manual Review', 'Active Cycle ID': self.cid,
                    'Blocked Reason': payload.get('reason', ''), 'Automatic Retry?': 'No',
                    'Coverage Status': 'Incomplete inventory', 'Last Scan Result': status,
                    'Next Action': 'Verify official careers URL / inspect manually; retry only on request',
                    **self.engine._ats_update(company, payload.get('ats', '')), 'Record Updated': now()})])
            else:
                self.engine._verify_same_board({'Official Careers URL': payload.get('requested_url', '')}, company)
                for posting in payload.get('jobs', []):
                    self.engine._stage_posting(local_cycle, company, posting)
                if status == 'complete':
                    self.engine._reconcile_absences(local_cycle, company, payload.get('jobs', []))
                self.engine._finish_company(local_cycle, company)
            # Preserve the user's manual opportunity decision while allowing the
            # writer to use narrow commit-time reads. Other fields come from the
            # local planning snapshot and may be refreshed on the next scan.
            for op in self.planner.operations:
                if op['tab'] == 'Job History':
                    expected = op.get('expected', {})
                    for number, row in self.planner.indexes['Job History'].matches(op['identity']):
                        prior = originals.get(('Job History', number), {})
                        manual = expected.get('Added to Opportunities?', prior.get('Added to Opportunities?', ''))
                        op['expected'] = {'Added to Opportunities?': manual}
                        if str(manual).strip().casefold() == 'manual review':
                            for field in ('Review Status', 'Source Hash'):
                                op['expected'][field] = expected.get(field, prior.get(field, ''))
                        # Legacy Job Keys are migrated using the unique job URL.
                        # Retain this guard so a concurrent identity change is
                        # replanned instead of overwritten.
                        if 'Job Key' in expected:
                            op['expected']['Job Key'] = expected['Job Key']
            final = {k: v for k, v in local_item.items() if k != 'jobs'}
            plan = {'operations': self.planner.operations, 'final': final,
                    'requested_url': payload.get('requested_url', '')}
            self.inbox.save_plan(self.cid, cid, plan)
        except Exception as exc:
            for tab, length in lengths.items():
                del self.planner.rows[tab][length:]
            for (tab, number), row in originals.items():
                if number < lengths[tab]:
                    self.planner.rows[tab][number] = row
            self.planner._reindex()
            self.engine.repo, self.engine.state = base_repo, base_state
            self.fail(cid, exc, 'planning inventory')
            return
        finally:
            self.engine.repo, self.engine.state = base_repo, base_state
            self.planner.commit = commit
            self.engine.performance['staging_seconds'] += time.monotonic() - started
        item.update({k: v for k, v in payload.items() if k != 'jobs'}, stage='inventory',
                    durable_inventory=True, locally_processed=True)
        self.state.save_cycle(self.cycle)
        self.dashboard.locally_processed(len(payload.get('jobs', [])))
        self.engine.performance['locally_processed_jobs'] = self.dashboard.local_job_count
        if payload.get('inventory_status') == 'failed':
            # Log source failures, but let their prepared status synchronize.
            self.engine._log_company_error(self.cycle, company, item,
                RuntimeError(payload.get('reason') or 'Fetch failed'), 'fetching inventory')
            item['stage'] = 'inventory'
            self.state.save_cycle(self.cycle)
        self.pending.append(cid)
        self.refresh_queue_status()

    def finish(self, cid, plan):
        self.cycle['companies'][cid].update(plan['final'])
        self.state.save_cycle(self.cycle)
        # Checkpoint first: a crash before deletion leaves a fully acknowledged
        # plan that finish() can safely replay without any Sheets writes.
        if plan['final']['stage'] in {'complete', 'partial'} or (
                plan['final'].get('browser_pending_urls') or plan['final'].get('browser_discovery_incomplete')):
            self.inbox.acknowledge(self.cid, cid)
        else:
            self.inbox.block(self.cid, cid)
        self.refresh_queue_status()

    def upload(self, entries):
        if not entries:
            return
        by_id = self.refresh_company_controls()
        valid = []
        for cid, cursor, ops in entries:
            if cid in self.ignored:
                continue
            plan = self.inbox.plan(self.cid, cid)[0]
            try:
                matches = by_id.get(cid, [])
                if len(matches) != 1:
                    raise ValueError('Company removed or identity ambiguous')
                company = matches[0]
                if str(company.get('Company Status', '')).strip().casefold() in {'pause', 'paused', 'remove'}:
                    raise ValueError('Company paused; saved results retained')
                if company.get('Claimed By') or company.get('Claim Token'):
                    raise ValueError('Company has an external claim; saved results retained')
                if str(company.get('Automatic Retry?', '')).casefold() == 'no' and company.get('Scan State') == 'Blocked / Manual Review' and not self.retry_blocked:
                    raise ValueError('Company placed on manual-review hold; explicit retry required')
                self.engine._verify_same_board({'Official Careers URL': plan['requested_url']}, company)
            except ValueError as exc:
                self.fail(cid, exc, 'checking company before sync')
                continue
            valid.append((cid, cursor, ops))
        entries = valid
        if not entries:
            return
        operations = [op for _, _, ops in entries for op in ops]
        self.dashboard.writer_message('Syncing Sheets', f'{len(entries)} companies', f'{len(operations)} changes')
        try:
            result = self.repo.commit(operations)
        except Exception as exc:
            if not isinstance(exc, RepositoryError) or isinstance(exc, UncertainWriteError) or exc.__cause__ is not None:
                # No automatic retry of an ambiguous write or exhausted API
                # backoff. Retain exact plans and continue other companies.
                for cid, _, _ in entries:
                    self.fail(cid, exc, 'syncing local changes')
                return
            if len(entries) > 1:
                # Validation failed before any write. Isolate the company;
                # unrelated companies can still synchronize.
                middle = len(entries) // 2
                self.upload(entries[:middle])
                self.upload(entries[middle:])
                return
            cid, cursor, ops = entries[0]
            if 'safety threshold' in str(exc) and len(ops) > 1:
                middle = len(ops) // 2
                self.upload([(cid, cursor, ops[:middle])])
                if cid not in self.ignored:
                    self.upload([(cid, cursor + middle, ops[middle:])])
                return
            self.inbox.discard_plan(self.cid, cid)
            self.fail(cid, exc, 'syncing local changes')
            return
        self.engine._report_new_jobs(result)
        # A lost response or Ctrl+C before this transaction replays the same
        # keyed operations with the original timestamp and expectations.
        self.inbox.advance(self.cid, {cid: cursor + len(ops) for cid, cursor, ops in entries})
        self.engine.performance['sync_batches'] = self.engine.performance.get('sync_batches', 0) + 1
        self.planner.accept_commit()
        self.engine._checkpoint()

    def flush(self, full_only=False):
        if not self.pending:
            return
        active = [(cid, *self.inbox.plan(self.cid, cid)) for cid in self.pending if cid not in self.ignored]
        self.pending.clear()
        entries, size, count = [], 0, 0
        for cid, plan, cursor in active:
            while cursor < len(plan['operations']) and cid not in self.ignored:
                op = plan['operations'][cursor]
                cost = len(json.dumps(op, ensure_ascii=True).encode())
                # This is a conservative planning budget; the repository also
                # enforces the actual 2.2 MB encoded API payload limit.
                if entries and (count >= self.engine.batch_size or size + cost > 500_000):
                    self.upload(entries)
                    entries, size, count = [], 0, 0
                if cid in self.ignored:
                    break
                if entries and entries[-1][0] == cid:
                    entries[-1][2].append(op)
                else:
                    entries.append((cid, cursor, [op]))
                cursor += 1
                count += 1
                size += cost
        # Carry an undersized tail into the next company's batch. The frozen
        # operations and acknowledged cursor remain in SQLite until drained.
        if not full_only or count >= self.engine.batch_size or size >= 500_000:
            self.upload(entries)
        for cid, plan, _ in active:
            if cid not in self.ignored:
                saved = self.inbox.plan(self.cid, cid)
                if saved[1] == len(plan['operations']):
                    self.finish(cid, plan)
                else:
                    self.pending.append(cid)
        # Frequent full batches must not keep postponing the partial-batch
        # deadline. Only a complete drain resets this timer.
        if not full_only:
            self.last_sync = time.monotonic()
        self.refresh_queue_status()

    def sync_cycle_progress(self, force=False):
        stages = tuple(item['stage'] for item in self.cycle['companies'].values())
        # The last loop iteration may already have written the final status.
        # Forcing completion bypasses the timer, not this no-change check.
        if stages == self.synced_stages:
            return
        if not force and time.monotonic() - self.last_cycle_sync < self.interval:
            return
        self.engine._sync_cycle(self.cycle)
        self.synced_stages = stages
        self.last_cycle_sync = time.monotonic()

    def run(self, fetch_workers=5, assignment_window=100, sync_only=False, defer_sync=False, retry_blocked=False,
            retry_partial=False):
        if not 1 <= fetch_workers <= MAX_FETCH_WORKERS or not 1 <= assignment_window <= 100:
            raise ValueError(f'Fetch workers must be 1-{MAX_FETCH_WORKERS} and assignment window 1-100')
        if sync_only and defer_sync:
            raise ValueError('Deferred fetching and sync-only cannot be combined')
        self.retry_blocked = retry_blocked
        self.dashboard = TerminalDashboard(fetch_workers)
        self.engine._dashboard = self.dashboard
        self.dashboard.start()
        self.refresh_company_controls()
        self.refresh_queue_status()
        completed = SimpleQueue()
        handled = set()
        snapshots = []
        saved_ids = set(self.inbox.pending(self.cid, include_blocked=True))
        for cid, item in self.cycle['companies'].items():
            company = self.companies.get(cid)
            sheet_queued = company is not None and str(company.get('Scan State', '')).strip().casefold() == 'queued'
            saved = self.inbox.get(self.cid, cid) if cid in saved_ids else None
            if saved:
                payload, blocked = saved
                stale_scoped_payload = company is not None and _stale_scoped_taleo_payload(company, payload)
                failed_fetch_payload = (not payload.get('jobs')
                                        and payload.get('inventory_status') in {'failed', 'blocked', 'unsupported'})
                retry_fetch_payload = failed_fetch_payload or stale_scoped_payload
                sheet_retry = sheet_queued and (item.get('stage') in {'blocked', 'failed', 'unsupported'} or retry_fetch_payload)
                if blocked and not (retry_blocked or sheet_retry):
                    continue
                if (retry_blocked or sheet_retry) and not sync_only and retry_fetch_payload:
                    self.inbox.acknowledge(self.cid, cid)
                    saved = None
                    item['stage'] = 'queued'
                else:
                    self.inbox.unblock(self.cid, cid)
                    item['stage'] = 'inventory'
                    completed.put(cid)
                    continue
            if sheet_queued and item.get('stage') in {'blocked', 'failed', 'unsupported'}:
                item['stage'] = 'queued'
            if item['stage'] == 'inventory':
                item['stage'] = 'queued'  # Legacy interruption without a saved inventory.
            if sync_only or item['stage'] == 'complete':
                continue
            if item['stage'] == 'partial':
                if not retry_partial:
                    continue
                item['stage'] = 'queued'
            if item['stage'] != 'queued' and not retry_blocked:
                continue
            company = self.companies.get(cid)
            if company is None:
                self.fail(cid, ValueError('Company removed from workbook'), 'assigning company')
                continue
            if str(company.get('Company Status', '')).strip().casefold() in {'pause', 'paused', 'remove'}:
                item.update(stage='paused', reason='User paused company')
                continue
            if company.get('Claimed By') or company.get('Claim Token'):
                self.fail(cid, ValueError('Company has external claim'), 'assigning company')
                continue
            if company.get('Scan State') == 'Blocked / Manual Review' and str(company.get('Automatic Retry?', '')).casefold() == 'no' and not retry_blocked:
                item.update(stage='blocked', reason='Manual-review hold; explicit retry required')
                continue
            item['stage'] = 'queued'
            snapshots.append(copy.deepcopy(company))
        self.cycle.pop('completed_at', None)
        self.cycle['status'] = 'In Progress'
        self.state.save_cycle(self.cycle)
        assignments = Queue(maxsize=max(fetch_workers, assignment_window))
        stop = Event()
        def feed():
            for snapshot in snapshots:
                while not stop.is_set():
                    try:
                        assignments.put(snapshot, timeout=.1)
                        break
                    except Full:
                        continue
                if stop.is_set():
                    return
            for _ in range(fetch_workers):
                while not stop.is_set():
                    try:
                        assignments.put(None, timeout=.1)
                        break
                    except Full:
                        continue
        def worker(slot):
            while not stop.is_set():
                try:
                    company = assignments.get(timeout=.1)
                except Empty:
                    continue
                if company is None:
                    return
                cid = company['Company ID']
                self.dashboard.worker_fetching(slot, company['Company'])
                try:
                    fetch = getattr(self.engine.fetcher, 'fetch_with_progress', None)
                    args = (str(company.get('ATS / Source', '')), company['Official Careers URL'], cid, company['Company'])
                    if fetch is not None:
                        result = fetch(*args, progress_factory=lambda source: BrowserProgress(
                            self.inbox, self.cid, cid, source))
                    else:
                        result = self.engine.fetcher(*args)
                    if not isinstance(result, Inventory):
                        raise ValueError('Invalid inventory')
                except Exception as exc:
                    result = Inventory('failed', reason=f'Fetch worker failed: {type(exc).__name__}')
                self.inbox.save(self.cid, cid, inventory_payload(result, company))
                self.refresh_queue_status()
                completed.put(cid)
                self.dashboard.worker_handoff(
                    slot, company['Company'], len(result.jobs), status=result.status,
                    pending_urls=len(result.browser_pending_urls),
                    discovery_incomplete=result.browser_discovery_incomplete)
        pool = ThreadPoolExecutor(max_workers=fetch_workers + 1)
        try:
            producer = pool.submit(feed)
            workers = [pool.submit(worker, slot) for slot in range(1, fetch_workers + 1)]
            while True:
                try:
                    cid = completed.get(timeout=.1)
                except Empty:
                    if all(f.done() for f in workers):
                        # Surface durability failures; do not silently lose a
                        # successful fetch whose SQLite save failed.
                        for future in workers:
                            future.result()
                        producer.result()
                        break
                else:
                    handled.add(cid)
                    if defer_sync:
                        payload = self.inbox.get(self.cid, cid)[0]
                        self.cycle['companies'][cid].update(
                            {k: v for k, v in payload.items() if k != 'jobs'}, stage='inventory', durable_inventory=True)
                        self.state.save_cycle(self.cycle)
                        self.refresh_queue_status()
                    else:
                        self.stage(cid)
                if not defer_sync and self.pending:
                    count = sum(len(self.inbox.plan(self.cid, cid)[0]['operations']) - self.inbox.plan(self.cid, cid)[1]
                                for cid in self.pending)
                    if time.monotonic() - self.last_sync >= self.interval:
                        self.flush()
                    elif count >= self.engine.batch_size:
                        self.flush(full_only=True)
                if not defer_sync:
                    self.sync_cycle_progress()
            if not defer_sync:
                self.flush()
            self.sync_cycle_progress(force=True)
            self.dashboard.writer_message('Saved locally' if defer_sync else self.cycle['status'])
        finally:
            stop.set()
            pool.shutdown(wait=True, cancel_futures=True)
        result = self.engine.status(self.cid)
        attempted = handled | self.ignored
        stages = [self.cycle['companies'][cid]['stage'] for cid in attempted]
        result['run_counts'] = {
            'new_jobs': self.dashboard.new_job_count,
            'successful': stages.count('complete'),
            'partial': stages.count('partial'),
            'skipped': len(set(self.cycle['companies']) - attempted),
            'failed': sum(stage in {'blocked', 'failed', 'unsupported'} for stage in stages),
            'pending': sum(stage in {'queued', 'inventory'} for stage in stages),
        }
        return result
