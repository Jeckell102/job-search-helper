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

    def block(self, cycle, company):
        with self.lock, self.connection:
            self.connection.execute("UPDATE inventories SET blocked=1 WHERE cycle=? AND company=?", (cycle, company))

    def close(self):
        self.connection.close()
