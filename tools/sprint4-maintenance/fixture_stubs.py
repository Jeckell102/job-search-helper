"""Fixture subprocesses. Never import either actual application source tree."""
from hashlib import sha256
import importlib.machinery
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys

from test_combined_release import (DROP_IN, HOST_SCHEMA, MARKER, PARKED, ROOT,
                                   UNITS, WRAPPER, WRAPPER_PATHS, write, encode)


def context(script):
    root = script.parent.parent if script.parent.name == 'capsule' else script.parent
    supplied = Path(os.environ['JSH_COMBINED_FIXTURE_ROOT'])
    assert supplied == root and root.resolve() == root and root.parent.parent == ROOT, root
    ident = json.loads((root / 'fixture-id').read_bytes())
    assert ident['root'] == str(root) and ident['hold_id'].startswith('s4-combined-disposable-')
    return root, ident


def append(root, name, event):
    with (root / name).open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(event, sort_keys=True) + '\n')
        stream.flush()
        os.fsync(stream.fileno())


def manifest(bundle):
    raw = (bundle / 'manifest.json').read_bytes()
    return json.loads(raw)['paths'], sha256(raw).hexdigest()


def matches(path, expected):
    if expected is None:
        return not os.path.lexists(path)
    return (path.is_file() and not path.is_symlink()
            and path.stat().st_mode & 0o7777 == int(expected['mode'], 8)
            and sha256(path.read_bytes()).hexdigest() == expected['sha256'])


def vector(root, package, side, *, compile_sources=False):
    project = root / 'project'
    rows, _ = manifest(root / 'capsule')
    for name, row in rows.items():
        path = package / Path(name).name if name.startswith('src/job_search_helper/') else project / name
        assert matches(path, row[side]), (side, str(path))
        if row[side] is not None:
            assert (path.stat().st_uid, path.stat().st_gid) == tuple(row['owner']), path
            if compile_sources and path.suffix == '.py':
                compile(path.read_bytes(), str(path), 'exec')


def stock_worker(package):
    # The only successful code body is the fixture-owned trivial initializer.
    script = ('import sys; sys.path.insert(0,sys.argv[1]); import job_search_helper; '
              'assert job_search_helper.OFFLINE_FIXTURE_ONLY is True')
    return subprocess.run([sys.executable, '-I', '-B', '-c', script, str(package.parent)],
                          text=True, capture_output=True, timeout=3)


def safe_wrapper_origins(tools):
    for rel in WRAPPER_PATHS:
        path = tools / Path(rel).name
        spec = importlib.machinery.PathFinder.find_spec(path.stem, [str(tools)])
        assert spec and spec.origin == str(path), (path, spec)


def service_state(root):
    return json.loads((root / 'services.json').read_bytes())


def effective_dropins(root, name):
    return sorted((root / 'units' / (name + '.d')).glob('*.conf'))


def condition_held(root, name):
    for config in effective_dropins(root, name):
        for line in config.read_text().splitlines():
            if line.startswith('ConditionPathExists=!'):
                condition = Path(line.split('!', 1)[1])
                assert condition.is_relative_to(root), condition
                if condition.exists():
                    return True
    return False


def systemctl(path):
    root, _ = context(path)
    mode, action, *arguments = sys.argv[1:]
    assert mode == '--user'
    status = service_state(root)
    if action == 'show':
        properties = [argument.split('=', 1)[1] for argument in arguments if argument.startswith('--property=')]
        blocks = []
        for name, service in status.items():
            active = service['active']
            values = {'Id': name, 'LoadState': 'loaded', 'ActiveState': 'active' if active else 'inactive',
                      'SubState': 'running' if active else 'dead', 'UnitFileState': service['enabled'],
                      'MainPID': '12345' if active else '0', 'ControlPID': '0',
                      'ControlGroup': '/jsh-s4-combined-disposable-only' if active else '',
                      'FragmentPath': str(root / 'units' / name),
                      'DropInPaths': ' '.join(map(str, effective_dropins(root, name))),
                      'NeedDaemonReload': 'no'}
            blocks.append('\n'.join(f'{key}={values[key]}' for key in properties))
        print('\n\n'.join(blocks))
        return
    if action in {'start', 'stop'}:
        for name in arguments:
            assert name in UNITS
            if action == 'start':
                if condition_held(root, name):
                    sys.exit('fixture unit condition held')
                package = root / 'project/src/job_search_helper'
                marker = root / 'project/.state' / MARKER
                assert not marker.exists(), 'service reopened over nonterminal marker'
                assert not (package / '__init__.so').exists()
                rows, _ = manifest(root / 'capsule')
                representative = root / 'project' / WRAPPER_PATHS[0]
                side = 'after' if matches(representative, rows[WRAPPER_PATHS[0]]['after']) else 'before'
                vector(root, package, side)
                safe_wrapper_origins(root / 'project' / WRAPPER)
                append(root, 'routes.jsonl', {'route': 'stub-service-start', 'side': side})
            status[name]['active'] = action == 'start'
        write(root / 'services.json', encode(status))
        return
    assert action == 'daemon-reload', action


