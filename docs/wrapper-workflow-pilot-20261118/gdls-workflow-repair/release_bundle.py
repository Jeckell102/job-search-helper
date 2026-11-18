"""Hash-verified source/prerequisite assembly; never changes an installed release."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat

PREREQUISITE_DIRS = ('coordinator_vendor', 'resources')
PREREQUISITE_FILES = ('wrapper-development-host.service', 'wrapper-development-tunnel.service')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def metadata(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1:
        raise ValueError('Expected ordinary single-link file: ' + str(path))
    for parent in path.parents:
        if parent.is_symlink():
            raise ValueError('Symlinked parent: ' + str(parent))
    raw = path.read_bytes()
    return {'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw),
            'mode': stat.S_IMODE(path.stat().st_mode)}


def tree(root):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('Expected ordinary directory: ' + str(root))
    result = {}
    for path in sorted(root.rglob('*')):
        relative = path.relative_to(root)
        if '__pycache__' in relative.parts or path.suffix == '.pyc':
            continue
        if path.is_symlink():
            raise ValueError('Symlink in release tree: ' + str(path))
        if path.is_file():
            result[relative.as_posix()] = metadata(path)
    return result


def source_manifest(stage):
    stage = Path(stage)
    paths = list((stage / 'host').glob('*.py')) + list((stage / 'jetson').glob('*.py'))
    paths += list((stage / 'backlog').glob('batch-*.json'))
    paths += [stage / name for name in ('WORKFLOW.md', 'deploy_campaign_update.py', 'release_bundle.py', 'rollout_controller.py')]
    required = ('host/coordinator.py', 'host/coordinator_store.py', 'host/coordinator_workspace.py',
                'host/coordinator_budget.py', 'jetson/wrapper_commands.py')
    manifest = {p.relative_to(stage).as_posix(): metadata(p) for p in sorted(paths)}
    if any(name not in manifest for name in required):
        raise ValueError('Missing required release source')
    return manifest


def prerequisite_manifest(tools):
    tools = Path(tools)
    result = {}
    for name in PREREQUISITE_DIRS:
        entries = tree(tools / name)
        if not entries:
            raise ValueError('Empty runtime prerequisite: ' + name)
        result.update({name + '/' + key: value for key, value in entries.items()})
    for name in PREREQUISITE_FILES:
        result[name] = metadata(tools / name)
    return result


def checked_copy(source, target, expected):
    if metadata(source) != expected:
        raise ValueError('Source changed before copy: ' + str(source))
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    if metadata(target) != expected or metadata(source) != expected:
        raise ValueError('Source changed during copy: ' + str(source))


def destination(name):
    if name.startswith('host/'):
        return 'tools/' + name.removeprefix('host/')
    if name.startswith('jetson/'):
        return name
    return 'inputs/' + name


def expected_release(sources, prerequisites):
    result = {destination(k): v for k, v in sources.items()}
    result.update({'tools/' + k: v for k, v in prerequisites.items()})
    return result


def verify_release(root, sources, prerequisites):
    expected = expected_release(sources, prerequisites)
    actual = tree(root)
    if actual != expected:
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        changed = sorted(k for k in set(expected) & set(actual) if expected[k] != actual[k])
        raise ValueError(f'Release mismatch: missing={missing[:8]} extra={extra[:8]} changed={changed[:8]}')
    return digest(expected)


def build_release(stage, installed_tools, target, sources, prerequisites):
    """Only a new disposable directory is written. Pin sets must be reviewed first."""
    stage, installed_tools, target = map(Path, (stage, installed_tools, target))
    if source_manifest(stage) != sources or prerequisite_manifest(installed_tools) != prerequisites:
        raise ValueError('Reviewed release inputs changed')
    if target.exists() or target.is_symlink():
        raise ValueError('Release destination already exists')
    target.mkdir(mode=0o700)
    for name, expected in sources.items():
        checked_copy(stage / name, target / destination(name), expected)
    for name, expected in prerequisites.items():
        checked_copy(installed_tools / name, target / 'tools' / name, expected)
    if source_manifest(stage) != sources or prerequisite_manifest(installed_tools) != prerequisites:
        raise ValueError('Reviewed release inputs changed during assembly')
    result = verify_release(target, sources, prerequisites)
    for path in target.rglob('*'):
        if path.is_file():
            with path.open('rb') as stream:
                os.fsync(stream.fileno())
    for path in [*sorted((p for p in target.rglob('*') if p.is_dir()), reverse=True), target]:
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    return result
