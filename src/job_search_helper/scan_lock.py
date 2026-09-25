"""A process lock held across fetching, without holding a SQL transaction."""
from contextlib import contextmanager
import os


class ScanBusyError(ValueError):
    pass


@contextmanager
def scan_lock(database_path):
    resolved = database_path.resolve()
    path = resolved.with_name(resolved.name + ".scan.lock")
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(descriptor, "r+b") as handle:
        if os.name == "nt":
            import msvcrt
            if os.fstat(handle.fileno()).st_size == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            lock = lambda: msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            unlock = lambda: msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            lock = lambda: fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            unlock = lambda: fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        try:
            lock()
        except OSError as exc:
            raise ScanBusyError("Another local scan is using this catalog") from exc
        try:
            yield
        finally:
            unlock()
