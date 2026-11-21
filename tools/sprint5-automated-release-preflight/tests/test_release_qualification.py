"""Guard the automated release path using disposable qualification fixtures."""

from contextlib import contextmanager
from hashlib import sha256
import json
import os
import runpy

import pytest

import test_integration_release as release_fixtures
from job_search_helper import release_controller
from job_search_helper.cli import WriterLockBusy, scraper_lock_name, writer_lock
from job_search_helper.integration_release import (
    assert_release_settled, config_tree_digest, digest, manifest_release_id, metadata,
    rollback_release, source_tree_digest,
)
from job_search_helper.release_qualification import open_release_qualification_owner


@pytest.fixture
def release():
    fixture = release_fixtures.IntegrationReleaseTests(
        'test_complete_activation_is_one_full_version_and_records_binding',
    )
    fixture.setUp()
    try:
        yield fixture
    finally:
        fixture.doCleanups()


def qualification(release):
    return {
        'schema': 'integration-live-release-qualification-v1',
        'result': 'PASS',
        'evidence_class': 'live_normal_dispatch',
        'release_qualification': True,
        'manifest_sha256': digest(release.manifest),
        'capture_manifest_sha256': 'c' * 64,
        'candidate_validation_sha256': release.manifest['validation_receipt_sha256'],
        'reviewed_tools_sha256': 'a' * 64,
    }


@contextmanager
def approved(release, contents=None):
    path = release.root / 'qualification'
    path.mkdir(mode=0o700)
    receipt = path / (release.manifest['release_id'] + '.json')
    payload = qualification(release) if contents is None else contents
    data = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()
    receipt.write_bytes(data)
    receipt.chmod(0o600)
    identity = path.stat()
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with open_release_qualification_owner(
            path, descriptor, expected_owner_identity=(identity.st_dev, identity.st_ino),
            approved_receipt_sha256=sha256(data).hexdigest(),
        ) as owner:
            yield owner, receipt
    finally:
        os.close(descriptor)


def schedule(release, owner, *, verify=None, fault=None):
    return release_controller.release_and_schedule_qualified(
        release.project, release.candidate, release.database, release.records, release.manifest,
        qualification_owner=owner, current_source_revision=lambda company_id: 'revision-1',
        dependency_digest=lambda: 'd' * 64,
        verify=verify or (lambda project, manifest: release.verification), fault=fault,
    )


def assert_pristine(release):
    assert not release.records.exists()
    assert not (release.state / 'integration-release-journal.json').exists()
    assert not (release.state / 'next-scan.json').exists()
    assert source_tree_digest(release.project) == release.manifest['before_source_manifest_sha256']
    assert config_tree_digest(release.project) == release.manifest['before_config_sha256']
    assert all(metadata(release.project / name) == item['before']
               for name, item in release.manifest['files'].items())


@pytest.mark.parametrize('change', [
    {'evidence_class': 'offline_saved_captures', 'result': 'VERIFIED_MISMATCH', 'release_qualification': False},
    {'evidence_class': 'synthetic_fixture', 'result': 'FIXTURE_PASS'},
    {'evidence_class': 'captured_public', 'result': 'PUBLIC_EVIDENCE_ACCEPTED', 'release_qualification': False},
    {'evidence_class': 'captured_public'},
    {'release_qualification': False},
    {'manifest_sha256': '9' * 64},
    {'candidate_validation_sha256': '9' * 64},
    {'reviewed_tools_sha256': 'unknown'},
])
def test_unqualified_receipt_stops_before_any_release_entry(release, monkeypatch, change):
    payload = {**qualification(release), **change}
    monkeypatch.setattr(release_controller, 'activate_release', lambda *args, **kw: pytest.fail('installer entered'))
    with approved(release, payload) as (owner, _):
        with pytest.raises(ValueError, match='lacks independent live release qualification'):
            schedule(release, owner)
    assert not (release.state / scraper_lock_name()).exists()
    assert_pristine(release)


def test_untrusted_receipt_dictionary_is_not_authority(release):
    with pytest.raises(ValueError, match='independently configured'):
        schedule(release, qualification(release))
    assert_pristine(release)


def test_receipt_removed_after_initial_read_holds_inside_the_scraper_lease(release, monkeypatch):
    original = release_controller._verify_projected_release
    with approved(release) as (owner, receipt):
        def withdraw(project_root, manifest):
            original(project_root, manifest)
            with pytest.raises(WriterLockBusy):
                with writer_lock(release.state / scraper_lock_name()):
                    pytest.fail('no scraper admission during qualification readback')
            receipt.rename(receipt.with_suffix('.withdrawn'))

        monkeypatch.setattr(release_controller, '_verify_projected_release', withdraw)
        with pytest.raises(ValueError, match='qualification receipt is unavailable'):
            schedule(release, owner)
    assert_pristine(release)


def test_same_receipt_relocated_to_a_new_owner_directory_holds(release):
    with approved(release) as (owner, record):
        raw = record.read_bytes()
        record.parent.rename(record.parent.with_name('retired-owner'))
        record.parent.mkdir(mode=0o700)
        record.write_bytes(raw)
        record.chmod(0o600)
        with pytest.raises(ValueError, match='directory is unavailable or was replaced'):
            schedule(release, owner)
    assert_pristine(release)


