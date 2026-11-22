"""Socket-activated MuleLab observer for the existing maintenance witness."""

import importlib.util
import os
from pathlib import Path
import re
import socket
import time


LAUNCH_UID = 1000
LISTENER_PORT = 18789
PROC = Path('/proc')
ROUTES = tuple(map(Path, (
    '/home/chris/job-search-helper_old',
    '/home/chris/job-search-helper_old_copy',
    '/home/chris/job-search-helper backup',
    '/home/chris/job-search-helper-sqlite-migration-20261012',
    '/home/chris/.exchange-park-s4-atomic-01-copy',
    '/home/chris/.exchange-park-s4-atomic-01-backup',
    '/home/chris/.exchange-park-s4-atomic-01-migration',
)))
WINDOW = re.compile(r's[1-9][0-9]?-[a-z0-9]+(?:-[a-z0-9]+){0,7}-[0-9]{8}-[0-9]{2,3}', re.ASCII)
CHALLENGE = re.compile(r'[0-9a-f]{32}', re.ASCII)
FIELDS = {'schema', 'scope', 'pid', 'challenge'}


def load_witness():
    path = Path(__file__).with_name('ancillary_process_witness.py')
    spec = importlib.util.spec_from_file_location('ancillary_process_witness', path)
    witness = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(witness)
    return witness


def verify_session(proc, pid, role):
    cgroup = (proc / str(pid) / 'cgroup').read_text().splitlines()
    prefix = '0::/user.slice/user-1000.slice/'
    if role == '(sd-pam)':
        expected = prefix + 'user@1000.service/init.scope'
        approved = cgroup == [expected]
    else:
        approved = len(cgroup) == 1 and re.fullmatch(
            re.escape(prefix) + r'session-[A-Za-z0-9]+\.scope', cgroup[0], re.ASCII,
        ) is not None
    if not approved:
        raise ValueError('System helper is outside the approved user session.')


def observe(request, witness):
    if set(request) not in (FIELDS, FIELDS | {'listener'}) or request['schema'] != witness.SCHEMA:
        raise ValueError('Unsupported observer request.')
    scope = request['scope']
    window = scope.get('maintenance_id') if type(scope) is dict else None
    if not isinstance(window, str) or len(window) > 100 or WINDOW.fullmatch(window) is None:
        raise ValueError('Unapproved maintenance identity.')
    if scope != witness.scope(PROC, LAUNCH_UID, window, ROUTES):
        raise ValueError('Unapproved maintenance scope.')
    pid, challenge = request['pid'], request['challenge']
    if type(pid) is not int or pid <= 1 or not isinstance(challenge, str) or CHALLENGE.fullmatch(challenge) is None:
        raise ValueError('Unapproved request identity.')

    proc = PROC / str(pid)
    prior = witness.process_identity(proc)
    if prior['uid'] != LAUNCH_UID or prior['comm'] not in witness.ROLES:
        raise ValueError('Unapproved process role.')
    verify_session(PROC, pid, prior['comm'])
    listener = witness.listener_request(request['listener'], LISTENER_PORT) if 'listener' in request else None
    measured = witness.capture(LAUNCH_UID, ROUTES, pid, listener=listener)
    if measured != prior:
        raise ValueError('System helper moved between checks.')
    verify_session(PROC, pid, measured['comm'])
    return {'request': request, 'process': measured}


def answer(connection, witness):
    if witness.peer_uid(connection) != LAUNCH_UID:
        return
    deadline = time.monotonic() + witness.SOCKET_TIMEOUT
    request = witness.receive(connection, deadline)
    result = observe(request, witness)
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ValueError('Observer request expired.')
    connection.settimeout(remaining)
    connection.sendall(witness.encoded(result))


def main():
    if os.geteuid() != 0:
        raise SystemExit('Expected the system socket service user.')
    witness = load_witness()
    with socket.fromfd(0, socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        try:
            answer(connection, witness)
        except (OSError, UnicodeError, ValueError):
            # An absent, changed or unapproved observation returns no proof.
            return


if __name__ == '__main__':
    main()
