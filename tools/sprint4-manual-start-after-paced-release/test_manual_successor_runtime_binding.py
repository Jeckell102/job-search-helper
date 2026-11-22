"""Disposable admission check for ordinary Start after an active paced release."""

from pathlib import Path
from shutil import copy2, copytree, ignore_patterns

import pytest

import release_admission_bootstrap as bootstrap
from job_search_helper.integration_release import (
    MANIFEST_SCHEMA,
    activate_release,
    config_tree_digest,
    dependency_manifest_digest,
    digest,
    manifest_release_id,
    metadata,
    source_tree_digest,
)


STAGE = Path(__file__).parent
PACED = Path('/tmp/jsh-amphenol-production-pacing.q7WLuQwO/candidate')
ADAPTER = 'src/job_search_helper/acquiretm.py'
MANUAL_FILES = ('src/job_search_helper/runner.py', 'src/job_search_helper/manual_company_start.py')
STATIC_FILES = ('pyproject.toml', 'title-blacklist.txt', 'title-review-list.txt')


def stage_public_sources(source, dest):
    copytree(source / 'src/job_search_helper', dest / 'src/job_search_helper',
             ignore=ignore_patterns('__pycache__', '*.pyc'))
    for name in STATIC_FILES:
        copy2(STAGE / name, dest / name)


def activate_fixture(project, candidate, paths, request):
    revision = 'a' * 64
    verification = {'result': 'PASS', 'disposable_test': True}
    manifest = {
        'schema': MANIFEST_SCHEMA,
        'company_id': 'COMP-FIXTURE',
        'failed_request_id': request,
        'source_revision': revision,
        'files': {
            name: {'before': metadata(project / name) if (project / name).exists() else None,
                   'after': metadata(candidate / name)}
            for name in paths
        },
        'before_source_manifest_sha256': source_tree_digest(project),
        'source_manifest_sha256': source_tree_digest(candidate),
        'before_config_sha256': config_tree_digest(project),
        'config_sha256': config_tree_digest(candidate),
        'dependency_manifest_sha256': dependency_manifest_digest(project),
        'validation_receipt_sha256': digest(verification),
    }
    manifest['release_id'] = manifest_release_id(manifest)
    state = project / '.state'
    return activate_release(
        project, candidate, state / 'state.db', state / 'integration-releases', manifest,
        current_source_revision=lambda _: revision,
        dependency_digest=lambda: dependency_manifest_digest(project),
        verify=lambda *_: verification,
    )


def test_manual_start_needs_a_successor_runtime_binding_after_paced_release(tmp_path):
    project = tmp_path / 'project'
    paced = tmp_path / 'paced'
    stage_public_sources(PACED, paced)
    stage_public_sources(PACED, project)
    copy2(STAGE / 'fixture-before-acquiretm.py', project / ADAPTER)
    state = project / '.state'
    state.mkdir()
    prior = activate_fixture(project, paced, (ADAPTER,), 'disposable-paced')
    former_record = state / 'integration-releases' / prior['release_id'] / 'receipt.json'
    former_receipt = former_record.read_bytes()
    assert bootstrap._validate_runtime(project, state)['release_id'] == prior['release_id']

    # Simulate a plain source overlay under the still-active prior journal.
    with pytest.raises(RuntimeError, match='Installed runtime does not match'):
        bootstrap._validate_runtime(STAGE, state)

    successor = activate_fixture(project, STAGE, MANUAL_FILES, 'disposable-manual-start')
    binding = bootstrap._validate_runtime(project, state)
    assert binding['state'] == 'COMPLETE'
    assert binding['release_id'] == successor['release_id'] != prior['release_id']
    assert binding['source_manifest_sha256'] == source_tree_digest(STAGE)
    assert metadata(project / ADAPTER) == metadata(PACED / ADAPTER)
    assert former_record.read_bytes() == former_receipt
    assert not (state / 'next-scan.json').exists()
