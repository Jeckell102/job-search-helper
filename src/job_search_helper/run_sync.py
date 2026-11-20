"""A Sheets publisher owned by one scraper invocation, never a resident watcher.

Each worker owns its SQLite and Google connections. A busy reviewer defers
Sheets intake and delivery while local scraping continues. Intake precedes
delivery; fresh-read/expected-value guards still protect remote edits.
"""
from contextlib import ExitStack, contextmanager, nullcontext
import threading
import time

from .sheets_sync import SheetsSynchronizer
from .sqlite_repository import SQLiteRepository, timestamp
from .repository import ReviewFieldsChangedError


def pending_cells(local):
    return local.db.execute('SELECT count(*) FROM dirty').fetchone()[0]


class PublishWindow:
    """One bounded gathering window at the remote publication boundary."""
    def __init__(self, max_wait=15, target_rows=100):
        self.max_wait = max_wait
        self.target_rows = target_rows
        self.first_pending = None

    def reset(self):
        self.first_pending = None

    def ready(self, local):
        rows = local.db.execute('SELECT count(*) FROM '
                                '(SELECT DISTINCT tab,row_id FROM dirty)').fetchone()[0]
        if not rows:
            self.reset()
            return False
        now = time.monotonic()
        if self.first_pending is None:
            self.first_pending = now
        if rows >= self.target_rows or now - self.first_pending >= self.max_wait:
            self.reset()
            return True
        return False


TIMING_METRICS = ('read_seconds', 'write_seconds', 'throttle_seconds',
                  'read_requests', 'write_requests', 'read_response_bytes')


def _remote_metrics(sync):
    remote = getattr(sync, 'remote', None)
    remote = getattr(remote, 'main', remote)
    metrics = getattr(remote, 'metrics', {})
    return {key: metrics.get(key, 0) for key in TIMING_METRICS}


def _batch_timings(sync, before, started):
    elapsed = time.monotonic() - started
    after = _remote_metrics(sync)
    timings = {key: max(0, after[key] - before[key]) for key in TIMING_METRICS}
    # Request timers include client decoding and read retry/backoff. Processing
    # measures work outside requests and deliberate pacing, including local ack.
    timings['processing_seconds'] = max(0.0, elapsed - sum(timings[key] for key in
        ('read_seconds', 'write_seconds', 'throttle_seconds')))
    timings['total_seconds'] = elapsed
    return timings


def publish_pending(sync, *, stop=None, max_seconds=300, max_batches=1000, progress=None,
                    batch_progress=None, lock_factory=nullcontext, ready=None):
    """Drain acknowledged work, with bounded retries and no whole-workbook pull.

    A zero-progress batch is not success when dirty cells remain. Conflicts,
    unavailable Sheets, and newer local changes remain durable for a later run.
    None disables a budget; final delivery drains until empty or unable to progress.
    """
    started = time.monotonic()
    rows = batches = 0
    remaining = pending_cells(sync.local)
    stop_reason = 'drained'
    while remaining:
        if stop is not None and stop.is_set():
            stop_reason = 'stopped'
            break
        if max_batches is not None and batches >= max_batches:
            stop_reason = 'batch_budget'
            break
        if max_seconds is not None and time.monotonic() - started >= max_seconds:
            stop_reason = 'time_budget'
            break
        if ready is not None and not ready(sync.local):
            stop_reason = 'gathering'
            break
        before = _remote_metrics(sync)
        batch_started = time.monotonic()
        result = None
        try:
            with lock_factory():
                result = sync.publish_batch()
        finally:
            if batch_progress is not None:
                batch_progress(_batch_timings(sync, before, batch_started), result)
        count = result.get('published_rows', 0)
        rows += count
        batches += 1
        after = pending_cells(sync.local)
        if progress is not None:
            progress(rows, after, batches)
        if not count and after >= remaining:
            remaining = after
            stop_reason = 'no_progress'
            break
        remaining = after
        if remaining and lock_factory is not nullcontext:
            # Give a waiting review publisher a turn between bounded batches,
            # including the final drain of a large scraper backlog.
            time.sleep(0.1)
    return {'published_rows': rows, 'batches': batches, 'pending_cells': remaining,
            'elapsed_seconds': time.monotonic() - started, 'stop_reason': stop_reason}


STOP_REASONS = {
    'time_budget': 'publishing time budget reached',
    'batch_budget': 'publishing batch limit reached',
    'no_progress': 'no further changes could be safely published in this pass',
    'stopped': 'stop requested',
}


@contextmanager
def sync_connection(database, spreadsheet_id, request_interval=1.1):
    # The worker acquires the shared writer lock before creating Google clients.
    from .cli import get_remote_repository
    from .sheet_profile import profile_schemas
    local = SQLiteRepository(database, spreadsheet_id)
    try:
        schemas = profile_schemas(local.get_meta('sheets_profile'))
        remote = get_remote_repository(write=True, interactive=True, renew_both=True,
            min_request_interval=request_interval, schemas=schemas,
            evidence_archives=schemas is None)
        yield SheetsSynchronizer(local, remote)
    finally:
        local.close()


