import multiprocessing as mp
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, '/home/chris/job-search-helper_old/dev/wrapper-coder/tools')
import coordinator as c


def owner(base, ready, release, output):
    co = c.Coordinator(base)
    co.run = lambda: release.wait(5)
    try:
        co.start()
        output.put(('owner', 'started'))
        ready.set()
        release.wait(5)
    except Exception as exc:
        output.put(('owner_error', f'{type(exc).__name__}: {exc}'))
    finally:
        release.set()
        if getattr(co, 'thread', None):
            co.thread.join(1)
        if co.scheduler_lock:
            co.scheduler_lock.close()


def contender(base, ready, release, output):
    ready.wait(5)
    co = c.Coordinator(base)
    co.run = lambda: release.wait(5)
    try:
        co.start()
        output.put(('contender', 'started'))
    except Exception as exc:
        output.put(('contender_error', f'{type(exc).__name__}: {exc}'))
    finally:
        if getattr(co, 'thread', None):
            release.set()
            co.thread.join(1)
        if co.scheduler_lock:
            co.scheduler_lock.close()


if __name__ == '__main__':
    ctx = mp.get_context('spawn')
    base = tempfile.mkdtemp(prefix='qa-cross-process-lock-')
    ready, release, output = ctx.Event(), ctx.Event(), ctx.Queue()
    first = ctx.Process(target=owner, args=(base, ready, release, output))
    second = ctx.Process(target=contender, args=(base, ready, release, output))
    first.start(); second.start()
    second.join(8); release.set(); first.join(8)
    results = []
    while not output.empty():
        results.append(output.get())
    print(results)
