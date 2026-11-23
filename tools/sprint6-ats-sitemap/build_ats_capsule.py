"""Prepare the exact ATS source overlay, rollback images, and isolated assignment."""
from difflib import diff_bytes, unified_diff
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory


PROJECT = Path('/home/chris/job-search-helper_old')
HANDOFF = Path('/tmp/jsh-successfactors-sitemap-host')
PACKAGE = Path(__file__).resolve().parent
TOOLS = Path('dev/wrapper-coder/tools')
APP = Path('src/job_search_helper')
FIXTURE = 'tests/test_ats_sitemap_parser.py'
PROTOCOL = 'docs/wrapper-development-test-protocol.md'
PRIVATE_INPUTS = {
    FIXTURE: '5020eb066ed85a86de51e2781ccc4de011d42e2bcfc4f3797bdf3e0350db27f0',
    PROTOCOL: '4c95994b3124f4c8b45cc4a7ba64b3f9777d6fce16d3403689b69a945a59a3c6',
}
EXPECTED = {
    'job-search-scraper', 'release_admission_bootstrap.py',
    *(str(TOOLS / (module + '.py')) for module in (
        'ats_operator_pilot', 'ats_parser_assignment', 'coordinator', 'coordinator_inference', 'host_server')),
    *(str(APP / (module + '.py')) for module in (
        'ats', 'ats_sitemap_parser', 'operator_amphenol_fetch', 'operator_company_request',
        'operator_embraer_settlement', 'operator_partial_scope', 'operator_selected_observation', 'runner',
        'successfactors', 'successfactors_sitemap')),
}


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def copy(origin, output, expected, mode=None):
    if (origin.resolve(strict=True) != origin or not origin.is_file()
            or origin.stat().st_nlink != 1 or not isinstance(expected, str)):
        raise ValueError(f'Expected a single ordinary file at {origin}')
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise ValueError(f'Duplicate source image {output}')
    shutil.copy2(origin, output)
    if mode is not None:
        output.chmod(mode)
    if digest(output) != expected:
        raise ValueError(f'Input bytes differ for {origin}')


def document(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + '\n')
    path.chmod(0o600)


