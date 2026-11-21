"""Default-off readiness check for the exact fresh Amphenol release."""

from hashlib import sha256
from importlib import import_module
from importlib.machinery import PathFinder
import json
import os
from pathlib import Path
import sys


STAGE = Path(__file__).resolve().parent
PROJECT = Path('/home/chris/job-search-helper_old')
RELEASE_ID = 'REL-53592bb86b62492840c58267'
MANIFEST_SHA = '9b02e2bb924666d240ec666d5ad6292def584e8f7155f89bfa3c465999fc323e'
STAGED_TOOLS = STAGE / 'release-tools'
INSTALLED_TOOLS = PROJECT / 'dev/wrapper-coder/tools'
CONTROLLER_ROOT = Path('/home/chris/.local/state/job-search-helper-maintenance/s5-operator-trigger-20261121-03')
TOOLS = {
    'amphenol_candidate_release': 'bf9ac48a86ee6e19290423899409f2603031e2ce3977247f05df21a4cd7d7c42',
    'amphenol_operator_one_shot': 'e00a40688045377d06a515004360ded7004fb336a99a6e5faa92ccca95a35638',
    'amphenol_operator_quiet_window': '8b124170b12897dcc37a82d6a5af5ed38538fee22d9194ddf4146c2565a2fdc4',
    'amphenol_operator_retained_release': 'df7e0aabcc961342aa18fed318ee957c6f679342a938d22dd4e8e51570e403b4',
    'amphenol_retry_completion': '1b598db426c24611adc5303a71c4f9d21fe4ddc5e2560459be7a78d1989abf67',
    'coordinator': 'db41607834c42a90f742d048c3df5a9e68ac8c9f75deb1414cc4d554c0d9caec',
    'coordinator_store': '48e3f2ccee38b83f5577d2a66398074d58ab16b3f3c9afd5fda69e83af8e3d7b',
}
INSTALLED_PINS = {
    'host_server.py': 'a1cafe60d2025116bcaa43dd8dd1b4099a9c2845c35353f3f25dec98a8df5567',
    'coordinator_store.py': '16c442d8019d5173f188348890fd89fe224d2c4315fde67528ed26e25478134d',
}
HISTORY_PINS = {
    'controller.py': 'f63f9399f3fcdec3d3b46a6d5e14fc3d1d78e420234b357b0adf44bd68a53ff8',
    'installer.py': 'd85405266310a425bcc49027b5629cfb81dcc89f391cfbf75df33da7ac2a0920',
    'host-check': 'c0bec31ab59dbdc1064e2ee7003b9aa68e115d5902c34e43ebbe75058bf2a53e',
}


def require_pin(path, pin):
    if (path.resolve(strict=True) != path or not path.is_file()
            or path.stat().st_nlink != 1 or sha256(path.read_bytes()).hexdigest() != pin):
        raise ValueError(f'Unexpected source custody for {path.name}')


def verify_tool_origins():
    if (not sys.flags.isolated or not sys.flags.dont_write_bytecode
            or Path(sys.prefix).resolve() != PROJECT / '.venv'):
        raise ValueError('The isolated production Python interpreter is required')
    if STAGED_TOOLS.resolve(strict=True) != STAGED_TOOLS or set(STAGED_TOOLS.iterdir()) != {
            STAGED_TOOLS / f'{name}.py' for name in TOOLS}:
        raise ValueError('The fresh tool directory must contain exactly the seven reviewed sources')
    for name, pin in TOOLS.items():
        require_pin(STAGED_TOOLS / f'{name}.py', pin)
    for name, pin in INSTALLED_PINS.items():
        require_pin(INSTALLED_TOOLS / name, pin)
    for name, pin in HISTORY_PINS.items():
        require_pin(CONTROLLER_ROOT / name, pin)

    empty_cache = STAGE / 'unpopulated-bytecode'
    if os.path.lexists(empty_cache):
        raise ValueError('Expected no release bytecode cache')
    sys.pycache_prefix = str(empty_cache)
    sys.path[:0] = [str(path) for path in (STAGED_TOOLS, INSTALLED_TOOLS, PROJECT / 'src',
                                         CONTROLLER_ROOT, CONTROLLER_ROOT / 'host-check')]
    origins = {name: STAGED_TOOLS / f'{name}.py' for name in TOOLS}
    origins.update({
        'host_server': INSTALLED_TOOLS / 'host_server.py',
        'controller': CONTROLLER_ROOT / 'controller.py',
        'installer': CONTROLLER_ROOT / 'installer.py',
    })
    PathFinder.invalidate_caches()
    for name, path in origins.items():
        spec = PathFinder.find_spec(name)
        if spec is None or spec.origin != str(path):
            raise ValueError(f'Wrong import origin for {name}')
    loaded = {name: import_module(name) for name in origins}
    if any(Path(loaded[name].__file__).resolve() != path for name, path in origins.items()):
        raise ValueError('Imported release tool origins do not match their measured sources')
    if loaded['host_server'].JOB_SEARCH_ROOT != PROJECT or loaded['host_server'].BASE != INSTALLED_TOOLS.parent:
        raise ValueError('Selected host does not bind the installed application and coordinator')
    return loaded


def main():
    if len(sys.argv) != 1:
        raise ValueError('This staged entry currently supports only read-only inspection')
    verify_tool_origins()
    from job_search_helper.cli import load_environment
    from job_search_helper.integration_release import (
        _verify_inputs, _verify_projected_release, canonical_manifest, digest,
    )

    load_environment(PROJECT / '.env')
    manifest = canonical_manifest(json.loads((STAGE / 'PROPOSED_MANIFEST.json').read_bytes()))
    if manifest['release_id'] != RELEASE_ID or digest(manifest) != MANIFEST_SHA:
        raise ValueError('The fresh proposal changed')
    candidate = STAGE / 'candidate'
    _verify_inputs(PROJECT, candidate, manifest)
    _verify_projected_release(PROJECT, manifest)
    print(json.dumps({'status': 'FRESH_RELEASE_IMPORTS_VERIFIED', 'release_id': RELEASE_ID,
                      'reviewed_tool_count': len(TOOLS), 'installation': 'not_requested'}, sort_keys=True))


if __name__ == '__main__':
    main()
