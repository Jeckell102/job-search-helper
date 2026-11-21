"""Assemble the one actual Amphenol build for qualification, without a release."""

from hashlib import sha256
import json
from pathlib import Path
from shutil import copy2
import sys


STAGE = Path(__file__).resolve().parent
PROJECT = Path('/home/chris/job-search-helper_old')
TARGET = 'src/job_search_helper/acquiretm.py'
REQUEST = 'operator-amphenol-20261121-05'
REQUEST_SHA = 'f8c53183ae54bb8b66f79f92edc68d1e0a9d136ed8d2e21a07d7ff497fde7feb'
OUTCOME = 'OUT-1dc536eeadea2d283052b05d'
TASK = 'WRAP-11dc97a3dd'
INFERENCE = 'd73599ddd718448bb9fa1297af268a08'
REVISION = 'b7a94094c57cb879e25db5aef9de565437f8ec5a855ad7b1275958e944f6a501'
BASELINE = 'a95953afe2bc10138714f6b11af22572b17ab344bf61d78b834647895025aa61'
BUILD_PINS = {
    TARGET: '895ec36e443eea5a1c49c622d99b505d5ed49d5ff6c22d37e71eb5a610bb3c9d',
    'reviewed.patch': 'ce042dffa0addfdbb04e14e450d6e5ae3979d2c881bd1ff9bf9c8173ce749abc',
    'build-receipt.json': 'aa12f5a86dbd13094f1473c79b1ca14840e1821bb3bbb2194dd9fee1e01578a5',
}
TOP = ('pyproject.toml', 'title-blacklist.txt', 'title-review-list.txt')
CONFIG = ('.env', '.storage-backend')
COPY_MARKERS = tuple(f'src/{name}/__init__.py' for name in (
    '.f3-maintenance-package', '.s3-archive-maintenance-package', '.s3-maintenance-package', '.s4-maintenance-package',
))
PREVIOUS_COMPLETE_VECTOR = '7e371be5094a3d23de58af47e8e8607c7f64d6d35a4a7e58bfb365baa132bdea'


def read_digest(path):
    if not path.is_file() or path.resolve(strict=True) != path or path.stat().st_nlink != 1:
        raise ValueError(f'Expected physical single-link input {path.name}')
    return sha256(path.read_bytes()).hexdigest()


def write_new(name, value):
    with (STAGE / name).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write('\n')


def main():
    if not sys.flags.isolated or not sys.flags.dont_write_bytecode:
        raise ValueError('Use the production interpreter with -I -B')
    sys.path[:0] = [str(PROJECT / 'src'), str(PROJECT / 'dev/wrapper-coder/tools')]
    from amphenol_installed_verification import measure_amphenol_recipe_runtime
    from job_search_helper.cli import load_environment
    from job_search_helper.integration_release import (
        MANIFEST_SCHEMA, _tree_metadata, _verify_inputs, _verify_projected_release,
        canonical_manifest, config_tree_digest, digest, manifest_release_id,
        metadata, source_tree_digest,
    )

    build = PROJECT / 'dev/wrapper-coder/tasks' / TASK / 'recipe-candidate'
    if {name: read_digest(build / name) for name in BUILD_PINS} != BUILD_PINS:
        raise ValueError('The independently accepted automatic build artifacts changed')
    receipt = json.loads((build / 'build-receipt.json').read_bytes())
    expected_build = {'company_id': 'COMP-0490', 'outcome_id': OUTCOME, 'request_id': INFERENCE,
                      'source_revision': REVISION, 'source_sha256': BASELINE, 'target_path': TARGET,
                      'output_sha256': BUILD_PINS[TARGET], 'installed': False, 'live_validated': False}
    if any(receipt.get(key) != value for key, value in expected_build.items()):
        raise ValueError('The automatic build receipt differs from the current owner')

    load_environment(PROJECT / '.env')
    before = measure_amphenol_recipe_runtime(PROJECT)
    if before['wrapper']['sha256'] != BASELINE:
        raise ValueError('The canonical installed adapter changed')

    candidate = STAGE / 'candidate'
    candidate.mkdir(mode=0o700)
    source_root = PROJECT / 'src/job_search_helper'
    source_paths = [f'src/job_search_helper/{name}' for name in _tree_metadata(source_root, suffix=('.py', '.json'))]
    config_relative = '.state/integration-configs'
    copied = source_paths + list(COPY_MARKERS) + [name for name in (*TOP, *CONFIG) if (PROJECT / name).exists()]
    if (PROJECT / config_relative).exists():
        copied += [f'{config_relative}/{name}' for name in _tree_metadata(PROJECT / config_relative)]
    for name in copied:
        original = (build if name == TARGET else PROJECT) / name
        destination = candidate / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        copy2(original, destination)
        if name == TARGET:
            destination.chmod(before['wrapper']['mode'])
        elif metadata(destination) != metadata(original):
            raise ValueError(f'Candidate copy drift on {name}')

    replacement = metadata(candidate / TARGET)
    if replacement['sha256'] != BUILD_PINS[TARGET]:
        raise ValueError('The candidate differs from the automatic build output')
    compile((candidate / TARGET).read_bytes(), TARGET, 'exec', dont_inherit=True)
    projected = {**before, 'wrapper': replacement, 'source_manifest_sha256': source_tree_digest(candidate),
                 'config_sha256': config_tree_digest(candidate)}
    if projected['config_sha256'] != before['config_sha256']:
        raise ValueError('A wrapper-only candidate must preserve effective configuration')
    manifest = {
        'schema': MANIFEST_SCHEMA, 'failed_request_id': REQUEST, 'company_id': 'COMP-0490',
        'source_revision': REVISION, 'files': {TARGET: {'before': before['wrapper'], 'after': replacement}},
        'before_source_manifest_sha256': before['source_manifest_sha256'],
        'before_config_sha256': before['config_sha256'],
        **{key: projected[key] for key in ('source_manifest_sha256', 'config_sha256', 'dependency_manifest_sha256')},
        'validation_receipt_sha256': digest(projected),
    }
    manifest['release_id'] = manifest_release_id(manifest)
    manifest = canonical_manifest(manifest)
    _verify_inputs(PROJECT, candidate, manifest)
    _verify_projected_release(PROJECT, manifest)

    vector_paths = list((candidate / 'src').rglob('*.py')) + [candidate / name for name in TOP]
    source_vector = {path.relative_to(candidate).as_posix(): read_digest(path) for path in sorted(vector_paths)}
    if len(source_vector) != 256 or digest(source_vector) != PREVIOUS_COMPLETE_VECTOR:
        raise ValueError('Candidate source differs from the previous complete public observation')
    details = {
        'state': 'HELD_PROPOSED_MANIFEST', 'qualification': 'pending', 'candidate_root': str(candidate),
        'failed_request_id': REQUEST, 'request_sha256': REQUEST_SHA, 'outcome_id': OUTCOME,
        'task_id': TASK, 'inference_request_id': INFERENCE, 'build_artifacts': BUILD_PINS,
        'candidate_vector_count': len(source_vector), 'candidate_vector_sha256': digest(source_vector),
        'dispatcher_sha256': source_vector['src/job_search_helper/ats.py'],
        'manifest_sha256': digest(manifest), 'release_id': manifest['release_id'],
    }
    write_new('PROPOSED_MANIFEST.json', manifest)
    write_new('EXPECTED_INSTALL_READBACK.json', projected)
    write_new('PREPARED.json', details)
    print(json.dumps(details, sort_keys=True))


if __name__ == '__main__':
    main()
