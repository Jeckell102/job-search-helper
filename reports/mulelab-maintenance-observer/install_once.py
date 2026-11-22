"""Install the fixed MuleLab observer units once, from the pinned package."""

from hashlib import sha256
from io import BytesIO
from pathlib import Path
import os
import pwd
import stat
import subprocess
from tempfile import NamedTemporaryFile
from zipfile import ZipFile


BUNDLE = Path('/tmp/jsh-observer-one-time-setup/observer-files.zip')
BUNDLE_PIN = 'efe78d1041748dfaeb49b8f2c762b0fbe9ac29cf2ed37b3a34989d90866658b9'
UNIT_ROOT = Path('/etc/systemd/system')
LIBEXEC = Path('/usr/local/libexec')
PROGRAM_ROOT = LIBEXEC / 'jsh-maintenance-observer'
SOCKET = 'jsh-maintenance-observer.socket'
TARGETS = {
    'observe_once.py': (PROGRAM_ROOT / 'observe_once.py', 0o644),
    'ancillary_process_witness.py': (PROGRAM_ROOT / 'ancillary_process_witness.py', 0o644),
    SOCKET: (UNIT_ROOT / SOCKET, 0o644),
    'jsh-maintenance-observer@.service': (UNIT_ROOT / 'jsh-maintenance-observer@.service', 0o644),
}


def trusted_directory(path):
    if path.resolve(strict=True) != path:
        raise ValueError(f'Unexpected installation directory: {path}')
    for directory in (path, *path.parents):
        info = directory.stat(follow_symlinks=False)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError(f'Untrusted installation directory: {directory}')


def read_staged_bundle(path):
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        owner = os.fstat(directory)
        if owner.st_uid != 1000 or stat.S_IMODE(owner.st_mode) != 0o700:
            raise ValueError('The observer package staging directory is not private.')
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                     dir_fd=directory)
        with os.fdopen(fd, 'rb') as file:
            info = os.fstat(file.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != 1000 or info.st_nlink != 1
                    or not 0 < info.st_size <= 65536):
                raise ValueError('The observer package is not the approved bounded regular file.')
            raw = file.read(65537)
            if len(raw) != info.st_size:
                raise ValueError('The observer package length changed.')
            return raw
    finally:
        os.close(directory)


def read_bundle():
    raw = read_staged_bundle(BUNDLE)
    if sha256(raw).hexdigest() != BUNDLE_PIN:
        raise ValueError('The reviewed observer package changed.')
    with ZipFile(BytesIO(raw)) as archive:
        if sorted(archive.namelist()) != sorted(TARGETS) or any(item.file_size > 65536 for item in archive.infolist()):
            raise ValueError('Unexpected contents in the reviewed observer package.')
        return {name: archive.read(name) for name in TARGETS}


def already_exact(target, expected, mode):
    if not os.path.lexists(target):
        return False
    info = target.stat(follow_symlinks=False)
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_gid != 0
            or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != mode
            or target.read_bytes() != expected):
        raise ValueError(f'Existing observer endpoint differs: {target}')
    return True


def install(target, expected, mode):
    if already_exact(target, expected, mode):
        return
    temporary = None
    try:
        with NamedTemporaryFile(dir=target.parent, prefix='.jsh-observer-', delete=False) as output:
            temporary = Path(output.name)
            os.fchmod(output.fileno(), mode)
            os.fchown(output.fileno(), 0, 0)
            output.write(expected)
            output.flush()
            os.fsync(output.fileno())
        os.link(temporary, target, follow_symlinks=False)
    finally:
        if temporary is not None:
            temporary.unlink()


def systemctl(*arguments):
    subprocess.run(
        ['/usr/bin/systemctl', '--system', *arguments], check=True,
        env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'},
    )


def main():
    if os.geteuid() != 0 or pwd.getpwnam('chris').pw_uid != 1000:
        raise ValueError('Use the one-time administrator setup on MuleLab.')
    contents = read_bundle()
    trusted_directory(UNIT_ROOT)
    trusted_directory(LIBEXEC.parent)
    for path in (LIBEXEC, PROGRAM_ROOT):
        path.mkdir(mode=0o755, exist_ok=True)
        trusted_directory(path)
    for name, (target, mode) in TARGETS.items():
        already_exact(target, contents[name], mode)
    for name, (target, mode) in TARGETS.items():
        install(target, contents[name], mode)

    systemctl('daemon-reload')
    systemctl('enable', '--now', SOCKET)
    systemctl('is-active', '--quiet', SOCKET)
    socket_path = Path('/run/jsh-maintenance-observer/observer.sock')
    trusted_directory(socket_path.parent)
    info = socket_path.stat(follow_symlinks=False)
    if (not stat.S_ISSOCK(info.st_mode) or info.st_uid != 0 or info.st_gid != pwd.getpwnam('chris').pw_gid
            or stat.S_IMODE(info.st_mode) != 0o660):
        raise ValueError('The observer socket does not match the private service policy.')
    print('One-time MuleLab observer installed. Ready for a read-only live verification.')


if __name__ == '__main__':
    main()