def build(scratch):
    from coordinator_baseline import binding, files
    from job_search_helper.integration_release import metadata, source_tree_digest
    from release_admission_bootstrap import _load_environment, _validate_runtime

    _load_environment(PROJECT / '.env')
    journal = PROJECT / '.state/integration-release-journal.json'
    journal_sha = digest(journal)
    runtime = _validate_runtime(PROJECT, journal.parent)
    if runtime['state'] != 'COMPLETE' or runtime['release_id'] != 'REL-ede347339c8faf1806583810':
        raise ValueError('Expected the verified Crown predecessor release')
    pin_path = HANDOFF / 'ATS_SOURCE_PINS.json'
    pin_sha = digest(pin_path)
    pins = json.loads(pin_path.read_text())
    if set(pins) != EXPECTED:
        raise ValueError('Reviewed ATS endpoint set differs')
    endpoints = {}
    groups = {'app_and_launchers': [], 'wrapper_tools': []}
    patch = bytearray()
    for name, pin in sorted(pins.items()):
        relative = Path(name)
        is_tool = relative.parent == TOOLS
        canonical_source = str(Path('tools') / relative.name) if is_tool else name
        if pin['source'] != canonical_source:
            raise ValueError(f'Staged source mapping differs for {name}')
        target = PROJECT / name
        if target.resolve() != target or (target.exists() and not target.is_file()):
            raise ValueError(f'Unexpected installed endpoint {name}')
        before = metadata(target) if target.exists() else None
        if (before['sha256'] if before else None) != pin['before_sha256']:
            raise ValueError(f'Installed bytes differ for {name}')
        before_image = scratch / 'before' / name
        if before:
            copy(target, before_image, before['sha256'])
            if metadata(before_image) != before:
                raise ValueError(f'Rollback image does not match {name}')
        image = scratch / 'staged' / name
        copy(HANDOFF / canonical_source, image, pin['staged_sha256'], before['mode'] if before else None)
        owner = (target if before else target.parent).stat()
        endpoints[name] = {'before': before, 'staged': metadata(image), 'owner': [owner.st_uid, owner.st_gid]}
        groups['wrapper_tools' if is_tool else 'app_and_launchers'].append(name)
        old = before_image.read_bytes() if before else b''
        patch.extend(b''.join(diff_bytes(unified_diff, old.splitlines(True), image.read_bytes().splitlines(True),
                                         ('a/' + name).encode() if before else b'/dev/null', ('b/' + name).encode())))

    initial = files(PROJECT)
    inputs = dict(initial)
    for name, entry in endpoints.items():
        if name.startswith('src/'):
            inputs[name] = entry['staged']['sha256']
    for name, expected in PRIVATE_INPUTS.items():
        if name in inputs:
            raise ValueError(f'Private input unexpectedly exists in production: {name}')
        inputs[name] = expected
    if digest(HANDOFF / 'ats_parser_contract.py') != PRIVATE_INPUTS[FIXTURE]:
        raise ValueError('Reviewed immutable fixture differs')
    baseline = scratch / 'assembly'
    for name, expected in sorted(inputs.items()):
        if name in PRIVATE_INPUTS:
            origin = HANDOFF / name
        elif name in endpoints:
            origin = scratch / 'staged' / name
        else:
            origin = PROJECT / name
        copy(origin, baseline / name, expected)
    if files(baseline) != inputs:
        raise ValueError('Private baseline does not contain the exact inputs')
    source_sha = source_tree_digest(baseline)
    if source_sha != source_tree_digest(HANDOFF):
        raise ValueError('Effective application source differs from the complete staged tree')
    baseline_sha = binding(inputs)['digest']
    relative = 'pilot-bases/ats-' + baseline_sha
    (scratch / 'pilot-bases').mkdir(mode=0o700)
    baseline.rename(scratch / relative)
    if (digest(journal) != journal_sha or _validate_runtime(PROJECT, journal.parent) != runtime
            or digest(pin_path) != pin_sha or files(PROJECT) != initial):
        raise ValueError('Release or assignment inputs changed during preparation')
    for name, entry in endpoints.items():
        p = PROJECT / name
        if (metadata(p) if p.exists() else None) != entry['before']:
            raise ValueError(f'Installed endpoint changed during preparation: {name}')
    (scratch / 'SOURCE_CHANGES.patch').write_bytes(patch)
    (scratch / 'SOURCE_CHANGES.patch').chmod(0o600)
    spec = {
        'schema': 'ats-owned-native-prepared-package-v1', 'approval': 'PREPARATION_ONLY',
        'live_runtime': runtime, 'live_journal_sha256': journal_sha,
        'staged_source_sha256': source_sha, 'package_files': endpoints, 'groups': groups,
        'pilot_baseline': {'relative_path': relative, 'sha256': baseline_sha, 'file_count': len(inputs)},
    }
    document(scratch / 'PREPARED_PACKAGE.json', spec)
    summary = {'package_sha256': digest(scratch / 'PREPARED_PACKAGE.json'), 'source_pins_sha256': pin_sha,
               'patch_sha256': digest(scratch / 'SOURCE_CHANGES.patch'), 'predecessor_release': runtime['release_id'],
               'source_sha256': source_sha, 'baseline': spec['pilot_baseline'], 'private_inputs': PRIVATE_INPUTS,
               'groups': {k: len(v) for k, v in groups.items()},
               'rollback_images': sum(entry['before'] is not None for entry in endpoints.values())}
    document(scratch / 'BUILD_READBACK.json', summary)
    return summary


if __name__ == '__main__':
    os.umask(0o077)
    sys.path[:0] = [str(PROJECT), str(PROJECT / 'src'), str(PROJECT / TOOLS)]
    artifacts = ('before', 'staged', 'pilot-bases', 'SOURCE_CHANGES.patch', 'BUILD_READBACK.json', 'PREPARED_PACKAGE.json')
    if any((PACKAGE / name).exists() for name in artifacts):
        raise SystemExit('The package already contains staged inputs')
    with TemporaryDirectory(dir=PACKAGE, prefix='.building-') as temp:
        scratch = Path(temp)
        summary = build(scratch)
        for name in artifacts:
            (scratch / name).rename(PACKAGE / name)
    print(json.dumps(summary, sort_keys=True))
