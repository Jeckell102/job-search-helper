"""Measure protected coordinator rows and the separately audited shutdown generation."""

import json
import sqlite3
from contextlib import closing
from hashlib import sha256
from pathlib import Path


CONTINUATION_TABLE = 'embraer_03_continuations'


def measure(path):
    """Hash existing logical rows and account for the allowed empty new table."""
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError('Coordinator database is unavailable on the expected route.')
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
        db.execute('BEGIN')
        schema = db.execute(
            'SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name').fetchall()
        original = [row for row in schema if row[2] != CONTINUATION_TABLE]
        summary = {}
        supervisor = None
        generation = None
        for kind, name, _, _ in original:
            if kind != 'table':
                continue
            quoted = '"' + name.replace('"', '""') + '"'
            digest = sha256()
            count = 0
            for row in db.execute(f'SELECT * FROM {quoted} ORDER BY rowid'):
                if name == 'settings' and row[0] == 'supervision_status':
                    supervisor = json.loads(row[1])
                    continue
                if name == 'settings' and row[0] == 'control_generation':
                    generation = json.loads(row[1])
                    if type(generation) is not int or generation < 0 or row[1] != json.dumps(generation):
                        raise ValueError('Expected the canonical integer control generation.')
                    continue
                # Preserve raw stored text including its exact JSON spelling.
                blob = json.dumps(row, separators=(',', ':'), ensure_ascii=True).encode()
                digest.update(blob + b'\n')
                count += 1
            summary[name] = {'row_count': count, 'rows_sha256': digest.hexdigest()}
        has_continuation = any(kind == 'table' and name == CONTINUATION_TABLE for kind, name, _, _ in schema)
        if has_continuation and db.execute(f'SELECT 1 FROM {CONTINUATION_TABLE} LIMIT 1').fetchone():
            raise ValueError('Source-only maintenance cannot create a continuation owner.')
        if (not isinstance(supervisor, dict) or supervisor.get('schema') != 'coordinator-supervision-v1'
                or supervisor.get('state') != 'ACTIVE' or supervisor.get('recovery_required') is not False
                or supervisor.get('error') != ''):
            raise ValueError('Current wrapper supervision must be active without a recovery hold.')
        if generation is None:
            raise ValueError('The persisted control generation is missing.')
        return {
            'control_generation': generation,
            'existing_schema_sha256': sha256(json.dumps(original, separators=(',', ':')).encode()).hexdigest(),
            'existing_tables': summary,
            'continuation_table_exists_and_empty': has_continuation,
            'supervision_active_without_recovery': True,
        }
