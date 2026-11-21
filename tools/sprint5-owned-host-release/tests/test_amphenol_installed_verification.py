from pathlib import Path

import pytest

from acquiretm_membership_recipe import TARGET_PATH
from amphenol_installed_verification import measure_amphenol_recipe_runtime, verify_installed_amphenol_recipe
from job_search_helper.integration_release import MANIFEST_SCHEMA, digest, manifest_release_id


@pytest.fixture
def installed(tmp_path):
    adapter = tmp_path / TARGET_PATH
    adapter.parent.mkdir(parents=True)
    adapter.write_text('PAGE_WAIT = True\n')
    (adapter.parent / 'other.py').write_text('ENABLED = True\n')
    (tmp_path / 'title-blacklist.txt').write_text('excluded\n')
    (tmp_path / 'requirements.txt').write_text('sample==1\n')
    evidence = measure_amphenol_recipe_runtime(tmp_path)
    manifest = {
        'schema': MANIFEST_SCHEMA,
        'failed_request_id': 'company-event:amphenol-fixture',
        'company_id': 'COMP-0490',
        'source_revision': 'a' * 64,
        'files': {TARGET_PATH: {'before': {**evidence['wrapper'], 'sha256': 'b' * 64},
                                'after': evidence['wrapper']}},
        'before_source_manifest_sha256': 'c' * 64,
        'source_manifest_sha256': evidence['source_manifest_sha256'],
        'dependency_manifest_sha256': evidence['dependency_manifest_sha256'],
        'before_config_sha256': evidence['config_sha256'],
        'config_sha256': evidence['config_sha256'],
        'validation_receipt_sha256': digest(evidence),
    }
    manifest['release_id'] = manifest_release_id(manifest)
    return tmp_path, manifest, evidence


def test_exact_installed_verification_replays(installed):
    root, manifest, evidence = installed
    assert verify_installed_amphenol_recipe(root, manifest) == evidence
    assert verify_installed_amphenol_recipe(root, manifest) == evidence


@pytest.mark.parametrize('path', [TARGET_PATH, Path(TARGET_PATH).with_name('other.py'),
                                  'title-blacklist.txt', 'requirements.txt'])
def test_installed_verification_holds_changed_bytes(installed, path):
    root, manifest, _ = installed
    (root / path).write_text('changed = True\n')
    with pytest.raises(ValueError, match='differs from the independently qualified version'):
        verify_installed_amphenol_recipe(root, manifest)


def test_installed_verification_holds_invalid_source_and_changed_receipt(installed):
    root, manifest, _ = installed
    manifest['validation_receipt_sha256'] = 'd' * 64
    manifest['release_id'] = manifest_release_id(manifest)
    with pytest.raises(ValueError, match='differs from the independently qualified version'):
        verify_installed_amphenol_recipe(root, manifest)
    (root / TARGET_PATH).write_text('PAGE_WAIT =\n')
    with pytest.raises(ValueError, match='failed to compile'):
        verify_installed_amphenol_recipe(root, manifest)
