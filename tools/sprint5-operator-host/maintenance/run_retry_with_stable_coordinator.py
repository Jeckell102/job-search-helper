"""Hold the idle coordinator's periodic writes until the normal release stops it."""

from hashlib import sha256
from pathlib import Path
import subprocess
import sys


ROOT = Path('/tmp/jsh-operator-native-prep')
CONTROL = Path('/tmp/jsh-retirement-pilot-control')
BUNDLE = Path('/home/chris/.local/state/job-search-helper-maintenance/s5-operator-trigger-20261121-03')
RUNNER = ROOT / 'run_retry_release.py'
ENROLLMENT = BUNDLE / 'preinstall-enrollment.json'
RUNNER_SHA = 'ccf7e1bb5c9d70d1fa956a1da859e98cc4fbd9d0ef9d364bb6b1429cf5ee759f'
ENROLLMENT_SHA = '8d428d7f605976867e36e9089ec0071e23b8baa1abb0727096e8eca5f2c54a5c'
PIN_SHA = 'd6fa29b0ad2e6af3568e38ccdb1f1606909e30d94f3d7e335b9444b5d5acd294'
WRAPPER = 'wrapper-development-host.service'


def command(*args):
    return subprocess.check_output(['/usr/bin/systemctl', '--user', *args], text=True, timeout=20).strip()


def unit():
    fields = command('show', WRAPPER, '-p', 'ActiveState', '-p', 'FreezerState', '-p', 'MainPID')
    return dict(line.split('=', 1) for line in fields.splitlines())


def main():
    for path, digest in ((RUNNER, RUNNER_SHA), (ENROLLMENT, ENROLLMENT_SHA),
                         (CONTROL / 'current-protected-pin.json', PIN_SHA)):
        if sha256(path.read_bytes()).hexdigest() != digest:
            raise RuntimeError(f'Approved {path.name} differs')
    attempt = BUNDLE.with_name(BUNDLE.name + '-attempt')
    if {path.name for path in attempt.iterdir()} != {'attempt.lock'} or (BUNDLE / 'controller.json').exists():
        raise RuntimeError('The captured install attempt is already used')
    sys.path.insert(0, str(CONTROL))
    from release_paused_slot import snapshot

    if snapshot()['pilot'] is not None:
        raise RuntimeError('The old wrapper pilot is no longer idle')
    before = unit()
    if before['ActiveState'] != 'active' or before['FreezerState'] != 'running' or int(before['MainPID']) <= 0:
        raise RuntimeError('The wrapper service is outside the expected idle baseline')
    try:
        command('freeze', WRAPPER)
        if unit() != {**before, 'FreezerState': 'frozen'} or snapshot()['pilot'] is not None:
            raise RuntimeError('The same idle wrapper did not enter its expected frozen state')
        print('Same idle wrapper frozen during the sealed preflight.', flush=True)
        result = subprocess.run([sys.executable, '-I', '-S', '-B', str(RUNNER), ENROLLMENT_SHA, str(ENROLLMENT)],
                                cwd=BUNDLE, check=False)
        return result.returncode
    finally:
        try:
            command('thaw', WRAPPER)
        except subprocess.SubprocessError:
            # A controller-held inactive unit may have nothing to thaw.
            if unit()['FreezerState'] != 'running':
                raise
        after = unit()
        if after['FreezerState'] != 'running':
            raise RuntimeError('Verify the wrapper has left the frozen state before continuing')
        print(f"Wrapper is unfrozen. Service state: {after['ActiveState']}.", flush=True)


if __name__ == '__main__':
    sys.exit(main())
