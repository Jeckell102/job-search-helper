"""Run only the pinned Sprint 5 transport fixture closure in a clean interpreter."""

import argparse
from hashlib import sha256
from importlib import import_module
from importlib.abc import Loader, MetaPathFinder
from importlib.util import spec_from_loader
import json
from pathlib import Path, PurePosixPath
import stat
import sys


class CapsuleError(Exception):
    pass


def require(condition, reason):
    if not condition:
        raise CapsuleError(reason)


def read_pinned(root, relative, expected):
    relative_path = PurePosixPath(relative)
    require(relative_path.parts and not relative_path.is_absolute() and '..' not in relative_path.parts
            and relative_path.as_posix() == relative, f'Noncanonical pinned path: {relative}')
    path = root / relative
    info = path.lstat()
    require(path.resolve(strict=True) == path and stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
            f'Noncanonical pinned file: {relative}')
    raw = path.read_bytes()
    require(sha256(raw).hexdigest() == expected, f'Digest mismatch before import: {relative}')
    return path, raw


class VerifiedSources(MetaPathFinder, Loader):
    def __init__(self, records):
        self.records = records

    def find_spec(self, fullname, path=None, target=None):
        if fullname in self.records:
            location, _ = self.records[fullname]
            package = location.name == '__init__.py'
            spec = spec_from_loader(fullname, self, origin=str(location), is_package=package)
            spec.has_location = True
            if package:
                spec.submodule_search_locations = [str(location.parent)]
            return spec
        if fullname.partition('.')[0] == 'job_search_helper' or fullname.startswith(('rippling_', 'test_s5_')):
            raise ModuleNotFoundError(f'Project module is outside the verified fixture closure: {fullname}')
        return None

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        path, raw = self.records[module.__name__]
        exec(compile(raw, str(path), 'exec', dont_inherit=True), module.__dict__)


def verify_module_origins(records, loader, framework_files, stdlib, *, complete=False):
    for name, module in sys.modules.copy().items():
        filename = getattr(module, '__file__', None)
        if name in records:
            require(filename == str(records[name][0]) and module.__spec__.loader is loader,
                    f'Module was not loaded from verified source bytes: {name}')
        elif filename is not None and name != '__main__':
            path = Path(filename).resolve()
            require(path in framework_files or any(path.is_relative_to(base) for base in stdlib),
                    f'Module resolved outside fixture or platform paths: {name}')
    if complete:
        require(set(records).issubset(sys.modules), 'The staged fixture closure was not fully exercised')


def deny_socket_activity(event, _arguments):
    if event in {'socket.__new__', 'socket.connect', 'socket.getaddrinfo', 'socket.gethostbyname',
                 'socket.gethostbyaddr', 'socket.sendto', 'socket.bind'}:
        raise RuntimeError('Native socket activity is disabled for this fixture')


def run(args):
    require(sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode
            and sys.flags.optimize == 0, 'Use Python -I -S -B without optimization')
    require(args.root.is_absolute() and args.root.resolve(strict=True) == args.root,
            'Fixture root must be canonical')
    _, raw_manifest = read_pinned(args.root, 'dependency-manifest.json', args.manifest_sha256)
    manifest = json.loads(raw_manifest)
    require(manifest['schema'] == 'jsh-s5-transport-fixture-dependency-manifest-v1',
            'Wrong fixture dependency manifest schema')
    require(not set(manifest['modules']).intersection(sys.modules),
            'A same-name fixture module was already loaded before verification')

    records = {
        name: read_pinned(args.root, entry['copied_path'], entry['sha256'])
        for name, entry in manifest['modules'].items()
    }
    framework_files = {
        read_pinned(args.root, relative, digest)[0]
        for relative, digest in manifest['test_framework_support'].items()
    }
    manifest_files = {args.root / 'dependency-manifest.json', *framework_files,
                      *(path for path, _ in records.values())}
    nodes = tuple(args.root.rglob('*'))
    require(not any(node.is_symlink() for node in nodes), 'Unexpected symlink in test capsule')
    require({node for node in nodes if not node.is_dir()} == manifest_files,
            'Fixture capsule contains paths outside the reviewed manifest')

    stdlib = tuple(Path(path).resolve() for path in sys.path)
    loader = VerifiedSources(records)
    sys.path.insert(0, str(args.root / 'support'))
    sys.meta_path.insert(0, loader)
    sys.addaudithook(deny_socket_activity)

    pytest = import_module('pytest')
    cases = manifest['fixture_order']
    for name in cases:
        import_module(name)
    verify_module_origins(records, loader, framework_files, stdlib)
    print(f'Verified {len(records)} copied source modules and {len(framework_files)} framework files.', flush=True)
    result = pytest.main([
        '-q', '-c', '/dev/null', '-p', 'no:cacheprovider', '--import-mode=prepend', '--tb=short',
        '--basetemp='+str(args.test_temp), '--rootdir='+str(args.root),
        *(str(records[name][0]) for name in cases),
    ])
    verify_module_origins(records, loader, framework_files, stdlib, complete=True)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--test-temp', required=True, type=Path)
    arguments = parser.parse_args()
    try:
        raise SystemExit(run(arguments))
    except (CapsuleError, KeyError, OSError, ValueError) as error:
        raise SystemExit(f'Fixture capsule rejected: {error}') from None
