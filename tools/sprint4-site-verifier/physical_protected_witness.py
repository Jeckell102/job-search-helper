"""Measure continuity of the protected files under independently verified holds."""
from contextlib import ExitStack
from hashlib import sha256
import os
from pathlib import Path
import stat

from alternate_writer_witness import file_mount_id
from protected_state import ARCHIVES, DATABASES, DISPATCH, RETAINED_FIRST_PASS, WitnessHold, encoded


OPTIONAL_DATABASES = (DISPATCH, 'retained-work-starts.sqlite3', 'retained-work-exceptions.sqlite3')
OPTIONAL_CONTROLS = ('next-scan.json', 'retained-operator-admission.json')
OPTIONAL_ARCHIVES = ('repair-retry/intents', 'repair-retry/receipts')
REPAIR_PROFILE = 'dev/wrapper-coder/tools/coordinator_repair_profiles.py'
SIDECARS = ('-wal', '-shm', '-journal')
DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def need(condition, reason):
    if not condition:
        raise WitnessHold(reason)


class Collector:
    def __init__(self, root, stack):
        self.stack = stack
        self.directories = {}
        self.records = {}
        require_root = Path(root)
        need(require_root.is_absolute() and require_root.anchor == '/' and '..' not in require_root.parts,
             'Protected checkout path is not canonical')
        parent = self.open_directory('/', None)
        for part in require_root.parts[1:]:
            parent = self.open_directory(part, parent)
        self.directories[''] = parent
        self.records['.'] = self.directory_identity(parent)

    def open_directory(self, name, parent):
        descriptor = os.open(name, DIRECTORY, dir_fd=parent)
        self.stack.callback(os.close, descriptor)
        return descriptor

    @staticmethod
    def directory_identity(descriptor):
        info = os.fstat(descriptor)
        return ('directory', file_mount_id(descriptor), info.st_dev, info.st_ino, info.st_uid,
                info.st_gid, stat.S_IMODE(info.st_mode))

    def directory(self, rel, *, optional=False):
        if rel in self.directories:
            return self.directories[rel]
        path = Path(rel)
        parent = self.directory('' if str(path.parent) == '.' else path.parent.as_posix())
        try:
            descriptor = self.open_directory(path.name, parent)
        except FileNotFoundError:
            need(optional, 'Protected directory is missing')
            self.records[rel] = None
            return None
        info = os.fstat(descriptor)
        named = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        need(os.path.samestat(info, named), 'Protected directory changed during observation')
        self.records[rel] = self.directory_identity(descriptor)
        self.directories[rel] = descriptor
        return descriptor

    def file(self, rel, *, optional=False):
        path = Path(rel)
        parent = self.directory('' if str(path.parent) == '.' else path.parent.as_posix())
        try:
            descriptor = os.open(path.name, os.O_PATH | os.O_NOFOLLOW, dir_fd=parent)
        except FileNotFoundError:
            need(optional, 'Protected file is missing')
            self.records[rel] = None
            return False
        try:
            info = os.fstat(descriptor)
            named = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
            need(os.path.samestat(info, named) and stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                 and (info.st_size, info.st_ctime_ns, info.st_mtime_ns)
                 == (named.st_size, named.st_ctime_ns, named.st_mtime_ns),
                 'Protected file is substituted or changed')
            self.records[rel] = ('file', file_mount_id(descriptor), info.st_dev, info.st_ino,
                                 info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode), info.st_nlink,
                                 info.st_size, info.st_ctime_ns, info.st_mtime_ns)
        finally:
            os.close(descriptor)
        return True


def physical_snapshot(project):
    """Return a digest with no protected row values or file paths in its result."""
    try:
        with ExitStack() as stack:
            scan = Collector(project, stack)
            for relative, optional in (
                *((name, False) for name in DATABASES.values()),
                *((f'.state/{name}', True) for name in OPTIONAL_DATABASES),
            ):
                exists = scan.file(relative, optional=optional)
                for suffix in SIDECARS:
                    sidecar = scan.file(relative + suffix, optional=True)
                    need(exists or not sidecar, 'Protected sidecar has no owning database')
            scan.file(REPAIR_PROFILE)
            for control in OPTIONAL_CONTROLS:
                scan.file(f'.state/{control}', optional=True)
            for archive in (*ARCHIVES, *OPTIONAL_ARCHIVES):
                relative = f'.state/{archive}'
                path = Path(relative)
                parents = list(path.parents)[:-1]
                if archive in OPTIONAL_ARCHIVES and any(
                        scan.directory(parent.as_posix(), optional=True) is None
                        for parent in reversed(parents)):
                    scan.records[relative] = None
                    continue
                directory = scan.directory(relative, optional=archive in OPTIONAL_ARCHIVES)
                if directory is not None:
                    for member in sorted(os.listdir(directory)):
                        scan.file(f'{relative}/{member}')
            relative = f'.state/{RETAINED_FIRST_PASS}'
            directory = scan.directory(relative, optional=True)
            if directory is not None:
                for bucket in sorted(os.listdir(directory)):
                    child = f'{relative}/{bucket}'
                    bucket_fd = scan.directory(child)
                    for member in sorted(os.listdir(bucket_fd)):
                        scan.file(f'{child}/{member}')
            return sha256(encoded(sorted(scan.records.items()))).hexdigest()
    except WitnessHold:
        raise
    except (OSError, ValueError, TypeError):
        raise WitnessHold('Protected physical evidence unavailable') from None
