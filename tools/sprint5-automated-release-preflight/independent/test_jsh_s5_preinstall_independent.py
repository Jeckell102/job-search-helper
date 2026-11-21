"""Independent disposable probes; staged application source is read-only."""

import json

import pytest

from test_release_qualification import (
    approved, assert_pristine, qualification, release, schedule,
)
from job_search_helper import release_controller
from job_search_helper.integration_release import config_tree_digest, manifest_release_id


@pytest.mark.parametrize('field', ['schema', 'evidence_class', 'release_qualification',
                                   'reviewed_tools_sha256', 'capture_manifest_sha256'])
def test_missing_qualification_field_cannot_enter_installer(release, monkeypatch, field):
    record = qualification(release)
    record.pop(field)
    monkeypatch.setattr(release_controller, 'activate_release',
                        lambda *a, **k: pytest.fail('installer entered'))
    with approved(release, record) as (owner, _):
        with pytest.raises(ValueError, match='lacks independent live release qualification'):
            schedule(release, owner)
    assert_pristine(release)


@pytest.mark.parametrize('name,body', [('.state/integration-configs/extra.json', '{}'),
                                     ('.storage-backend', 'sqlite')])
def test_qualified_but_unlisted_config_is_rejected_before_backup(release, name, body):
    (release.candidate / name).write_text(body)
    release.manifest['config_sha256'] = config_tree_digest(release.candidate)
    release.manifest['release_id'] = manifest_release_id(release.manifest)
    with approved(release) as (owner, _):
        with pytest.raises(ValueError, match='release files do not produce the complete qualified version'):
            schedule(release, owner)
    assert_pristine(release)


def test_config_changes_after_approval_are_rejected_before_backup(release):
    with approved(release) as (owner, _):
        (release.candidate / '.state/integration-configs/extra.json').write_text('{}')
        with pytest.raises(ValueError, match='complete candidate differs'):
            schedule(release, owner)
    assert_pristine(release)


def test_offline_result_cannot_be_added_beneath_approved_live_envelope(release, monkeypatch):
    record = qualification(release)
    record['evidence'] = {'mode': 'offline_saved_captures', 'application_authority': False}
    monkeypatch.setattr(release_controller, 'activate_release',
                        lambda *a, **k: pytest.fail('installer entered'))
    with approved(release, record) as (owner, _):
        with pytest.raises(ValueError, match='lacks independent live release qualification'):
            schedule(release, owner)
    assert_pristine(release)


def test_same_owner_replacement_receipt_is_rejected_at_admission(release, monkeypatch):
    original = release_controller._verify_projected_release
    with approved(release) as (owner, path):
        def replace(project, manifest):
            original(project, manifest)
            changed = json.loads(path.read_bytes())
            changed['capture_manifest_sha256'] = 'e' * 64
            path.write_text(json.dumps(changed))
        monkeypatch.setattr(release_controller, '_verify_projected_release', replace)
        with pytest.raises(ValueError, match='qualification receipt changed'):
            schedule(release, owner)
    assert_pristine(release)
