"""Create one immutable controller-pinned host-check executable."""
from hashlib import sha256
import io
import os
from pathlib import Path
from secrets import token_hex
import zipfile


BUNDLE_ENTRIES = frozenset({
    '__main__.py', 'host_checkpoint.py', 'alternate_writer_witness.py',
    'protected_state.py', 'launcher_witness.py', 'site_policy.py', 'approved_site_policy.json',
    'physical_protected_witness.py', 'protected_continuity.py',
    'alternate_exchange_witness.py', 'host_exchange.py',
})


def build_host_checker(destination, entries):
    """Build an isolated Python zipapp from explicitly reviewed bytes."""
    if set(entries) != BUNDLE_ENTRIES or any(not isinstance(data, bytes) or not data for data in entries.values()):
        raise ValueError('Expected the complete reviewed site checker and policy')
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, mode='w', compression=zipfile.ZIP_STORED) as bundle:
        for basename, data in sorted(entries.items()):
            member = zipfile.ZipInfo(basename)
            member.external_attr = 0o600 << 16
            bundle.writestr(member, data)
    payload = b'#!/usr/bin/python3 -I\n' + archive.getvalue()
    destination = Path(destination)
    parent = destination.parent
    if not destination.is_absolute() or parent.resolve(strict=True) != parent:
        raise ValueError('Site checker destination must have a physical absolute parent')
    folder = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    temporary = ".host-check-" + token_hex(16)
    created = False
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o700, dir_fd=folder)
        created = True
        with os.fdopen(descriptor, 'wb') as stream:
            os.fchmod(stream.fileno(), 0o700)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, destination.name, src_dir_fd=folder, dst_dir_fd=folder,
                follow_symlinks=False)
        os.fsync(folder)
    finally:
        try:
            if created:
                os.unlink(temporary, dir_fd=folder)
                os.fsync(folder)
        finally:
            os.close(folder)
    return sha256(payload).hexdigest()
