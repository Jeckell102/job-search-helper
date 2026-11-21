"""Exercise a paired Forterra mapping correction on disposable release stores."""

from hashlib import sha256
import json
from pathlib import Path
import shutil

import pytest

from job_search_helper.integration_release import (
    canonical_manifest, config_tree_digest, manifest_release_id, metadata, rollback_release, source_tree_digest,
)
from job_search_helper.release_source_mapping import DESCRIPTOR, REGISTRY, verify_companion_mapping
from job_search_helper.source_configuration_snapshot import _PATHS
from test_release_qualification import approved, assert_pristine, release, schedule


COMPANY = 'COMP-0066'
STABLE_COMPANY = 'COMP-0178'
GOOD_BOARD = 'https://ats.rippling.com/forterra/jobs'
STALE_BOARD = 'https://ats.rippling.com/retired-fixture/jobs'
CONTROL_BOARD = 'https://ats.rippling.com/pdwcareers/jobs'


def specimen(root, board, *, control_board=CONTROL_BOARD, extra='', recorded_board=None):
    rows = [
        (COMPANY, 'Forterra', 'https://www.forterra.com/careers', board),
        (STABLE_COMPANY, 'PDW', 'https://www.pdw.ai/careers', control_board),
    ]
    registry = {
        cid: {'ats': 'Rippling', 'company': company, 'url': url, 'expected_url': authority, 'evidence': authority}
        for cid, company, authority, url in rows
    }
    source = ('REPAIRS = ' + repr(registry) + '\n' + extra).encode()
    (root / REGISTRY).write_bytes(source)
    descriptor = {
        'schema': 'source-configuration-manifest-v1',
        'capabilities': [{'capability_id': 'rippling-shared-v1', 'provider': 'rippling', 'source_paths': list(_PATHS)}],
        'mappings': [{
            'company_id': cid, 'company': company, 'provider': 'rippling', 'expected_url': authority,
            'configured_url': (recorded_board or url) if cid == COMPANY else url, 'evidence': authority,
            'capability_id': 'rippling-shared-v1', 'company_sources_sha256': sha256(source).hexdigest(),
        } for cid, company, authority, url in rows],
    }
    (root / DESCRIPTOR).write_text(json.dumps(descriptor))


def prepare(release, **candidate_options):
    for name in release.paths:
        shutil.copy2(release.project / name, release.candidate / name)
    specimen(release.project, STALE_BOARD)
    specimen(release.candidate, GOOD_BOARD, **candidate_options)
    release.manifest.update(
        company_id=COMPANY,
        files={name: {'before': metadata(release.project / name), 'after': metadata(release.candidate / name)}
               for name in (REGISTRY, DESCRIPTOR)},
        before_source_manifest_sha256=source_tree_digest(release.project),
        source_manifest_sha256=source_tree_digest(release.candidate),
        before_config_sha256=config_tree_digest(release.project),
        config_sha256=config_tree_digest(release.candidate),
    )
    release.manifest['release_id'] = manifest_release_id(release.manifest)


def test_exact_paired_source_and_descriptor_can_install_and_schedule_once(release):
    prepare(release)
    with approved(release) as (owner, _):
        first = schedule(release, owner)
        again = schedule(release, owner)
    assert first['state'] == 'REQUEST_WRITTEN' and again['state'] == 'REQUEST_ALREADY_DURABLE'
    assert first['attempt_id'] == again['attempt_id']
    assert all((release.project / name).read_bytes() == (release.candidate / name).read_bytes()
               for name in (REGISTRY, DESCRIPTOR))


def test_a_manual_release_does_not_use_the_companion_exception(release):
    prepare(release)
    with pytest.raises(ValueError, match='requires automated candidate qualification'):
        release.activate()
    assert_pristine(release)


def test_a_preinstall_callback_alone_does_not_qualify_the_mapping_companion(release):
    prepare(release)
    with pytest.raises(ValueError, match='requires automated candidate qualification'):
        release.activate(preinstall=lambda manifest: pytest.fail('unqualified installer callback ran'))
    assert_pristine(release)


def test_an_automated_registry_change_requires_its_measured_descriptor(release):
    prepare(release)
    release.manifest['files'].pop(DESCRIPTOR)
    release.manifest['release_id'] = manifest_release_id(release.manifest)
    with approved(release) as (owner, _):
        with pytest.raises(ValueError, match='requires its paired source mapping descriptor'):
            schedule(release, owner)
    assert_pristine(release)


@pytest.mark.parametrize('change,reason', [
    ({'control_board': 'https://ats.rippling.com/other-control/jobs'}, 'changes unqualified Company'),
    ({'extra': 'UNRELATED_RUNTIME_BEHAVIOR = True\n'}, 'outside the qualified Company board'),
    ({'recorded_board': 'https://ats.rippling.com/foreign-fixture/jobs'}, 'exact literal Company mapping'),
])
def test_qualified_descriptor_still_requires_an_exact_single_board_change(release, change, reason):
    prepare(release, **change)
    with approved(release) as (owner, _):
        with pytest.raises(ValueError, match=reason):
            schedule(release, owner)
    assert_pristine(release)


def test_extra_package_json_remains_outside_release_scope(release):
    prepare(release)
    unreviewed = 'src/job_search_helper/unreviewed.json'
    (release.candidate / unreviewed).write_text('{}')
    release.manifest['files'][unreviewed] = {'before': None, 'after': metadata(release.candidate / unreviewed)}
    release.manifest['release_id'] = manifest_release_id(release.manifest)
    with pytest.raises(ValueError, match='Python modules only'):
        canonical_manifest(release.manifest)


def test_mapping_companion_rolls_back_both_files_if_installed_verification_holds(release):
    prepare(release)
    rollback_bytes = {name: (release.project / name).read_bytes() for name in (REGISTRY, DESCRIPTOR)}
    with approved(release) as (owner, _):
        with pytest.raises(RuntimeError, match='Installed release verification did not pass'):
            schedule(release, owner, verify=lambda root, manifest: {'result': 'HOLD'})
    rollback_release(release.project, release.database, release.records, release.manifest['release_id'])
    assert not (release.state / 'next-scan.json').exists()
    assert rollback_bytes == {name: (release.project / name).read_bytes() for name in (REGISTRY, DESCRIPTOR)}


def test_measured_application_registry_accepts_the_exact_disposable_board_correction(tmp_path):
    source = Path(__file__).resolve().parents[1]
    previous = tmp_path / 'previous'
    candidate = tmp_path / 'candidate'
    for root in (previous, candidate):
        for name in (REGISTRY, DESCRIPTOR):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / name, path)
    original = (previous / REGISTRY).read_bytes()
    needle = GOOD_BOARD.encode()
    assert original.count(needle) == 1
    induced = original.replace(needle, STALE_BOARD.encode(), 1)
    (previous / REGISTRY).write_bytes(induced)
    descriptor = json.loads((previous / DESCRIPTOR).read_bytes())
    for mapping in descriptor['mappings']:
        mapping['company_sources_sha256'] = sha256(induced).hexdigest()
        if mapping['company_id'] == COMPANY:
            mapping['configured_url'] = STALE_BOARD
    (previous / DESCRIPTOR).write_text(json.dumps(descriptor))
    files = {name: {'before': metadata(previous / name), 'after': metadata(candidate / name)}
             for name in (REGISTRY, DESCRIPTOR)}
    verify_companion_mapping(previous, candidate, {'files': files, 'company_id': COMPANY})
