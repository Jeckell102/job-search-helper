"""Assemble only reviewed source and static checker inputs for a future release."""

from hashlib import sha256
import json
from pathlib import Path
from shutil import copy2
import stat
import sys

BACKUP = Path('/tmp/jsh-m1-scope-backup')
PATCH = Path('/tmp/jsh-s6-current-site-pin.kzzbe44q')
PREDECESSOR = Path('/home/chris/.local/state/job-search-helper-maintenance/s4-freeform-20261120-01')
SCOPED_BACKUP = BACKUP / 'tools/sprint6-consolidated-source-preparation'
SCOPE = BACKUP / 'reports/S5_S6_CONSOLIDATED_SOURCE_SCOPE_20261121.json'
SCOPE_SHA = '09e871ceb0cc91685461294abef1651766cbebcb52b5655a63940fde74db13e3'
MANIFEST_SHA = '8ea29b5ae423c18c0b4b108ea1d337359132433e1ad1b9e0cb39e7179117ea11'
LAUNCHER = 'job-search-scraper'
HOST = 'dev/wrapper-coder/tools/host_server.py'


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def stage_source(origin, target, pin):
    if not origin.is_file() or origin.is_symlink():
        raise ValueError(f'Source is not an ordinary reviewed file: {origin.name}')
    if digest(origin) != pin['sha256'] or origin.stat().st_size != pin['bytes']:
        raise ValueError(f'Source differs from reviewed bytes: {origin.name}')
    target.parent.mkdir(parents=True, exist_ok=True)
    copy2(origin, target)
    target.chmod(int(pin['mode'], 8))
    info = target.stat()
    if digest(target) != pin['sha256'] or [info.st_uid, info.st_gid] != pin['owner']:
        raise ValueError(f'Staged file differs from approved metadata: {target.name}')


def main():
    output = Path(__file__).resolve().parent / 'payload'
    output.mkdir(mode=0o700)
    assert digest(SCOPE) == SCOPE_SHA
    inputs = json.loads(SCOPE.read_bytes())
    paths = inputs['paths']
    assert len(paths) == 38
    for path, entry in paths.items():
        stage_source(SCOPED_BACKUP / 'reviewed_after_images' / path, output / 'candidate' / path, entry['after'])

    manifest = output / 'manifest.json'
    copy2(SCOPED_BACKUP / 'independent_policy/exact_38_metadata.json', manifest)
    manifest.chmod(0o600)
    assert digest(manifest) == MANIFEST_SHA
    names = ('controller.py', 'installer.py', 'gate.py', 'verify_hold', 'preinstall_abort.py', 'host_exchange.py')
    for name in names:
        copy2((PATCH if name in {'controller.py', 'installer.py', 'gate.py'} else PREDECESSOR) / name, output / name)
    (output / 'site-source').mkdir(mode=0o700)
    for path in sorted((PREDECESSOR / 'site-source').glob('*.py')):
        assert not path.is_symlink()
        copy2(path, output / 'site-source' / path.name)

    sys.path.insert(0, str(output))
    import installer

    parsed = installer.load_manifest(manifest, MANIFEST_SHA)
    assert parsed.schema == installer.CONSOLIDATED_SCHEMA and set(parsed.paths) == set(paths)
    for name, pin in paths.items():
        assert parsed.owners[name] == pin['after']['owner']
        for side in ('before', 'after'):
            entry = pin[side]
            expected = None if entry is None else (int(entry['mode'], 8), entry['sha256'])
            selected = parsed.before if side == 'before' else parsed.after
            assert selected[name] == expected
    pinned_host = {side: {'digest': paths[HOST][side]['sha256'], 'mode': int(paths[HOST][side]['mode'], 8),
                          'uid': paths[HOST][side]['owner'][0]} for side in ('before', 'after')}
    launcher_rule = {'before': {LAUNCHER: paths[LAUNCHER]['before']['sha256']},
                     'after': {LAUNCHER: paths[LAUNCHER]['after']['sha256']}}
    for side in launcher_rule:
        for name in ('job-search-helper', 'release_admission_bootstrap.py'):
            launcher_rule[side][name] = digest(Path(inputs['native']) / name)
    static = {'source_manifest_sha256': MANIFEST_SHA, 'source_paths': sorted(paths),
              'before_host': pinned_host['before'], 'after_host': pinned_host['after'],
              'launcher_hashes': launcher_rule, 'enrollment_state': 'OFFLINE_SOURCE_PREPARATION'}
    (output / 'offline_checker_inputs.json').write_text(json.dumps(static, sort_keys=True, indent=2) + '\n')
    files = [path for path in sorted(output.rglob('*')) if path.is_file()]
    results = {str(path.relative_to(output)): {'sha256': digest(path), 'mode': f'{stat.S_IMODE(path.stat().st_mode):04o}'}
               for path in files}
    result = {'result': 'PREPARED_OFFLINE_ONLY', 'reviewed_source_count': len(paths), 'file_count': len(files),
              'manifest_sha256': MANIFEST_SHA, 'files': results}
    (output.parent / 'RESULT.json').write_text(json.dumps(result, indent=2) + '\n')
    print(f'Prepared {len(paths)} exact source paths and {len(files)} total files. No native enrollment.')


if __name__ == '__main__':
    main()
