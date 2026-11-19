"""Durable fetch results, independent of Sheets and cycle checkpoints.

Each producer commits the complete inventory before handing off its worker.
The sync consumer deletes it only after the company's Sheets writes AND local
checkpoint are acknowledged. Failed companies retain their evidence for retry.
"""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from threading import RLock
import time

from .title_audit import TITLE_AUDIT_SCHEMA, remember_title_audit
from .browser_progress import SCHEMA as BROWSER_PROGRESS_SCHEMA
from . import publication_receipts


class InventoryInbox:
    @staticmethod
    def destination_id(path):
        """Read the durable inbox destination without opening a writer."""
        location = Path(path)
        if not location.is_file():
            raise ValueError('Saved-inventory database is missing.')
        uri = location.resolve().as_uri() + '?mode=ro'
        with sqlite3.connect(uri, uri=True) as connection:
            rows = connection.execute('SELECT id FROM destination').fetchall()
        if len(rows) != 1 or not str(rows[0][0]).strip():
            raise ValueError('Saved-inventory destination is missing or ambiguous.')
        return str(rows[0][0]).strip()

    @staticmethod
    def has_unblocked_inventory(path, cycle):
        """Read exact-cycle eligibility without opening a SQLite writer."""
        location = Path(path)
        if not location.is_file():
            raise ValueError('Saved-inventory database is missing.')
        uri = location.resolve().as_uri() + '?mode=ro'
        with sqlite3.connect(uri, uri=True) as connection:
            return bool(connection.execute(
                'SELECT 1 FROM inventories WHERE cycle=? AND blocked=0 LIMIT 1', (cycle,)
            ).fetchone())

    def __init__(self, path, spreadsheet_id):
        self.path = str(path)
        if self.path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.connection = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        self.lock = RLock()
        self.checkpoint_seconds = 0.0
        self.payload_bytes = 0
        self.saved = 0
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        try:
            with self.connection:
                self.connection.execute("CREATE TABLE IF NOT EXISTS destination (id TEXT NOT NULL)")
                row = self.connection.execute("SELECT id FROM destination").fetchone()
                if row and row[0] != spreadsheet_id:
                    raise ValueError("Inventory inbox belongs to a different spreadsheet; keep its original destination.")
                if not row:
                    self.connection.execute("INSERT INTO destination VALUES (?)", (spreadsheet_id,))
                self.connection.execute("""CREATE TABLE IF NOT EXISTS inventories (
                    cycle TEXT, company TEXT, payload TEXT NOT NULL, blocked INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(cycle, company))""")
                self.connection.execute(TITLE_AUDIT_SCHEMA)
                self.connection.execute(BROWSER_PROGRESS_SCHEMA)
                self.connection.execute("""CREATE TABLE IF NOT EXISTS sync_plans (
                    cycle TEXT, company TEXT, payload TEXT NOT NULL, cursor INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(cycle, company))""")
                self.connection.execute("""CREATE TABLE IF NOT EXISTS exact_sync_chunks (
                    cycle TEXT NOT NULL, company TEXT NOT NULL, cursor INTEGER NOT NULL,
                    count INTEGER NOT NULL, digest TEXT NOT NULL DEFAULT '', state TEXT NOT NULL,
                    PRIMARY KEY(cycle, company, cursor))""")
                columns = {row[1] for row in self.connection.execute('PRAGMA table_info(exact_sync_chunks)')}
                if 'digest' not in columns:
                    self.connection.execute("ALTER TABLE exact_sync_chunks ADD COLUMN digest TEXT NOT NULL DEFAULT ''")
                publication_receipts.initialize(self.connection)
        except BaseException:
            self.connection.close()
            raise
        if self.path != ":memory:":
            Path(path).chmod(0o600)

    def save(self, cycle, company, payload):
        started = time.monotonic()
        encoded = json.dumps(payload, ensure_ascii=False)
        with self.lock:
            try:
                with self.connection:
                    # Never replace a pending inventory with a refetch: its
                    # checkpoint indexes refer to this exact ordering/content.
                    cursor = self.connection.execute("INSERT OR IGNORE INTO inventories VALUES (?,?,?,0)",
                                                     (cycle, company, encoded))
                    if cursor.rowcount:
                        remember_title_audit(self.connection, company, payload)
                if cursor.rowcount:
                    self.saved += 1
                    self.payload_bytes += len(encoded.encode("utf-8"))
            finally:
                self.checkpoint_seconds += time.monotonic() - started

    def get(self, cycle, company):
        with self.lock:
            row = self.connection.execute("SELECT payload,blocked FROM inventories WHERE cycle=? AND company=?",
                                          (cycle, company)).fetchone()
        return (json.loads(row[0]), bool(row[1])) if row else None

    def cycles(self, include_blocked=False):
        with self.lock:
            return [row[0] for row in self.connection.execute(
                "SELECT DISTINCT cycle FROM inventories" + ("" if include_blocked else " WHERE blocked=0"))]

    def acknowledge(self, cycle, company):
        with self.lock, self.connection:
            self.connection.execute("DELETE FROM inventories WHERE cycle=? AND company=?", (cycle, company))
            self.connection.execute("DELETE FROM sync_plans WHERE cycle=? AND company=?", (cycle, company))
            self.connection.execute("DELETE FROM exact_sync_chunks WHERE cycle=? AND company=?", (cycle, company))

    def block(self, cycle, company):
        with self.lock, self.connection:
            self.connection.execute("UPDATE inventories SET blocked=1 WHERE cycle=? AND company=?", (cycle, company))

    def save_plan(self, cycle, company, plan, receipt=None):
        """Freeze keyed operations before a Sheets request; never replace a replay."""
        started = time.monotonic()
        encoded = json.dumps(plan, ensure_ascii=False)
        with self.lock, self.connection:
            if not self.connection.execute(
                    "SELECT 1 FROM inventories WHERE cycle=? AND company=?", (cycle, company)).fetchone():
                raise ValueError("Cannot plan without a durable inventory")
            cursor = self.connection.execute("INSERT OR IGNORE INTO sync_plans VALUES (?,?,?,0)",
                                             (cycle, company, encoded))
            if receipt is not None:
                publication_receipts.local_committed(
                    self.connection, receipt['binding'], receipt['records'], receipt['schedule'],
                    timestamp=receipt['timestamp'])
            if cursor.rowcount:
                self.payload_bytes += len(encoded.encode("utf-8"))
        self.checkpoint_seconds += time.monotonic() - started

    def plan(self, cycle, company):
        with self.lock:
            row = self.connection.execute("SELECT payload,cursor FROM sync_plans WHERE cycle=? AND company=?",
                                          (cycle, company)).fetchone()
        return (json.loads(row[0]), row[1]) if row else None

    def ensure_receipt(self, receipt):
        """Recover a legacy frozen plan without changing it or its cursor."""
        with self.lock, self.connection:
            return publication_receipts.local_committed(
                self.connection, receipt['binding'], receipt['records'], receipt['schedule'],
                timestamp=receipt['timestamp'])

    def mark_receipt_pending(self, receipt, *, timestamp):
        with self.lock, self.connection:
            return publication_receipts.mark_sync_pending(self.connection, receipt['binding'], timestamp=timestamp)

    def reconcile_receipt(self, receipt, observed_records, acknowledgement_id, *, timestamp):
        with self.lock, self.connection:
            return publication_receipts.reconcile_sync(
                self.connection, receipt['binding'], observed_records, acknowledgement_id, timestamp=timestamp)

    def receipt(self, receipt):
        with self.lock:
            return publication_receipts.receipt(self.connection, receipt['binding'])

    def find_receipt(self, company_id, records):
        """Find the one existing receipt bound to this frozen plan's records.

        This is intentionally an exact fingerprint match, not a cycle-wide
        scan or a best-effort row match.  Legacy plans without a receipt simply
        receive a new frozen-plan binding from the scoped publisher.
        """
        expected = json.dumps(dict(sorted(records.items())), ensure_ascii=False,
                              sort_keys=True, separators=(',', ':'))
        with self.lock:
            rows = self.connection.execute(
                'SELECT binding,records,schedule,created_at FROM publication_receipts WHERE records=?',
                (expected,)).fetchall()
        matches = []
        for binding, stored_records, schedule, created_at in rows:
            decoded = json.loads(binding)
            if str(decoded.get('company_id', '')).strip() == str(company_id).strip():
                matches.append({
                    'binding': decoded, 'records': json.loads(stored_records),
                    'schedule': json.loads(schedule), 'created_at': created_at,
                })
        if len(matches) > 1:
            raise ValueError('Frozen plan has ambiguous existing receipts; exact delivery is held.')
        return matches[0] if matches else None

    def pending(self, cycle, include_blocked=False):
        with self.lock:
            return [row[0] for row in self.connection.execute(
                "SELECT company FROM inventories WHERE cycle=?" +
                ("" if include_blocked else " AND blocked=0") + " ORDER BY rowid", (cycle,))]

    def summary(self, cycle):
        with self.lock:
            ready = self.connection.execute(
                "SELECT count(*) FROM inventories WHERE cycle=? AND blocked=0", (cycle,)
            ).fetchone()[0]
            blocked = self.connection.execute(
                "SELECT count(*) FROM inventories WHERE cycle=? AND blocked=1", (cycle,)
            ).fetchone()[0]
            planned = self.connection.execute(
                "SELECT count(*) FROM sync_plans WHERE cycle=?", (cycle,)
            ).fetchone()[0]
        return {"ready": ready, "blocked": blocked, "planned": planned}

    def advance(self, cycle, cursors, *, expected=None):
        """Only called after an acknowledged atomic Sheets commit."""
        started = time.monotonic()
        with self.lock, self.connection:
            for company, cursor in cursors.items():
                if expected is None or company not in expected:
                    updated = self.connection.execute(
                        "UPDATE sync_plans SET cursor=? WHERE cycle=? AND company=?",
                        (cursor, cycle, company)).rowcount
                else:
                    updated = self.connection.execute(
                        "UPDATE sync_plans SET cursor=? WHERE cycle=? AND company=? AND cursor=?",
                        (cursor, cycle, company, expected[company])).rowcount
                if updated != 1:
                    raise ValueError('Exact sync cursor changed before acknowledged advance.')
        self.checkpoint_seconds += time.monotonic() - started

    def exact_chunk(self, cycle, company, cursor):
        with self.lock:
            row = self.connection.execute(
                'SELECT count,digest,state FROM exact_sync_chunks WHERE cycle=? AND company=? AND cursor=?',
                (cycle, company, cursor)).fetchone()
        return {'count': row[0], 'digest': row[1], 'state': row[2]} if row else None

    def begin_exact_chunk(self, cycle, company, cursor, count, digest):
        """Durably record one scoped request before any remote write."""
        if type(cursor) is not int or type(count) is not int or cursor < 0 or count < 1:
            raise ValueError('Exact chunk cursor/count must be positive integers.')
        with self.lock, self.connection:
            self.connection.execute(
                'INSERT OR IGNORE INTO exact_sync_chunks(cycle,company,cursor,count,digest,state) VALUES (?,?,?,?,?,?)',
                (cycle, company, cursor, count, digest, 'PENDING'))
            row = self.connection.execute(
                'SELECT count,digest,state FROM exact_sync_chunks WHERE cycle=? AND company=? AND cursor=?',
                (cycle, company, cursor)).fetchone()
        if row[0] != count or row[1] != digest:
            raise ValueError('Exact chunk changed after its durable request record.')
        return {'count': row[0], 'digest': row[1], 'state': row[2]}

    def confirm_exact_chunk(self, cycle, company, cursor):
        with self.lock, self.connection:
            updated = self.connection.execute(
                "UPDATE exact_sync_chunks SET state='CONFIRMED' WHERE cycle=? AND company=? AND cursor=?",
                (cycle, company, cursor)).rowcount
        if not updated:
            raise ValueError('Cannot confirm an exact chunk without its durable request record.')

    def discard_plan(self, cycle, company):
        # Only for a confirmed preflight rejection, never an uncertain write.
        # The original inventory remains durable for a fresh explicit retry.
        with self.lock, self.connection:
            self.connection.execute("DELETE FROM sync_plans WHERE cycle=? AND company=?", (cycle, company))

    def unblock(self, cycle, company):
        with self.lock, self.connection:
            self.connection.execute("UPDATE inventories SET blocked=0 WHERE cycle=? AND company=?",
                                    (cycle, company))

    def close(self):
        self.connection.close()
