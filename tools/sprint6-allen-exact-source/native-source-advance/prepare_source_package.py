"""Prepare the reviewed four-file Allen package without changing MuleLab."""

from hashlib import sha256
import json
from pathlib import Path
from shutil import copy2, copytree, ignore_patterns
import stat
import sys
from tempfile import TemporaryDirectory


LIVE = Path('/home/chris/job-search-helper_old')
STAGED = Path('/tmp/jsh-s6-allen-publish.Ha9WnPpI')
PACKAGE = Path(__file__).resolve().parent
SCOPE_SHA = '5fea258531852c33341bae79b2e95683bcfe9100ec49b90780094e713e9e1be1'
EXPECTED_PATHS = frozenset({
    'src/job_search_helper/allen_source_reconciliation.py',
    'src/job_search_helper/exact_cycle_sync.py',
    'src/job_search_helper/sheets_sync.py',
    'src/job_search_helper/sqlite_repository.py',
})

sys.path[:0] = [str(LIVE), str(LIVE / 'src')]
from release_admission_bootstrap import _load_environment, _validate_runtime
from job_search_helper.integration_release import metadata, source_tree_digest


def prepare_sources(scope):
    result = {}
    for name, digests in sorted(scope['files'].items()):
        pair = {}
        for side, tree in (('before', LIVE), ('staged', STAGED)):
            source = tree / name
            if digests[side] is None:
                if source.exists() or source.is_symlink():
                    raise ValueError('A source expected to be absent now exists.')
                pair[side] = None
                continue
            value = metadata(source)
            if value['sha256'] != digests[side]:
                raise ValueError('A reviewed source file changed: ' + name)
            target = PACKAGE / side / name
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() or target.is_symlink():
                raise ValueError('The package must have a fresh source destination.')
            copy2(source, target)
            if metadata(target) != value:
                raise ValueError('The private source copy differs: ' + name)
            pair[side] = value
        actual = LIVE / name
        owner = (actual if pair['before'] else actual.parent).stat()
        result[name] = {**pair, 'owner': [owner.st_uid, owner.st_gid]}
    return result


def rehearse_bytes(scope, facts):
    with TemporaryDirectory(prefix='jsh-s6-source-rehearsal-') as temporary:
        scratch = Path(temporary)
        copytree(LIVE / 'src', scratch / 'src', ignore=ignore_patterns('__pycache__', '*.pyc'))
        bootstrap = 'release_admission_bootstrap.py'
        copy2(LIVE / bootstrap, scratch / bootstrap)
        for side, expected in (('staged', 'staged_source_sha256'), ('before', 'live_source_sha256')):
            for name, pair in facts.items():
                target = scratch / name
                if pair[side] is None:
                    target.unlink()
                else:
                    copy2(PACKAGE / side / name, target)
                    if metadata(target) != pair[side]:
                        raise ValueError('Private rehearsal file differs: ' + name)
            if source_tree_digest(scratch) != scope[expected]:
                raise ValueError('The private rehearsal source tree differs: ' + side)


def main():
    raw = (STAGED / 'SOURCE_SCOPE.json').read_bytes()
    if sha256(raw).hexdigest() != SCOPE_SHA:
        raise ValueError('The independent source-only review has a different scope.')
    scope = json.loads(raw)
    if set(scope['files']) != EXPECTED_PATHS:
        raise ValueError('The package is restricted to the four reviewed Allen files.')
    if stat.S_IMODE(PACKAGE.stat().st_mode) != 0o700:
        raise ValueError('Use a private package directory.')
    _load_environment(LIVE / '.env')
    state = LIVE / '.state'
    runtime = _validate_runtime(LIVE, state)
    if (runtime['state'] != 'COMPLETE' or runtime['release_id'] != 'REL-bc64482443373843f2f93cb5'
            or runtime['source_manifest_sha256'] != scope['live_source_sha256']
            or source_tree_digest(STAGED) != scope['staged_source_sha256']):
        raise ValueError('The installed or reviewed source version changed.')
    journal = (state / 'integration-release-journal.json').read_bytes()
    if sha256(journal).hexdigest() != 'de1c2a8445b810574c626eef4f9fb0d60e3561bc7208584028193da95e30738c':
        raise ValueError('The independently verified GA predecessor journal changed.')
    prior = json.loads(journal)
    if any(prior['release'][field] != runtime[field] for field in (
            'source_manifest_sha256', 'config_sha256', 'dependency_manifest_sha256')):
        raise ValueError('The installed predecessor release journal differs.')
    facts = prepare_sources(scope)
    rehearse_bytes(scope, facts)
    if _validate_runtime(LIVE, state) != runtime or (state / 'integration-release-journal.json').read_bytes() != journal:
        raise ValueError('The installed runtime changed during preparation.')
    evidence = {
        'kind': 'independently-reviewed-source-before-and-after-preparation',
        'approval': 'PREPARATION_ONLY',
        'live_runtime': runtime,
        'live_journal_sha256': sha256(journal).hexdigest(),
        'scope_sha256': SCOPE_SHA,
        'staged_source_sha256': scope['staged_source_sha256'],
        'package_files': facts,
        'disposable_source_install_rollback_rehearsal': 'PASS',
    }
    with (PACKAGE / 'PREPARED_PACKAGE.json').open('x', encoding='utf-8') as output:
        json.dump(evidence, output, indent=2, sort_keys=True)
        output.write('\n')
    print('Packaged four measured source transitions and passed private byte restoration.')


if __name__ == '__main__':
    main()
