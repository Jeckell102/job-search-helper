"""Fail-closed Linux sandbox for offline wrapper tests; no elevated privileges."""
import ctypes
import errno
import os
from pathlib import Path
import resource
import sys


def restrict(read_dirs, read_files, scratch, list_dir):
    libc = ctypes.CDLL(None, use_errno=True)
    abi = libc.syscall(444, 0, 0, 1)
    if abi < 3:
        raise RuntimeError('Landlock ABI 3 or newer is required; tests were not run.')
    class Rules(ctypes.Structure):
        _fields_ = [('handled_access_fs', ctypes.c_uint64)]
    class Rule(ctypes.Structure):
        _pack_ = 1
        _fields_ = [('allowed_access', ctypes.c_uint64), ('parent_fd', ctypes.c_int)]
    handled = (1 << 15) - 1
    attr = Rules(handled)
    fd = libc.syscall(444, ctypes.byref(attr), ctypes.sizeof(attr), 0)
    if fd < 0:
        raise OSError(ctypes.get_errno(), 'landlock_create_ruleset')
    def grant(path, access):
        pfd = os.open(path, os.O_PATH | os.O_CLOEXEC)
        try:
            rule = Rule(access, pfd)
            if libc.syscall(445, fd, 1, ctypes.byref(rule), 0) < 0:
                raise OSError(ctypes.get_errno(), 'landlock_add_rule')
        finally:
            os.close(pfd)
    try:
        grant(list_dir, 8)
        for path in read_dirs:
            grant(path, 1 | 4 | 8)
        for path in read_files:
            if Path(path).exists():
                grant(path, 4)
        grant('/dev/null', 2 | 4)
        # Only regular scratch files/directories, no links, device nodes or sockets.
        grant(scratch, 2 | 4 | 8 | 16 | 32 | 128 | 256 | 16384)
        if libc.prctl(38, 1, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), 'no_new_privileges')
        if libc.syscall(446, fd, 0) != 0:
            raise OSError(ctypes.get_errno(), 'landlock_restrict_self')
    finally:
        os.close(fd)
    # Prevent network, process interference and unmediated I/O interfaces.
    sec = ctypes.CDLL('libseccomp.so.2')
    sec.seccomp_init.argtypes = [ctypes.c_uint32]
    sec.seccomp_init.restype = ctypes.c_void_p
    sec.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
    sec.seccomp_load.argtypes = [ctypes.c_void_p]
    sec.seccomp_release.argtypes = [ctypes.c_void_p]
    sec.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    ctx = sec.seccomp_init(0x7fff0000)
    if not ctx:
        raise RuntimeError('seccomp_init failed')
    try:
        for name in ('socket', 'socketpair', 'connect', 'bind', 'ptrace', 'process_vm_readv',
                     'process_vm_writev', 'kill', 'tkill', 'tgkill', 'pidfd_send_signal',
                     'rt_sigqueueinfo', 'rt_tgsigqueueinfo',
                     'pidfd_getfd', 'io_uring_setup', 'bpf', 'mount', 'umount2',
                     'setsid', 'setpgid', 'unshare', 'setns', 'setpriority',
                     'sched_setparam', 'sched_setscheduler', 'sched_setaffinity',
                     'keyctl', 'add_key', 'request_key', 'shmget', 'shmat', 'msgget',
                     'semget', 'chmod', 'fchmod', 'fchmodat', 'fchmodat2', 'chown',
                     'fchown', 'fchownat', 'lchown', 'setxattr', 'lsetxattr', 'fsetxattr',
                     'removexattr', 'lremovexattr', 'fremovexattr', 'utime', 'utimes',
                     'futimesat', 'utimensat'):
            nr = sec.seccomp_syscall_resolve_name(name.encode())
            if nr >= 0 and sec.seccomp_rule_add(ctx, 0x50000 | errno.EPERM, nr, 0) != 0:
                raise RuntimeError('seccomp rule failed: ' + name)
        # Deny clone3 while allowing libc to fall back to the existing clone
        # path for pthreads. EPERM stops that fallback on current glibc.
        clone3 = sec.seccomp_syscall_resolve_name(b'clone3')
        if clone3 >= 0 and sec.seccomp_rule_add(ctx, 0x50000 | errno.ENOSYS, clone3, 0) != 0:
            raise RuntimeError('seccomp rule failed: clone3')
        class Compare(ctypes.Structure):
            _fields_ = [('arg', ctypes.c_uint), ('op', ctypes.c_int), ('a', ctypes.c_uint64), ('b', ctypes.c_uint64)]
        sec.seccomp_rule_add_array.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint, ctypes.POINTER(Compare)]
        # Prevent asynchronous signals to host processes via file-descriptor ownership.
        for name, commands in [('fcntl', (8, 10, 15)), ('fcntl64', (8, 10, 15)),
                               ('ioctl', (0x5452, 0x8901, 0x5410, 0x5412, 0x40045436))]:
            nr = sec.seccomp_syscall_resolve_name(name.encode())
            if nr < 0: continue
            for command in commands:
                cmp = Compare(1, 4, command, 0)
                if sec.seccomp_rule_add_array(ctx, 0x50000 | errno.EPERM, nr, 1, ctypes.byref(cmp)) != 0:
                    raise RuntimeError('seccomp fcntl rule failed')
        if sec.seccomp_load(ctx) != 0:
            raise RuntimeError('seccomp_load failed')
    finally:
        sec.seccomp_release(ctx)


def main():
    repo, venv, scratch, *tests = sys.argv[1:]
    repo, venv, scratch = map(lambda p: str(Path(p).resolve()), (repo, venv, scratch))
    os.chdir(repo)
    resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
    resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))
    resource.setrlimit(resource.RLIMIT_FSIZE, (16*1024**2, 16*1024**2))
    resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    reads = ['/usr', '/lib', venv, repo + '/src', repo + '/tests']
    reads += [p for p in ['/lib64'] if Path(p).exists()]
    restrict(reads, [repo + '/pyproject.toml', repo + '/title-blacklist.txt',
                     repo + '/title-review-list.txt', '/etc/ld.so.cache',
                     '/dev/urandom', '/dev/random'], scratch, repo)
    env = {'PATH': venv + '/bin:/usr/bin:/bin', 'HOME': scratch, 'TMPDIR': scratch,
           'PYTHONPATH': repo + '/src', 'PYTHONDONTWRITEBYTECODE': '1',
           'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1', 'LANG': 'C.UTF-8'}
    os.execve(venv + '/bin/python', [venv + '/bin/python', '-B', '-m', 'pytest',
              '-q', '-c', repo + '/pyproject.toml', '--rootdir=' + repo, '-p', 'no:cacheprovider', '--confcutdir=' + repo, *tests], env)


if __name__ == '__main__':
    main()
