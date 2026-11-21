from hashlib import sha256
from pathlib import Path
from tempfile import mkdtemp
from contextlib import closing
import json
import sqlite3
import os
import shutil
import subprocess

base = Path('/tmp/jsh-s6-retry-status-recheck.fVX7VwTb/actual-queued-company-sckhmo0e')
project = base / 'project'
app = project / '.state'
proof = Path(mkdtemp(prefix='read-surface-', dir=base.parent))
for filename in ('state.db', 'jobs.sqlite3', 'inventories.sqlite3', 'integration-release-journal.json', 'next-scan.json'):
    db = app / filename
    wal = db.with_name(db.name + '-wal')
    assert not wal.exists() or wal.stat().st_size == 0
    shutil.copy2(db, proof / filename)
shutil.copytree(app / 'repair-retry/intents', proof / 'repair-retry/intents')
attempt, = (item.stem for item in (proof / 'repair-retry/intents').glob('*.json'))


def observe(root):
    return {str(item.relative_to(root)): (item.stat().st_ino, item.stat().st_mtime_ns,
            sha256(item.read_bytes()).hexdigest()) for item in root.rglob('*') if item.is_file()}


before = observe(proof)
environment = {**os.environ, 'JOB_STORAGE_BACKEND': 'sqlite', 'JOB_DB_FILE': str(proof / 'jobs.sqlite3'),
               'STATE_DB_FILE': str(proof / 'state.db'), 'SPREADSHEET_ID': 'fixture-sheet', 'PYTHONDONTWRITEBYTECODE': '1'}
execution = subprocess.run([str(project / 'job-search-scraper'), 'company-queue-status', '--attempt-id', attempt],
    cwd=project, env=environment, capture_output=True, text=True, timeout=10, check=True)
assert json.loads(execution.stdout)['status'] == 'HELD_SOURCE'
after = observe(proof)
added = sorted(set(after) - set(before))
changed = sorted(name for name in before if before[name] != after.get(name))
assert not added and not changed, (added, changed)
with closing(sqlite3.connect(proof / 'jobs.sqlite3')) as writer:
    writer.execute('PRAGMA wal_autocheckpoint=0')
    writer.execute('CREATE TABLE recheck_checkpoint_probe (value TEXT)')
    writer.execute('INSERT INTO recheck_checkpoint_probe VALUES (?)', ('disposable pending WAL',))
    writer.commit()
    wal = proof / 'jobs.sqlite3-wal'
    assert wal.stat().st_size > 0
    before_wal = observe(proof)
    wal_execution = subprocess.run(
        [str(project / 'job-search-scraper'), 'company-queue-status', '--attempt-id', attempt],
        cwd=project, env=environment, capture_output=True, text=True, timeout=10, check=True,
    )
    wal_status = json.loads(wal_execution.stdout)['status']
    assert wal_status == 'STATUS_SNAPSHOT_BUSY' and not wal_execution.stderr
    assert observe(proof) == before_wal
    wal_bytes = wal.stat().st_size
with closing(sqlite3.connect(proof / 'state.db')) as writer:
    assert writer.execute('PRAGMA journal_mode=DELETE').fetchone() == ('delete',)
    writer.execute('BEGIN IMMEDIATE')
    writer.execute('CREATE TABLE recheck_rollback_probe (value TEXT)')
    journal = proof / 'state.db-journal'
    assert journal.stat().st_size > 0
    before_journal = observe(proof)
    journal_execution = subprocess.run(
        [str(project / 'job-search-scraper'), 'company-queue-status', '--attempt-id', attempt],
        cwd=project, env=environment, capture_output=True, text=True, timeout=10, check=True,
    )
    journal_status = json.loads(journal_execution.stdout)['status']
    assert journal_status == 'STATUS_SNAPSHOT_BUSY' and not journal_execution.stderr
    assert observe(proof) == before_journal
    journal_bytes = journal.stat().st_size
    writer.rollback()
result = {'status': 'HELD_SOURCE', 'created_paths': added, 'changed_preexisting_paths': changed,
          'all_files_preexisting': not added and not changed, 'wal_real_committed_bytes': wal_bytes,
          'wal_status': wal_status, 'wal_store_paths_inode_mtime_bytes_identical': True,
          'rollback_journal_bytes': journal_bytes, 'rollback_journal_status': journal_status,
          'rollback_store_paths_inode_mtime_bytes_identical': True}
print(json.dumps(result, sort_keys=True))
(proof / 'RESULT.json').write_text(json.dumps(result, sort_keys=True) + '\n')
print(proof)
