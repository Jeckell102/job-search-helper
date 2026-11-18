"""Backed-up, idle-only host deployment for the reviewed November 18 workflow."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import time

stage = Path(__file__).resolve().parent
project = Path('/home/chris/job-search-helper_old')
base = project / 'dev/wrapper-coder'
archive = base / 'repairs' / time.strftime('persistent-workflow-%Y%m%d-%H%M%S')
tools = base / 'tools'


def idle():
    with sqlite3.connect('file:' + str(base/'tasks/tasks.sqlite3') + '?mode=ro', uri=True) as db:
        active = [json.loads(r[0])['id'] for r in db.execute('SELECT state FROM tasks')
                  if json.loads(r[0])['status'] in ('RUNNING', 'QUEUED', 'PAUSING')]
    if active:
        raise RuntimeError('Active tasks prevent upgrade: ' + ', '.join(active))


idle()
archive.mkdir(parents=True, mode=0o700)
changed = [p for p in (stage/'host').glob('*.py') if not (tools/p.name).exists() or p.read_bytes() != (tools/p.name).read_bytes()]
for area in ('before', 'after'):
    (archive/area).mkdir()
for p in changed:
    if (tools/p.name).exists():
        shutil.copy2(tools/p.name, archive/'before'/p.name)
    shutil.copy2(p, archive/'after'/p.name)
shutil.copy2(stage/'WORKFLOW.md', archive/'WORKFLOW.md')
subprocess.run(['systemctl', '--user', 'stop', 'wrapper-development-host.service'], check=True)
try:
    idle()
    with sqlite3.connect(base/'tasks/tasks.sqlite3') as db, sqlite3.connect(archive/'tasks-before.sqlite3') as out:
        db.backup(out)
        assert out.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
    snapshot = base/'queue-base'
    if snapshot.exists():
        raise RuntimeError('queue-base already exists; refusing to replace a workflow baseline.')
    snapshot.mkdir()
    hashes = {}
    for area in ('src', 'tests', 'docs'):
        for src in (project/area).rglob('*'):
            if not src.is_file() or src.suffix not in {'.py','.md','.txt','.json','.html','.xml','.toml','.csv'}:
                continue
            if any(p.is_symlink() for p in (src, *src.parents)) or src.stat().st_nlink != 1 or src.stat().st_size > 2000000:
                raise RuntimeError('Unsafe source baseline: ' + str(src))
            rel = src.relative_to(project)
            dst = snapshot/rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            content = src.read_bytes(); dst.write_bytes(content)
            hashes[str(rel)] = hashlib.sha256(content).hexdigest()
    shutil.copy2(project/'pyproject.toml', snapshot/'pyproject.toml')
    shutil.copy2(base/'repo/docs/wrapper-development-test-protocol.md', snapshot/'docs/wrapper-development-test-protocol.md')
    shutil.copytree(stage/'backlog/docs/backlog', snapshot/'docs/backlog')
    shutil.copytree(stage/'backlog', base/'backlog-20261118')
    (archive/'baseline-source-hashes.json').write_text(json.dumps(hashes, indent=2))
    for p in changed:
        temp = tools/(p.name+'.new')
        temp.write_bytes(p.read_bytes()); os.chmod(temp, 0o600)
        temp.replace(tools/p.name)
        assert (tools/p.name).read_bytes() == p.read_bytes()
    # Disable scheduling until the real isolated acceptance and queue import pass.
    with sqlite3.connect(base/'tasks/tasks.sqlite3') as db:
        db.execute('CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
        db.execute("INSERT INTO settings VALUES ('queue_enabled','false') ON CONFLICT(key) DO UPDATE SET value=excluded.value")
    shutil.copy2(stage/'WORKFLOW.md', base/'PERSISTENT_WORKFLOW.md')
    (archive/'deployment.json').write_text(json.dumps({'installed': [p.name for p in changed], 'queue_enabled': False}, indent=2))
finally:
    subprocess.run(['systemctl', '--user', 'start', 'wrapper-development-host.service'], check=True)
print(json.dumps({'archive': str(archive), 'installed': len(changed), 'queue': 'paused'}))
