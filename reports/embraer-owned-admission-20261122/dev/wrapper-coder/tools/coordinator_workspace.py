"""Isolated, source-only company workspaces; all paths stay on MuleLab."""
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json
from pathlib import Path
import tempfile

import coding_tools as code

BATCH_SOURCE_OVERRIDE = ContextVar('wrapper_batch_source_override', default=None)


def batch_source():
    selected = BATCH_SOURCE_OVERRIDE.get()
    if selected is not None:
        return selected
    # Unit/acceptance fixtures replace ROOT with a private repository. Respect
    # that explicit source before consulting the installed campaign snapshot.
    default_root = code.BASE / 'repo'
    if code.ROOT != default_root:
        return code.ROOT
    source = code.BASE / 'queue-base'
    return source if source.is_dir() else code.ROOT


@contextmanager
def workspace(store, state, create=False):
    if not state.get('isolated_workspace'):
        if not state.get('manifest'):
            from coordinator_baseline import verify
            verify(state, code.root())
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
            from coordinator_baseline import verify, files
            source = batch_source()
            hashes = verify(state, source)
            for name in hashes:
                dest = staging / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes((source / name).read_bytes())
            verify(state, source)
            if files(staging) != hashes:
                raise ValueError('Assignment baseline changed while copying workspace.')
            token = code.WORKSPACE.set(staging)
            try:
                code.git('init', '--quiet')
                code.git('add', '--', *sorted(hashes))
                code.git('commit', '--quiet', '-m', 'Company development baseline')
            finally:
                code.WORKSPACE.reset(token)
            (staging / 'baseline-manifest.json').write_text(json.dumps(hashes, sort_keys=True))
            verify(state, source)
            if files(staging) != hashes:
                raise ValueError('Staged assignment baseline changed before publication.')
            staging.rename(target)
    if not target.is_dir() or target.is_symlink():
        raise ValueError('Company workspace is missing; inspect its saved task before resuming.')
    if not state.get('manifest'):
        from coordinator_baseline import verify
        verify(state, target)
    token = code.WORKSPACE.set(target)
    try:
        yield
    finally:
        code.WORKSPACE.reset(token)
