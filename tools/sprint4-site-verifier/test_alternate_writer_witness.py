import os

import pytest

from alternate_writer_witness import CoverPin, identity, matching_mounts, reject_unsafe_probe, verify_cover


def test_mount_info_distinguishes_exact_escaped_checkout_and_parent(tmp_path):
    target = tmp_path / 'job-search-helper backup'
    encoded = str(target).replace(' ', r'\040')
    rows = [
        f'10 8 8:1 / {tmp_path} rw,relatime - ext4 /dev/fake rw',
        f'41 10 8:1 /covered {encoded} ro,relatime - ext4 /dev/fake rw',
        f'52 41 8:1 /covered/sub {encoded}/sub ro - ext4 /dev/fake rw',
    ]
    assert tuple(matching_mounts(rows, target)) == ((41, {'ro', 'relatime'}),)


@pytest.mark.parametrize('relative', ['../job-search-scraper', '/usr/bin/python3', '.'])
def test_launcher_probe_cannot_leave_checkout(relative):
    with pytest.raises(ValueError):
        reject_unsafe_probe(relative)


def test_uncaptured_namespace_refuses_without_touching_checkout(tmp_path):
    pin = CoverPin(tmp_path / 'missing', identity(tmp_path.stat()), 1, (-1, -1), os.geteuid(),
                   ('job-search-scraper',))
    with pytest.raises(ValueError, match='namespace|non-root launch account'):
        verify_cover(pin)
