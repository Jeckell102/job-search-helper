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


class InventoryInbox:
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
                self.connection.execute("""CREATE TABLE IF NOT EXISTS sync_plans (
                    cycle TEXT, company TEXT, payload TEXT NOT NULL, cursor INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(cycle, company))""")
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

    def block(self, cycle, company):
        with self.lock, self.connection:
            self.connection.execute("UPDATE inventories SET blocked=1 WHERE cycle=? AND company=?", (cycle, company))

    def save_plan(self, cycle, company, plan):
        """Freeze keyed operations before a Sheets request; never replace a replay."""
        started = time.monotonic()
        encoded = json.dumps(plan, ensure_ascii=False)
        with self.lock, self.connection:
            if not self.connection.execute(
                    "SELECT 1 FROM inventories WHERE cycle=? AND company=?", (cycle, company)).fetchone():
                raise ValueError("Cannot plan without a durable inventory")
            cursor = self.connection.execute("INSERT OR IGNORE INTO sync_plans VALUES (?,?,?,0)",
                                             (cycle, company, encoded))
            if cursor.rowcount:
                self.payload_bytes += len(encoded.encode("utf-8"))
        self.checkpoint_seconds += time.monotonic() - started

    def plan(self, cycle, company):
        with self.lock:
            row = self.connection.execute("SELECT payload,cursor FROM sync_plans WHERE cycle=? AND company=?",
                                          (cycle, company)).fetchone()
        return (json.loads(row[0]), row[1]) if row else None

    def pending(self, cycle, include_blocked=False):
        with self.lock:
            return [row[0] for row in self.connection.execute(
                "SELECT company FROM inventories WHERE cycle=?" +
                ("" if include_blocked else " AND blocked=0") + " ORDER BY rowid", (cycle,))]

    def advance(self, cycle, cursors):
        """Only called after an acknowledged atomic Sheets commit."""
        started = time.monotonic()
        with self.lock, self.connection:
            for company, cursor in cursors.items():
                self.connection.execute("UPDATE sync_plans SET cursor=? WHERE cycle=? AND company=?",
                                        (cursor, cycle, company))
        self.checkpoint_seconds += time.monotonic() - started

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
