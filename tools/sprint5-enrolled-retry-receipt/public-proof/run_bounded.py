import os
from pathlib import Path
import socket
import sys

root = Path(__file__).resolve().parent
dependencies = Path('/home/chris/job-search-helper_old/.venv/lib/python3.11/site-packages')
sys.path[:0] = [str(root / 'src'), str(root / 'tests'), str(root), str(dependencies)]
os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'

from public_guard import HOST

addresses = set()
resolver = socket.getaddrinfo

def resolve(host, port, *args, **kwargs):
    if host != HOST or port != 443:
        raise RuntimeError('Foreign name resolution is forbidden in the rehearsal.')
    result = resolver(host, port, *args, **kwargs)
    addresses.update(row[4][0] for row in result)
    return result

socket.getaddrinfo = resolve

def restrict(event, args):
    if event == 'socket.connect':
        address = args[1]
        if not isinstance(address, tuple) or address[0] not in addresses or address[1] != 443:
            raise RuntimeError('Foreign Python connection is forbidden in the rehearsal.')
    if event == 'socket.bind' and args[1] != ('127.0.0.1', 0):
        raise RuntimeError('Only the private loopback TLS gate can bind.')
    if event == 'subprocess.Popen':
        if Path(args[0]).resolve() != dependencies / 'playwright/driver/node':
            raise RuntimeError('Only the existing Playwright driver process is allowed.')

sys.addaudithook(restrict)

import pytest
raise SystemExit(pytest.main(['-q', '-s', '-p', 'no:cacheprovider',
                              '--basetemp', str(root / 'run'), str(root / 'test_public_continuation.py'),
                              *sys.argv[1:]]))
