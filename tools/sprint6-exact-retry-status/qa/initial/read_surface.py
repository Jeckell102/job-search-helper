from hashlib import sha256
from pathlib import Path
from tempfile import mkdtemp
import json
import os
import shutil
import subprocess

base = Path('/tmp/jsh-s6-retry-status-independent.IjAUKZdD/actual-queued-company-_qzqbgq_')
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
result = {'status': 'HELD_SOURCE', 'created_paths': added, 'changed_preexisting_paths': changed,
          'all_files_preexisting': not added and not changed}
print(json.dumps(result, sort_keys=True))
(proof / 'RESULT.json').write_text(json.dumps(result, sort_keys=True) + '\n')
print(proof)
