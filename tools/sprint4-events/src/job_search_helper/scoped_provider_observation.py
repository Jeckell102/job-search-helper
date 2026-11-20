"""Durable claim and result for a scoped Company provider call."""
import json
import os
import stat
import tempfile

from .ats import lever_location_scope, resolve_board
from .retained_operator_journal import provider_inventory_digest
from .retained_work_exception import _provider_identity
from .scan_request import _timestamp
from .temporary_retry import _canonical, _selected_sha, _sync_directory


def provider_identity(ats, url):
    identity = _provider_identity(ats, url)
    provider = identity.partition(':')[0]
    if provider not in {'greenhouse', 'lever', 'ashby'}:
        return identity
    try:
        adapter, board, api_root = resolve_board(ats, url)
        if adapter.casefold() != provider:
            return ''
        if provider == 'lever':
            return 'lever:' + _canonical([api_root, board.casefold(), lever_location_scope(url).casefold()])
    except ValueError:
        return ''
    return provider + ':' + board.casefold()


def read_observation(path, binding):
    try:
        attrs = path.parent.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISDIR(attrs.st_mode) or stat.S_IMODE(attrs.st_mode) != 0o700 or attrs.st_uid != os.geteuid():
        raise ValueError('Scoped provider inventory directory is unsafe.')
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    with os.fdopen(fd, 'r', encoding='utf-8') as stream:
        attrs = os.fstat(stream.fileno())
        if (not stat.S_ISREG(attrs.st_mode) or stat.S_IMODE(attrs.st_mode) != 0o600
                or attrs.st_uid != os.geteuid() or attrs.st_nlink != 1):
            raise ValueError('Scoped provider inventory record is unsafe.')
        raw = stream.read()
    record = json.loads(raw)
    if not isinstance(record, dict) or _canonical(record) + '\n' != raw:
        raise ValueError('Scoped provider inventory record is malformed.')
    expected = {'state', 'binding', 'fetch_started_at', 'sha256'}
    if record.get('state') == 'FROZEN':
        expected.update(('inventory', 'inventory_sha256'))
    if (set(record) != expected or record['binding'] != binding or record['state'] not in ('CLAIMED', 'FROZEN')
            or record['sha256'] != _selected_sha({key: value for key, value in record.items() if key != 'sha256'})):
        raise ValueError('Scoped provider inventory record conflicts with its exact admission.')
    started = _timestamp(record['fetch_started_at'], 'Scoped provider fetch claim time')
    if record['state'] == 'FROZEN':
        inventory = record['inventory']
        if (provider_inventory_digest(inventory, event_scope=True) != record['inventory_sha256']
                or _timestamp(inventory.get('fetched_at'), 'Scoped provider fetch completion time') < started):
            raise ValueError('Scoped provider frozen inventory is inconsistent.')
    return record


def write_observation(path, record, *, initial):
    path.parent.mkdir(mode=0o700, exist_ok=True)
    _sync_directory(path.parent.parent)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.observation-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(_canonical({**record, 'sha256': _selected_sha(record)}) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        if initial:
            os.link(temporary, path, follow_symlinks=False)
            os.unlink(temporary)
        else:
            os.replace(temporary, path)
        _sync_directory(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
