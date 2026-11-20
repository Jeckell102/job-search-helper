"""Let idle company workers fetch independent details for busy workers.

This scheduler creates no threads and never owns inventories or persistence.
Company runners bind their existing workers; adapters explicitly opt in with
``iter_details`` only when their requests can safely run on another thread.
Owners also execute their own detail tasks, so all workers can own companies
without waiting for spare executor capacity. Only idle workers call ``help_*``.
"""
from collections import deque
from concurrent.futures import Future
from contextlib import contextmanager
from dataclasses import dataclass
from threading import Condition, Lock, local
import time


_worker = local()


@dataclass(eq=False)
class _Detail:
    group: object
    company: str
    function: object
    item: object
    future: Future


class CooperativeFetchWork:
    """Run-scoped detail queue shared by a fixed number of company workers.

    Each active iterator has at most ``max_pending`` outstanding details. Results
    are yielded in input order even when helpers finish them out of order. Closing
    an iterator cancels its unclaimed work and waits for already started requests;
    the company coordinator can then safely reconcile or report a partial result.
    """

    def __init__(self, company_count=0, *, max_pending=10, scope_id=''):
        if company_count < 0 or max_pending < 1:
            raise ValueError('Company count must be nonnegative and detail window positive')
        self.max_pending = max_pending
        self.scope_id = scope_id
        self._remaining = company_count
        self._condition = Condition()
        self._queue = deque()
        self._resource_lock = Lock()
        self._resources = {}

    @contextmanager
    def bind_worker(self, company_name=''):
        previous = getattr(_worker, 'binding', None)
        _worker.binding = (self, company_name)
        try:
            yield
        finally:
            _worker.binding = previous

    def company_added(self, count=1):
        if count < 0:
            raise ValueError('Added company count must be nonnegative')
        with self._condition:
            self._remaining += count
            self._condition.notify_all()

    def company_done(self):
        with self._condition:
            if self._remaining <= 0:
                raise RuntimeError('Company completion has no matching assignment')
            self._remaining -= 1
            self._condition.notify_all()

    def get_shared_resource(self, key, factory):
        """Share run-local request limits without sharing browser sessions."""
        with self._resource_lock:
            if key not in self._resources:
                self._resources[key] = factory()
            return self._resources[key]

    def _claim_locked(self, group=None):
        for task in self._queue:
            if group is None or task.group is group:
                self._queue.remove(task)
                if task.future.set_running_or_notify_cancel():
                    return task
                break
        return None

    def _execute(self, task):
        try:
            with self.bind_worker(task.company):
                result = task.function(task.item)
        except BaseException as exc:
            task.future.set_exception(exc)
        else:
            task.future.set_result(result)
        finally:
            with self._condition:
                self._condition.notify_all()

    def help_one(self, timeout=0, on_help=None):
        """Execute at most one available detail using the calling idle worker."""
        deadline = time.monotonic() + timeout
        with self._condition:
            task = self._claim_locked()
            while task is None and timeout > 0:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
                task = self._claim_locked()
        if task is None:
            return False
        # A dashboard failure must not leave a claimed future unfinished.
        try:
            if on_help is not None:
                on_help(task.company)
        finally:
            self._execute(task)
        return True

    def help_until_finished(self, stop_event, on_help=None):
        """Keep an idle worker available until all company coordinators finish."""
        while not stop_event.is_set():
            with self._condition:
                if self._remaining == 0:
                    return
            self.help_one(timeout=.1, on_help=on_help)

    def iter_details(self, function, items, company_name=''):
        group = object()
        pending = deque()
        source = iter(items)
        exhausted = False
        try:
            while pending or not exhausted:
                while len(pending) < self.max_pending and not exhausted:
                    try:
                        item = next(source)
                    except StopIteration:
                        exhausted = True
                        break
                    task = _Detail(group, company_name, function, item, Future())
                    pending.append(task)
                    with self._condition:
                        self._queue.append(task)
                        self._condition.notify_all()
                if not pending:
                    break
                first = pending[0]
                while not first.future.done():
                    with self._condition:
                        task = self._claim_locked(group)
                        if task is None and not first.future.done():
                            self._condition.wait(.1)
                    if task is not None:
                        self._execute(task)
                result = first.future.result()
                pending.popleft()
                yield result
        finally:
            with self._condition:
                for task in list(self._queue):
                    if task.group is group:
                        self._queue.remove(task)
                        task.future.cancel()
                # Started HTTP requests cannot be interrupted safely. Drain them
                # before this coordinator rechecks the listing or saves results.
                while any(task.future.running() for task in pending):
                    self._condition.wait(.1)


def iter_details(function, items):
    """Yield ordered detail results; close early-exited iterators to drain work."""
    binding = getattr(_worker, 'binding', None)
    if binding is None:
        yield from map(function, items)
    else:
        work, company_name = binding
        yield from work.iter_details(function, items, company_name)


def get_shared_resource(key, factory):
    """Return a run-scoped resource when called inside a company worker."""
    binding = getattr(_worker, 'binding', None)
    return factory() if binding is None else binding[0].get_shared_resource(key, factory)


def current_scan_scope():
    """Identify the owning scan without transferring ownership to helpers."""
    binding = getattr(_worker, 'binding', None)
    return binding[0].scope_id if binding is not None else ''
