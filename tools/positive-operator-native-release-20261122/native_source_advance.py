"""Advance only the reviewed application sources under native exclusion.

The native maintenance owner calls these functions inside its measured host
hold. They take the ordinary application locks and never start a worker.
"""

from contextlib import contextmanager
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import os

from job_search_helper import integration_release as release
from job_search_helper.cli import writer_lock
from release_admission_bootstrap import _validate_runtime


REVIEWED_PATHS = frozenset({
    'job-search-scraper',
    'release_admission_bootstrap.py',
    'src/job_search_helper/exact_cycle_planner.py',
    'src/job_search_helper/exact_cycle_receipt.py',
    'src/job_search_helper/exact_cycle_recovery.py',
    'src/job_search_helper/exact_cycle_sync.py',
    'src/job_search_helper/inbox.py',
    'src/job_search_helper/ordinary_company_event_command.py',
    'src/job_search_helper/positive_operator.py',
    'src/job_search_helper/runner.py',
})
SOURCE = 'source_manifest_sha256'
CONFIG = 'config_sha256'
DEPENDENCIES = 'dependency_manifest_sha256'
RUNTIME_FIELDS = (SOURCE, CONFIG, DEPENDENCIES)


def _read_spec(package, spec_sha256):
    raw = (package / 'PREPARED_PACKAGE.json').read_bytes()
    if sha256(raw).hexdigest() != spec_sha256:
        raise ValueError('The exact approved maintenance package changed.')
    spec = json.loads(raw)
    if (spec['schema'] != 'positive-operator-source-prepared-v1'
            or spec['approval'] != 'PREPARATION_ONLY' or set(spec['package_files']) != REVIEWED_PATHS):
        raise ValueError('The maintenance package must contain the reviewed positive-operator source paths.')
    return spec


def _binding(project, spec, spec_sha256):
    predecessor = spec['live_runtime']
    manifest = {
        'schema': 'native-source-maintenance-manifest-v1',
        'project': str(project),
        'purpose': 'positive-operator-company-only-entry',
        'package_sha256': spec_sha256,
        'predecessor_release_id': predecessor['release_id'],
        'predecessor_journal_sha256': spec['live_journal_sha256'],
        'before_source_manifest_sha256': predecessor[SOURCE],
        SOURCE: spec['staged_source_sha256'], CONFIG: predecessor[CONFIG],
        DEPENDENCIES: predecessor[DEPENDENCIES],
        'files': spec['package_files'],
    }
    manifest_sha256 = release.digest(manifest)
    binding = {'schema': 'integration-release-binding-v1', 'release_id': 'REL-' + manifest_sha256[:24],
               SOURCE: spec['staged_source_sha256'], CONFIG: predecessor[CONFIG],
               DEPENDENCIES: predecessor[DEPENDENCIES]}
    return manifest, manifest_sha256, binding


@contextmanager
def _application_locks(root):
    with writer_lock(root / 'scraper.lock'), writer_lock(root / 'writer.lock'):
        yield


def _current_endpoint(target, owner):
    if not target.exists() and not target.is_symlink():
        return None
    info = target.stat(follow_symlinks=False)
    if [info.st_uid, info.st_gid] != owner:
        raise ValueError('The application file owner changed: ' + target.name)
    return release.metadata(target)


def _check_vectors(project, spec, spec_side):
    fields = spec['live_runtime']
    source_digest = fields[SOURCE] if spec_side == 'before' else spec['staged_source_sha256']
    if (release.source_tree_digest(project) != source_digest
            or release.config_tree_digest(project) != fields[CONFIG]
            or release.dependency_manifest_digest(project) != fields[DEPENDENCIES]):
        raise ValueError('Application source, configuration or installed dependencies changed.')
    for name, pair in spec['package_files'].items():
        if _current_endpoint(project / name, pair['owner']) != pair[spec_side]:
            raise ValueError('Application source endpoint differs: ' + name)


def _seal_record(root, record, package, manifest, spec, journal):
    root.mkdir(mode=0o700, exist_ok=True)
    if root.is_symlink() or not root.is_dir() or root.stat().st_mode & 0o077:
        raise ValueError('Native runtime records require a private physical directory.')
    if record.exists() or record.is_symlink():
        if (record.is_symlink() or not record.is_dir()
                or {path.name for path in record.iterdir()} != {'before', 'staged', 'manifest.json', 'prior-journal.json'}
                or release._read_json(record / 'manifest.json') != manifest
                or release.metadata(record / 'prior-journal.json') != release.metadata(journal)):
            raise ValueError('The prepared maintenance record does not match the unchanged predecessor.')
        for name, pair in spec['package_files'].items():
            for side in ('before', 'staged'):
                path = record / side / name
                if path.resolve() != path:
                    raise ValueError('A prepared maintenance image is not a physical path.')
                actual = release.metadata(path) if path.exists() or path.is_symlink() else None
                if actual != pair[side]:
                    raise ValueError('A prepared maintenance image changed: ' + name)
        release._fsync_directory(root)
        return
    with TemporaryDirectory(prefix='.prepare-native-', dir=root) as temporary:
        prepared = Path(temporary) / 'record'
        prepared.mkdir(mode=0o700)
        for name, pair in spec['package_files'].items():
            for side in ('before', 'staged'):
                if pair[side] is not None:
                    target = prepared / side / name
                    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                    release._atomic_copy(package / side / name, target, pair[side])
        release._atomic_copy(journal, prepared / 'prior-journal.json', release.metadata(journal))
        release._write_json(prepared / 'manifest.json', manifest)
        for directory, _, _ in os.walk(prepared, topdown=False):
            release._fsync_directory(directory)
        prepared.rename(record)
        release._fsync_directory(root)


