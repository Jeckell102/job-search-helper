"""Measure the exact qualified Embraer repair after the guarded install."""

from hashlib import sha256
from pathlib import Path

from job_search_helper.integration_release import (
    canonical_manifest,
    config_tree_digest,
    dependency_manifest_digest,
    digest,
    metadata,
    source_tree_digest,
)


SOURCE = 'src/job_search_helper/shared_boards.py'
SCOPE = {SOURCE, 'tests/test_shared_boards.py', 'tests/test_embraer_typed_defect.py'}


def measure_embraer_runtime(project_root, changed_paths, *, unchanged_runtime_root=None):
    """Measure candidate source with the unchanged runtime used for qualification."""
    project_root = Path(project_root)
    runtime_root = Path(unchanged_runtime_root) if unchanged_runtime_root is not None else project_root
    paths = set(changed_paths)
    if SOURCE not in paths or not paths <= SCOPE:
        raise ValueError('The Embraer release must contain the assigned source and only assigned files.')

    files = {}
    for name in sorted(paths):
        path = project_root / name
        measured = metadata(path)
        contents = path.read_bytes()
        if sha256(contents).hexdigest() != measured['sha256']:
            raise ValueError('An Embraer release file changed during measurement.')
        compile(contents, name, 'exec', dont_inherit=True)
        files[name] = measured
    return {
        'schema': 'embraer-installed-repair-verification-v1',
        'result': 'PASS',
        'files': files,
        'source_manifest_sha256': source_tree_digest(project_root),
        'config_sha256': config_tree_digest(runtime_root),
        'dependency_manifest_sha256': dependency_manifest_digest(runtime_root),
    }


def verify_installed_embraer_repair(project_root, manifest):
    """Match installed bytes and full runtime to the exact qualified candidate."""
    manifest = canonical_manifest(manifest)
    if manifest['company_id'] != 'COMP-0634':
        raise ValueError('The installed verification is scoped to Embraer.')

    evidence = measure_embraer_runtime(project_root, manifest['files'])
    if (any(evidence['files'][name] != file['after'] for name, file in manifest['files'].items())
            or any(evidence[key] != manifest[key] for key in (
                'source_manifest_sha256', 'config_sha256', 'dependency_manifest_sha256',
            ))
            or digest(evidence) != manifest['validation_receipt_sha256']):
        raise ValueError('The installed Embraer repair differs from the independently qualified runtime.')
    return evidence
