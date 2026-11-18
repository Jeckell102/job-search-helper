"""Isolated, source-only company workspaces; all paths stay on MuleLab."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import tempfile

import coding_tools as code


def batch_source():
    source = code.BASE / 'queue-base'
    return source if source.is_dir() else code.ROOT


@contextmanager
def workspace(store, state, create=False):
    if not state.get('isolated_workspace'):
        yield
        return
    folder = store.base / state['id']
    target = folder / 'repo'
    if not target.exists() and create:
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Build and baseline entirely before the atomic rename. A crash here
        # cannot publish half a workspace or replay a model edit.
        with tempfile.TemporaryDirectory(prefix='prepare-', dir=folder) as tmp:
            staging = Path(tmp) / 'repo'
            staging.mkdir()
            hashes = {}
            source = batch_source()
            for area in ('src', 'tests', 'docs'):
                for path in (source / area).rglob('*'):
                    if path.suffix not in code.EXTENSIONS or not path.is_file():
                        continue
                    name = path.relative_to(source).as_posix()
                    if any(p.is_symlink() for p in (path, *path.parents)) or path.stat().st_nlink != 1 or path.stat().st_size > 2000000:
                        raise ValueError('Unsafe or oversized baseline file: ' + name)
                    content = path.read_bytes()
                    dest = staging / name
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(content)
                    hashes[name] = hashlib.sha256(content).hexdigest()
            config = source / 'pyproject.toml'
            if config.exists():
                if config.is_symlink() or config.stat().st_size > 256000:
                    raise ValueError('Unsafe test configuration.')
                (staging / config.name).write_bytes(config.read_bytes())
            token = code.WORKSPACE.set(staging)
            try:
                code.git('init', '--quiet')
                code.git('add', '--', 'src', 'tests', 'docs')
                code.git('commit', '--quiet', '-m', 'Company development baseline')
            finally:
                code.WORKSPACE.reset(token)
            (staging / 'baseline-manifest.json').write_text(json.dumps(hashes, sort_keys=True))
            staging.rename(target)
    if not target.is_dir() or target.is_symlink():
        raise ValueError('Company workspace is missing; inspect its saved task before resuming.')
    token = code.WORKSPACE.set(target)
    try:
        yield
    finally:
        code.WORKSPACE.reset(token)
