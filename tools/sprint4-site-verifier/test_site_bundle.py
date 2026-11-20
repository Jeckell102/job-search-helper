from hashlib import sha256
import os
import stat
import subprocess

import pytest

from site_bundle import BUNDLE_ENTRIES, build_host_checker


def example_inputs():
    data = {basename: b'# test-only module\n' for basename in BUNDLE_ENTRIES}
    data['host_checkpoint.py'] = b'MARKER = "pinned code"\n'
    data['approved_site_policy.json'] = b'{"scope":"approved fixture"}\n'
    data['__main__.py'] = b'''import sys
import zipfile
from host_checkpoint import MARKER
with zipfile.ZipFile(sys.argv[0]) as package:
    print(MARKER + " " + package.read("approved_site_policy.json").decode().strip())
'''
    return data


def test_bundled_bytes_are_deterministic_and_import_ignores_pythonpath(tmp_path):
    first, second = tmp_path / 'host-check', tmp_path / 'next-host-check'
    inputs = example_inputs()
    digest = build_host_checker(first, inputs)
    assert digest == build_host_checker(second, dict(reversed(list(inputs.items()))))
    assert digest == sha256(first.read_bytes()).hexdigest()
    assert stat.S_IMODE(first.stat().st_mode) == 0o700
    assert first.stat().st_nlink == 1
    (tmp_path / 'host_checkpoint.py').write_text('raise AssertionError("foreign package")\n')
    observed = subprocess.check_output([first], env={**os.environ, 'PYTHONPATH': str(tmp_path)})
    assert observed == b'pinned code {"scope":"approved fixture"}\n'


def test_existing_checker_and_unreviewed_members_are_refused(tmp_path):
    path = tmp_path / 'host-check'
    path.write_bytes(b'keep exact existing checker')
    with pytest.raises(FileExistsError):
        build_host_checker(path, example_inputs())
    assert path.read_bytes() == b'keep exact existing checker'
    supplied = {**example_inputs(), '../host_checkpoint.py': b'foreign'}
    with pytest.raises(ValueError, match='complete reviewed'):
        build_host_checker(tmp_path / 'new-host-check', supplied)
    assert list(tmp_path.iterdir()) == [path]
