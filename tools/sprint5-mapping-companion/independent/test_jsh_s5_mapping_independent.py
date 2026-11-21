"""Independent scope probes for the paired source release."""

import json

import pytest

from job_search_helper.integration_release import canonical_manifest, manifest_release_id, metadata, source_tree_digest
from test_release_qualification import approved, assert_pristine, qualification, release, schedule
from test_release_source_mapping import COMPANY, DESCRIPTOR, REGISTRY, prepare, specimen


def refresh(release):
    for name in (REGISTRY, DESCRIPTOR):
        release.manifest['files'][name]['after'] = metadata(release.candidate / name)
    release.manifest['source_manifest_sha256'] = source_tree_digest(release.candidate)
    release.manifest['release_id'] = manifest_release_id(release.manifest)


def test_descriptor_cannot_be_released_without_registry(release):
    prepare(release)
    del release.manifest['files'][REGISTRY]
    release.manifest['release_id'] = manifest_release_id(release.manifest)
    with pytest.raises(ValueError, match='paired existing registry and descriptor'):
        canonical_manifest(release.manifest)
    assert_pristine(release)


@pytest.mark.parametrize('name', [REGISTRY, DESCRIPTOR])
def test_companion_gate_does_not_create_missing_members(release, name):
    prepare(release)
    release.manifest['files'][name]['before'] = None
    release.manifest['release_id'] = manifest_release_id(release.manifest)
    with pytest.raises(ValueError, match='paired existing registry and descriptor'):
        canonical_manifest(release.manifest)
    assert not release.records.exists()


def test_additional_configuration_is_not_part_of_mapping_exception(release):
    prepare(release)
    name = '.state/integration-configs/C-1.json'
    (release.candidate / name).write_text('{"version":3}')
    release.manifest['files'][name] = {
        'before': metadata(release.project / name), 'after': metadata(release.candidate / name),
    }
    release.manifest['release_id'] = manifest_release_id(release.manifest)
    with pytest.raises(ValueError, match='paired existing registry and descriptor'):
        canonical_manifest(release.manifest)
    assert_pristine(release)


@pytest.mark.parametrize('change', ['capability', 'membership', 'duplicate_mapping'])
def test_descriptor_cannot_extend_qualified_scope(release, change):
    prepare(release)
    path = release.candidate / DESCRIPTOR
    data = json.loads(path.read_bytes())
    if change == 'capability':
        data['capabilities'][0]['provider'] = 'greenhouse'
    elif change == 'membership':
        data['mappings'] = [item for item in data['mappings'] if item['company_id'] == COMPANY]
    else:
        data['mappings'].append(dict(data['mappings'][0]))
    path.write_text(json.dumps(data))
    refresh(release)
    with approved(release) as (owner, _):
        with pytest.raises(ValueError, match='companion'):
            schedule(release, owner)
    assert_pristine(release)


def test_target_cannot_change_to_an_unqualified_provider_host(release):
    prepare(release)
    specimen(release.candidate, 'https://foreign.example/forterra/jobs')
    refresh(release)
    with approved(release) as (owner, _):
        with pytest.raises(ValueError, match='invalid or unmeasured mapping'):
            schedule(release, owner)
    assert_pristine(release)


def test_paired_release_still_refuses_public_only_qualification(release):
    prepare(release)
    record = qualification(release)
    record.update(result='PUBLIC_EVIDENCE_ACCEPTED', evidence_class='captured_public', release_qualification=False)
    with approved(release, record) as (owner, _):
        with pytest.raises(ValueError, match='lacks independent live release qualification'):
            schedule(release, owner)
    assert_pristine(release)
