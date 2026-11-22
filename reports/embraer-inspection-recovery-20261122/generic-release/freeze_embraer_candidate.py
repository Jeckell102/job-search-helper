"""Freeze the measured Embraer worktree changes for independent qualification."""

from pathlib import Path
from shutil import copy2

from embraer_installed_verification import SCOPE, SOURCE, measure_embraer_runtime
from job_search_helper.integration_release import (
    MANIFEST_SCHEMA, _tree_metadata, _verify_inputs, _verify_projected_release,
    canonical_manifest, config_tree_digest, digest, manifest_release_id, metadata,
)


def freeze_embraer_candidate(project, workspace, candidate, binding, final_diff):
    """Copy only candidate source/config and the verified changed test files."""
    project, workspace, candidate = map(Path, (project, workspace, candidate))
    paths = set(binding['changed_paths'])
    if (binding['schema'] != 'embraer-generic-terminal-candidate-v1'
            or binding['task_id'] != 'WRAP-fbb9ff24d3'
            or binding['company_id'] != 'COMP-0634'
            or SOURCE not in paths or not paths <= SCOPE
            or paths != set(final_diff['paths'])
            or workspace.resolve(strict=True) != workspace
            or candidate.parent.resolve(strict=True) != candidate.parent):
        raise ValueError('Candidate preparation requires the exact measured Embraer scope.')

    before = measure_embraer_runtime(project, paths)
    if any(before['files'][path]['sha256'] != final_diff['before'][path]
           or metadata(workspace / path)['sha256'] != final_diff['after'][path]
           for path in paths):
        raise ValueError('The installed or worker source differed from the reviewed diff.')
    candidate.mkdir(mode=0o700)

    package = 'src/job_search_helper'
    configs = '.state/integration-configs'
    names = {f'{package}/{name}' for name in _tree_metadata(project / package, suffix=('.py', '.json'))}
    names.update(name for name in ('.env', '.storage-backend', 'title-blacklist.txt', 'title-review-list.txt')
                 if (project / name).exists())
    if (project / configs).exists():
        names.update(f'{configs}/{name}' for name in _tree_metadata(project / configs))

    for name in sorted(names | paths):
        original = (workspace if name in paths else project) / name
        target = candidate / name
        target.parent.mkdir(parents=True, exist_ok=True)
        expected = metadata(original)
        copy2(original, target)
        if metadata(target) != expected:
            raise ValueError('The candidate copy did not preserve the measured file: ' + name)
        if name in paths:
            target.chmod(before['files'][name]['mode'])

    expected = measure_embraer_runtime(candidate, paths, unchanged_runtime_root=project)
    if config_tree_digest(candidate) != before['config_sha256']:
        raise ValueError('The private candidate did not preserve installed configuration.')
    if any(expected['files'][path]['sha256'] != final_diff['after'][path] for path in paths):
        raise ValueError('The candidate differs from the worker-produced files.')
    proposed = {
        'schema': MANIFEST_SCHEMA,
        'failed_request_id': binding['request_id'],
        'company_id': binding['company_id'],
        'source_revision': binding['source_revision'],
        'files': {path: {'before': before['files'][path], 'after': expected['files'][path]} for path in sorted(paths)},
        'before_source_manifest_sha256': before['source_manifest_sha256'],
        'before_config_sha256': before['config_sha256'],
        'validation_receipt_sha256': digest(expected),
        **{key: expected[key] for key in ('source_manifest_sha256', 'config_sha256', 'dependency_manifest_sha256')},
    }
    proposed['release_id'] = manifest_release_id(proposed)
    manifest = canonical_manifest(proposed)
    _verify_inputs(project, candidate, manifest)
    _verify_projected_release(project, manifest)
    return manifest, expected