def test_unlisted_candidate_file_holds_before_rollback_backup(release):
    (release.candidate / 'src/job_search_helper/unlisted.py').write_text('EXTRA = True\n')
    release.manifest['source_manifest_sha256'] = source_tree_digest(release.candidate)
    release.manifest['release_id'] = manifest_release_id(release.manifest)
    with approved(release) as (owner, _):
        with pytest.raises(ValueError, match='release files do not produce the complete qualified version'):
            schedule(release, owner)
    assert_pristine(release)


def test_candidate_changed_after_receipt_holds_without_backup(release):
    with approved(release) as (owner, _):
        (release.candidate / 'src/job_search_helper/unlisted.py').write_text('EXTRA = True\n')
        with pytest.raises(ValueError, match='complete candidate differs'):
            schedule(release, owner)
    assert_pristine(release)


def test_qualified_activation_replays_once_after_a_cut_before_retry(release):
    verification_calls = []

    def verify(installed, manifest):
        assert source_tree_digest(installed) == manifest['source_manifest_sha256']
        assert config_tree_digest(installed) == manifest['config_sha256']
        assert not (release.state / 'next-scan.json').exists()
        verification_calls.append(manifest['release_id'])
        return release.verification

    def cut(stage):
        if stage == 'after_activation':
            raise RuntimeError('interrupted before retry scheduling')

    with approved(release) as (owner, _):
        with pytest.raises(RuntimeError, match='before retry scheduling'):
            schedule(release, owner, verify=verify, fault=cut)
        assert not (release.state / 'next-scan.json').exists()
        receipt = release.records / release.manifest['release_id'] / 'receipt.json'
        first_record = receipt.read_bytes()
        first = schedule(release, owner, verify=verify)
        second = schedule(release, owner, verify=verify)
    assert first['state'] == 'REQUEST_WRITTEN' and second['state'] == 'REQUEST_ALREADY_DURABLE'
    assert first['attempt_id'] == second['attempt_id']
    assert first_record == receipt.read_bytes()
    assert verification_calls == [release.manifest['release_id']]


@pytest.mark.parametrize('field,replacement', [
    ('company_id', 'C-2'), ('source_revision', 'different'), ('failed_request_id', 'other-request'),
    ('activated_at', '2026-11-20T21:30:00Z'), ('verification', {'result': 'PASS', 'tests': 999}),
])
def test_qualified_replay_refuses_a_changed_completed_receipt_before_retry(release, field, replacement):
    def cut(stage):
        if stage == 'after_activation':
            raise RuntimeError('interrupted before retry scheduling')

    with approved(release) as (owner, _):
        with pytest.raises(RuntimeError, match='before retry scheduling'):
            schedule(release, owner, fault=cut)
        receipt = release.records / release.manifest['release_id'] / 'receipt.json'
        saved = json.loads(receipt.read_bytes())
        saved[field] = replacement
        receipt.write_text(json.dumps(saved))
        with pytest.raises(RuntimeError, match='release identity conflicts with its receipt'):
            schedule(release, owner)
    assert not (release.state / 'next-scan.json').exists()


def test_qualified_replay_requires_receipt_pin_and_legacy_manual_replay_still_works(release):
    original = release.activate()
    journal_path = release.state / 'integration-release-journal.json'
    journal = json.loads(journal_path.read_bytes())
    assert journal.pop('receipt_sha256') == digest(original)
    journal_path.write_text(json.dumps(journal))
    with approved(release) as (owner, _):
        with pytest.raises(RuntimeError, match='release identity conflicts with its receipt'):
            schedule(release, owner)
    assert not (release.state / 'next-scan.json').exists()
    assert release.activate() == original


def test_post_install_verification_remains_required_before_retry(release):
    with approved(release) as (owner, _):
        with pytest.raises(RuntimeError, match='Installed release verification did not pass'):
            schedule(release, owner, verify=lambda root, manifest: {'result': 'HOLD'})
    with pytest.raises(RuntimeError, match='interrupted integration release'):
        assert_release_settled(release.state)
    assert not (release.state / 'next-scan.json').exists()
    rollback_release(release.project, release.database, release.records, release.manifest['release_id'])
    assert source_tree_digest(release.project) == release.manifest['before_source_manifest_sha256']
    assert config_tree_digest(release.project) == release.manifest['before_config_sha256']
    assert not (release.state / 'next-scan.json').exists()


def test_capture_root_config_pin_matches_the_measured_bootstrap(release, monkeypatch):
    project = release.project
    bootstrap = runpy.run_path(os.fspath(release_controller.Path(release_controller.__file__).resolve().parents[2]
                                          / 'release_admission_bootstrap.py'))
    baseline = config_tree_digest(project)
    monkeypatch.setenv('JOB_SEARCH_ORDINARY_CAPTURE_ROOT', os.fspath(release.root / 'private-captures'))
    assert config_tree_digest(project) == bootstrap['config_tree_digest'](project)
    assert config_tree_digest(project) != baseline
