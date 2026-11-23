"""Seal the three independently reviewed Festo application endpoints."""

from hashlib import sha256
import json
from pathlib import Path
import stat
import sys

PROJECT = Path('/home/chris/job-search-helper_old')
CANDIDATE = Path('/tmp/jsh-s6-festo-preflight/guarded-candidate')
PACKAGE = Path(__file__).resolve().parent
PACKAGE_SCHEMA = 'festo-source-only-prepared-v1'
PREDECESSOR = 'REL-4141919bb885000b0e7244c2'
PREDECESSOR_JOURNAL = '9a0ffa49dcff4bddfe29a18398c8b2002f316ebfaa086253bc1011dc6ee557ee'
REVIEWED_SOURCE = {
    'ats.py': '14ff39e6c4626fc2abd5048a74d58dba4865b1b688fff4f8cb25b3678be61c9f',
    'company_sources.py': '8da7dc61616567e582c517dbdd9e3be14af65920de610981a99bed2e19aee82d',
    'successfactors.py': '21ad9f10b168680cdf7efaa067ef5ea21fa95241d33a5c842b5cf86b9dbe33b6',
}
QUALIFICATION = Path('/tmp/jsh-s6-festo-preflight/CANDIDATE_OBSERVATION.json')
QUALIFICATION_PIN = '0674dedc899079fb56977f5d0fcbf9db5edbdcca0eded47ae1fb32d2d4398a4f'


def main():
    if (Path(sys.prefix).resolve() != PROJECT / '.venv'
            or not sys.flags.isolated or not sys.flags.dont_write_bytecode
            or sys.pycache_prefix != '/dev/null'):
        raise ValueError('Use production Python in isolated, no-cache mode.')
    if stat.S_IMODE(PACKAGE.stat().st_mode) != 0o700:
        raise ValueError('The release stage must be private.')
    sys.path[:0] = [str(PROJECT), str(PROJECT / 'src')]
    from release_admission_bootstrap import _load_environment, _validate_runtime
    from job_search_helper import integration_release as release

    _load_environment(PROJECT / '.env')
    state = PROJECT / '.state'
    journal = state / 'integration-release-journal.json'
    runtime = _validate_runtime(PROJECT, state)
    if (runtime['state'] != 'COMPLETE' or runtime['release_id'] != PREDECESSOR
            or sha256(journal.read_bytes()).hexdigest() != PREDECESSOR_JOURNAL):
        raise ValueError('The active predecessor differs from the reviewed release.')
    if sha256(QUALIFICATION.read_bytes()).hexdigest() != QUALIFICATION_PIN:
        raise ValueError('The reviewed public qualification changed.')

    source_root = Path('src/job_search_helper')
    production_files = release._tree_metadata(PROJECT / source_root, suffix=('.py', '.json'))
    candidate_files = release._tree_metadata(CANDIDATE / source_root, suffix=('.py', '.json'))
    changed = {
        path for path in production_files.keys() | candidate_files.keys()
        if production_files.get(path) != candidate_files.get(path)
    }
    if (changed != set(REVIEWED_SOURCE)
            or any(candidate_files[name]['sha256'] != pin for name, pin in REVIEWED_SOURCE.items())):
        raise ValueError('The candidate differs from the three reviewed file changes.')

    endpoints = {}
    for name in sorted(changed):
        relative_path = source_root / name
        installed = PROJECT / relative_path
        owner = installed.stat(follow_symlinks=False)
        pair = endpoints[relative_path.as_posix()] = {'owner': [owner.st_uid, owner.st_gid]}
        for side, tree, fields in (
            ('before', PROJECT, production_files),
            ('staged', CANDIDATE, candidate_files),
        ):
            target = PACKAGE / side / relative_path
            if target.exists() or target.is_symlink():
                raise ValueError('Use a fresh destination for the measured endpoint copy.')
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            pair[side] = fields[name]
            release._atomic_copy(tree / relative_path, target, pair[side])

    if (_validate_runtime(PROJECT, state) != runtime
            or sha256(journal.read_bytes()).hexdigest() != PREDECESSOR_JOURNAL):
        raise ValueError('The active predecessor changed during preparation.')
    spec = {
        'schema': PACKAGE_SCHEMA,
        'approval': 'PREPARATION_ONLY',
        'company_id': 'COMP-0560',
        'live_runtime': runtime,
        'live_journal_sha256': PREDECESSOR_JOURNAL,
        'staged_source_sha256': release.digest(candidate_files),
        'qualification_sha256': QUALIFICATION_PIN,
        'package_files': endpoints,
    }
    destination = PACKAGE / 'PREPARED_PACKAGE.json'
    if destination.exists() or destination.is_symlink():
        raise ValueError('Use a fresh package destination.')
    release._write_json(destination, spec)
    print(json.dumps({'package_sha256': sha256(destination.read_bytes()).hexdigest(),
                      'production_files': sorted(endpoints),
                      'staged_source_sha256': spec['staged_source_sha256']}, sort_keys=True))


if __name__ == '__main__':
    main()
