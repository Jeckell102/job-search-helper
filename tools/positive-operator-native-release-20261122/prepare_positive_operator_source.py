"""Seal the reviewed positive operator application and launcher endpoints."""

from hashlib import sha256
import json
from pathlib import Path
import stat
import sys

PROJECT = Path('/home/chris/job-search-helper_old')
CANDIDATE = Path('/tmp/jsh-positive-operator-candidate')
PACKAGE = Path(__file__).resolve().parent
PACKAGE_SCHEMA = 'positive-operator-source-prepared-v1'
PREDECESSOR = 'REL-e91024875ba7d854b83c33f8'
PREDECESSOR_JOURNAL = '5bb34eaad32652d52605f9282e86601fbdc793bd8f2af5231b97e2ea2d757eaa'
REVIEWED_ENDPOINTS = {'job-search-scraper': '6566abcc1d4c06ab2bd3f98a8c911250ad0c3d4c518889a86a256889bc741f8a', 'release_admission_bootstrap.py': 'fb18d988bfbaaca369a3d8d36a9d187bd8c5eafa1bfe04870ff8f1cad33ab084', 'src/job_search_helper/exact_cycle_planner.py': '801bd65e85b1d5c69147eddf79eb541dbd8d75351801459167ca617dd9040b7c', 'src/job_search_helper/exact_cycle_receipt.py': '3fe395b14930f6f5c906933a68d0982d21647e53ccaf7903486662e68c6759b1', 'src/job_search_helper/exact_cycle_recovery.py': '7a81b02066ee7044467c847ef383a8c1855b6835bd3b99bfefc18f7723d3358c', 'src/job_search_helper/exact_cycle_sync.py': 'b8c8e41745c4fc3267974494ead071f377c19a481343c2e3406abb478c02f4b5', 'src/job_search_helper/inbox.py': '1745f9d3a6f46e4be1a95a306ff14eb1aca4913daec54e83f022c150f723d014', 'src/job_search_helper/ordinary_company_event_command.py': '93f36d0d6139e14834b1fb0aeb56300a5417fcff8dce16d3b22f68a8a0654d82', 'src/job_search_helper/positive_operator.py': 'a8ff192466015a55ba8c01d5081b552aad381f5cf901197254c96c1dbd28f348', 'src/job_search_helper/runner.py': '21283c61212a2cbcdd2dd3d3ac097eb226212d66d34377ec1f001d6f8e0a373f'}



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
    source_root = Path('src/job_search_helper')
    production_files = release._tree_metadata(PROJECT / source_root, suffix=('.py', '.json'))
    candidate_files = release._tree_metadata(CANDIDATE / source_root, suffix=('.py', '.json'))
    changed = {
        path for path in production_files.keys() | candidate_files.keys()
        if production_files.get(path) != candidate_files.get(path)
    }
    reviewed_source = {
        name.removeprefix('src/job_search_helper/') for name in REVIEWED_ENDPOINTS
        if name.startswith('src/job_search_helper/')
    }
    if changed != reviewed_source:
        raise ValueError('Application changes differ from the reviewed exact scope.')

    endpoints = {}
    for name, expected in sorted(REVIEWED_ENDPOINTS.items()):
        relative_path = Path(name)
        installed = PROJECT / relative_path
        owner = (installed if installed.exists() else installed.parent).stat(follow_symlinks=False)
        pair = endpoints[name] = {'owner': [owner.st_uid, owner.st_gid]}
        for side, tree in (('before', PROJECT), ('staged', CANDIDATE)):
            original = tree / relative_path
            actual = release.metadata(original) if original.exists() or original.is_symlink() else None
            pair[side] = actual
            if side == 'staged' and (actual is None or actual['sha256'] != expected):
                raise ValueError('A reviewed candidate endpoint changed: ' + name)
            if actual is None:
                continue
            target = PACKAGE / side / relative_path
            if target.exists() or target.is_symlink():
                raise ValueError('Use a fresh destination for the measured endpoint copy.')
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            release._atomic_copy(original, target, actual)
        if pair['staged'] == pair['before']:
            raise ValueError('The approved endpoint must be a real change: ' + name)

    if (_validate_runtime(PROJECT, state) != runtime
            or sha256(journal.read_bytes()).hexdigest() != PREDECESSOR_JOURNAL):
        raise ValueError('The active predecessor changed during preparation.')
    spec = {
        'schema': PACKAGE_SCHEMA,
        'approval': 'PREPARATION_ONLY',
        'live_runtime': runtime,
        'live_journal_sha256': PREDECESSOR_JOURNAL,
        'staged_source_sha256': release.digest(candidate_files),
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