class RunSheetsSync:
    """One worker; busy Sheets delivery never waits on the local scraper."""

    def __init__(self, factory, *, interval=60, log=None, lock_factory=nullcontext,
                 pending_count=None, coalesce_seconds=15, target_rows=100):
        if interval <= 0:
            raise ValueError('Sheets sync interval must be positive.')
        self.factory = factory
        self.lock_factory = lock_factory
        self.pending_count = pending_count
        self.interval = interval
        self.window = PublishWindow(min(coalesce_seconds, interval), target_rows)
        self.log = log or (lambda message: print(message, flush=True))
        self.stop_requested = threading.Event()
        self.ready = threading.Event()
        self.thread = None
        self._closed = False
        self.startup_error = None
        self.final_error = None
        self.report = {}
        # Set only while the worker is delivering immediately after a due
        # external intake.  Keeping this as internal state preserves the
        # long-standing _publish(sync, phase, *, final=False) seam used by
        # lifecycle and stale-control tests.
        self._due_intake_publish = False
        self.totals = {'sheets_published_row_updates': 0, 'sheets_publish_batches': 0,
                       'sheets_pending_cells': 0, 'sheets_publish_seconds': 0.0,
                       'sheets_pull_seconds': 0.0}
        for key in (*TIMING_METRICS, 'processing_seconds', 'total_seconds'):
            self.totals['sheets_publish_' + key] = 0

    def __enter__(self):
        self.thread = threading.Thread(target=self._worker, name='run-sheets-sync', daemon=False)
        self.thread.start()
        try:
            self.ready.wait()
        except BaseException:
            self.stop_requested.set()
            self.thread.join()
            raise
        if self.startup_error is not None:
            self.thread.join()
            raise RuntimeError(f'Sheets startup sync failed; scraping was not started: {self.startup_error}') from self.startup_error
        return self

    def __exit__(self, exc_type, exc, traceback):
        """Stop this run-owned worker exactly once.

        ``run_start`` may need its final intake to complete before it makes a
        terminal Company-event admission decision while still owning the
        scraper lock.  Making close idempotent lets that boundary be explicit
        without asking the surrounding ExitStack to stop the worker twice.
        """
        if self._closed:
            return False
        self._closed = True
        self.stop_requested.set()
        self.thread.join()
        if self.final_error is not None:
            message = f'Final Sheets sync incomplete; pending changes remain saved locally: {self.final_error}'
            self.log(message)
            if exc_type is None:
                raise RuntimeError(message) from self.final_error
        return False

    def _remember_error(self, sync, error):
        try:
            with sync.local.transaction():
                sync.local.set_meta('last_error', f'{timestamp()} {type(error).__name__}: {error}')
        except Exception:
            # Do not hide the original network/storage exception with a status failure.
            pass

    def _publish(self, sync, phase, *, final=False):
        previous_rows = previous_batches = 0
        batch_timing_text = ''

        def batch_progress(timings, result):
            nonlocal batch_timing_text
            for key, value in timings.items():
                self.totals['sheets_publish_' + key] += value
            if result and result.get('held_missing_rows'):
                self.log(f"Sheets {phase}: held {result['held_missing_rows']} removed company row(s); "
                         'local history is preserved and other changes can publish on the next update.')
            batch_timing_text = (
                f"read={timings['read_seconds']:.2f}s, "
                f"processing={timings['processing_seconds']:.2f}s, "
                f"write={timings['write_seconds']:.2f}s, "
                f"pacing={timings['throttle_seconds']:.2f}s, "
                f"total={timings['total_seconds']:.2f}s; "
                f"{timings['read_requests']} read(s), {timings['write_requests']} write(s), "
                f"{timings['read_response_bytes'] / 1048576:.2f} MiB read")
            if result is None:
                self.log(f'Sheets {phase}: batch failed; {batch_timing_text}. '
                         'Pending changes remain saved locally.')

        def progress(rows, remaining, batches):
            nonlocal previous_rows, previous_batches
            self.totals['sheets_published_row_updates'] += rows - previous_rows
            self.totals['sheets_publish_batches'] += batches - previous_batches
            self.totals['sheets_pending_cells'] = remaining
            previous_rows, previous_batches = rows, batches
            self.log(f'Sheets {phase}: batch {batches} complete; {rows} row(s) published, '
                     f'{remaining} cell(s) still pending. {batch_timing_text}.')

        started = time.monotonic()
        try:
            result = publish_pending(sync,
                stop=None if final else self.stop_requested,
                max_seconds=None if final else self.interval,
                max_batches=None if final else 20,
                progress=progress, batch_progress=batch_progress,
                lock_factory=self.lock_factory,
                ready=(self.window.ready if phase == 'periodic' and not final
                       and not self._due_intake_publish else None))
        finally:
            self.totals['sheets_publish_seconds'] += time.monotonic() - started
            self.totals['sheets_pending_cells'] = pending_cells(sync.local)
        self.report[phase] = result
        if result['published_rows'] or (result['pending_cells'] and result['stop_reason'] != 'gathering') or phase == 'startup' or final:
            self.log(f"Sheets {phase}: published {result['published_rows']} row(s); "
                     f"{result['pending_cells']} pending cell(s) retained locally.")
        reason = STOP_REASONS.get(result['stop_reason'], result['stop_reason'])
        if phase == 'startup' and result['pending_cells']:
            self.log(f'Sheets startup: {reason}; starting scraping with the backlog saved locally. '
                     'Pending changes will be retried during this run; reconciliation protections remain enabled.')
        if final and result['pending_cells']:
            raise RuntimeError(f"{result['pending_cells']} cell(s) are still pending ({reason})")
        return result

    def _worker(self):
        from .cli import WriterLockBusy

        started = intake_complete = False
        # A full Sheets intake is deliberately much less frequent than the
        # cheap local pending-work poll below.  Keep its own schedule so an
        # idle run can notice a post-start Company control/source edit without
        # turning every two-second local check into a Google read.
        next_intake = None
        sync = None
        busy = False
        try:
            with ExitStack() as resources:
                def perform(phase, *, final=False, refresh_intake=False):
                    nonlocal sync, intake_complete, next_intake
                    # Acquire only for active intake/publication, never for the
                    # entire scrape or while idle between publishing intervals.
                    with self.lock_factory():
                        if sync is None:
                            sync = resources.enter_context(self.factory())
                        if not intake_complete or refresh_intake:
                            message = ('Sheets startup: pulling current company controls and manual edits...'
                                       if not intake_complete else
                                       'Sheets periodic: reconciling current company controls and manual edits...')
                            self.log(message)
                            tick = time.monotonic()
                            pull = sync.pull()
                            pull_seconds = time.monotonic() - tick
                            if not intake_complete:
                                self.report['pull'] = pull
                                self.report['pull_seconds'] = pull_seconds
                                self.totals['sheets_pull_seconds'] = pull_seconds
                            else:
                                self.report['periodic_pull'] = pull
                                self.report['periodic_pull_seconds'] = pull_seconds
                                self.totals['sheets_pull_seconds'] += pull_seconds
                            intake_complete = True
                            # Do not advance the cadence on a failed pull: its
                            # durable baseline and outbox remain untouched, and
                            # the normal periodic retry will try again later.
                            next_intake = time.monotonic() + self.interval
                    if phase == 'startup':
                        self.log(f'Sheets startup: publishing previously saved changes '
                                 f'({self.interval:g}s budget, checked between batches)...')
                    for replan in range(2):
                        try:
                            # A due intake already satisfies the periodic
                            # coalescing window, so do not let matching
                            # interval values starve a saved local update.
                            self._due_intake_publish = refresh_intake
                            try:
                                self._publish(sync, phase, final=final)
                            finally:
                                self._due_intake_publish = False
                            break
                        except ReviewFieldsChangedError:
                            # Only this typed, pre-write rejection proves
                            # the batch was not sent. Pull current manual
                            # choices/notes, then rebuild from local rows.
                            # Other failures retain exact delivery state.
                            intake_complete = False
                            if replan:
                                raise
                            self.log('Sheets choices changed since the saved plan; '
                                     'refreshing current choices and notes before retrying.')
                            tick = time.monotonic()
                            with self.lock_factory():
                                self.report['replan_pull'] = sync.pull()
                            self.totals['sheets_pull_seconds'] += time.monotonic() - tick
                            intake_complete = True
                            next_intake = time.monotonic() + self.interval
                    with sync.local.transaction():
                        sync.local.set_meta('last_sync', timestamp())
                        sync.local.set_meta('last_error', '')

                def defer(phase):
                    nonlocal busy
                    remaining = (pending_cells(sync.local) if sync is not None else
                                 self.pending_count() if self.pending_count is not None else 0)
                    self.totals['sheets_pending_cells'] = remaining
                    self.report[phase] = {'published_rows': 0, 'batches': 0,
                        'pending_cells': remaining, 'stop_reason': 'writer_busy'}
                    if phase == 'startup':
                        self.log('Sheets startup deferred: another local Sheet writer is active. '
                                 'Scraping starts now using saved local company controls; '
                                 'Sheets intake and publication will retry in the background.')
                    elif phase == 'final':
                        self.log(f'Sheets final deferred: another local Sheet writer is active; '
                                 f'{remaining} pending cell(s) remain saved locally for the next sync.')
                    elif not busy:
                        self.log('Sheets update deferred: another local Sheet writer is active; '
                                 'scraping continues and saved changes will retry in the background.')
                    busy = True

                try:
                    perform('startup')
                except ReviewFieldsChangedError as error:
                    # Both attempts were rejected before submission. Intake
                    # succeeded, so ongoing review activity should defer Sheets
                    # delivery rather than prevent local scraping from starting.
                    # perform() invalidated intake; the next pass pulls again.
                    remaining = pending_cells(sync.local)
                    self.totals['sheets_pending_cells'] = remaining
                    self.report['startup'] = {
                        'published_rows': self.totals['sheets_published_row_updates'],
                        'batches': self.totals['sheets_publish_batches'],
                        'pending_cells': remaining, 'stop_reason': 'review_fields_changed'}
                    self._remember_error(sync, error)
                    self.log(f'Sheets startup deferred: review fields changed again during publication; '
                             f'{remaining} pending cell(s) remain saved locally. '
                             'Scraping starts now; Sheets will pull fresh choices and retry '
                             'in the background with reconciliation protections enabled.')
                except WriterLockBusy:
                    defer('startup')
                except Exception as error:
                    self.startup_error = error
                    if sync is not None:
                        self._remember_error(sync, error)
                    return
                started = True
                if not busy:
                    self.log(f'Sheets ready: checking local changes every 2s; publishing at '
                             f'{self.window.target_rows} pending rows or after '
                             f'{self.window.max_wait:g}s of gathering. Exit drains immediately.')
                self.ready.set()
                def next_delay(phase):
                    if busy:
                        return min(5, self.interval)
                    report = self.report.get(phase, {})
                    if report.get('stop_reason') == 'gathering':
                        return min(2, self.interval)
                    if report.get('stop_reason') == 'review_fields_changed':
                        return self.interval
                    if report.get('pending_cells'):
                        # Continue immediately after progress; back off held work.
                        return 0 if report.get('published_rows') else self.interval
                    return min(2, self.interval)

                delay = next_delay('startup')
                while not self.stop_requested.wait(delay):
                    # Cheap local polling needs no Google request while idle.
                    intake_due = next_intake is None or time.monotonic() >= next_intake
                    if (not busy and sync is not None and not pending_cells(sync.local)
                            and not intake_due):
                        self.window.reset()
                        delay = min(2, self.interval, max(0, next_intake - time.monotonic()))
                        continue
                    try:
                        perform('periodic', refresh_intake=intake_due)
                        if busy:
                            self.log('Sheets sync resumed; local scraping continued during the deferral.')
                        busy = False
                        delay = next_delay('periodic')
                    except WriterLockBusy:
                        defer('periodic')
                        delay = min(5, self.interval)
                    except Exception as error:
                        busy = False
                        if sync is not None:
                            self._remember_error(sync, error)
                        self.log(f'Sheets update deferred ({type(error).__name__}: {error}); changes are saved locally and will retry during this run.')
                        delay = self.interval
                    # Keep local polling responsive but wake at the scheduled
                    # reconciliation boundary even when nothing is dirty.
                    if next_intake is not None:
                        delay = min(delay, max(0, next_intake - time.monotonic()))
                self.log('Sheets final: reconciling current company controls and publishing remaining saved changes...')
                try:
                    # A Company edit can occur after the last periodic intake
                    # and before scraper completion.  This last pull is the
                    # run's terminal external-read boundary; the runner will
                    # consume its durable outbox only after this worker stops.
                    perform('final', final=True, refresh_intake=True)
                except WriterLockBusy:
                    defer('final')
                except Exception as error:
                    self.final_error = error
                    if sync is not None:
                        self._remember_error(sync, error)
                self.log(f"Sheets run total: {self.totals['sheets_published_row_updates']} row update(s) "
                         f"across {self.totals['sheets_publish_batches']} publish batch(es); "
                         f"{self.totals['sheets_pending_cells']} pending cell(s). "
                         'Includes startup backlog and repeated updates to the same row.')
                self.log('Sheets sync stopped. No background watcher remains for this run.')
        except BaseException as error:
            if started:
                self.final_error = error
            else:
                self.startup_error = error
        finally:
            self.ready.set()


def run_scoped_sync(repo, database, *, interval=60, request_interval=1.1):
    from .cli import writer_lock

    def pending_count():
        local = SQLiteRepository(repo.path, repo.spreadsheet_id, readonly=True)
        try:
            return pending_cells(local)
        finally:
            local.close()

    return RunSheetsSync(lambda: sync_connection(repo.path, repo.spreadsheet_id,
        request_interval), interval=interval,
        lock_factory=lambda: writer_lock(database.parent / 'writer.lock'),
        pending_count=pending_count)
