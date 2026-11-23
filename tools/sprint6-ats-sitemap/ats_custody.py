"""Read-only coordinator custody check for the ATS source window."""

from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3


TERMINAL_PILOT = 'WRAP-b1665c4c13'
TASKS = {
    'WRAP-250158dc79': ('PAUSED_BUDGET', '4fe7746444f70cf818f652db04cebee4974f2ff1d97809bb85d5f0cacc59294a', 15),
    TERMINAL_PILOT: ('PAUSED_TEST_FAILURE', '828d29294f31e939891985890c2f6e5095fc88ac8f8dc4d1be8d44a2b9c16f8a', 1),
}


def measure(path, *, require_active=True):
    path = Path(path)
    if path.resolve(strict=True) != path or not path.is_file():
        raise ValueError('Expected the physical production coordinator store.')
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
        db.execute('BEGIN')
        settings = {
            key: json.loads(raw) for key, raw in db.execute('SELECT key, value FROM settings')
            if key in ('queue_enabled', 'campaign_enabled', 'autopilot_enabled', 'pilot_task',
                       'control_generation', 'supervision_status')
        }
        if (settings.get('queue_enabled') is not False or settings.get('campaign_enabled', False) is not False
                or settings.get('autopilot_enabled', False) is not False or settings.get('pilot_task') != TERMINAL_PILOT
                or type(settings.get('control_generation')) is not int):
            raise ValueError('Expected broad controls off and the exact terminal Crown pilot.')
        if require_active:
            health = settings.get('supervision_status') or {}
            if (health.get('schema') != 'coordinator-supervision-v1' or health.get('state') != 'ACTIVE'
                    or health.get('recovery_required') is not False or health.get('error') != ''):
                raise ValueError('Wrapper supervision is not active and settled.')
        if (db.execute("SELECT 1 FROM tasks WHERE json_extract(state,'$.status') IN ('QUEUED','RUNNING','PAUSING') LIMIT 1").fetchone()
                or db.execute("SELECT 1 FROM inference_receipts WHERE status IN ('DISPATCHING','UNCERTAIN') LIMIT 1").fetchone()
                or db.execute("SELECT 1 FROM receipts WHERE result IS NULL LIMIT 1").fetchone()):
            raise ValueError('Active work prevents ATS source maintenance.')
        for task, (status, expected_hash, expected_count) in TASKS.items():
            raw = db.execute('SELECT state FROM tasks WHERE id=?', (task,)).fetchone()
            receipt_count = db.execute(
                "SELECT count(*) FROM inference_receipts WHERE task=? AND status='COMPLETED'", (task,),
            ).fetchone()[0]
            if (raw is None or sha256(raw[0].encode()).hexdigest() != expected_hash
                    or json.loads(raw[0])['status'] != status or receipt_count != expected_count):
                raise ValueError('A protected repair task or its settled receipts changed.')
        schema = db.execute('SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name').fetchall()
        tables = {}
        for kind, name, _, _ in schema:
            if kind != 'table':
                continue
            quoted = '"' + name.replace('"', '""') + '"'
            digest = sha256()
            count = 0
            for row in db.execute(f'SELECT * FROM {quoted} ORDER BY rowid'):
                if name == 'settings' and row[0] in ('supervision_status', 'control_generation'):
                    continue
                digest.update(json.dumps(row, separators=(',', ':'), ensure_ascii=True).encode() + b'\n')
                count += 1
            tables[name] = {'row_count': count, 'rows_sha256': digest.hexdigest()}
        return {
            'control_generation': settings['control_generation'],
            'schema_sha256': sha256(json.dumps(schema, separators=(',', ':')).encode()).hexdigest(),
            'tables': tables,
        }


def compare(before, after, *, shutdowns):
    if shutdowns not in (0, 1, 2) or after['control_generation'] != before['control_generation'] + shutdowns:
        raise ValueError('Wrapper control generation did not follow the audited shutdowns.')
    if after['schema_sha256'] != before['schema_sha256'] or after['tables'] != before['tables']:
        raise ValueError('Protected coordinator state changed during source maintenance.')
