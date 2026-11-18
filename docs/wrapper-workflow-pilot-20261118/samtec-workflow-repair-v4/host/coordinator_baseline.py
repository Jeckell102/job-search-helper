"""Canonical source-only assignment inputs, including consumed root configuration."""
import hashlib
import json
from pathlib import Path
import coding_tools as code

ROOT_INPUTS = ('pyproject.toml', 'title-blacklist.txt', 'title-review-list.txt')

def files(root):
    root = Path(root)
    result = {}
    paths = []
    for area in ('src', 'tests', 'docs'):
        base = root / area
        if base.is_symlink():
            raise ValueError('Unsafe baseline directory: ' + area)
        for path in base.rglob('*'):
            if any(part in ('__pycache__', '.pytest_cache', '.git', '.mypy_cache', '.ruff_cache') for part in path.relative_to(base).parts):
                continue
            if path.is_symlink():
                raise ValueError('Unsafe baseline symlink: ' + str(path))
            if path.is_file():
                paths.append(path)
    paths.extend(root / name for name in ROOT_INPUTS if (root / name).exists() or (root / name).is_symlink())
    for path in sorted(paths):
        name = path.relative_to(root).as_posix()
        if (not path.is_file() or any(p.is_symlink() for p in (path, *path.parents))
                or path.stat().st_nlink != 1 or path.stat().st_size > 2000000):
            raise ValueError('Unsafe or oversized baseline input: ' + name)
        result[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result

def binding(manifest):
    return {'version': 1, 'manifest': dict(manifest), 'digest': hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()).hexdigest()}

def verify(state, root):
    saved = state.get('assignment_baseline')
    if not isinstance(saved, dict) or saved != binding(saved.get('manifest', {})):
        raise ValueError('Assignment baseline is missing or invalid; reviewed migration required.')
    if files(root) != saved['manifest']:
        raise ValueError('Assignment baseline drift; ordinary resume cannot approve changed inputs.')
    return saved['manifest']


def verify_initial(store, state):
    """First activation may only use its reviewed assignment source."""
    if state.get('manifest'):
        return
    if state.get('isolated_workspace'):
        from coordinator_workspace import batch_source
        target = store.base / state['id'] / 'repo'
        verify(state, target if target.exists() else batch_source())
    else:
        verify(state, code.root())
