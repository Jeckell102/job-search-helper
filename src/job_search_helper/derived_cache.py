"""Disposable, content-keyed calculations; never authoritative job decisions."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3


def content_digest(parts):
    digest = hashlib.sha256()
    for part in parts:
        value = part.encode('utf-8') if isinstance(part, str) else part
        digest.update(len(value).to_bytes(8, 'big'))
        digest.update(value)
    return digest.hexdigest()


class DerivedCache:
    """Keep the latest calculation per identity, invalidated by exact inputs.

    Corrupt/unavailable caches fall back to calculation. Chunked transactions
    amortize local writes; losing a chunk can only cause recomputation.
    """
    def __init__(self, path):
        self.db = None
        self.pending = 0
        self.metrics = {}
        self.used = set()
        try:
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.db = sqlite3.connect(path, timeout=1)
            path.chmod(0o600)
            self.db.execute('PRAGMA journal_mode=WAL')
            self.db.execute('CREATE TABLE IF NOT EXISTS calculations ('
                            'namespace TEXT, identity TEXT, input_hash TEXT, payload TEXT, '
                            'payload_hash TEXT, PRIMARY KEY(namespace,identity))')
            self.db.commit()
        except (OSError, sqlite3.Error):
            self._disable()

    def _disable(self):
        if self.db is not None:
            try:
                self.db.close()
            except sqlite3.Error:
                pass
        self.db = None

    def calculate(self, namespace, identity, inputs, compute):
        self.used.add((namespace, identity))
        signature = content_digest(inputs)
        counts = self.metrics.setdefault(namespace, {'reused': 0, 'computed': 0})
        if self.db is not None:
            try:
                row = self.db.execute('SELECT input_hash,payload,payload_hash FROM calculations '
                                      'WHERE namespace=? AND identity=?', (namespace, identity)).fetchone()
                if row and row[0] == signature and content_digest([row[1]]) == row[2]:
                    value = json.loads(row[1])
                    counts['reused'] += 1
                    return value
            except (ValueError, sqlite3.Error):
                self._disable()
        value = compute()
        counts['computed'] += 1
        if self.db is not None:
            try:
                payload = json.dumps(value, ensure_ascii=False, separators=(',', ':'))
                self.db.execute('INSERT OR REPLACE INTO calculations VALUES (?,?,?,?,?)',
                                (namespace, identity, signature, payload, content_digest([payload])))
                self.pending += 1
                if self.pending >= 100:
                    self.db.commit()
                    self.pending = 0
            except sqlite3.Error:
                self._disable()
        return value

    def prune(self):
        """Drop unused derived entries after a complete build; keep all sources."""
        if self.db is None:
            return
        try:
            self.db.execute('CREATE TEMP TABLE IF NOT EXISTS used_calculations ('
                            'namespace TEXT, identity TEXT, PRIMARY KEY(namespace,identity))')
            self.db.execute('DELETE FROM used_calculations')
            self.db.executemany('INSERT INTO used_calculations VALUES (?,?)', self.used)
            self.db.execute('DELETE FROM calculations WHERE NOT EXISTS '
                            '(SELECT 1 FROM used_calculations u WHERE u.namespace=calculations.namespace '
                            'AND u.identity=calculations.identity)')
            self.db.commit()
        except sqlite3.Error:
            self._disable()

    def close(self):
        if self.db is not None:
            try:
                self.db.commit()
            except sqlite3.Error:
                pass
            self._disable()


@contextmanager
def calculation_cache(path):
    cache = DerivedCache(path)
    try:
        yield cache
    finally:
        cache.close()