def _apply_sources(project, record, spec, side):
    for name, pair in spec['package_files'].items():
        target = project / name
        if pair[side] is None:
            if target.exists():
                target.unlink()
                release._fsync_directory(target.parent)
        else:
            release._atomic_copy(record / side / name, target, pair[side])


def _complete(project, journal, record, marker, binding, spec):
    _check_vectors(project, spec, 'staged')
    receipt = {'schema': 'native-source-maintenance-receipt-v1', 'state': 'COMPLETE',
               'release_id': binding['release_id'], 'manifest_sha256': marker['manifest_sha256'], 'release': binding}
    release._write_json(record / 'receipt.json', receipt)
    release._write_json(journal, {**marker, 'state': 'COMPLETE', 'receipt_sha256': release.digest(receipt)})
    if _validate_runtime(project, journal.parent) != {'state': 'COMPLETE', **{k: binding[k] for k in ('release_id', *RUNTIME_FIELDS)}}:
        raise RuntimeError('The new runtime does not satisfy pre-import admission.')
    return receipt


def advance(project, package, spec_sha256, *, check_idle):
    project, package = project.resolve(strict=True), package.resolve(strict=True)
    root = project / '.state'
    journal = root / 'integration-release-journal.json'
    spec = _read_spec(package, spec_sha256)
    manifest, manifest_sha256, binding = _binding(project, spec, spec_sha256)
    record_root = root / 'native-runtime-releases'
    record = record_root / binding['release_id']
    marker = {'schema': 'integration-release-journal-v1', 'state': 'PREPARED',
              'kind': 'native-source-maintenance', 'release_id': binding['release_id'],
              'manifest_sha256': manifest_sha256, 'release': binding, 'record': str(record)}
    with _application_locks(root):
        if (_validate_runtime(project, root) != spec['live_runtime']
                or sha256(journal.read_bytes()).hexdigest() != spec['live_journal_sha256']
                or (root / 'next-scan.json').exists() or (root / 'next-scan.json').is_symlink()):
            raise ValueError('The previous runtime or empty scan queue no longer matches approval.')
        _check_vectors(project, spec, 'before')
        check_idle(project)
        _seal_record(record_root, record, package, manifest, spec, journal)
        release._write_json(journal, marker)
        _apply_sources(project, record, spec, 'staged')
        return _complete(project, journal, record, marker, binding, spec)


def rollback_prepared(project, package, spec_sha256):
    project, package = project.resolve(strict=True), package.resolve(strict=True)
    root = project / '.state'
    journal = root / 'integration-release-journal.json'
    spec = _read_spec(package, spec_sha256)
    manifest, manifest_sha256, binding = _binding(project, spec, spec_sha256)
    record = root / 'native-runtime-releases' / binding['release_id']
    with _application_locks(root):
        marker = release._read_json(journal)
        if (marker.get('state') != 'PREPARED' or marker.get('kind') != 'native-source-maintenance'
                or marker.get('manifest_sha256') != manifest_sha256 or marker.get('release') != binding
                or marker.get('record') != str(record) or release._read_json(record / 'manifest.json') != manifest):
            raise ValueError('There is no matching interrupted native maintenance to roll back.')
        prior = record / 'prior-journal.json'
        prior_metadata = release.metadata(prior)
        if prior_metadata['sha256'] != spec['live_journal_sha256']:
            raise ValueError('The predecessor active journal backup changed.')
        for name, pair in spec['package_files'].items():
            actual = _current_endpoint(project / name, pair['owner'])
            if actual not in (pair['before'], pair['staged']):
                raise ValueError('An application endpoint changed outside this maintenance.')
            if pair['before'] is not None and release.metadata(record / 'before' / name) != pair['before']:
                raise ValueError('A predecessor source backup changed.')
        _apply_sources(project, record, spec, 'before')
        _check_vectors(project, spec, 'before')
        release._write_json(record / 'native-rollback.json', {'state': 'ROLLED_BACK',
                            'release_id': binding['release_id'], 'manifest_sha256': manifest_sha256})
        release._atomic_copy(prior, journal, prior_metadata)
        if _validate_runtime(project, root) != spec['live_runtime']:
            raise RuntimeError('The restored predecessor runtime is no longer admissible.')
        return {'state': 'ROLLED_BACK', 'restored_release_id': spec['live_runtime']['release_id']}
