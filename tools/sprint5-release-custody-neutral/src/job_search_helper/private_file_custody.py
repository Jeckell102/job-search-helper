"""Provider-neutral, owner-only filesystem custody primitives.

Callers choose their error type; the checks intentionally match the established
ordinary capture custody contract rather than adding release-policy rules.
"""
import json
import os
import stat


class CustodyError(ValueError):
    pass


def _fail(error_type, code):
    raise error_type(code)


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()


def decode(raw, error_type=CustodyError):
    def unique(items):
        result = dict(items)
        if len(result) != len(items):
            _fail(error_type, 'duplicate_capture_metadata')
        return result
    try:
        value = json.loads(raw, object_pairs_hook=unique)
        if not isinstance(value, dict) or encode(value) != raw:
            _fail(error_type, 'noncanonical_capture_metadata')
    except (ValueError, TypeError, RecursionError) as error:
        if isinstance(error, error_type):
            raise
        raise error_type('invalid_capture_metadata') from None
    return value


def identity(info):
    return [info.st_dev, info.st_ino]


def stamp(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_nlink, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def directory(info, error_type=CustodyError):
    if not (stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o700
            and info.st_uid == os.geteuid()):
        _fail(error_type, 'unsafe_capture_directory')
    return identity(info)


def named_path_identity(path, directory_check=directory):
    descriptor = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for segment in path.parts[1:]:
            child = os.open(segment, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return directory_check(os.fstat(descriptor))
    finally:
        os.close(descriptor)


def file(info, error_type=CustodyError):
    if not (stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600
            and info.st_uid == os.geteuid() and info.st_nlink == 1):
        _fail(error_type, 'unsafe_capture_file')
    return info


def named_file(directory_fd, name, expected_stamp, error_type=CustodyError):
    info = file(os.stat(name, dir_fd=directory_fd, follow_symlinks=False), error_type)
    if stamp(info) != expected_stamp:
        _fail(error_type, 'capture_file_replaced_or_changed')


def read_file(directory_fd, name, limit, error_type=CustodyError):
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
    with os.fdopen(descriptor, 'rb') as stream:
        info = file(os.fstat(stream.fileno()), error_type)
        checked_stamp = stamp(info)
        if not 0 < info.st_size <= limit:
            _fail(error_type, 'capture_file_size_out_of_bounds')
        raw = stream.read(limit + 1)
        if not (len(raw) == info.st_size and stamp(file(os.fstat(stream.fileno()), error_type)) == checked_stamp):
            _fail(error_type, 'capture_file_replaced_or_changed')
        named_file(directory_fd, name, checked_stamp, error_type)
    return raw, identity(info), checked_stamp
