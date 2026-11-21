from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import stat

CANDIDATE = Path('/tmp/jsh-s6-native-release-hold-reason.20261121')
NATIVE = Path('/home/chris/job-search-helper_old')
S5 = Path('/tmp/job-search-helper-integration-automation/temp/integration-coordinator/S5_NATIVE_SOURCE_SCOPE_20261121.json')
SCOPES = ('src/job_search_helper', 'dev/wrapper-coder/tools')
LAUNCHERS = ('job-search-scraper', 'release_admission_bootstrap.py')


def stat_key(st):
    return tuple(getattr(st, name) for name in (
        'st_dev', 'st_ino', 'st_mode', 'st_size', 'st_mtime_ns', 'st_ctime_ns', 'st_uid', 'st_gid'))


def observe(path):
    try:
        before = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        return {'type': 'nonordinary', 'mode': f'{stat.S_IMODE(before.st_mode):04o}'}
    raw = path.read_bytes()
    if stat_key(path.lstat()) != stat_key(before):
        raise ValueError(f'Source changed during readback: {path}')
    return {'sha256': sha256(raw).hexdigest(), 'bytes': len(raw),
            'mode': f'{stat.S_IMODE(before.st_mode):04o}', 'owner': [before.st_uid, before.st_gid]}


def selected(name):
    return name.suffix == '.py' and not name.name.startswith('test_') and name.name != 'conftest.py' \
        and not set(name.parts).intersection(('__pycache__', 'tests', 'fixtures'))


def inventory(root):
    names = set()
    excluded = set()
    links = set()
    for area in SCOPES:
        base = root / area
        for path in base.rglob('*'):
            rel = path.relative_to(root)
            if path.is_symlink():
                links.add(rel.as_posix())
            if selected(rel) and path.is_file():
                names.add(rel.as_posix())
            elif path.suffix == '.json' and path.is_file():
                excluded.add(rel.as_posix())
    return names, excluded, links


def relation(before, after):
    if before is None:
        return 'addition'
    if after is None:
        return 'native_only_absent_from_snapshot'
    if before == after:
        return 'equal'
    return 'replacement' if before.get('sha256') != after.get('sha256') else 'metadata_only'


s5_bytes = S5.read_bytes()
s5 = json.loads(s5_bytes)
current, excluded, stage_links = inventory(CANDIDATE)
native, excluded_native, native_links = inventory(NATIVE)
by_path = {}
for name in sorted(current | native | set(LAUNCHERS) | set(s5['paths'])):
    before, after = (observe(root / name) for root in (NATIVE, CANDIDATE))
    category = relation(before, after)
    old = s5['paths'].get(name)
    by_path[name] = {
        'category': category,
        'old_scope': 'unlisted' if old is None else 'unchanged_after' if old['after'] == after else 'changed_after',
        'old_native_matches': None if old is None else old['before'] == before,
        'installed': before, 'candidate': after,
    }
summary = {area: dict(Counter(value['category'] for name, value in by_path.items()
                              if name.startswith(area + '/'))) for area in SCOPES}
delta = {key: value for key, value in by_path.items() if value['category'] not in {'equal', 'native_only_absent_from_snapshot'}}
print(json.dumps({
    'observed_at': datetime.now(timezone.utc).isoformat(), 's5_manifest_sha256': sha256(s5_bytes).hexdigest(),
    'launcher_results': {name: by_path[name] for name in LAUNCHERS},
    'counts_by_source_scope': summary, 'counts_including_launchers': dict(Counter(row['category'] for row in by_path.values())),
    'candidate_source_symlinks': sorted(stage_links), 'native_source_symlinks': sorted(native_links),
    'scoped_configuration_json_excluded': sorted(excluded | excluded_native),
    'candidate_vs_installed_delta': delta,
    'original_s5_native_drift': [k for k, v in by_path.items() if v['old_native_matches'] is False],
    'original_s5_after_changed': [k for k, v in by_path.items() if v['old_scope'] == 'changed_after'],
    'extra_delta': [k for k, v in delta.items() if v['old_scope'] == 'unlisted'],
    'native_only_paths': [k for k, v in by_path.items() if v['category'] == 'native_only_absent_from_snapshot'],
}, indent=2, sort_keys=True))
