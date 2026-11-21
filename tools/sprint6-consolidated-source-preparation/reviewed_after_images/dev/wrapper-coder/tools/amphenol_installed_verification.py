"""Measure the installed runtime of the already qualified AcquireTM recipe."""

from hashlib import sha256
from pathlib import Path

from acquiretm_membership_recipe import TARGET_PATH
from job_search_helper.integration_release import (
    canonical_manifest, config_tree_digest, dependency_manifest_digest, digest, metadata,
    source_tree_digest,
)


def measure_amphenol_recipe_runtime(project_root):
    """Produce the deterministic runtime readback bound by independent approval."""
    project_root = Path(project_root)
    target = project_root / TARGET_PATH
    wrapper = metadata(target)
    source = target.read_bytes()
    if sha256(source).hexdigest() != wrapper['sha256']:
        raise ValueError('AcquireTM source changed during installed verification.')
    try:
        compile(source, TARGET_PATH, 'exec', dont_inherit=True)
    except SyntaxError as exc:
        raise ValueError('The installed AcquireTM wrapper failed to compile.') from exc
    return {
        'schema': 'amphenol-installed-recipe-verification-v1',
        'result': 'PASS',
        'wrapper': wrapper,
        'source_manifest_sha256': source_tree_digest(project_root),
        'config_sha256': config_tree_digest(project_root),
        'dependency_manifest_sha256': dependency_manifest_digest(project_root),
    }


def verify_installed_amphenol_recipe(project_root, manifest):
    """Read back the exact approved files after the guarded install."""
    manifest = canonical_manifest(manifest)
    if manifest['company_id'] != 'COMP-0490' or set(manifest['files']) != {TARGET_PATH}:
        raise ValueError('Installed verification requires the one approved Amphenol wrapper.')
    evidence = measure_amphenol_recipe_runtime(project_root)
    if (evidence['wrapper'] != manifest['files'][TARGET_PATH]['after']
            or any(evidence[key] != manifest[key] for key in (
                'source_manifest_sha256', 'config_sha256', 'dependency_manifest_sha256',
            )) or digest(evidence) != manifest['validation_receipt_sha256']):
        raise ValueError('The installed Amphenol runtime differs from the independently qualified version.')
    return evidence
