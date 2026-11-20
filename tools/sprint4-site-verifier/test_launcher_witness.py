from hashlib import sha256
from pathlib import Path
import sys

import pytest

from launcher_witness import LAUNCH_FILES, LauncherPolicy, probe_launchers


@pytest.fixture
def checkout(tmp_path):
    root = tmp_path / 'checkout'
    package = root / 'src/job_search_helper'
    package.mkdir(parents=True)
    interpreter = root / '.venv/bin/python'
    interpreter.parent.mkdir(parents=True)
    interpreter.symlink_to(Path(sys.executable).resolve())
    for name in LAUNCH_FILES - {'release_admission_bootstrap.py'}:
        (root / name).write_text('''root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
exec "$root/.venv/bin/python" -I -S "$root/release_admission_bootstrap.py" "$@"
''')
    (root / 'release_admission_bootstrap.py').write_text('raise AssertionError("maintenance probe executed the bootstrap")\n')
    pins = {name: sha256((root / name).read_bytes()).hexdigest() for name in LAUNCH_FILES}
    launcher = LauncherPolicy(interpreter, interpreter.resolve(), Path('/bin/bash').resolve(), pins, pins)
    (package / 'runner.py').write_text('def scrape_main(args):\n    assert args == ["--help"]\n    return 0\n')
    return root, package, launcher


def test_phase_routes_do_not_execute_start_and_require_guard(checkout):
    root, package, launcher = checkout
    init = package / '__init__.py'
    init.write_text('raise ImportError("Job Search Helper is held for source maintenance")\n')
    probe_launchers(root, launcher, 'pre-publish', 'INSTALLED')
    init.write_text('')
    extension = package / '__init__.so'
    extension.touch()
    probe_launchers(root, launcher, 'published', 'INSTALLED')
    extension.unlink()
    probe_launchers(root, launcher, 'admitted', 'INSTALLED')
    probe_launchers(root, launcher, 'before-host-reopen', 'ROLLED_BACK')


def test_changed_launcher_refuses_before_running_its_source(checkout):
    root, _, launcher = checkout
    (root / 'job-search-helper').write_text('touch unapproved-marker\n')
    with pytest.raises(ValueError, match='source differs'):
        probe_launchers(root, launcher, 'preflight', 'INSTALLED')
    assert not (root / 'unapproved-marker').exists()


def test_unrelated_runner_write_is_denied(checkout):
    root, package, launcher = checkout
    (package / '__init__.py').write_text('')
    witness = root / 'would-write'
    (package / 'runner.py').write_text(f'def scrape_main(args):\n    open({str(witness)!r}, "w")\n    return 0\n')
    import subprocess
    with pytest.raises(subprocess.CalledProcessError):
        probe_launchers(root, launcher, 'admitted', 'INSTALLED')
    assert not witness.exists()
