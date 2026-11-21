"""Verify a substituted or preloaded same-name project module holds before collection."""

from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory


def check(root, manifest_sha256):
    runner = root / 'run_verified_fixture_capsule.py'
    capsule = root / 'capsule'
    python = ['/usr/bin/python3.11', '-I', '-S', '-B']
    clean_environment = {'PATH': '/usr/bin:/bin', 'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1'}

    with TemporaryDirectory(prefix='capsule-negative-', dir=root) as scratch:
        temporary = Path(scratch)
        copied = temporary / 'capsule'
        shutil.copytree(capsule, copied)
        replacement = copied / 'dev/pre_release_validation/rippling_capture.py'
        replacement.write_text('raise AssertionError("substituted parser was executed")\n')

        def refused(command, selected, reason):
            test_temp = temporary / 'unexpected-pytest'
            completed = subprocess.run(
                [*python, *command, '--root', str(selected), '--manifest-sha256', manifest_sha256,
                 '--test-temp', str(test_temp)],
                cwd=root, env=clean_environment, text=True, capture_output=True, timeout=20,
            )
            assert completed.returncode == 1 and not completed.stdout and not test_temp.exists(), completed
            assert completed.stderr.strip() == f'Fixture capsule rejected: {reason}', completed
            print(completed.stderr.strip())

        refused([str(runner)], copied,
                'Digest mismatch before import: dev/pre_release_validation/rippling_capture.py')
        loader = (
            "import runpy,sys,types; sys.modules['rippling_capture'] = types.ModuleType('rippling_capture'); "
            f"runpy.run_path({str(runner)!r}, run_name='__main__')"
        )
        refused(['-c', loader], capsule, 'A same-name fixture module was already loaded before verification')


if __name__ == '__main__':
    check(Path(__file__).resolve().parent, sys.argv[1])
