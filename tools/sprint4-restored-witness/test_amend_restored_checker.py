from contextlib import contextmanager
import fcntl
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from amend_restored_checker import amended, commit_rebind, verify_archive_delta, verify_held_protected
from host_exchange import _exchange
from test_protected_state import ProtectedWitnessTests as WitnessFixture


def checker(**entries):
    file = BytesIO()
    with ZipFile(file, 'w') as archive:
        for name, text in entries.items():
            archive.writestr(name, text)
    return b'#!/usr/bin/python3 -I\n' + file.getvalue()


def test_only_entrypoint_can_change_under_same_policy():
    before = {'__main__.py': 'old', 'approved_site_policy.json': '{"held":true}', 'rule.py': 'unchanged'}
    original = checker(**before)
    approved = {**before, '__main__.py': 'new'}
    assert verify_archive_delta(original, checker(**approved)) == {'held': True}
    for key in ('approved_site_policy.json', 'rule.py'):
        with pytest.raises(ValueError, match='Only the independently reviewed'):
            verify_archive_delta(original, checker(**{**approved, key: 'changed'}))


def test_only_checker_binding_can_change_for_actual_refused_rollback():
    original = {'binding': {'files': {'/mock/checker': ['old'], '/mock/guard': ['same']}, 'lock': 'exact'},
                'phase': 'RELEASE_REFUSED', 'target': 'ROLLED_BACK',
                'receipt': {'phase': 'ROLLED_BACK', 'frozen': 'original receipt'}}
    expected = amended(original, '/mock/checker', ['old'], ['new'])
    assert expected['receipt'] is original['receipt']
    assert expected['binding']['lock'] == 'exact'
    assert expected['binding']['files'] == {'/mock/checker': ['new'], '/mock/guard': ['same']}
    assert original['binding']['files']['/mock/checker'] == ['old']
    with pytest.raises(ValueError, match='Only a refused original-source rollback'):
        amended({**original, 'phase': 'HELD'}, '/mock/checker', ['old'], ['new'])
    with pytest.raises(ValueError, match='completed installer rollback receipt'):
        amended({**original, 'receipt': None}, '/mock/checker', ['old'], ['new'])
    with pytest.raises(ValueError, match='Original checker authority differs'):
        amended(original, '/mock/checker', ['wrong'], ['new'])


def fixture_storage(tmp_path):
    original, replacement, journal = (tmp_path / n for n in ('checker', 'checker.alternate', 'controller.json'))
    original.write_bytes(b'old bits')
    replacement.write_bytes(b'new bits')
    journal.write_bytes(b'old journal')

    def ref(path):
        return path.stat().st_ino, sha256(path.read_bytes()).hexdigest()

    def rename(left, right, flags):
        assert flags == 2 and left.parent == right.parent == tmp_path
        fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            _exchange(fd, left.name, right.name)
        finally:
            os.close(fd)

    def write(path, data, *, replace):
        assert replace
        scratch = path.with_name('pending-journal')
        scratch.write_bytes(data)
        os.replace(scratch, path)

    joint = SimpleNamespace(ref=ref, read=lambda p: (p.read_bytes(),), write=write,
                            gate=SimpleNamespace(rename=rename, syncdir=lambda path: None))
    return joint, (original, replacement, journal, ref(original), ref(replacement), b'old journal', b'new journal')


def test_atomic_checker_exchange_can_replay_before_and_after_journal(tmp_path):
    joint, args = fixture_storage(tmp_path)
    original, replacement, journal, *_ = args
    write = joint.write

    def cut(*args, **kwargs):
        raise InterruptedError('between the two names')

    joint.write = cut
    with pytest.raises(InterruptedError):
        commit_rebind(joint, *args)
    assert original.read_bytes() == b'new bits' and replacement.read_bytes() == b'old bits'
    assert journal.read_bytes() == b'old journal'

    def after(*args, **kwargs):
        write(*args, **kwargs)
        raise InterruptedError('after journal swap')

    joint.write = after
    with pytest.raises(InterruptedError):
        commit_rebind(joint, *args)
    assert journal.read_bytes() == b'new journal'
    commit_rebind(joint, *args)
    assert original.read_bytes() == b'new bits' and replacement.read_bytes() == b'old bits'


def test_unknown_journal_or_checker_cannot_be_adopted(tmp_path):
    joint, args = fixture_storage(tmp_path)
    original, replacement, journal, *_ = args
    journal.write_bytes(b'foreign')
    with pytest.raises(ValueError, match='Old checker cannot own'):
        commit_rebind(joint, *args)
    assert original.read_bytes() == b'old bits'
    journal.write_bytes(b'old journal')
    replacement.write_bytes(b'tampered')
    with pytest.raises(ValueError, match='Unexpected checker amendment'):
        commit_rebind(joint, *args)
    assert original.read_bytes() == b'old bits'


@contextmanager
def protected_fixture():
    fixture = WitnessFixture()
    fixture.setUp()
    try:
        yield fixture
    finally:
        fixture.doCleanups()


def test_sealed_held_proof_checks_real_marker_lease_and_same_baseline():
    with protected_fixture() as fixture:
        came_from = Path(__file__).resolve().parent
        members = ['protected_state.py', 'physical_protected_witness.py', 'alternate_writer_witness.py']
        source = checker(**{name: (came_from / name).read_text() for name in members})
        expected = 'reviewed-test-maintenance'
        marker = fixture.root / '.state/integration-release-journal.json'
        marker.write_text(json.dumps({'schema': 'integration-release-journal-v1',
                                      'state': 'FOUNDATION_MAINTENANCE', 'maintenance_id': expected}))
        policy = {'protected_pin_file': str(fixture.pin), 'protected_pin_sha256': fixture.digest,
                  'site': {'maintenance_id': expected}}
        lease = fixture.root / '.state/scraper.lock'
        with lease.open('wb') as fd:
            with pytest.raises(ValueError, match='under the exact held marker'):
                verify_held_protected(fixture.root, source, policy)
            fcntl.flock(fd, fcntl.LOCK_EX)
            verify_held_protected(fixture.root, source, policy)
            marker.unlink()
            with pytest.raises(ValueError, match='under the exact held marker'):
                verify_held_protected(fixture.root, source, policy)
