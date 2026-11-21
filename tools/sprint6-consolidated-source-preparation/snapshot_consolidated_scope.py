"""Reconcile a reviewed source overlay and reproduce it in a disposable directory."""

import argparse
from datetime import datetime
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory


LATER_REVIEWED_SHA256 = {
    'dev/wrapper-coder/tools/amphenol_candidate_release.py':
        '7cf2c0795925f077b5cda4a67ce6418adf6fbafae2a955732f60765951ab087f',
    'dev/wrapper-coder/tools/amphenol_installed_verification.py':
        'aeea069ce3ea41d721f19eba73b21ac351ac820d991e3da9f85e546c33d58b8d',
    'dev/wrapper-coder/tools/amphenol_retry_completion.py':
        'c7ca5f021989a5f552482be2f3eb3d40a3da428c733f49b6f8a601c05945f6ef',
    'dev/wrapper-coder/tools/host_server.py':
        '0e13fcae57c4baa4edf1b59454546d2924c49054aebd253dd1b24f666b8e672a',
    'src/job_search_helper/company_events.py':
        '0c82c1091b413622f0fc4a727225efcd3792598e527d0731e78d3d427b5d265b',
    'src/job_search_helper/company_intake_dispatcher.py':
        '4f7181b4f701fefbb05db3803c53cd1c148832a73cbf6fc415773f9de6f57f85',
    'src/job_search_helper/engine.py':
        '1c466d8c33d1dbd102325eee8b7d834667024ad9f20d119a4efab019fc3424f8',
    'src/job_search_helper/inbox.py':
        'dc6f207088e755ac98bd6541ed1ec1b608dc81b2359b7c908883eeb81e43dee1',
    'src/job_search_helper/qualified_release_owner.py':
        '5cf4e70829ad40d797dde4779cb6a1f0a75953f303ed330c0610ee7f0e5b23e6',
    'src/job_search_helper/repair_retry_status.py':
        'ef5e8d51490e073de119fca876e5cc85ffb6418961f3daf97b36191e041b5290',
    'src/job_search_helper/runner.py':
        '0b4e80b429b242a1eec02eadb5b89ac501b8d13f7dc0c3122015e01eece91003',
    'src/job_search_helper/sqlite_repository.py':
        '3ab772748e685a131f885c0eefa7bd8055ed5c22114d4f89204a6dce3d8ff742',
    'src/job_search_helper/sync_cli.py':
        '5af96a0d8abe8496d52824c197e0245207df7ce6e949027f2c392a6bf2d13de2',
}
UNCHANGED_ROOT_PATHS = ('release_admission_bootstrap.py', 'pyproject.toml')


def endpoints(root):
    paths = {'job-search-scraper'}
    for directory, recursive in (('src/job_search_helper', True), ('dev/wrapper-coder/tools', False)):
        scope = root / directory
        entries = scope.rglob('*') if recursive else scope.iterdir()
        paths.update(
            path.relative_to(root).as_posix() for path in entries
            if path.suffix in {'.py', '.json'} and not path.name.startswith('test_')
            and '__pycache__' not in path.parts and (path.is_file() or path.is_symlink())
        )
    return paths


def digest_endpoints(records):
    return sha256(json.dumps(records, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def reproduce_overlay(native, candidate, before, after, changed, read_endpoint):
    """Copy only reviewed software and check the complete disposable result."""
    with TemporaryDirectory(prefix='jsh-reviewed-source-overlay.') as temporary:
        overlay = Path(temporary)
        for name in sorted(before):
            path = overlay / name
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(native / name, path)
            if read_endpoint(overlay, name) != before[name]:
                raise ValueError(f'Scratch before-image differs for {name}')
        for name in sorted(changed):
            path = overlay / name
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(candidate / name, path)
            if path.suffix == '.py':
                compile(path.read_bytes(), name, 'exec', dont_inherit=True)
        if endpoints(overlay) != set(after):
            raise ValueError('Scratch overlay contains a different runtime path set')
        readback = {name: read_endpoint(overlay, name) for name in sorted(after)}
        if readback != after:
            raise ValueError('Scratch overlay does not reproduce the full staged source endpoints')
        return digest_endpoints(readback)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('native', type=Path)
    parser.add_argument('candidate', type=Path)
    parser.add_argument('prior_manifest', type=Path)
    parser.add_argument('prior_scope_tool', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    native = args.native.resolve(strict=True)
    candidate = args.candidate.resolve(strict=True)
    if candidate.is_relative_to(native) or args.output.resolve().is_relative_to(native):
        raise ValueError('Candidate and output must stay outside the native checkout')
    spec = importlib.util.spec_from_file_location('previous_scope', args.prior_scope_tool)
    baseline = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(baseline)
    read_endpoint = baseline.endpoint

    prior_raw = args.prior_manifest.read_bytes()
    prior = json.loads(prior_raw)
    before = {name: read_endpoint(native, name) for name in sorted(endpoints(native))}
    after = {name: read_endpoint(candidate, name) for name in sorted(endpoints(candidate))}
    if set(before) - set(after):
        raise ValueError('Staged application or direct wrapper tools are missing an installed runtime file')
    if any(before.get(name) != value['before'] for name, value in prior['paths'].items()):
        raise ValueError('One of the earlier native before-images has drifted')
    changed = {name for name, value in after.items() if before.get(name) != value}
    if changed != set(prior['paths']) | set(LATER_REVIEWED_SHA256):
        raise ValueError('Runtime endpoint changes differ from the reviewed prior and later scope')
    rows = {}
    for name in sorted(changed):
        if name in LATER_REVIEWED_SHA256:
            if after[name]['sha256'] != LATER_REVIEWED_SHA256[name]:
                raise ValueError(f'Exact later source-review pin differs for {name}')
            origin = 'later_independent_source_review'
        elif after[name] == prior['paths'][name]['after']:
            origin = 'original_s5_scope'
        else:
            raise ValueError(f'Original staged endpoint differs for {name}')
        rows[name] = {'before': before.get(name), 'after': after[name], 'source_review': origin}
    stable = {name: read_endpoint(native, name) for name in UNCHANGED_ROOT_PATHS}
    if any(read_endpoint(candidate, name) != value for name, value in stable.items()):
        raise ValueError('Stable native bootstrap or package manifest differs')
    result = reproduce_overlay(native, candidate, before, after, changed, read_endpoint)
    if before != {name: read_endpoint(native, name) for name in sorted(endpoints(native))}:
        raise ValueError('Native source changed while preparing read-only scope proof')
    report = {
        'observed_at': datetime.now().astimezone().isoformat(timespec='seconds'),
        'disposition': 'REVIEW_ONLY_SOURCE_OVERLAY',
        'native': str(native), 'candidate': str(candidate),
        'prior_scope_sha256': sha256(prior_raw).hexdigest(),
        'runtime_path_count': len(rows),
        'replacement_count': sum(row['before'] is not None for row in rows.values()),
        'addition_count': sum(row['before'] is None for row in rows.values()),
        'revised_prior_path_count': len(set(prior['paths']) & set(LATER_REVIEWED_SHA256)),
        'new_scope_path_count': len(set(LATER_REVIEWED_SHA256) - set(prior['paths'])),
        'unchanged_root_pins': stable,
        'installed_source_before_sha256': digest_endpoints(before),
        'consolidated_source_sha256': digest_endpoints(after),
        'disposable_overlay_sha256': result,
        'paths': rows,
    }
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(f"{len(rows)} paths, {report['replacement_count']} replacements and {report['addition_count']} additions.")
    print(f"Dormant scratch overlay matches staged runtime files under {result}.")


if __name__ == '__main__':
    main()