def kill_fixture_ancestor(script):
    """Kill only the exact copied controller/installer already running this fixture."""
    pid = os.getppid()
    target = str(script)
    while pid > 1:
        path = Path('/proc') / str(pid)
        argv = (path / 'cmdline').read_bytes().split(b'\0')
        if target.encode() in argv:
            assert script.name in {'installer.py', 'controller.py'} and script.parent.name == 'capsule'
            assert script.is_relative_to(ROOT)
            assert int((path / 'status').read_text().split('Uid:', 1)[1].split()[0]) == os.getuid()
            os.kill(pid, signal.SIGKILL)
            return
        pid = int((path / 'stat').read_text().rsplit(')', 1)[1].split()[1])
    raise AssertionError('expected fixture process is not an ancestor: ' + target)


def attest(path):
    root, ident = context(path)
    bundle = path.parent
    project = root / 'project'
    canonical = project / 'src/job_search_helper'
    parked = canonical.with_name(PARKED)
    marker = project / '.state' / MARKER
    fence = root / 'direct-admission-closed'
    request = json.load(sys.stdin)
    rows, manifest_digest = manifest(bundle)
    assert not ident['legacy'], 'old tools must refuse the combined manifest before calling the host'
    assert set(request) == {'schema', 'nonce', 'checkpoint', 'project', 'package', 'marker', 'backend', 'target',
                            'maintenance_id', 'locks', 'pycache_prefixes', 'source_manifest_sha256'}
    assert request['schema'] == HOST_SCHEMA and re.fullmatch('[0-9a-f]{32}', request['nonce'])
    assert request['project'] == str(project) and request['maintenance_id'] == ident['hold_id']
    assert request['backend'] == 'sqlite' and request['pycache_prefixes'] == []
    assert request['marker'] == str(marker) and request['source_manifest_sha256'] == manifest_digest
    assert request['locks'] == [str(project / '.integration-install.lock'), *(
        str(project / '.state' / name) for name in ('scraper.lock', 'writer.lock', 'review-writeback.lock'))]
    checkpoint, target = request['checkpoint'], request['target']
    assert target in {'INSTALLED', 'ROLLED_BACK'}
    assert checkpoint in {'preflight', 'pre-publish', 'published', 'admitted'} or checkpoint.startswith('held:')
    package = Path(request['package'])
    parked_phase = checkpoint.startswith('held:') or checkpoint == 'pre-publish'
    assert package == (parked if parked_phase else canonical), request

    if checkpoint == 'preflight':
        if (root / 'disable-direct-fence').exists():
            sys.exit('direct route cannot be durably closed')
        vector(root, canonical, 'before' if target == 'INSTALLED' else 'after')
        write(fence, encode({'root': str(root), 'hold_id': ident['hold_id']}))
    else:
        assert fence.is_file() and marker.is_file()
        assert not any(row['active'] for row in service_state(root).values())
        assert all(condition_held(root, name) for name in UNITS)
    if parked_phase:
        assert 'raise ImportError' in (canonical / '__init__.py').read_text()
    if checkpoint in {'pre-publish', 'published', 'admitted'}:
        vector(root, package, 'after' if target == 'INSTALLED' else 'before', compile_sources=True)
        safe_wrapper_origins(project / WRAPPER)
    if checkpoint in {'published', 'admitted'}:
        fresh_import = stock_worker(canonical)
        if checkpoint == 'published':
            assert fresh_import.returncode and '__init__.so: file too short' in fresh_import.stderr
        else:
            assert fresh_import.returncode == 0, fresh_import.stderr
    count = sum(matches(project / name, rows[name]['after']) for name in WRAPPER_PATHS)
    evidence = {'checkpoint': checkpoint, 'target': target, 'wrapper_after_count': count, 'nonce': request['nonce']}
    configured_fault = root / 'fixture-fault.json'
    fault = json.loads(configured_fault.read_bytes()) if configured_fault.exists() else {}
    if target == 'INSTALLED' and fault.get('action') == 'install':
        stage = fault.get('stage')
        if stage == 'after-one-wrapper' and checkpoint.startswith('held:INSTALLING:') and count == 1:
            append(root, 'attestations.jsonl', {**evidence, 'fault': stage})
            kill_fixture_ancestor(bundle / 'installer.py')
            sys.exit(91)
        if stage == 'after-package-publication' and checkpoint == 'published':
            append(root, 'attestations.jsonl', {**evidence, 'fault': stage})
            kill_fixture_ancestor(bundle / 'controller.py')
            sys.exit(92)
    append(root, 'attestations.jsonl', evidence)
    print(json.dumps({**request, 'verified': True}))


def route_cli(path):
    root, _ = context(path)
    project = root / 'project'
    package = project / 'src/job_search_helper'
    route, side = sys.argv[1:]
    assert route in {'worker', 'direct-wrapper', 'supervised-wrapper'} and side in {'before', 'after'}
    if route == 'worker':
        probe = stock_worker(package)
        if probe.returncode:
            assert 'ImportError' in probe.stderr
            print(probe.stderr, file=sys.stderr)
            sys.exit(23)
    if (root / 'direct-admission-closed').exists() or (project / '.state' / MARKER).exists():
        sys.exit(23)
    if route == 'supervised-wrapper' and not service_state(root)['wrapper-development-host.service']['active']:
        sys.exit(23)
    try:
        vector(root, package, side)
    except AssertionError:
        write(root / 'unexpected-execution', b'route entered with invalid endpoint pair\n')
        raise
    if route != 'worker':
        safe_wrapper_origins(project / WRAPPER)
    append(root, 'routes.jsonl', {'route': route, 'side': side})
    print(f'{route} resolves the matching {side} pair')
