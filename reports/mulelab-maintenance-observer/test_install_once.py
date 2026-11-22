import os

import pytest

from install_once import read_staged_bundle


def test_root_stage_input_accepts_only_bounded_regular_file(tmp_path):
    stage = tmp_path / 'private'
    stage.mkdir(mode=0o700)
    bundle = stage / 'bundle'
    bundle.write_bytes(b'approved bytes')
    assert read_staged_bundle(bundle) == b'approved bytes'
    symlink = stage / 'alias'
    symlink.symlink_to(bundle)
    with pytest.raises(OSError):
        read_staged_bundle(symlink)
    fifo = stage / 'fifo'
    os.mkfifo(fifo)
    with pytest.raises(ValueError, match='bounded regular file'):
        read_staged_bundle(fifo)
    directory_alias = tmp_path / 'directory_alias'
    directory_alias.symlink_to(stage, target_is_directory=True)
    with pytest.raises(OSError):
        read_staged_bundle(directory_alias / bundle.name)
