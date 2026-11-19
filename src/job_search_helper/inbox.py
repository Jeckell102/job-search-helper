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
                self.connection.execute("""CREATE TABLE IF NOT EXISTS exact_plan_local_state (
                    cycle TEXT NOT NULL, company TEXT NOT NULL,
                    plan_digest TEXT NOT NULL,
                    local_operations_digest TEXT NOT NULL,
                    remote_projection_digest TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('FROZEN','LOCAL_APPLIED','LOCAL_VERIFIED')),
                    local_apply_id TEXT,
                    local_records_digest TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(cycle, company),
                    FOREIGN KEY(cycle, company) REFERENCES sync_plans(cycle, company))""")
                self.connection.execute("""CREATE TABLE IF NOT EXISTS exact_legacy_plan_migrations (
                    cycle TEXT NOT NULL, company TEXT NOT NULL,
                    legacy_plan_digest TEXT NOT NULL,
                    inventory_payload_digest TEXT NOT NULL,
                    operation_count INTEGER NOT NULL,
                    original_local_cursor INTEGER NOT NULL,
                    verified_local_cursor INTEGER NOT NULL DEFAULT 0,
                    row_scope TEXT, remote_projection TEXT,
                    remote_projection_digest TEXT,
                    state TEXT NOT NULL CHECK(state IN
                      ('FROZEN','PREFIX_VERIFIED','LOCAL_COMPLETE','REMOTE_PLAN_FROZEN')),
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    PRIMARY KEY(cycle, company),
                    FOREIGN KEY(cycle, company) REFERENCES sync_plans(cycle, company))""")
                self.connection.execute("""CREATE TABLE IF NOT EXISTS exact_remote_plans (
                    cycle TEXT NOT NULL, company TEXT NOT NULL,
                    local_plan_digest TEXT NOT NULL,
                    projection TEXT NOT NULL, projection_digest TEXT NOT NULL,
                    receipt_id TEXT NOT NULL, intent_id TEXT NOT NULL,
                    remote_cursor INTEGER NOT NULL DEFAULT 0,
                    state TEXT NOT NULL CHECK(state IN
                      ('FROZEN','SYNC_PENDING','SYNC_CONFIRMED','LOCAL_ACKNOWLEDGED')),
                    first_attempt_claimed INTEGER NOT NULL DEFAULT 0,
                    attempted_at TEXT, acknowledgement_id TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    PRIMARY KEY(cycle, company))""")
                columns = {row[1] for row in self.connection.execute('PRAGMA table_info(exact_sync_chunks)')}
                if 'digest' not in columns:
                    self.connection.execute("ALTER TABLE exact_sync_chunks ADD COLUMN digest TEXT NOT NULL DEFAULT ''")
                remote_columns = {row[1] for row in self.connection.execute(
                    'PRAGMA table_info(exact_remote_plans)')}
                for name, ddl in (
                        ('receipt_id', "TEXT NOT NULL DEFAULT ''"),
                        ('intent_id', "TEXT NOT NULL DEFAULT ''"),
                        ('first_attempt_claimed', 'INTEGER NOT NULL DEFAULT 0'),
                        ('attempted_at', 'TEXT')):
                    if name not in remote_columns:
                        self.connection.execute(
                            f'ALTER TABLE exact_remote_plans ADD COLUMN {name} {ddl}')
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

    def _require_exact_local_acknowledgement(self, local, cycle, company,
                                             plan_digest, receipt_id,
                                             acknowledgement_id,
                                             expected_apply_id=None):
        """Prove the concrete job DB durably acknowledged this exact receipt."""
        from .sqlite_repository import SQLiteRepository
        if not isinstance(local, SQLiteRepository):
            raise ValueError('Exact v2 finalization requires its SQLite repository.')
        with self.lock:
            destination = self.connection.execute('SELECT id FROM destination').fetchone()
        if destination != (local.spreadsheet_id,):
            raise ValueError('Exact v2 local acknowledgement belongs to another workbook.')
        tables = {row[0] for row in local.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
            "('exact_local_applications','exact_local_acknowledgements')")}
        if tables != {'exact_local_applications', 'exact_local_acknowledgements'}:
            raise ValueError('Exact v2 local acknowledgement journal is unavailable.')
        parent = local.db.execute(
            'SELECT apply_id,state FROM exact_local_applications '
            'WHERE cycle=? AND company=? AND plan_digest=?',
            (cycle, company, plan_digest)).fetchone()
        if (parent is None or parent[1] != 'VERIFIED'
                or (expected_apply_id is not None and parent[0] != expected_apply_id)):
            raise ValueError('Exact v2 local application is not durably verified.')
        acknowledgement = local.db.execute(
            'SELECT acknowledgement_id,selected_fields_digest '
            'FROM exact_local_acknowledgements '
            'WHERE apply_id=? AND receipt_id=?',
            (parent[0], receipt_id)).fetchone()
        selected = acknowledgement[1] if acknowledgement else ''
        if (acknowledgement is None or acknowledgement[0] != acknowledgement_id
                or len(selected) != 64
                or any(character not in '0123456789abcdef' for character in selected)):
            raise ValueError('Exact v2 selected local evidence is not durably acknowledged.')
        return {'apply_id': parent[0], 'selected_fields_digest': selected}

    def acknowledge(self, cycle, company, *, local=None):
        with self.lock, self.connection:
            # An exact-v2 marker is the durable barrier that keeps all legacy
            # receipt/chunk reconciliation paths fail-closed.  It may only be
            # removed after the trusted Sheets path has confirmed the receipt
            # and the exact local acknowledgement has been persisted.
            exact = self.connection.execute(
                'SELECT local_plan_digest,receipt_id,acknowledgement_id,state '
                'FROM exact_remote_plans WHERE cycle=? AND company=?',
                (cycle, company)).fetchone()
            local_exact = self.connection.execute(
                'SELECT state,local_apply_id FROM exact_plan_local_state '
                'WHERE cycle=? AND company=?', (cycle, company)).fetchone()
            if local_exact is not None and exact is None:
                raise ValueError(
                    'Exact v2 cleanup requires a registered, terminal remote plan.')
            if exact is not None:
                receipt = self.connection.execute(
                    'SELECT acknowledgement_id,state FROM publication_receipts '
                    'WHERE receipt_id=?', (exact[1],)).fetchone()
                if (exact[3] != 'LOCAL_ACKNOWLEDGED'
                        or not exact[2]
                        or receipt != (exact[2], publication_receipts.SYNC_CONFIRMED)):
                    raise ValueError(
                        'Exact v2 cleanup requires a locally acknowledged, '
                        'durably confirmed receipt.')
                self._require_exact_local_acknowledgement(
                    local, cycle, company, exact[0], exact[1], exact[2],
                    expected_apply_id=local_exact[1] if local_exact else None)
            self.connection.execute("DELETE FROM inventories WHERE cycle=? AND company=?", (cycle, company))
            self.connection.execute("DELETE FROM exact_sync_chunks WHERE cycle=? AND company=?", (cycle, company))
            self.connection.execute("DELETE FROM exact_remote_plans WHERE cycle=? AND company=?", (cycle, company))
            self.connection.execute("DELETE FROM exact_legacy_plan_migrations WHERE cycle=? AND company=?",
                                    (cycle, company))
            self.connection.execute("DELETE FROM exact_plan_local_state WHERE cycle=? AND company=?",
                                    (cycle, company))
            self.connection.execute("DELETE FROM sync_plans WHERE cycle=? AND company=?", (cycle, company))

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

    def save_exact_plan(self, cycle, company, plan, *, timestamp):
        """Freeze a v2 local/remote plan without claiming local durability."""
        from .exact_cycle_planner import _exact_plan_digest, _digest
        from .publication_receipts import record_fingerprints
        if (not isinstance(plan, dict) or plan.get('exact_plan_version') != 2
                or plan.get('cycle_id') != cycle or plan.get('company_id') != company
                or not isinstance(plan.get('plan_digest'), str) or not plan['plan_digest']
                or not isinstance(plan.get('local_operations_digest'), str)
                or not plan['local_operations_digest']
                or not isinstance(plan.get('remote_projection_digest'), str)
                or not plan['remote_projection_digest']
                or plan.get('plan_digest') != _exact_plan_digest(plan)
                or plan.get('local_operations_digest') != _digest(plan.get('local_operations'))
                or plan.get('local_expected_records') != record_fingerprints(plan.get('local_operations', []))
                or plan.get('local_expected_records_digest') != _digest(plan.get('local_expected_records'))
                or plan.get('remote_projection_digest') != _digest(plan.get('remote_projection'))
                or plan.get('remote_records') != record_fingerprints(plan.get('remote_projection', []))
                or plan.get('remote_records_digest') != _digest(plan.get('remote_records'))):
            raise ValueError('Exact v2 plan is missing immutable durability evidence.')
        if not isinstance(timestamp, str) or not timestamp.strip():
            raise ValueError('Exact v2 plan requires a durable timestamp.')
        encoded = json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        with self.lock, self.connection:
            if not self.connection.execute(
                    'SELECT 1 FROM inventories WHERE cycle=? AND company=?',
                    (cycle, company)).fetchone():
                raise ValueError('Cannot freeze an exact plan without a durable inventory.')
            existing = self.connection.execute(
                'SELECT payload,cursor FROM sync_plans WHERE cycle=? AND company=?',
                (cycle, company)).fetchone()
            local = self.connection.execute(
                'SELECT plan_digest,local_operations_digest,remote_projection_digest,state '
                'FROM exact_plan_local_state WHERE cycle=? AND company=?',
                (cycle, company)).fetchone()
            evidence = (plan['plan_digest'], plan['local_operations_digest'],
                        plan['remote_projection_digest'])
            if existing is not None or local is not None:
                if (existing is None or local is None or existing[0] != encoded
                        or tuple(local[:3]) != evidence):
                    raise ValueError('Exact v2 plan conflicts with existing frozen evidence.')
                return {'cycle_id': cycle, 'company_id': company,
                        'state': local[3], 'created': False}
            self.connection.execute(
                'INSERT INTO sync_plans(cycle,company,payload,cursor) VALUES (?,?,?,0)',
                (cycle, company, encoded))
            self.connection.execute(
                'INSERT INTO exact_plan_local_state VALUES (?,?,?,?,?,?,?,?,?,?)',
                (cycle, company, *evidence, 'FROZEN', None, None,
                 timestamp.strip(), timestamp.strip()))
        return {'cycle_id': cycle, 'company_id': company,
                'state': 'FROZEN', 'created': True}

    def exact_local_state(self, cycle, company):
        with self.lock:
            row = self.connection.execute(
                'SELECT plan_digest,local_operations_digest,remote_projection_digest,state,'
                'local_apply_id,local_records_digest,created_at,updated_at '
                'FROM exact_plan_local_state WHERE cycle=? AND company=?',
                (cycle, company)).fetchone()
            plan_row = self.connection.execute(
                'SELECT payload FROM sync_plans WHERE cycle=? AND company=?',
                (cycle, company)).fetchone()
        if row is None:
            return None
        if plan_row is None:
            raise ValueError('Exact local state is orphaned from its frozen plan.')
        from .exact_cycle_planner import _digest, _exact_plan_digest
        plan = json.loads(plan_row[0])
        if (plan.get('cycle_id') != cycle or plan.get('company_id') != company
                or plan.get('plan_digest') != row[0]
                or _exact_plan_digest(plan) != row[0]
                or _digest(plan.get('local_operations')) != row[1]
                or _digest(plan.get('remote_projection')) != row[2]):
            raise ValueError('Exact frozen plan or local-state evidence is corrupt.')
        keys = ('plan_digest', 'local_operations_digest', 'remote_projection_digest',
                'state', 'local_apply_id', 'local_records_digest',
                'created_at', 'updated_at')
        return {'cycle_id': cycle, 'company_id': company,
                **dict(zip(keys, row))}

    def mark_exact_local_applied(self, cycle, company, *, plan_digest,
                                 apply_id, records_digest, timestamp):
        """Mirror one authoritative local-DB application monotonically."""
        values = (str(plan_digest).strip(), str(apply_id).strip(),
                  str(records_digest).strip(), str(timestamp).strip())
        if not all(values):
            raise ValueError('Exact local application evidence is incomplete.')
        with self.lock, self.connection:
            row = self.connection.execute(
                'SELECT plan_digest,state,local_apply_id,local_records_digest '
                'FROM exact_plan_local_state WHERE cycle=? AND company=?',
                (cycle, company)).fetchone()
            if row is None or row[0] != values[0]:
                raise ValueError('Exact local application has no matching frozen plan.')
            stored = self.connection.execute(
                'SELECT payload,cursor FROM sync_plans WHERE cycle=? AND company=?',
                (cycle, company)).fetchone()
            from .exact_cycle_planner import _exact_plan_digest
            frozen = json.loads(stored[0]) if stored is not None else {}
            if (stored is None or frozen.get('plan_digest') != values[0]
                    or _exact_plan_digest(frozen) != values[0]):
                raise ValueError('Exact local application plan payload is missing or changed.')
            if row[1] in {'LOCAL_APPLIED', 'LOCAL_VERIFIED'}:
                if row[2:] != values[1:3]:
                    raise ValueError('Exact local application evidence changed after persistence.')
                return self.exact_local_state(cycle, company)
            updated = self.connection.execute(
                'UPDATE exact_plan_local_state SET state=?,local_apply_id=?,local_records_digest=?,updated_at=? '
                'WHERE cycle=? AND company=? AND state=? AND plan_digest=?',
                ('LOCAL_APPLIED', values[1], values[2], values[3],
                 cycle, company, 'FROZEN', values[0])).rowcount
            if updated != 1:
                raise ValueError('Exact local application state changed unexpectedly.')
        return self.exact_local_state(cycle, company)

    def mark_exact_local_verified(self, cycle, company, *, plan_digest,
                                  apply_id, records_digest, timestamp):
        """Mirror exact local readback; never skip the applied state."""
        values = (str(plan_digest).strip(), str(apply_id).strip(),
                  str(records_digest).strip(), str(timestamp).strip())
        if not all(values):
            raise ValueError('Exact local verification evidence is incomplete.')
        with self.lock, self.connection:
            row = self.connection.execute(
                'SELECT plan_digest,state,local_apply_id,local_records_digest '
                'FROM exact_plan_local_state WHERE cycle=? AND company=?',
                (cycle, company)).fetchone()
            if (row is None or row[0] != values[0]
                    or row[2:] != values[1:3]):
                raise ValueError('Exact local verification does not match applied evidence.')
            stored = self.connection.execute(
                'SELECT payload FROM sync_plans WHERE cycle=? AND company=?',
                (cycle, company)).fetchone()
            from .exact_cycle_planner import _exact_plan_digest
            frozen = json.loads(stored[0]) if stored is not None else {}
            if frozen.get('plan_digest') != values[0] or _exact_plan_digest(frozen) != values[0]:
                raise ValueError('Exact local verification plan payload is missing or changed.')
            if row[1] == 'LOCAL_VERIFIED':
                return self.exact_local_state(cycle, company)
            if row[1] != 'LOCAL_APPLIED':
                raise ValueError('Exact local verification requires LOCAL_APPLIED state.')
            updated = self.connection.execute(
                'UPDATE exact_plan_local_state SET state=?,updated_at=? '
                'WHERE cycle=? AND company=? AND state=? AND plan_digest=?',
                ('LOCAL_VERIFIED', values[3], cycle, company,
                 'LOCAL_APPLIED', values[0])).rowcount
            if updated != 1:
                raise ValueError('Exact local verification state changed unexpectedly.')
        return self.exact_local_state(cycle, company)

    def advance_exact_local_cursor(self, cycle, company, cursor, *, expected):
        """Advance only the local apply cursor with compare-and-swap."""
        if (type(cursor) is not int or type(expected) is not int
                or expected < 0 or cursor <= expected):
            raise ValueError('Exact local cursor advance is invalid.')
        with self.lock, self.connection:
            row = self.connection.execute(
                'SELECT payload FROM sync_plans WHERE cycle=? AND company=? AND cursor=?',
                (cycle, company, expected)).fetchone()
            state = self.connection.execute(
                'SELECT state FROM exact_plan_local_state WHERE cycle=? AND company=?',
                (cycle, company)).fetchone()
            if row is None or state is None:
                raise ValueError('Exact local cursor has no matching frozen plan.')
            plan = json.loads(row[0])
            if plan.get('exact_plan_version') != 2 or cursor > len(plan.get('local_operations', [])):
                raise ValueError('Exact local cursor exceeds the immutable operation stream.')
            updated = self.connection.execute(
                'UPDATE sync_plans SET cursor=? WHERE cycle=? AND company=? AND cursor=?',
                (cursor, cycle, company, expected)).rowcount
            if updated != 1:
                raise ValueError('Exact local cursor changed before verified advance.')
        return cursor

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
            receipt_id = publication_receipts._receipt_id(receipt['binding'])
            binding = receipt['binding']
            if (self.connection.execute(
                    'SELECT 1 FROM exact_remote_plans WHERE receipt_id=?',
                    (receipt_id,)).fetchone()
                    or self.connection.execute(
                        'SELECT 1 FROM exact_plan_local_state '
                        'WHERE cycle=? AND company=?',
                        (binding.get('request_id'),
                         binding.get('company_id'))).fetchone()):
                raise ValueError('Exact remote receipts require trusted Sheets confirmation.')
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

    def exact_remote_state(self, cycle, company):
        """Return the trusted remote-intent journal for one frozen exact plan."""
        with self.lock:
            row = self.connection.execute(
                'SELECT local_plan_digest,projection,projection_digest,receipt_id,intent_id,'
                'remote_cursor,state,first_attempt_claimed,attempted_at,acknowledgement_id,'
                'created_at,updated_at FROM exact_remote_plans WHERE cycle=? AND company=?',
                (cycle, company)).fetchone()
        if row is None:
            return None
        keys = ('local_plan_digest', 'projection', 'projection_digest', 'receipt_id',
                'intent_id', 'remote_cursor', 'state', 'first_attempt_claimed',
                'attempted_at', 'acknowledgement_id', 'created_at', 'updated_at')
        result = dict(zip(keys, row))
        result['projection'] = json.loads(result['projection'])
        result['first_attempt_claimed'] = bool(result['first_attempt_claimed'])
        return {'cycle_id': cycle, 'company_id': company, **result}

    def freeze_exact_remote_plan(self, cycle, company, *, local_plan_digest,
                                 projection, projection_digest, receipt_id,
                                 intent_id, timestamp):
        """Bind an immutable Sheets projection to its receipt and intent."""
        from .exact_cycle_planner import _digest
        values = tuple(str(value).strip() for value in (
            local_plan_digest, projection_digest, receipt_id, intent_id, timestamp))
        if not all(values) or not isinstance(projection, list):
            raise ValueError('Exact remote plan binding is incomplete.')
        if _digest(projection) != values[1]:
            raise ValueError('Exact remote projection digest is invalid.')
        encoded = json.dumps(projection, ensure_ascii=False, sort_keys=True,
                             separators=(',', ':'))
        with self.lock, self.connection:
            local = self.connection.execute(
                'SELECT l.plan_digest,l.remote_projection_digest,l.state,p.payload '
                'FROM exact_plan_local_state l JOIN sync_plans p '
                'ON p.cycle=l.cycle AND p.company=l.company '
                'WHERE l.cycle=? AND l.company=?', (cycle, company)).fetchone()
            receipt = self.connection.execute(
                'SELECT binding,state FROM publication_receipts WHERE receipt_id=?',
                (values[2],)).fetchone()
            if local is None or (local[0], local[2]) != (values[0], 'LOCAL_VERIFIED'):
                raise ValueError('Exact remote plan requires matching LOCAL_VERIFIED evidence.')
            if receipt is None:
                raise ValueError('Exact remote plan requires its durable receipt.')
            receipt_binding = json.loads(receipt[0])
            if (receipt_binding.get('request_id') != cycle
                    or receipt_binding.get('company_id') != company):
                raise ValueError('Exact remote receipt names another request or company.')
            row = self.connection.execute(
                'SELECT local_plan_digest,projection,projection_digest,receipt_id,intent_id '
                'FROM exact_remote_plans WHERE cycle=? AND company=?',
                (cycle, company)).fetchone()
            expected = (values[0], encoded, values[1], values[2], values[3])
            if row is None:
                if receipt[1] == publication_receipts.SYNC_CONFIRMED:
                    raise ValueError('Exact remote registration rejects a pre-confirmed receipt.')
                self.connection.execute(
                    'INSERT INTO exact_remote_plans('
                    'cycle,company,local_plan_digest,projection,projection_digest,'
                    'receipt_id,intent_id,remote_cursor,state,first_attempt_claimed,'
                    'attempted_at,acknowledgement_id,created_at,updated_at) '
                    "VALUES (?,?,?,?,?,?,?,0,'FROZEN',0,NULL,NULL,?,?)",
                    (cycle, company, *expected, values[4], values[4]))
            elif tuple(row) != expected:
                raise ValueError('Exact remote plan conflicts with frozen binding.')
        return self.exact_remote_state(cycle, company)

    def claim_exact_remote_attempt(self, cycle, company, *, local_plan_digest,
                                   projection_digest, receipt_id, intent_id,
                                   cursor, count, chunk_digest, timestamp):
        """Atomically journal pending state and claim the sole remote attempt."""
        from .exact_cycle_planner import _digest
        if (type(cursor) is not int or type(count) is not int
                or cursor < 0 or count < 1):
            raise ValueError('Exact remote chunk cursor/count is invalid.')
        binding = tuple(str(value).strip() for value in (
            local_plan_digest, projection_digest, receipt_id, intent_id,
            chunk_digest, timestamp))
        if not all(binding):
            raise ValueError('Exact remote attempt binding is incomplete.')
        with self.lock, self.connection:
            remote = self.connection.execute(
                'SELECT local_plan_digest,projection_digest,receipt_id,intent_id,'
                'remote_cursor,state,first_attempt_claimed,projection FROM exact_remote_plans '
                'WHERE cycle=? AND company=?', (cycle, company)).fetchone()
            if remote is None or tuple(remote[:4]) != binding[:4]:
                raise ValueError('Exact remote attempt does not match its frozen intent.')
            if remote[4] != cursor or remote[5] not in {'FROZEN', 'SYNC_PENDING'}:
                raise ValueError('Exact remote attempt cursor/state is invalid.')
            projection = json.loads(remote[7])
            if (cursor + count > len(projection)
                    or projection[cursor:cursor + count] == []
                    or _digest(projection[cursor:cursor + count]) != binding[4]):
                raise ValueError('Exact remote chunk does not match the frozen projection slice.')
            receipt = self.connection.execute(
                'SELECT binding,state FROM publication_receipts WHERE receipt_id=?',
                (binding[2],)).fetchone()
            if receipt is None or receipt[1] not in {
                    publication_receipts.LOCAL_COMMITTED,
                    publication_receipts.SYNC_PENDING}:
                raise ValueError('Exact remote attempt requires an unconfirmed durable receipt.')
            existing = self.connection.execute(
                'SELECT count,digest,state FROM exact_sync_chunks '
                'WHERE cycle=? AND company=? AND cursor=?',
                (cycle, company, cursor)).fetchone()
            expected_chunk = (count, binding[4])
            if existing is not None and tuple(existing[:2]) != expected_chunk:
                raise ValueError('Exact remote chunk conflicts with durable evidence.')
            if receipt[1] == publication_receipts.LOCAL_COMMITTED:
                publication_receipts.mark_sync_pending(
                    self.connection, json.loads(receipt[0]), timestamp=binding[5])
            self.connection.execute(
                'INSERT OR IGNORE INTO exact_sync_chunks'
                '(cycle,company,cursor,count,digest,state) VALUES (?,?,?,?,?,?)',
                (cycle, company, cursor, count, binding[4], 'PENDING'))
            # The durable chunk row is the one-shot authority for this exact
            # cursor.  A later chunk may make its own first attempt after the
            # prior chunk was confirmed; a restart at the same cursor may not.
            first_attempt = existing is None
            if first_attempt:
                self.connection.execute(
                    "UPDATE exact_remote_plans SET state='SYNC_PENDING',"
                    'first_attempt_claimed=1,'
                    'attempted_at=COALESCE(attempted_at,?),updated_at=? '
                    "WHERE cycle=? AND company=? AND state IN ('FROZEN','SYNC_PENDING')",
                    (binding[5], binding[5], cycle, company))
            else:
                self.connection.execute(
                    "UPDATE exact_remote_plans SET state='SYNC_PENDING',updated_at=? "
                    'WHERE cycle=? AND company=?', (binding[5], cycle, company))
        result = self.exact_remote_state(cycle, company)
        return {**result, 'first_attempt': first_attempt}

    def require_exact_remote_confirmed(self, cycle, company, *, local_plan_digest,
                                       projection_digest, receipt_id, intent_id,
                                       acknowledgement_id):
        """Verify the stored remote and receipt acknowledgement binding."""
        expected = tuple(str(value).strip() for value in (
            local_plan_digest, projection_digest, receipt_id, intent_id,
            acknowledgement_id))
        if not all(expected):
            raise ValueError('Exact confirmed binding is incomplete.')
        with self.lock:
            remote = self.connection.execute(
                'SELECT local_plan_digest,projection_digest,receipt_id,intent_id,'
                'acknowledgement_id,state FROM exact_remote_plans '
                'WHERE cycle=? AND company=?', (cycle, company)).fetchone()
            receipt = self.connection.execute(
                'SELECT acknowledgement_id,state FROM publication_receipts '
                'WHERE receipt_id=?', (expected[2],)).fetchone()
        if (remote is None or tuple(remote[:5]) != expected
                or remote[5] not in {'SYNC_CONFIRMED', 'LOCAL_ACKNOWLEDGED'}
                or receipt != (expected[4], publication_receipts.SYNC_CONFIRMED)):
            raise ValueError('Exact remote acknowledgement is not durably confirmed.')
        return self.exact_remote_state(cycle, company)

    def mark_exact_remote_locally_acknowledged(self, cycle, company, *,
                                               local,
                                               local_plan_digest,
                                               projection_digest, receipt_id,
                                               intent_id, acknowledgement_id,
                                               timestamp):
        with self.lock:
            local_state = self.connection.execute(
                'SELECT local_apply_id,state FROM exact_plan_local_state '
                'WHERE cycle=? AND company=? AND plan_digest=?',
                (cycle, company, local_plan_digest)).fetchone()
        if local_state is None or local_state[1] != 'LOCAL_VERIFIED':
            raise ValueError('Exact v2 inbox local application is not verified.')
        self._require_exact_local_acknowledgement(
            local, cycle, company, local_plan_digest, receipt_id,
            acknowledgement_id, expected_apply_id=local_state[0])
        self.require_exact_remote_confirmed(
            cycle, company, local_plan_digest=local_plan_digest,
            projection_digest=projection_digest, receipt_id=receipt_id,
            intent_id=intent_id, acknowledgement_id=acknowledgement_id)
        with self.lock, self.connection:
            updated = self.connection.execute(
                "UPDATE exact_remote_plans SET state='LOCAL_ACKNOWLEDGED',updated_at=? "
                'WHERE cycle=? AND company=? AND local_plan_digest=? '
                'AND projection_digest=? AND receipt_id=? AND intent_id=? '
                'AND acknowledgement_id=? '
                "AND state IN ('SYNC_CONFIRMED','LOCAL_ACKNOWLEDGED')",
                (str(timestamp).strip(), cycle, company, local_plan_digest,
                 projection_digest, receipt_id, intent_id, acknowledgement_id)).rowcount
        if updated != 1:
            raise ValueError('Exact remote local acknowledgement binding changed.')
        return self.exact_remote_state(cycle, company)

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
            if (self.connection.execute(
                    'SELECT 1 FROM exact_remote_plans WHERE cycle=? AND company=?',
                    (cycle, company)).fetchone()
                    or self.connection.execute(
                        'SELECT 1 FROM exact_plan_local_state '
                        'WHERE cycle=? AND company=?',
                        (cycle, company)).fetchone()):
                raise ValueError('Exact remote chunks require trusted Sheets publication.')
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
            if (self.connection.execute(
                    'SELECT 1 FROM exact_remote_plans WHERE cycle=? AND company=?',
                    (cycle, company)).fetchone()
                    or self.connection.execute(
                        'SELECT 1 FROM exact_plan_local_state '
                        'WHERE cycle=? AND company=?',
                        (cycle, company)).fetchone()):
                raise ValueError('Exact remote chunks require trusted Sheets confirmation.')
            updated = self.connection.execute(
                "UPDATE exact_sync_chunks SET state='CONFIRMED' WHERE cycle=? AND company=? AND cursor=?",
                (cycle, company, cursor)).rowcount
        if not updated:
            raise ValueError('Cannot confirm an exact chunk without its durable request record.')

    def discard_plan(self, cycle, company):
        # Only for a confirmed preflight rejection, never an uncertain write.
        # The original inventory remains durable for a fresh explicit retry.
        with self.lock, self.connection:
            if self.connection.execute(
                    'SELECT 1 FROM exact_plan_local_state WHERE cycle=? AND company=?',
                    (cycle, company)).fetchone():
                raise ValueError('Exact v2 frozen plans are immutable and cannot be discarded.')
            self.connection.execute("DELETE FROM sync_plans WHERE cycle=? AND company=?", (cycle, company))

    def unblock(self, cycle, company):
        with self.lock, self.connection:
            self.connection.execute("UPDATE inventories SET blocked=0 WHERE cycle=? AND company=?",
                                    (cycle, company))

    def close(self):
        self.connection.close()
