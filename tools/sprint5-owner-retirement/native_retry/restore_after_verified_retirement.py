"""Measure retirement and restore only the three enrolled alternate routes."""
import argparse
from contextlib import closing
from hashlib import sha256
from pathlib import Path
import json
import os
import sys


WORK = Path(__file__).resolve().parent
BUNDLE = Path('/home/chris/.local/state/job-search-helper-maintenance/s5-owner-retirement-20261121-02')
PROJECT = Path('/home/chris/job-search-helper_old')
ARCHIVE = '/home/chris/.local/state/job-search-helper-backups/current-scraper-20261121-090919/project/.state'
SCOPE = 'dfeb109aa9ef751053871e5d6f6f702e69bab6692fb8f28cbb317c3339cae7a7'
CHECKER = '6b29cb0cc76f40e33f91a469a4c1094e46edd44bd96b333d3e07026180ee2db7'
PIN = 'd6fa29b0ad2e6af3568e38ccdb1f1606909e30d94f3d7e335b9444b5d5acd294'
EXCHANGE = '521b7e399ba7fdf47223edf190082f9c72a38fcb6ce33fb40af392312c3a9576'
TOOLS = {
    'controller.py': '83eb3246bdf0d5818e322ed85fb6fd73c6f2cd0138b62ad23585d73ba0b7d708',
    'installer.py': 'e335cbc47c00e9e8b1bbc1d1984161e0a71789f4b776667073e008d8e0d32909',
    'host_exchange.py': '8168d900979d68aebc950d7bb8495705a5190368e8ca3ac932a7da4d4c7dfb1f',
    'gate.py': '7df4121796ce400461be9b4329984bc6f1ced83858588d3a63d4e5258d286537',
    'preinstall_abort.py': '5d4c94876a2b9325fc5f7f22bb4e8099a973ff66a67e642ef3ac7b56743562ea',
}


def require(condition, note):
    if not condition:
        raise RuntimeError(note)


def checked(path, expected):
    require(path.resolve(strict=True) == path and sha256(path.read_bytes()).hexdigest() == expected,
            f'Pinned file differs: {path.name}')


def run(approval=None, approved_sha=None):
    for name, digest in TOOLS.items():
        checked(BUNDLE / name, digest)
    checked(WORK / 'retirement_restoration.py', '7f9cce7e1e67253f9100c36515fe938a8f5b0470b9e7fe24d6e8d569e8529b49')
    checked(WORK / 'verify_installed_source.py', '9485454caecf06b64a97a6dbfc6fe643cf3b2e2ecf129652241dae9198b45739')

    sys.path[:0] = [str(BUNDLE), str(WORK)]
    import verify_installed_source
    import retirement_restoration as restoration
    import preinstall_abort as abort

    verify_installed_source.measure()
    sys.path.insert(0, str(PROJECT / 'src'))

    controller = abort.joint.Controller(BUNDLE)
    archive, protected, fence = abort.checker_policy(controller, CHECKER, PIN)
    require(fence['policy_sha256'] == EXCHANGE, 'Alternate route approval changed')
    exchange = abort.HostExchange(fence['policy_file'], EXCHANGE, enable_host_writes=approval is not None)

    def retired():
        verify_installed_source.measure()
        from job_search_helper.engine import State
        from job_search_helper.retained_cycle_retirement import _digest
        from job_search_helper.retained_cycle_retirement_control import _read
        with closing(State(str(PROJECT / '.state/state.db'), readonly=True)) as state:
            record = _read(state.connection, restoration.CYCLE_ID)
            require(record is not None, 'Exact retirement must be durable before reopening routes')
            selection = {'cycle_id': restoration.CYCLE_ID, 'archive_root': ARCHIVE,
                         'archive_scope_sha256': SCOPE, 'retirement_record_sha256': _digest(record)}
            return restoration.read_verified_retirement(state, selection)

    def protected_unchanged():
        abort.joint.locked_by(os.getpid(), abort.leases(controller))
        abort.verify_protected(controller, archive, protected)
        path = Path(protected['path'])
        raw = path.read_bytes()
        require(sha256(raw).hexdigest() == PIN, 'Current protected pin changed')
        return {'protected_pin_sha256': PIN,
                'witness_sha256': sha256(abort.encode(json.loads(raw)['witness'])).hexdigest()}

    arguments = {'read_verified_retirement': retired, 'read_protected_state': protected_unchanged}
    if approval is None:
        observed = restoration.observe_after_retirement(controller, exchange, **arguments)
        sys.stdout.buffer.write(abort.encode(observed))
    else:
        result = restoration.restore_after_retirement(
            controller, exchange, approval, approved_sha256=approved_sha, **arguments,
        )
        require(exchange.witness('restored') == result, 'Restored route verification failed')
        print(json.dumps({'state':result.phase, 'alternate_count':len(result.pairs),
                          'exact_proof_sha256':result.terminal_proof_sha256}, sort_keys=True))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--approval', type=Path)
    parser.add_argument('--approved-sha256')
    args = parser.parse_args()
    require(bool(args.approval) == bool(args.approved_sha256), 'Provide exact approval bytes and digest together')
    run(args.approval.read_bytes() if args.approval else None, args.approved_sha256)
