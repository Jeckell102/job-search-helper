"""Launch one scoped native installation with its pre-enrolled attempt capture."""

from contextlib import ExitStack
from hashlib import sha256
import json
import os
import stat
from pathlib import Path
import subprocess
import sys


OBSERVER = 'f4a82eaed30a46b507c525875418d4ec471b8b9147036adc67061970a5e70819'
BRIDGE = 'jetson-assistant-bridge.service'
WRAPPER = 'wrapper-development-host.service'
SYNC = 'job-search-sync.service'
PROC = Path('/proc')


def command(*args):
    return subprocess.check_output(['/usr/bin/systemctl', '--user', *args], text=True, timeout=65).strip()


def status(unit, field):
    return command('show', f'--property={field}', '--value', unit)


def main(bundle, approved_enrollment, private_enrollment):
    sys.path.insert(0, str(bundle))
    from controller import Controller, lock
    from host_exchange import Hold
    from preinstall_abort import (attempt_custody, block_installation_routes, capture_refused_install,
                                  closed_identity, enrolled_capsule, exchange_for, leases,
                                  require_unused_attempt, source_before, verify_protected)
    sys.path.insert(0, str(bundle / 'site-source'))
    from site_policy import load_policy
    from host_checkpoint import unit_status, verify_listener, verify_route_drain, verify_wrapper_process

    assert private_enrollment.resolve(strict=True) == private_enrollment
    enrollment = private_enrollment.read_bytes()
    controller, archive, original = enrolled_capsule(enrollment, approved_enrollment)
    script = controller.bundle / 'controller.py'
    info = script.lstat()
    if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700
            or info.st_uid != os.geteuid() or not os.access(script, os.X_OK)
            or script.read_bytes().splitlines()[0] != b'#!/usr/bin/python3 -I'):
        raise RuntimeError('Enrolled controller is not the exact private executable; routes remain open.')
    policy, *_ = load_policy(str(bundle / 'host-check'))
    observer = policy.ancillary_process_evidence.with_name('observer.py')
    assert sha256(observer.read_bytes()).hexdigest() == OBSERVER
    assert status(BRIDGE, 'ActiveState') == 'active' and command('is-enabled', BRIDGE) == 'enabled'
    assert status(SYNC, 'ActiveState') == 'inactive' and status(SYNC, 'UnitFileState') == 'disabled'
    attempt = Path(original['attempt']['path'])
    try:
        command('stop', BRIDGE)
        assert status(BRIDGE, 'ActiveState') == 'inactive'
        with ExitStack() as held:
            for path in leases(controller):
                held.enter_context(lock(path))
            require_unused_attempt(held.enter_context(attempt_custody(original)))
            assert not controller.state.exists()
            block_installation_routes(controller)
            source_before(controller)
            verify_protected(controller, archive, original['protected_pin'])
            wrap = unit_status(policy.systemctl, WRAPPER)
            assert wrap['ActiveState'] == 'active'
            pid = int(wrap['MainPID'])
            started = verify_wrapper_process(policy, pid, PROC)
            listening = verify_listener(policy, pid, PROC)
            verify_route_drain(policy, pid, PROC)
            assert verify_listener(policy, pid, PROC) == listening
            assert verify_wrapper_process(policy, pid, PROC) == started
            journal = Path(original['fence']['policy_file']).with_name('exchange.json')
            prepared = json.loads(journal.read_bytes())
            assert prepared['phase'] == 'closing' and prepared['completed'] == 0
            closure = exchange_for(original, write=True).close()
            closed_identity(closure, original['fence'])
            verify_route_drain(policy, pid, PROC)
        print('Approved alternate checkout routes held. Starting the single captured install.', flush=True)

        capture_error = None
        try:
            refusal = capture_refused_install(enrollment, approved_enrollment_sha256=approved_enrollment)
        except (Hold, OSError, ValueError, subprocess.SubprocessError) as error:
            capture_error = error
        else:
            print(f'Initial preflight refused; exact recovery evidence {sha256(refusal).hexdigest()}', flush=True)
            for line in (attempt / 'stderr').read_text().splitlines():
                if line.startswith('Site checkpoint held. Protected release evidence could not be verified. ['):
                    print(line, flush=True)
            return 2

        exit_log = attempt / 'exit.json'
        if not exit_log.is_file():
            raise RuntimeError('Captured install has no observed exit. Preserve the attempt directory.') from capture_error
        result = json.loads(exit_log.read_bytes())
        if result['returncode'] != 0:
            phase = 'NO_CONTROLLER_JOURNAL'
            if controller.journal.is_file():
                phase = Controller(bundle).load(canonical=True)['phase']
            print(f'Install stopped at {phase}. Preserve the original attempt transcript.', flush=True)
            return 3
        fresh = Controller(bundle)
        with fresh.restoration_terminal() as terminal:
            assert terminal['source'] == 'INSTALLED'
            assert status(SYNC, 'ActiveState') == 'inactive'
            print('Installed source and terminal receipt verified. Wrapper active; sync inactive.', flush=True)
            print('Terminal controller journal:', terminal['controller_journal_sha256'], flush=True)
    finally:
        command('start', BRIDGE)
        assert status(BRIDGE, 'ActiveState') == 'active' and command('is-enabled', BRIDGE) == 'enabled'
        print('Assistant bridge restored and verified active/enabled.', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main(Path.cwd(), sys.argv[1], Path(sys.argv[2])))
