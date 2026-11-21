"""Linux maintenance gate. Caller serializes transitions and drains existing readers."""
import ctypes
import os
from pathlib import Path
import stat
import tempfile


PARKED = ".s4-maintenance-package"
MESSAGE = b'raise ImportError("Job Search Helper is held for source maintenance")\n'


def syncdir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def rename(left, right, flags):
    call = ctypes.CDLL(None, use_errno=True).renameat2
    call.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    call.restype = ctypes.c_int
    if call(-100, os.fsencode(left), -100, os.fsencode(right), flags):
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err), str(left), None, str(right))
    syncdir(left.parent)


def paths(project):
    src = Path(project) / "src"
    if src.resolve(strict=True) != src.absolute():
        raise ValueError("Unexpected source directory alias")
    return src / "job_search_helper", src / PARKED


def is_original(path, inode):
    value = path.lstat()
    return stat.S_ISDIR(value.st_mode) and value.st_ino == inode and value.st_dev == path.parent.stat().st_dev


def verify_marker(path):
    attrs = path.lstat()
    if not stat.S_ISDIR(attrs.st_mode) or stat.S_IMODE(attrs.st_mode) != 0o555:
        raise ValueError("Unexpected maintenance marker directory")
    marker = path / "__init__.py"
    if list(path.iterdir()) != [marker] or not stat.S_ISREG(marker.lstat().st_mode):
        raise ValueError("Unexpected maintenance marker contents")
    if marker.read_bytes() != MESSAGE or stat.S_IMODE(marker.stat().st_mode) != 0o444:
        raise ValueError("Unexpected maintenance marker bytes or permissions")


def create_marker(parked):
    temp = Path(tempfile.mkdtemp(prefix=".s4-marker-", dir=parked.parent))
    marker = temp / "__init__.py"
    with marker.open("xb") as stream:
        stream.write(MESSAGE)
        stream.flush()
        os.fchmod(stream.fileno(), 0o444)
        os.fsync(stream.fileno())
    temp.chmod(0o555)
    syncdir(temp)
    rename(temp, parked, 1)  # RENAME_NOREPLACE


def verify_parked(project, inode):
    canonical, parked = paths(project)
    verify_marker(canonical)
    if not is_original(parked, inode):
        raise ValueError("Parked package identity changed")
    syncdir(canonical.parent)


def guard_identity(path):
    def identity(attrs):
        return [attrs.st_dev, attrs.st_ino, stat.S_IMODE(attrs.st_mode), attrs.st_uid, attrs.st_gid]

    marker = path / "__init__.py"
    directory = path.lstat()
    if not stat.S_ISDIR(directory.st_mode) or stat.S_IMODE(directory.st_mode) != 0o555 or list(path.iterdir()) != [marker]:
        raise ValueError("Unexpected maintenance marker directory or contents")
    with os.fdopen(os.open(marker, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
        opened = os.fstat(stream.fileno())
        if (not stat.S_ISREG(opened.st_mode) or stat.S_IMODE(opened.st_mode) != 0o444
                or opened.st_nlink != 1 or stream.read(len(MESSAGE) + 1) != MESSAGE):
            raise ValueError("Unexpected maintenance marker file")
        named = marker.lstat()
        if (identity(opened), opened.st_nlink, opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns) != (
                identity(named), named.st_nlink, named.st_size, named.st_mtime_ns, named.st_ctime_ns):
            raise ValueError("Maintenance marker file changed while being read")
    after = path.lstat()
    if (identity(directory), directory.st_mtime_ns, directory.st_ctime_ns) != (
            identity(after), after.st_mtime_ns, after.st_ctime_ns):
        raise ValueError("Maintenance marker changed while being read")
    return {"directory": identity(directory), "marker": identity(opened)}


def verify_guard_identity(path, approved_identity):
    if guard_identity(path) != approved_identity:
        raise ValueError("Approved maintenance marker identity changed")


def park(project, inode, *, approved_guard=None):
    canonical, parked = paths(project)
    if is_original(canonical, inode):
        if approved_guard is None:
            if not os.path.lexists(parked):
                create_marker(parked)
            verify_marker(parked)
        else:
            verify_guard_identity(parked, approved_guard)
        rename(canonical, parked, 2)  # RENAME_EXCHANGE
    verify_parked(project, inode)
    if approved_guard is not None:
        verify_guard_identity(canonical, approved_guard)


def publish(project, inode, *, approved_guard=None):
    canonical, parked = paths(project)
    if not is_original(canonical, inode):
        verify_parked(project, inode)
        if approved_guard is not None:
            verify_guard_identity(canonical, approved_guard)
        rename(canonical, parked, 2)
    verify_marker(parked)
    if approved_guard is not None:
        verify_guard_identity(parked, approved_guard)
    if not is_original(canonical, inode):
        raise ValueError("Published package identity changed")
    syncdir(canonical.parent)
