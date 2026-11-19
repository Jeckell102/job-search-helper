"""Minimal Jetson-side control receipts for a single MuleLab inference turn.

This store deliberately retains no prompt, source file, job inventory, model
content, or tool call.  It exists only so a lost transport can be settled as
completed-without-delivery, cancelled, or still-running without issuing the
same model request twice.
"""
import json
from pathlib import Path
import re
import sqlite3
import time
import uuid


_ID = re.compile(r'[0-9a-f]{32}')
_DIGEST = re.compile(r'[0-9a-f]{64}')
_DONE_REASONS = {'stop', 'length', 'tool_calls', 'cancelled', 'error'}
_ACTIVE = ('RUNNING', 'UNCERTAIN')


class InferenceControlStore:
    def __init__(self, path, *, now=time.time):
        self.path = Path(path)
        self.now = now
        self.instance_id = uuid.uuid4().hex
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self._connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS wrapper_inference_control (
                request_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
                owner_generation TEXT NOT NULL, status TEXT NOT NULL,
                created REAL NOT NULL, updated REAL NOT NULL,
                response_digest TEXT, usage TEXT, cancel_requested INTEGER NOT NULL DEFAULT 0,
                handler_instance TEXT)''')
            columns = {row[1] for row in db.execute('PRAGMA table_info(wrapper_inference_control)')}
            if 'handler_instance' not in columns:
                db.execute('ALTER TABLE wrapper_inference_control ADD COLUMN handler_instance TEXT')
            # A prior service instance cannot prove that its in-flight backend
            # work stopped.  Keep that lane closed until reconciliation does.
            db.execute("UPDATE wrapper_inference_control SET status='UNCERTAIN',updated=?,handler_instance=NULL "
                       "WHERE status='RUNNING' AND (handler_instance IS NULL OR handler_instance!=?)",
                       (self.now(), self.instance_id))

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA synchronous=FULL')
        return db

    @staticmethod
    def _validate(request_id, fingerprint, owner_generation):
        if not isinstance(request_id, str) or not _ID.fullmatch(request_id):
            raise ValueError('Invalid inference request ID.')
        if not isinstance(fingerprint, str) or not _DIGEST.fullmatch(fingerprint):
            raise ValueError('Invalid inference request fingerprint.')
        if not isinstance(owner_generation, str) or not _DIGEST.fullmatch(owner_generation):
            raise ValueError('Invalid inference owner generation.')

    def begin(self, request_id, fingerprint, owner_generation):
        """Atomically reserve one request; duplicates never trigger inference."""
        self._validate(request_id, fingerprint, owner_generation)
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT fingerprint,owner_generation,status FROM wrapper_inference_control WHERE request_id=?',
                             (request_id,)).fetchone()
            if row:
                if row[:2] != (fingerprint, owner_generation):
                    raise ValueError('Inference request ID conflicts with prior control record.')
                return {'start': False, **self.status(request_id, _db=db)}
            active = db.execute("SELECT request_id FROM wrapper_inference_control WHERE status IN ('RUNNING','UNCERTAIN') LIMIT 1").fetchone()
            if active:
                return {'start': False, 'request_id': request_id, 'status': 'BUSY'}
            now = self.now()
            db.execute('INSERT INTO wrapper_inference_control(request_id,fingerprint,owner_generation,status,created,updated,handler_instance) '
                       'VALUES (?,?,?,?,?,?,?)', (request_id, fingerprint, owner_generation, 'RUNNING', now, now, self.instance_id))
        return {'start': True, **self.status(request_id)}

    def lane_blocked(self):
        """Whether a retained wrapper turn makes another Jetson turn unsafe."""
        with self._connect() as db:
            return bool(db.execute("SELECT 1 FROM wrapper_inference_control "
                                   "WHERE status IN ('RUNNING','UNCERTAIN') LIMIT 1").fetchone())

    def status(self, request_id, *, _db=None):
        if not isinstance(request_id, str) or not _ID.fullmatch(request_id):
            raise ValueError('Invalid inference request ID.')
        if _db is None:
            with self._connect() as db:
                return self.status(request_id, _db=db)
        row = _db.execute('SELECT request_id,fingerprint,owner_generation,status,created,updated,response_digest,usage,cancel_requested '
                          'FROM wrapper_inference_control WHERE request_id=?', (request_id,)).fetchone()
        if not row:
            return None
        usage = json.loads(row[7]) if row[7] else None
        return {'request_id': row[0], 'fingerprint': row[1], 'owner_generation': row[2],
                'status': row[3], 'created': row[4], 'updated': row[5],
                'response_digest': row[6], 'usage': usage, 'cancel_requested': bool(row[8])}

    def owned_status(self, request_id, fingerprint, owner_generation):
        """Return only non-secret receipt facts to the request owner."""
        self._validate(request_id, fingerprint, owner_generation)
        current = self.status(request_id)
        if current is None:
            return None
        if (current['fingerprint'], current['owner_generation']) != (fingerprint, owner_generation):
            raise ValueError('Inference control does not own this request.')
        return {key: current[key] for key in ('request_id', 'status', 'created', 'updated',
                                               'response_digest', 'usage', 'cancel_requested')}

    def cancel(self, request_id, fingerprint, owner_generation):
        """Request cancellation; a terminal acknowledgement is separately visible."""
        self._validate(request_id, fingerprint, owner_generation)
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            current = self.status(request_id, _db=db)
            if current is None:
                return None
            if (current['fingerprint'], current['owner_generation']) != (fingerprint, owner_generation):
                raise ValueError('Inference cancellation does not own this request.')
            if current['status'] in _ACTIVE:
                db.execute('UPDATE wrapper_inference_control SET cancel_requested=1,updated=? WHERE request_id=?',
                           (self.now(), request_id))
                current = self.status(request_id, _db=db)
            return current

    def cancellation_requested(self, request_id):
        current = self.status(request_id)
        return bool(current and current['status'] in _ACTIVE and current['cancel_requested'])

    def uncertain(self, request_id):
        """Record an ambiguous transport loss without releasing the GPU lane."""
        if not isinstance(request_id, str) or not _ID.fullmatch(request_id):
            raise ValueError('Invalid inference request ID.')
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            current = self.status(request_id, _db=db)
            if current is None:
                raise ValueError('Unknown inference request.')
            if current['status'] != 'RUNNING':
                return current
            db.execute("UPDATE wrapper_inference_control SET status='UNCERTAIN',updated=?,handler_instance=NULL WHERE request_id=?",
                       (self.now(), request_id))
            return self.status(request_id, _db=db)

    def reconcile_orphan(self, request_id, fingerprint, owner_generation, *, execution_inactive):
        """Settle an orphan only after an independent backend-inactivity check.

        This never replays work or treats a cancellation request as an
        acknowledgement.  Callers must provide a positive, current proof that
        the backend is no longer executing this lane.
        """
        self._validate(request_id, fingerprint, owner_generation)
        if execution_inactive is not True:
            return self.owned_status(request_id, fingerprint, owner_generation)
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            current = self.status(request_id, _db=db)
            if current is None:
                return None
            if (current['fingerprint'], current['owner_generation']) != (fingerprint, owner_generation):
                raise ValueError('Inference reconciliation does not own this request.')
            if current['status'] == 'UNCERTAIN':
                status = 'CANCELLED' if current['cancel_requested'] else 'FAILED'
                db.execute('UPDATE wrapper_inference_control SET status=?,updated=? WHERE request_id=?',
                           (status, self.now(), request_id))
            settled = self.status(request_id, _db=db)
            return {key: settled[key] for key in ('request_id', 'status', 'created', 'updated',
                                                   'response_digest', 'usage', 'cancel_requested')}

    def finish(self, request_id, *, response_digest=None, usage=None, cancelled=False):
        if not isinstance(request_id, str) or not _ID.fullmatch(request_id):
            raise ValueError('Invalid inference request ID.')
        if response_digest is not None and (not isinstance(response_digest, str) or not _DIGEST.fullmatch(response_digest)):
            raise ValueError('Invalid inference response digest.')
        if usage is not None:
            if not isinstance(usage, dict) or set(usage) != {'prompt_eval_count', 'eval_count', 'done_reason'}:
                raise ValueError('Invalid inference usage receipt.')
            counts = (usage['prompt_eval_count'], usage['eval_count'])
            if (any(type(value) is not int or not 0 <= value <= 10000000 for value in counts)
                    or usage['done_reason'] not in _DONE_REASONS):
                raise ValueError('Invalid inference usage receipt.')
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            current = self.status(request_id, _db=db)
            if current is None:
                raise ValueError('Unknown inference request.')
            if current['status'] != 'RUNNING':
                return current
            status = 'CANCELLED' if cancelled or current['cancel_requested'] else 'COMPLETED'
            db.execute('UPDATE wrapper_inference_control SET status=?,updated=?,response_digest=?,usage=? WHERE request_id=?',
                       (status, self.now(), response_digest, json.dumps(usage, sort_keys=True) if usage is not None else None,
                        request_id))
            return self.status(request_id, _db=db)
