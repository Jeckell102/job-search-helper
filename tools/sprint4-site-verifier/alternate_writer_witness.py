"""Read-only check of a previously authorized alternate checkout cover."""
from dataclasses import dataclass
import os
from pathlib import Path
import re
import stat


@dataclass(frozen=True)
class CoverPin:
    path: Path
    covering_directory: tuple[int, int]
    mount_id: int
    namespace: tuple[int, int]
    launch_uid: int
    probe_paths: tuple[str, ...]


def mount_path(field):
    return re.sub(r"\\([0-7]{3})", lambda match: chr(int(match[1], 8)), field)


def matching_mounts(lines, target):
    for line in lines:
        fields = line.split()
        if len(fields) < 10 or "-" not in fields[6:]:
            raise ValueError("Linux mount information is incomplete")
        if mount_path(fields[4]) == str(target):
            yield int(fields[0]), set(fields[5].split(","))


def file_mount_id(fd):
    for line in Path(f"/proc/self/fdinfo/{fd}").read_text().splitlines():
        if line.startswith("mnt_id:"):
            return int(line.split()[1])
    raise ValueError("Kernel did not report the opened directory mount")


def identity(info):
    return info.st_dev, info.st_ino


def reject_unsafe_probe(relative):
    path = Path(relative)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise ValueError("Alternate launcher probe leaves its covered checkout")


def verify_cover(pin):
    """Verify path closure in exactly the invoking launch account and namespace."""
    if pin.launch_uid == 0 or os.geteuid() != pin.launch_uid:
        raise ValueError("Cover must be observed as the actual non-root launch account")
    if identity(Path("/proc/self/ns/mnt").stat()) != pin.namespace:
        raise ValueError("Launch mount namespace differs from the approved witness")
    if not pin.path.is_absolute() or pin.path.resolve(strict=True) != pin.path or not pin.probe_paths:
        raise ValueError("Expected a canonical checkout with scoped launcher probes")
    for relative in pin.probe_paths:
        reject_unsafe_probe(relative)
    # O_PATH permits identity verification even though the cover denies traversal.
    descriptor = os.open(pin.path, os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        attrs = os.fstat(descriptor)
        if (identity(attrs) != pin.covering_directory or attrs.st_uid != 0
                or stat.S_IMODE(attrs.st_mode) & 0o077):
            raise ValueError("Checkout does not expose the expected administrator-owned cover")
        rows = Path("/proc/self/mountinfo").read_text().splitlines()
        observed = file_mount_id(descriptor)
        if observed != pin.mount_id or (observed, True) not in {
            (mount_id, "ro" in flags) for mount_id, flags in matching_mounts(rows, pin.path)
        }:
            raise ValueError("Expected the exact read-only cover at the checkout mountpoint")
        for relative in pin.probe_paths:
            try:
                probe = os.open(relative, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
            except (FileNotFoundError, PermissionError):
                continue
            os.close(probe)
            raise ValueError("A scoped alternate launch path remains readable")
        if identity(pin.path.lstat()) != pin.covering_directory:
            raise ValueError("Checkout cover changed during verification")
    finally:
        os.close(descriptor)
