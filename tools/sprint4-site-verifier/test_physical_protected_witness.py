import os

import pytest

from physical_protected_witness import physical_snapshot, WitnessHold
import test_protected_state as fixtures


@pytest.fixture
def checkout():
    disposable = fixtures.ProtectedWitnessTests()
    disposable.setUp()
    try:
        yield disposable.root
    finally:
        disposable.doCleanups()


def test_stable_files_have_same_fingerprint_and_archive_membership_drift_changes_it(checkout):
    original = physical_snapshot(checkout)
    assert physical_snapshot(checkout) == original
    archive = checkout / '.state/retained-operator-admission-archive'
    (archive / 'new-receipt.json').write_bytes(b'fixture drift')
    assert physical_snapshot(checkout) != original


def test_retained_first_pass_bucket_and_nested_file_change_break_continuity(checkout):
    original = physical_snapshot(checkout)
    bucket = checkout / '.state/retained-first-pass/example'
    bucket.mkdir(parents=True)
    evidence = bucket / 'release.json'
    evidence.write_text('first fixture version')
    added = physical_snapshot(checkout)
    assert added != original
    evidence.write_text('other fixture version')
    assert physical_snapshot(checkout) != added


def test_sidecar_presence_is_pinned_and_requires_owning_database(checkout):
    own = checkout / '.state/jobs.sqlite3-wal'
    start = physical_snapshot(checkout)
    own.write_bytes(b'')
    assert physical_snapshot(checkout) != start
    missing = checkout / '.state/company-intake-dispatch.sqlite3-wal'
    missing.write_bytes(b'')
    with pytest.raises(WitnessHold, match='no owning database'):
        physical_snapshot(checkout)


def test_same_size_and_mtime_rewrite_is_not_continuity(checkout):
    source = checkout / 'dev/wrapper-coder/tools/coordinator_repair_profiles.py'
    original = physical_snapshot(checkout)
    prior = source.stat()
    source.write_bytes(b'x' * prior.st_size)
    os.utime(source, ns=(prior.st_atime_ns, prior.st_mtime_ns))
    assert physical_snapshot(checkout) != original


def test_alias_cannot_substitute_for_a_protected_file(checkout):
    original = checkout / '.state/state.db'
    moved = original.rename(original.with_suffix('.previous'))
    original.symlink_to(moved)
    with pytest.raises(WitnessHold, match='substituted'):
        physical_snapshot(checkout)
