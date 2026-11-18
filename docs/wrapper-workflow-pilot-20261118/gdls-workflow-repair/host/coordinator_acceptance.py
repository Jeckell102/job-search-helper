"""Exact edit scopes and host-owned, immutable offline acceptance inputs."""
import ast
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile

import coding_tools as code

CONFIG_INPUTS = ('pyproject.toml', 'title-blacklist.txt', 'title-review-list.txt')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def exact_paths(paths):
    if not isinstance(paths, list) or not paths or len(paths) > 40:
        raise ValueError('Scope requires one to forty exact file paths.')
    result = []
    for name in paths:
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_./-]+', name):
            raise ValueError('Scope requires safe exact paths.')
        path = PurePosixPath(name)
        if (str(path) != name or path.parts[0] not in code.ALLOWED
                or any(p.startswith('.') for p in path.parts) or path.suffix not in code.EXTENSIONS
                or name == 'docs/wrapper-development-test-protocol.md'):
            raise ValueError('Scope path is not an editable source, test, or output document.')
        if name not in result:
            result.append(name)
    return sorted(result)


def initial_scope(state):
    identity = state.get('integration_identity')
    paths = identity['source_targets'] + identity['tests'] if identity else list(state['tests']) + re.findall(r'\b(?:src|tests|docs)/[A-Za-z0-9_./-]+\.(?:py|md|txt|json|html|xml|toml|csv)\b', state['objective'])
    paths = [p for p in paths if p != 'docs/wrapper-development-test-protocol.md']
    paths = exact_paths(paths)
    return dict(paths=paths, version=1, digest=digest(paths), history=[])


def validate_scope(state):
    scope = state.get('edit_scope')
    if not isinstance(scope, dict) or scope.get('paths') != exact_paths(scope.get('paths')) or scope.get('digest') != digest(scope['paths']):
        raise ValueError('Task edit scope is missing or changed; explicit operator migration required.')
    if not isinstance(scope.get('version'), int) or scope['version'] < 1:
        raise ValueError('Invalid edit scope version.')
    return scope


def files(root, areas=('tests',), configs=True):
    result = {}
    for area in areas:
        base = root / area
        if base.is_symlink():
            raise ValueError('Unsafe acceptance input directory.')
        for path in sorted(base.rglob('*')):
            if '__pycache__' in path.parts or path.suffix == '.pyc':
                continue
            if path.is_symlink():
                raise ValueError('Unsafe acceptance input link.')
            if not path.is_file():
                continue
            if path.stat().st_nlink != 1 or path.stat().st_size > 2000000:
                raise ValueError('Unsafe or oversized acceptance input.')
            result[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    if configs:
        for name in CONFIG_INPUTS:
            path = root / name
            if path.exists() or path.is_symlink():
                if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1 or path.stat().st_size > 256000:
                    raise ValueError('Unsafe acceptance configuration.')
                result[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def assertion_present(path):
    tree = ast.parse(path.read_text())
    return any(isinstance(node, ast.Assert) or isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
               and (node.func.attr.startswith('assert') or node.func.attr in ('raises', 'fail')) for node in ast.walk(tree))


def bundle_path(store, state):
    return store.base / state['id'] / 'acceptance-original'


def validate_bundle(store, state):
    bundle = state.get('acceptance_bundle')
    target = bundle_path(store, state)
    if not bundle or bundle.get('digest') != digest(bundle.get('manifest')) or bundle.get('tests') != state['tests']:
        raise ValueError('Independent baseline acceptance bundle is missing or changed.')
    if target.is_symlink() or not target.is_dir() or files(target) != bundle['manifest']:
        raise ValueError('Acceptance bundle, fixture, or config hash changed.')
    return bundle


def ensure_bundle(store, state, root):
    if state.get('acceptance_bundle'):
        validate_bundle(store, state)
        return state
    # A resumed task with prior edits must never bless its edited tests as baseline.
    if any(r['name'] in ('code_edit', 'code_create') for r in store.receipts(state['id'])):
        raise ValueError('Prior edits lack independent baseline assertions; operator acceptance required.')
    for name in state['tests']:
        path = root / name
        if not path.is_file() or not assertion_present(path):
            raise ValueError('Assigned test lacks an original independent acceptance assertion: ' + name)
    manifest = files(root)
    if state.get('acceptance_baseline_manifest') != manifest:
        raise ValueError('Original acceptance inputs changed since assignment; operator acceptance required.')
    target = bundle_path(store, state)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise ValueError('Unregistered acceptance bundle requires operator inspection.')
    with tempfile.TemporaryDirectory(prefix='acceptance-prepare-', dir=target.parent) as tmp:
        staging = Path(tmp) / 'bundle'
        staging.mkdir()
        for name in manifest:
            dest = staging / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes((root / name).read_bytes())
        if files(staging) != manifest or files(root) != manifest:
            raise ValueError('Acceptance inputs changed during capture.')
        staging.rename(target)
    bundle = dict(manifest=manifest, digest=digest(manifest), tests=list(state['tests']))
    return store.record_acceptance_bundle(state['id'], bundle)


def verify_bundle(store, state, root):
    scope = validate_scope(state)
    bundle = validate_bundle(store, state)
    source_before = files(root, ('src',), False)
    with tempfile.TemporaryDirectory(prefix='acceptance-run-', dir=store.base / state['id']) as tmp:
        sandbox = Path(tmp)
        for name in bundle['manifest']:
            dest = sandbox / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes((bundle_path(store, state) / name).read_bytes())
        for name in source_before:
            dest = sandbox / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes((root / name).read_bytes())
        if files(sandbox) != bundle['manifest'] or files(sandbox, ('src',), False) != source_before:
            raise ValueError('Acceptance sandbox copy changed.')
        token = code.WORKSPACE.set(sandbox)
        try:
            value = code.run_tests(' '.join(state['tests']))
        finally:
            code.WORKSPACE.reset(token)
        validate_bundle(store, state)
        if files(sandbox) != bundle['manifest'] or files(root, ('src',), False) != source_before or files(sandbox, ('src',), False) != source_before:
            raise ValueError('Acceptance inputs changed during verification.')
        return dict(value, acceptance_bundle_digest=bundle['digest'], source_manifest=source_before,
                    source_manifest_digest=digest(source_before), frozen_tests_root=str(sandbox / 'tests'),
                    edited_source_origin=str(root / 'src'), edited_source_import_path=str(sandbox / 'src'),
                    command=value.get('command', ['coding_tools.run_tests', *state['tests']]),
                    bundle_digest_before=bundle['digest'], bundle_digest_after=bundle['digest'],
                    edit_scope_digest=scope['digest'], edit_scope_version=scope['version'],
                    independent_acceptance=True)
