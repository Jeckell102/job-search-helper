"""Linux maintenance gate. Caller serializes transitions and drains existing readers."""
import ctypes
import os
from pathlib import Path
import stat
import tempfile


PARKED = ".s3-maintenance-package"
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
    temp = Path(tempfile.mkdtemp(prefix=".s3-marker-", dir=parked.parent))
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


def park(project, inode):
    canonical, parked = paths(project)
    if is_original(canonical, inode):
        if not os.path.lexists(parked):
            create_marker(parked)
        verify_marker(parked)
        rename(canonical, parked, 2)  # RENAME_EXCHANGE
    verify_parked(project, inode)


def publish(project, inode):
    canonical, parked = paths(project)
    if not is_original(canonical, inode):
        verify_parked(project, inode)
        rename(canonical, parked, 2)
    verify_marker(parked)
    if not is_original(canonical, inode):
        raise ValueError("Published package identity changed")
    syncdir(canonical.parent)
