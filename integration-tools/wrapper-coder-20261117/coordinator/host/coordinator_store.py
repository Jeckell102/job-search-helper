"""Durable MuleLab task state and write-ahead tool receipts."""
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
import threading


class Store:
    def __init__(self, base):
        self.base = Path(base)
        self.base.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.base / 'tasks.sqlite3'
        self.export_lock = threading.Lock()
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, state TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS receipts(
                    id INTEGER PRIMARY KEY, task TEXT NOT NULL, phase TEXT NOT NULL,
                    name TEXT NOT NULL, arguments TEXT NOT NULL, result TEXT,
                    signature TEXT NOT NULL, created REAL NOT NULL);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.execute('PRAGMA synchronous=FULL')
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, objective, tests, mode, max_sessions=10):
        task_id = 'WRAP-' + uuid.uuid4().hex[:10]
        state = dict(id=task_id, objective=objective, tests=tests, mode=mode,
                     status='QUEUED', phase='baseline', created=time.time(),
                     sessions=0, calls=0, tokens=0, max_sessions=max_sessions,
                     checkpoint={}, manifest={}, stop_requested=False, reason='',
                     no_progress=0, errors=0, phase_start=0)
        with self.connect() as db:
            db.execute('INSERT INTO tasks VALUES (?,?)', (task_id, json.dumps(state)))
        return state

    def get(self, task_id):
        if not isinstance(task_id, str) or not re.fullmatch(r'WRAP-[a-f0-9]{10}', task_id):
            raise ValueError('Use a task ID from /wrapper list.')
        with self.connect() as db:
            row = db.execute('SELECT state FROM tasks WHERE id=?', (task_id,)).fetchone()
        if not row:
            raise ValueError('Task not found.')
        return json.loads(row[0])

    def update(self, task_id, **fields):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT state FROM tasks WHERE id=?', (task_id,)).fetchone()
            if not row:
                raise ValueError('Task not found.')
            state = json.loads(row[0])
            state.update(fields)
            db.execute('UPDATE tasks SET state=? WHERE id=?', (json.dumps(state), task_id))
        return state

    def all(self):
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute('SELECT state FROM tasks ORDER BY rowid')]

    def intent(self, task_id, phase, name, args):
        encoded = json.dumps(args, sort_keys=True)
        signature = hashlib.sha256((name + encoded).encode()).hexdigest()
        with self.connect() as db:
            cursor = db.execute('INSERT INTO receipts(task,phase,name,arguments,signature,created) VALUES (?,?,?,?,?,?)',
                                (task_id, phase, name, encoded, signature, time.time()))
            return cursor.lastrowid

    def finish(self, receipt_id, result):
        with self.connect() as db:
            db.execute('UPDATE receipts SET result=? WHERE id=?', (json.dumps(result), receipt_id))

    def receipts(self, task_id):
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            rows = db.execute('SELECT * FROM receipts WHERE task=? ORDER BY id', (task_id,)).fetchall()
        return [{**dict(row), 'arguments': json.loads(row['arguments']),
                 'result': json.loads(row['result']) if row['result'] else None} for row in rows]

    def recover(self):
        for state in self.all():
            if state['status'] == 'PAUSING':
                self.update(state['id'], status='PAUSED', reason='Pause preserved across service restart.')
            elif state['status'] == 'RUNNING':
                uncertain = any(r['result'] is None for r in self.receipts(state['id']))
                self.update(state['id'], status='PAUSED_RECOVERY' if uncertain else 'QUEUED',
                            reason='Interrupted action needs inspection before resume.' if uncertain else 'Recovered checkpoint.')

    def export(self, task_id):
        with self.export_lock:
            return self._export(task_id)

    def _export(self, task_id):
        state = self.get(task_id)
        folder = self.base / task_id
        folder.mkdir(exist_ok=True, mode=0o700)
        checkpoint = state['checkpoint']
        text = (f"# {task_id}\n\nStatus: {state['status']}\nPhase: {state['phase']}\n\n"
                f"Objective: {state['objective']}\n\nReason: {state['reason']}\n\n"
                f"Worker summary (model-authored, verify against receipts):\n{checkpoint.get('summary', '')}\n\n"
                f"Next action: {checkpoint.get('next_action', 'Continue the next incomplete phase.')}\n\n"
                f"Resume in Wrapper Coder:\n\n`/wrapper resume {task_id}`\n\n"
                f"Inspect progress:\n\n`/wrapper status {task_id}`\n\n"
                "Live scraper validation, installation and GitHub delivery of generated wrappers require operator review.\n")
        for name, payload in [('checkpoint.json', json.dumps(state, indent=2)),
                              ('receipts.json', json.dumps(self.receipts(task_id), indent=2)),
                              ('HANDOFF.md', text)]:
            temporary = folder / (name + '.new')
            temporary.write_text(payload)
            temporary.replace(folder / name)
        return text
