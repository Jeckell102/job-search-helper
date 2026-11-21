"""Record explicit Sprint 5 runtime file endpoints for source-only review."""

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import stat


APPLICATION = (
    'acquiretm', 'ats', 'company_sources', 'exact_cycle_planner', 'exact_cycle_receipt',
    'exact_cycle_recovery', 'exact_cycle_sync', 'inbox', 'integration_release',
    'ordinary_company_event_command', 'ordinary_company_event_publication',
    'ordinary_event_settlement', 'private_file_custody', 'qualified_release_owner',
    'release_controller', 'release_qualification', 'repair_retry', 'runner',
    'scan_request', 'scrape_outcome_producer', 'sqlite_repository',
)
HOST = (
    'acquiretm_membership_recipe', 'amphenol_recipe_candidate', 'amphenol_recipe_choice_input',
    'amphenol_retry_completion', 'coordinator', 'coordinator_inference', 'coordinator_store',
    'coordinator_supervision', 'host_server',
)
SCOPED_PATHS = (
    *(f'src/job_search_helper/{name}.py' for name in APPLICATION),
    *(f'dev/wrapper-coder/tools/{name}.py' for name in HOST),
    'job-search-scraper',
)


def endpoint(root, relative, *, allow_missing=False):
    path = root / relative
    for parent in path.parents:
        if parent == root:
            break
        if parent.is_symlink() or not parent.is_dir():
            raise ValueError(f'Unsafe file directory for {relative}')
    try:
        before = path.lstat()
    except FileNotFoundError:
        if allow_missing:
            return None
        raise
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise ValueError(f'Expected ordinary single-link file for {relative}')
    contents = path.read_bytes()
    after = path.lstat()
    metadata = ('st_dev', 'st_ino', 'st_mode', 'st_size', 'st_mtime_ns', 'st_ctime_ns', 'st_uid', 'st_gid')
    if any(getattr(before, key) != getattr(after, key) for key in metadata):
        raise ValueError(f'File changed during readback for {relative}')
    return {'sha256': hashlib.sha256(contents).hexdigest(), 'bytes': len(contents),
            'mode': f'{stat.S_IMODE(after.st_mode):04o}', 'owner': [after.st_uid, after.st_gid]}


def historical_match(before, known):
    if known is None:
        return 'unlisted_in_freeform_capsule'
    target = known['after']
    if target is None:
        return 'unchanged_absence' if before is None else 'different_from_freeform_capsule'
    if (before and all(before[key] == target[key] for key in ('sha256', 'mode'))
            and before['owner'] == known['owner']):
        return 'matches_freeform_capsule'
    return 'different_from_freeform_capsule'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('native', type=Path)
    parser.add_argument('candidate', type=Path)
    parser.add_argument('prior_manifest', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    native = args.native.resolve(strict=True)
    candidate = args.candidate.resolve(strict=True)
    if candidate.is_relative_to(native) or args.output.resolve().is_relative_to(native):
        raise ValueError('Review output and candidate must be outside the native checkout')
    historic_bytes = args.prior_manifest.read_bytes()
    historic = json.loads(historic_bytes)['paths']
    paths = {}
    for name in SCOPED_PATHS:
        before = endpoint(native, name, allow_missing=True)
        after = endpoint(candidate, name)
        if before is not None and before['sha256'] == after['sha256'] and before['mode'] == after['mode']:
            raise ValueError(f'Scoped runtime target no longer has a source delta: {name}')
        paths[name] = {
            'before': before, 'after': after, 'freeform_endpoint': historical_match(before, historic.get(name)),
        }
    for directory, recursive in (('src/job_search_helper', True), ('dev/wrapper-coder/tools', False)):
        observed = set()
        for root in (native, candidate):
            scope = root / directory
            matches = scope.rglob('*') if recursive else scope.iterdir()
            observed.update(path.relative_to(root).as_posix() for path in matches
                            if path.suffix in {'.py', '.json'}
                            and not path.name.startswith('test_')
                            and '__pycache__' not in path.parts
                            and path.is_file())
        changed = set()
        for name in observed:
            before = endpoint(native, name, allow_missing=True)
            after = endpoint(candidate, name, allow_missing=True)
            if after is not None and (before is None or before['sha256'] != after['sha256']
                                      or before['mode'] != after['mode']):
                changed.add(name)
        if changed != {name for name in paths if name.startswith(directory + '/')}:
            raise ValueError(f'Runtime additions/replacements differ from reviewed scope in {directory}')
    stable = 'release_admission_bootstrap.py'
    bootstrap = endpoint(native, stable)
    if endpoint(candidate, stable) != bootstrap:
        raise ValueError('The stable launcher bootstrap no longer matches')
    report = {
        'disposition': 'READ_ONLY_SOURCE_SCOPE_REVIEW_ONLY',
        'observed_at': datetime.now().astimezone().isoformat(),
        'native': str(native), 'candidate': str(candidate),
        'historical_manifest_sha256': hashlib.sha256(historic_bytes).hexdigest(),
        'runtime_path_count': len(paths),
        'replacement_count': sum(row['before'] is not None for row in paths.values()),
        'addition_count': sum(row['before'] is None for row in paths.values()),
        'paths': paths, 'unchanged_bootstrap': bootstrap,
    }
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    counts = {row['freeform_endpoint'] for row in paths.values()}
    print(f"{len(paths)} exact paths: {report['replacement_count']} replacements, {report['addition_count']} additions.")
    for label in sorted(counts):
        print(label, sum(row['freeform_endpoint'] == label for row in paths.values()))


if __name__ == '__main__':
    main()
