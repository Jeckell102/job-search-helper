"""Disposable checks of the existing measurement scope. Holds no issuance authority."""

from contextlib import contextmanager
import fcntl
from hashlib import sha256
import os

import pytest

import release_admission_bootstrap as bootstrap


@contextmanager
def _locked(path):
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(descriptor)


@contextmanager
def _measurement_window(state):
    with _locked(state / 'scraper.lock'), _locked(state / 'writer.lock'):
        yield


@pytest.fixture
def completed_runtime(tmp_path):
    project = tmp_path / 'project'
    state = tmp_path / 'state'
    record = tmp_path / 'release'
    source = project / 'src/job_search_helper'
    for directory in (source, state, record):
        directory.mkdir(mode=0o700, parents=True)
    app_file = source / 'fixture.py'
    app_file.write_text('value = 1\n')
    (project / 'pyproject.toml').write_text('[project]\nname = "fixture"\n')
    (project / 'title-blacklist.txt').write_text('first\n')
    launcher = project / 'release_admission_bootstrap.py'
    launcher.write_bytes(b'# Test launcher file outside the measured package.\n')

    with _measurement_window(state):
        no_release = bootstrap._validate_runtime(project, state)
    assert no_release.pop('state') == 'NO_RELEASE'
    release = {'schema': 'integration-release-binding-v1', 'release_id': 'REL-measurement-fixture', **no_release}
    complete = {
        'state': 'COMPLETE', 'release_id': release['release_id'], 'manifest_sha256': '1' * 64,
        'release': release,
    }
    (record / 'receipt.json').write_text(bootstrap._canonical(complete))
    (state / 'integration-release-journal.json').write_text(bootstrap._canonical({
        'schema': bootstrap.JOURNAL_SCHEMA, 'record': str(record), **complete,
    }))
    return project, state, launcher, {'state': 'COMPLETE', 'release_id': release['release_id'], **no_release}


@pytest.mark.parametrize('changed_path', ('src/job_search_helper/fixture.py', 'title-blacklist.txt', 'pyproject.toml'))
def test_fresh_measurement_after_lease_reentry_holds_runtime_drift(completed_runtime, changed_path):
    project, state, _, expected = completed_runtime
    with _measurement_window(state):
        assert bootstrap._validate_runtime(project, state) == expected

    changed = project / changed_path
    changed.write_bytes(changed.read_bytes() + b'# changed during the fixture gap\n')

    with _measurement_window(state), pytest.raises(RuntimeError, match='does not match the terminal release'):
        bootstrap._validate_runtime(project, state)


def test_application_measurement_does_not_measure_standalone_launcher(completed_runtime):
    project, state, launcher, expected = completed_runtime
    with _measurement_window(state):
        assert bootstrap._validate_runtime(project, state) == expected
        initial_digest = sha256(launcher.read_bytes()).hexdigest()

    launcher.write_bytes(b'# Replacement fixture bytes.\n')

    with _measurement_window(state):
        assert bootstrap._validate_runtime(project, state) == expected
        assert sha256(launcher.read_bytes()).hexdigest() != initial_digest
