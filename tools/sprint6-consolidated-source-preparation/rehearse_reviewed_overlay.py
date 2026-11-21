"""Run the accepted fixture suites from the 38-path software overlay."""

import argparse
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory

from snapshot_consolidated_scope import digest_endpoints, endpoints


TESTS = (
    'tests/test_qualified_release_owner.py',
    'tests/test_amphenol_installed_verification.py',
    'dev/wrapper-coder/tools/test_amphenol_candidate_release.py',
    'dev/wrapper-coder/tools/test_amphenol_host_enrollment.py',
    'dev/wrapper-coder/tools/test_owned_recipe_scheduler.py',
    'tests/test_ordinary_company_event_dispatch.py',
    'tests/test_company_event_bridge.py',
    'tests/test_company_intake_observe.py',
    'tests/test_retained_company_event.py',
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('prior_scope_tool', type=Path)
    parser.add_argument('python', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    manifest_bytes = args.manifest.read_bytes()
    manifest = json.loads(manifest_bytes)
    native = Path(manifest['native'])
    staged = Path(manifest['candidate'])
    if args.output.resolve().is_relative_to(native.resolve()):
        raise ValueError('Fixture output must stay outside the native checkout')
    spec = importlib.util.spec_from_file_location('previous_scope', args.prior_scope_tool)
    baseline = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(baseline)
    read_endpoint = baseline.endpoint

    with TemporaryDirectory(prefix='jsh-deployment-source-proof.') as temporary:
        project = Path(temporary)
        native_paths = endpoints(native)
        before = {name: read_endpoint(native, name) for name in sorted(native_paths)}
        if digest_endpoints(before) != manifest['installed_source_before_sha256']:
            raise ValueError('Native before-images changed since scope verification')
        for name in sorted(native_paths | set(manifest['paths'])):
            destination = project / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            origin = staged if name in manifest['paths'] else native
            shutil.copy2(origin / name, destination)
        software = {name: read_endpoint(project, name) for name in sorted(endpoints(project))}
        if digest_endpoints(software) != manifest['consolidated_source_sha256']:
            raise ValueError('Review-only source overlay differs from the approved test input')

        for name, unchanged in manifest['unchanged_root_pins'].items():
            if read_endpoint(native, name) != unchanged:
                raise ValueError(f'Retained native root file differs for {name}')
            shutil.copy2(native / name, project / name)
            if read_endpoint(project, name) != unchanged:
                raise ValueError(f'Scratch retained root file differs for {name}')
        # Tests use fixture policy files. The overlay writes neither policy file.
        for name in ('title-blacklist.txt', 'title-review-list.txt'):
            shutil.copy2(staged / name, project / name)
        shutil.copytree(staged / 'tests', project / 'tests',
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        for path in (staged / 'dev/wrapper-coder/tools').glob('test_*.py'):
            shutil.copy2(path, project / 'dev/wrapper-coder/tools' / path.name)

        sandbox_home = project / 'fixture-home'
        sandbox_home.mkdir()
        environment = {
            'PATH': os.defpath, 'HOME': str(sandbox_home), 'LANG': 'C.UTF-8',
            'PYTHONDONTWRITEBYTECODE': '1', 'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1',
            'JOB_STORAGE_BACKEND': 'sqlite', 'PYTHONPATH': 'src:tests:dev/wrapper-coder/tools',
        }
        test = subprocess.run(
            [str(args.python), '-B', '-m', 'pytest', '-q', '-p', 'no:cacheprovider', *TESTS],
            cwd=project, env=environment, text=True, capture_output=True, timeout=150,
        )
        after = {name: read_endpoint(project, name) for name in sorted(endpoints(project))}
        if after != software:
            raise ValueError('Fixture tests changed a measured source endpoint')
        if any(read_endpoint(project, name) != value
               for name, value in manifest['unchanged_root_pins'].items()):
            raise ValueError('Fixture tests changed a retained root file')
    proof = {
        'scope_manifest_sha256': sha256(manifest_bytes).hexdigest(),
        'reconstructed_runtime_sha256': digest_endpoints(software),
        'runtime_paths_unchanged_by_fixture': True,
        'retained_root_files_verified': sorted(manifest['unchanged_root_pins']),
        'test_exit': test.returncode, 'test_files': TESTS,
        'test_stdout': test.stdout,
    }
    args.output.write_text(json.dumps(proof, indent=2, sort_keys=True) + '\n')
    print(test.stdout, end='')
    if test.stderr:
        print(test.stderr, end='')
    raise SystemExit(test.returncode)


if __name__ == '__main__':
    main()
