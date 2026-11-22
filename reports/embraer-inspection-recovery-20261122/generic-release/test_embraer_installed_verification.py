import pytest

from embraer_installed_verification import SOURCE, measure_embraer_runtime, verify_installed_embraer_repair
from job_search_helper.integration_release import (
    MANIFEST_SCHEMA, digest, manifest_release_id, metadata, source_tree_digest,
)


def test_verifier_binds_the_qualified_application_bytes(tmp_path):
    (tmp_path / 'pyproject.toml').write_text('[project]\nname = "fixture"\n')
    target = tmp_path / SOURCE
    target.parent.mkdir(parents=True)
    target.write_text('before = True\n')
    previous, before_source = metadata(target), source_tree_digest(tmp_path)

    target.write_text('after = True\n')
    witness = measure_embraer_runtime(tmp_path, [SOURCE])
    manifest = {
        'schema': MANIFEST_SCHEMA,
        'failed_request_id': 'operator-embraer-fixture',
        'company_id': 'COMP-0634',
        'source_revision': 'fixture-revision',
        'files': {SOURCE: {'before': previous, 'after': metadata(target)}},
        'before_source_manifest_sha256': before_source,
        'source_manifest_sha256': witness['source_manifest_sha256'],
        'dependency_manifest_sha256': witness['dependency_manifest_sha256'],
        'before_config_sha256': witness['config_sha256'],
        'config_sha256': witness['config_sha256'],
        'validation_receipt_sha256': digest(witness),
    }
    manifest['release_id'] = manifest_release_id(manifest)
    assert verify_installed_embraer_repair(tmp_path, manifest) == witness

    candidate = tmp_path / 'private-candidate'
    candidate_target = candidate / SOURCE
    candidate_target.parent.mkdir(parents=True)
    candidate_target.write_bytes(target.read_bytes())
    candidate_target.chmod(target.stat().st_mode & 0o777)
    assert measure_embraer_runtime(candidate, [SOURCE], unchanged_runtime_root=tmp_path) == witness

    target.write_text('unapproved = True\n')
    with pytest.raises(ValueError, match='independently qualified runtime'):
        verify_installed_embraer_repair(tmp_path, manifest)


def test_freeze_copies_exact_scoped_change_and_keeps_config(tmp_path):
    from freeze_embraer_candidate import freeze_embraer_candidate
    from job_search_helper.integration_release import config_tree_digest

    from coordinator_evidence import manifest_digest

    project, candidate = tmp_path/'project', tmp_path/'candidate'
    task_id = 'WRAP-d012345678'
    workspace = project/'dev/wrapper-coder/tasks'/task_id/'repo'
    for root, text in ((project, 'before = True\n'), (workspace, 'after = True\n')):
        target = root / SOURCE
        target.parent.mkdir(parents=True)
        target.write_text(text)
    (project / 'pyproject.toml').write_text('[project]\nname = "fixture"\n')
    (project / '.env').write_text('# private fixture configuration\n')
    generated = {SOURCE: metadata(workspace / SOURCE)['sha256']}
    binding = {
        'schema': 'embraer-generic-terminal-candidate-v1',
        'task_id': task_id,
        'request_id': 'operator-embraer-fixture',
        'company_id': 'COMP-0634',
        'source_revision': 'fixture-revision',
        'changed_paths': [SOURCE],
        'source_manifest_sha256': manifest_digest(generated),
    }
    diff = {
        'paths': [SOURCE],
        'source_manifest': generated,
        'before': {SOURCE: metadata(project / SOURCE)['sha256']},
        'after': {SOURCE: metadata(workspace / SOURCE)['sha256']},
    }
    manifest, witness = freeze_embraer_candidate(project, workspace, candidate, binding, diff)
    assert config_tree_digest(candidate) == config_tree_digest(project) == manifest['config_sha256']
    assert digest(witness) == manifest['validation_receipt_sha256']
    assert (candidate / SOURCE).read_bytes() == (workspace / SOURCE).read_bytes()
