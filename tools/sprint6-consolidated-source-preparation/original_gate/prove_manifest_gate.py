"""Use only the exact accepted parser's read-only load_manifest function."""
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
SCOPE = Path('/tmp/jsh-consolidated-scope.20261121/RESULT.json')
SCOPE_SHA = '09e871ceb0cc91685461294abef1651766cbebcb52b5655a63940fde74db13e3'
CAPSULE = Path('/home/chris/.local/state/job-search-helper-maintenance/s4-freeform-20261120-01')
INSTALLER_SHA = '796e8b04cca48c7641c45480611ab43f2d19a2a96da9dc9a08d548d029fc1ee4'
FREEFORM_SHA = 'a1863753a251058e1cd99266568aef3b6e9b3076e49c52dd0adff11d93f6a163'
SELECTION = Path('/tmp/jsh-s4-freeform-live.tif0p2q_/pilot-restoration-selection.json')
BRIDGE = 'dev/wrapper-coder/tools/coordinator_receipt_host_bridge.py'


def digest(data):
    return sha256(data).hexdigest()


def pinned(path, expected):
    raw = path.read_bytes()
    assert digest(raw) == expected, path.name
    return raw


def shape(record):
    return None if record is None else {key: record[key] for key in ('mode', 'sha256')}


def main():
    frozen = json.loads(pinned(SCOPE, SCOPE_SHA))
    selected = json.loads(SELECTION.read_bytes())['tools']
    assert (selected['installer.py'], selected['manifest.json']) == (INSTALLER_SHA, FREEFORM_SHA)
    inventory = dict(line.split('  ', 1)[::-1] for line in (CAPSULE / 'SHA256SUMS').read_text().splitlines())
    assert inventory['installer.py'] == INSTALLER_SHA and inventory['manifest.json'] == FREEFORM_SHA
    parser_copy = HERE / 'accepted_freeform_installer.py'
    parser_copy.write_bytes(pinned(CAPSULE / 'installer.py', INSTALLER_SHA))
    original_copy = HERE / 'accepted_freeform_manifest.json'
    original_copy.write_bytes(pinned(CAPSULE / 'manifest.json', FREEFORM_SHA))
    original = json.loads(original_copy.read_bytes())
    assert original['schema'] == 'sprint-4-source-manifest-v1'

    paths = {}
    for name, row in frozen['paths'].items():
        old, new = row['before'], row['after']
        assert old is None or old['owner'] == new['owner']
        paths[name] = {'before': shape(old), 'after': shape(new), 'owner': new['owner']}
    assert len(paths) == 38 and sum(row['before'] is None for row in paths.values()) == 10
    candidate = {'schema': original['schema'], 'paths': paths}
    encoded = json.dumps(candidate, sort_keys=True, separators=(',', ':')).encode() + b'\n'
    scratch_manifest = HERE / 'consolidated_exact_38_manifest.json'
    scratch_manifest.write_bytes(encoded)
    input_sha = digest(encoded)

    name = 'archived_freeform_parser'
    spec = importlib.util.spec_from_file_location(name, parser_copy)
    installer = importlib.util.module_from_spec(spec)
    sys.modules[name] = installer
    spec.loader.exec_module(installer)
    assert installer.encode(candidate) == encoded

    parsing = False

    def guard(event, args):
        if parsing and (event.startswith(('socket.', 'subprocess.'))
                or (event == 'open' and args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC))
                or event in ('os.mkdir', 'os.rename', 'os.remove', 'os.chmod', 'os.link', 'os.exec')):
            raise AssertionError('Parser call attempted an effect: ' + event)

    sys.addaudithook(guard)
    try:
        parsing = True
        accepted = installer.load_manifest(original_copy, FREEFORM_SHA)
        assert len(accepted.paths) == 47 and accepted.sha256 == FREEFORM_SHA
        try:
            installer.load_manifest(scratch_manifest, input_sha)
        except ValueError as error:
            refusal = str(error)
        else:
            raise AssertionError('Exact Freeform parser unexpectedly accepted the 38-path overlay')
    finally:
        parsing = False

    wrappers = sorted(name for name in paths if name.startswith('dev/wrapper-coder/tools/'))
    rejected = sorted(name for name in paths
                      if not installer.SOURCE_PATH.fullmatch(name) and name not in installer.WRAPPER_PATHS)
    allowed = sorted(set(paths) - set(rejected))
    mandatory_existing = sorted(installer.WRAPPER_PATHS)
    missing = sorted(set(mandatory_existing) - set(paths))
    assert refusal == f'Source path is outside the allowed scope: {rejected[0]}'
    assert len(wrappers) == 11 and len(rejected) == 9 and len(allowed) == 29 and missing == [BRIDGE]
    assert all(name in wrappers for name in rejected)
    for name, row in paths.items():
        assert installer.endpoint(row['before'], allow_absent=True) != installer.endpoint(row['after']), name
    bridge_staged = Path(frozen['candidate']) / BRIDGE
    bridge_known = original['paths'][BRIDGE]['after']
    assert digest(bridge_staged.read_bytes()) == bridge_known['sha256']
    assert f'{bridge_staged.stat().st_mode & 0o777:04o}' == bridge_known['mode']
    result = {'result': 'REFUSED_EXACT_38_BY_ACCEPTED_FREEFORM_PARSER', 'freeform_parser_sha256': INSTALLER_SHA,
              'accepted_47_control_sha256': FREEFORM_SHA, 'accepted_47_control_paths': len(accepted.paths),
              'frozen_scope_sha256': SCOPE_SHA, 'exact_38_manifest_sha256': input_sha, 'refusal': refusal,
              'endpoint_rows_well_formed': 38, 'lexically_allowed_paths': allowed,
              'lexically_refused_paths': rejected,
              'lexically_allowed_package_module_count': sum(name.startswith('src/job_search_helper/') for name in allowed),
              'lexically_allowed_wrapper_paths': sorted(set(wrappers) & set(allowed)),
              'mandatory_existing_wrapper_paths': mandatory_existing, 'missing_mandatory_wrapper_paths': missing,
              'missing_bridge_matches_accepted_after_bytes_and_mode_in_staged_candidate': bridge_known,
              'same_before_after_rows_rejected_by_exact_parser_rule': True,
              'only_load_manifest_called': True}
    (HERE / 'RESULT.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'lexically_allowed_paths'}, sort_keys=True))


if __name__ == '__main__':
    main()
