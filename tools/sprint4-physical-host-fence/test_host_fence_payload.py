"""Disposable wrapper fence endpoint and installer projection checks."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

import installer


def test_wrapper_reopen_requires_sealed_bytes_and_never_overwrites(tmp_path):
    tools = tmp_path / 'tools'
    state = tmp_path / 'private'
    tools.mkdir()
    state.mkdir(mode=0o700)
    host = tools / 'host_server.py'
    old = b'raise AssertionError("this fixture should not run while fenced")\n'
    new = b'print("verified disposable wrapper")\n'
    host.write_bytes(old)
    host.chmod(0o640)
    expected_old, expected_new = [(0o640, installer.digest(value)) for value in (old, new)]
    owner = [os.geteuid(), os.getegid()]

    with installer.directory(tools) as parent, installer.directory(state) as private:
        def verify_parent():
            assert tools.stat().st_ino == os.fstat(parent).st_ino

        installer.seal_host_image(private, 'before', old, expected_old)
        installer.seal_host_image(private, 'after', new, expected_new)
        with host.open('rb') as loaded_before_closure:
            installer.close_host_path(parent, expected_old, owner, verify_parent)
            installer.close_host_path(parent, expected_old, owner, verify_parent)
            for argument in (str(host), host.name):
                refused = subprocess.run([sys.executable, '-B', argument], cwd=tools, capture_output=True)
                assert refused.returncode == 2 and b'No such file or directory' in refused.stderr
            assert loaded_before_closure.read() == old

        host.write_bytes(b'foreign source that must be preserved')
        with pytest.raises(ValueError, match='does not match'):
            installer.open_host_path(private, parent, 'after', expected_new, owner, verify_parent)
        assert host.read_bytes() == b'foreign source that must be preserved'
        host.unlink()
        installer.open_host_path(private, parent, 'after', expected_new, owner, verify_parent)
        installed_inode = host.stat().st_ino
        installer.open_host_path(private, parent, 'after', expected_new, owner, verify_parent)
        assert host.stat().st_ino == installed_inode
        assert subprocess.check_output([sys.executable, '-B', host.name], cwd=tools) == b'verified disposable wrapper\n'
        installer.close_host_path(parent, expected_new, owner, verify_parent)
        installer.open_host_path(private, parent, 'before', expected_old, owner, verify_parent)
        assert host.read_bytes() == old


def test_installer_preserves_host_absence_during_install_and_candidate_free_rollback(tmp_path):
    from shutil import rmtree
    from types import SimpleNamespace
    from unittest.mock import Mock

    import gate

    project, candidate, state = (tmp_path / name for name in ('checkout', 'candidate', 'transaction'))
    state.mkdir(mode=0o700)
    package_file = 'src/job_search_helper/runner.py'
    scope = (*installer.WRAPPER_PATHS, package_file)
    before = {path: f'old {path}'.encode() for path in scope}
    after = {path: f'new {path}'.encode() for path in scope}
    directions = [before, after]
    for root, images in zip((project, candidate), directions):
        for relative, data in images.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            path.chmod(0o640)
    original_inode = (project / 'src/job_search_helper').stat().st_ino
    host = project / installer.WRAPPER_HOST
    host.unlink()
    gate.park(project, original_inode)
    owners = {path: [os.geteuid(), os.getegid()] for path in scope}
    endpoints = [{path: (0o640, installer.digest(data)) for path, data in images.items()} for images in directions]
    manifest = installer.SourceManifest('f' * 64, endpoints[0], endpoints[1], owners)
    gate_file = tmp_path / 'gate'
    gate_file.touch(mode=0o600)
    with installer.source_tree(project, parked=True) as tree, installer.directory(state) as journal, gate_file.open('rb') as lock:
        hold = SimpleNamespace(gate=lock.fileno(), marker_digest='g' * 64, verify=Mock())
        args = SimpleNamespace(project=project, candidate=candidate, gate=gate_file,
                               marker=tmp_path / 'marker', state=state, verifier=tmp_path / 'verifier',
                               hold_id='fixture', parked_package=True, fenced_host=True, action='install')
        receipt = installer.Transaction(args, tree, journal, hold, manifest).run()
        assert receipt['phase'] == 'INSTALLED' and receipt['wrapper_host_fenced'] is True
        assert not host.exists()
        for path in set(scope) - {installer.WRAPPER_HOST}:
            assert installer.read_file(*installer.entry(tree, path))[0] == after[path]
        assert installer.Transaction(args, tree, journal, hold, manifest).run() == receipt

        rmtree(candidate)
        args.candidate = None
        args.action = 'rollback'
        rollback = installer.Transaction(args, tree, journal, hold, manifest).run()
        assert rollback['phase'] == 'ROLLED_BACK' and rollback['wrapper_host_fenced'] is True
        assert not host.exists()
        for path in set(scope) - {installer.WRAPPER_HOST}:
            assert installer.read_file(*installer.entry(tree, path))[0] == before[path]
        assert installer.Transaction(args, tree, journal, hold, manifest).run() == rollback
