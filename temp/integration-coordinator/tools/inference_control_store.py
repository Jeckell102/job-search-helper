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


_ID = re.compile(r'[0-9a-f]{32}')
_DIGEST = re.compile(r'[0-9a-f]{64}')
_DONE_REASON = re.compile(r'[a-z0-9_.-]{1,64}')


class InferenceControlStore:
    def __init__(self, path, *, now=time.time):
        self.path = Path(path)
        self.now = now
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self._connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS wrapper_inference_control (
                request_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
                owner_generation TEXT NOT NULL, status TEXT NOT NULL,
                created REAL NOT NULL, updated REAL NOT NULL,
                response_digest TEXT, usage TEXT, cancel_requested INTEGER NOT NULL DEFAULT 0)''')

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
            active = db.execute("SELECT request_id FROM wrapper_inference_control WHERE status='RUNNING' LIMIT 1").fetchone()
            if active:
                return {'start': False, 'request_id': request_id, 'status': 'BUSY'}
            now = self.now()
            db.execute('INSERT INTO wrapper_inference_control(request_id,fingerprint,owner_generation,status,created,updated) '
                       'VALUES (?,?,?,?,?,?)', (request_id, fingerprint, owner_generation, 'RUNNING', now, now))
        return {'start': True, **self.status(request_id)}

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
            if current['status'] == 'RUNNING':
                db.execute('UPDATE wrapper_inference_control SET cancel_requested=1,updated=? WHERE request_id=?',
                           (self.now(), request_id))
                current = self.status(request_id, _db=db)
            return current

    def cancellation_requested(self, request_id):
        current = self.status(request_id)
        return bool(current and current['status'] == 'RUNNING' and current['cancel_requested'])

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
                    or not isinstance(usage['done_reason'], str)
                    or not _DONE_REASON.fullmatch(usage['done_reason'])):
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
