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
                CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS batches(digest TEXT PRIMARY KEY, task_ids TEXT NOT NULL);
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

    def create(self, objective, tests, mode, max_sessions=10, *, authorization_version=0, evidence_requirements=None, workflow_version=1):
        state = self.new_state(objective, tests, mode, max_sessions, authorization_version, evidence_requirements, workflow_version)
        with self.connect() as db:
            db.execute('INSERT INTO tasks VALUES (?,?)', (state['id'], json.dumps(state)))
        return state

    def new_state(self, objective, tests, mode, max_sessions, authorization_version, evidence_requirements, workflow_version):
        task_id = 'WRAP-' + uuid.uuid4().hex[:10]
        state = dict(id=task_id, objective=objective, tests=tests, mode=mode,
                     status='QUEUED', phase='baseline', created=time.time(),
                     time_budget_policy='wall_time_from_creation_including_queue_and_pause',
                     sessions=0, calls=0, tokens=0, max_sessions=max_sessions,
                     checkpoint={}, manifest={}, stop_requested=False, reason='',
                     no_progress=0, errors=0, phase_start=0,
                     authorization_version=authorization_version, evidence_requirements=evidence_requirements or {},
                     workflow_version=workflow_version, workflow={})
        if workflow_version == 2:
            state.update(activated_at=None, time_budget_policy='one_hour_from_first_assignment_including_pauses')
        return state

    def enqueue_batch(self, digest, specs):
        """Atomic and idempotent: a retried submission never duplicates work."""
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT task_ids FROM batches WHERE digest=?', (digest,)).fetchone()
            if existing:
                return json.loads(existing[0]), True
            states = [self.new_state(**spec) for spec in specs]
            for state in states:
                state['isolated_workspace'] = True
                db.execute('INSERT INTO tasks VALUES (?,?)', (state['id'], json.dumps(state)))
            ids = [s['id'] for s in states]
            db.execute('INSERT INTO batches VALUES (?,?)', (digest, json.dumps(ids)))
            return ids, False

    def queue_enabled(self):
        with self.connect() as db:
            value = db.execute("SELECT value FROM settings WHERE key='queue_enabled'").fetchone()
        return value is None or value[0] == 'true'

    def set_queue_enabled(self, enabled):
        with self.connect() as db:
            db.execute("INSERT INTO settings VALUES ('queue_enabled',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(enabled),))

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
            uncertain = (state['status'] in ('RUNNING', 'PAUSING', 'QUEUED') and
                         any(r['result'] is None for r in self.receipts(state['id'])))
            if uncertain:
                self.update(state['id'], status='PAUSED_RECOVERY',
                            reason='Interrupted action needs inspection before resume; no action was replayed.')
            elif state['status'] == 'PAUSING':
                self.update(state['id'], status='PAUSED', reason='Pause preserved across service restart.')
            elif state['status'] == 'RUNNING':
                self.update(state['id'], status='QUEUED', reason='Recovered checkpoint.')

    def export(self, task_id):
        with self.export_lock:
            return self._export(task_id)

    def _export(self, task_id):
        state = self.get(task_id)
        folder = self.base / task_id
        folder.mkdir(exist_ok=True, mode=0o700)
        checkpoint = state['checkpoint']
        text = (f"# {task_id}\n\nStatus: {state['status']}\nPhase: {state['phase']}\n\n"
                f"Objective: {state['objective']}\n\nReason: {state['reason']}\n\n" +
                ('Budgets: One hour from first assignment, including pauses; initial queue wait is excluded. ' if state.get('workflow_version') == 2 else 'Budgets: One-hour lifetime from creation, including queued and paused time. ') +
                'Resume does not reset time, calls, sessions or tokens. Already-started actions may finish; the next action is checked before dispatch.\n\n' +
                f"Worker summary (model-authored, verify against receipts):\n{checkpoint.get('summary', '')}\n\n"
                f"Next action: {checkpoint.get('next_action', 'Continue the next incomplete phase.')}\n\n"
                f"Python work plan: {json.dumps(state.get('workflow', {}).get('plan', {}))}\n\n"
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
