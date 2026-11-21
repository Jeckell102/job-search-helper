"""Durable fetch results, independent of Sheets and cycle checkpoints.

Each producer commits the complete inventory before handing off its worker.
The sync consumer deletes it only after the company's Sheets writes AND local
checkpoint are acknowledged. Failed companies retain their evidence for retry.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
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

    @staticmethod
    def sealed_selected_legacy_recovery(path, cycle, company):
        """Read one frozen selected-recovery candidate without creating tables."""
        location = Path(path)
        if not location.is_file():
            return None
        uri = location.resolve().as_uri() + '?mode=ro'
        try:
            with sqlite3.connect(uri, uri=True) as connection:
                exists = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' "
                    "AND name='exact_selected_legacy_recoveries'").fetchone()
                if not exists:
                    return None
                columns = {row[1] for row in connection.execute(
                    'PRAGMA table_info(exact_selected_legacy_recoveries)')}
                required = {'authorization_digest', 'claims_digest', 'key_id',
                            'authorization_expires_at', 'successor_plan_digest',
                            'remote_projection_digest', 'candidate', 'evidence', 'state'}
                if not required.issubset(columns):
                    return None
                row = connection.execute(
                    'SELECT authorization_digest,claims_digest,key_id,authorization_expires_at,'
                    'successor_plan_digest,remote_projection_digest,candidate,evidence,state '
                    'FROM exact_selected_legacy_recoveries WHERE cycle=? AND company=?',
                    (cycle, company)).fetchone()
        except sqlite3.Error:
            return None
        if row is None:
            return None
        keys = ('authorization_digest', 'claims_digest', 'key_id',
                'authorization_expires_at', 'successor_plan_digest',
                'remote_projection_digest', 'candidate', 'evidence', 'state')
        result = dict(zip(keys, row))
        try:
            result['candidate'] = json.loads(result['candidate'])
            result['evidence'] = json.loads(result['evidence'])
        except (TypeError, ValueError):
            return None
        return result

    @staticmethod
    def archived_selected_legacy_cancellation(path, cycle, company):
        """Read one cancellation archive without opening a SQLite writer."""
        location = Path(path)
        if not location.is_file():
            return None
        uri = location.resolve().as_uri() + '?mode=ro'
        try:
            with sqlite3.connect(uri, uri=True) as connection:
                exists = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' "
                    "AND name='exact_selected_legacy_recovery_archive'").fetchone()
                if not exists:
                    return None
                row = connection.execute(
                    'SELECT evidence FROM exact_selected_legacy_recovery_archive '
                    'WHERE cycle=? AND company=?', (cycle, company)).fetchone()
        except sqlite3.Error:
            return None
        if row is None:
            return None
        try:
            value = json.loads(row[0])
        except (TypeError, ValueError):
            return None
        if (not isinstance(value, dict)
                or value.get('version') != 'selected-recovery-cancellation-v1'
                or not isinstance(value.get('selected_recovery'), dict)
                or not isinstance(value.get('cancellation'), dict)):
            return None
        return value

    def __init__(self, path, spreadsheet_id, *, readonly=False):
        self.path = str(path)
        self.lock = RLock()
        self.checkpoint_seconds = 0.0
        self.payload_bytes = 0
        self.saved = 0
        if readonly:
            uri = Path(path).resolve().as_uri() + '?mode=ro'
            self.connection = sqlite3.connect(uri, uri=True, timeout=30, check_same_thread=False)
            try:
                self.connection.execute('PRAGMA query_only=ON')
                if self.connection.execute('SELECT id FROM destination').fetchall() != [(spreadsheet_id,)]:
                    raise ValueError('Inventory inbox belongs to a different spreadsheet.')
            except BaseException:
                self.connection.close()
                raise
            return
        if self.path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.connection = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
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
                # This is intentionally separate from exact_legacy_plan_migrations:
                # that journal represents an already-complete legacy local
                # stream, while this journal begins with an independently
                # verified prefix and an unapplied suffix.
                self.connection.execute("""CREATE TABLE IF NOT EXISTS exact_selected_legacy_recoveries (
                    cycle TEXT NOT NULL, company TEXT NOT NULL,
                    authorization_digest TEXT NOT NULL,
                    claims_digest TEXT NOT NULL,
                    key_id TEXT NOT NULL DEFAULT '',
                    authorization_expires_at TEXT NOT NULL DEFAULT '',
                    legacy_plan_digest TEXT NOT NULL,
                    inventory_payload_digest TEXT NOT NULL,
                    successor_plan_digest TEXT NOT NULL,
                    remote_projection_digest TEXT NOT NULL,
                    verified_prefix_cursor INTEGER NOT NULL,
                    candidate TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN
                      ('FROZEN','PREFIX_VERIFIED','SELECTED_LOCAL_VERIFIED',
                       'V2_PLAN_FROZEN','REMOTE_PLAN_FROZEN')),
                    evidence TEXT NOT NULL, created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(cycle, company),
                    UNIQUE(successor_plan_digest),
                    FOREIGN KEY(cycle, company) REFERENCES sync_plans(cycle, company))""")
                selected_columns = {row[1] for row in self.connection.execute(
                    'PRAGMA table_info(exact_selected_legacy_recoveries)')}
                if 'key_id' not in selected_columns:
                    self.connection.execute(
                        "ALTER TABLE exact_selected_legacy_recoveries ADD COLUMN key_id TEXT NOT NULL DEFAULT ''")
                if 'authorization_expires_at' not in selected_columns:
                    self.connection.execute(
                        "ALTER TABLE exact_selected_legacy_recoveries ADD COLUMN authorization_expires_at TEXT NOT NULL DEFAULT ''")
                self.connection.execute("""CREATE TABLE IF NOT EXISTS
                    exact_selected_legacy_recovery_archive (
                      cycle TEXT NOT NULL, company TEXT NOT NULL,
                      evidence TEXT NOT NULL, archived_at TEXT NOT NULL,
                      PRIMARY KEY(cycle,company))""")
                # This exceptional ordering never shares the v1 selected
                # recovery journal.  It is intentionally local-only until a
                # future dedicated release gate is designed and approved.
                self.connection.execute("""CREATE TABLE IF NOT EXISTS
                    exact_control_before_prefix_recoveries (
                    cycle TEXT NOT NULL, company TEXT NOT NULL,
                    authorization_digest TEXT NOT NULL, claims_digest TEXT NOT NULL,
                    key_id TEXT NOT NULL, authorization_expires_at TEXT NOT NULL,
                    original_legacy_plan_digest TEXT NOT NULL,
                    inventory_payload_digest TEXT NOT NULL,
                    successor_plan_digest TEXT NOT NULL,
                    remote_projection_digest TEXT NOT NULL,
                    original_verified_prefix_cursor INTEGER NOT NULL,
                    control_original_index INTEGER NOT NULL,
                    candidate TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('FROZEN','LOCAL_ONLY_FROZEN')),
                    evidence TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    PRIMARY KEY(cycle, company), UNIQUE(successor_plan_digest),
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
                        ('attempted_at', 'TEXT'),
                        ('delivery_mode', "TEXT NOT NULL DEFAULT 'write_once'"),
                        ('observed_at', 'TEXT')):
                    if name not in remote_columns:
                        self.connection.execute(
                            f'ALTER TABLE exact_remote_plans ADD COLUMN {name} {ddl}')
                migration_columns = {row[1] for row in self.connection.execute(
                    'PRAGMA table_info(exact_legacy_plan_migrations)')}
                for name, ddl in (
                        ('legacy_plan', 'TEXT'), ('successor_plan', 'TEXT'),
                        ('successor_plan_digest', 'TEXT'),
                        ('workbook_id_digest', 'TEXT'),
                        ('current_local_snapshot_digest', 'TEXT'),
                        ('selected_fields_readback_digest', 'TEXT'),
                        ('protected_guard_digest', 'TEXT'),
                        ('approved_conflicts', 'TEXT'),
                        ('local_apply_id', 'TEXT'),
                        ('local_records_digest', 'TEXT')):
                    if name not in migration_columns:
                        self.connection.execute(
                            f'ALTER TABLE exact_legacy_plan_migrations ADD COLUMN {name} {ddl}')
                self.connection.execute("""CREATE TABLE IF NOT EXISTS
                    exact_legacy_plan_migration_archive (
                      cycle TEXT NOT NULL, company TEXT NOT NULL,
                      evidence TEXT NOT NULL, archived_at TEXT NOT NULL,
                      PRIMARY KEY(cycle,company))""")
                self.connection.execute("""CREATE TABLE IF NOT EXISTS
                    exact_legacy_delivery_evidence (
                      cycle TEXT NOT NULL, company TEXT NOT NULL,
                      version TEXT NOT NULL, delivery_mode TEXT NOT NULL,
                      plan_digest TEXT NOT NULL, legacy_plan_digest TEXT NOT NULL,
                      evidence_digest TEXT NOT NULL, evidence TEXT NOT NULL,
                      state TEXT NOT NULL CHECK(state IN ('BOUND')),
                      created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                      PRIMARY KEY(cycle,company),
                      FOREIGN KEY(cycle,company) REFERENCES
                        exact_legacy_plan_migrations(cycle,company))""")
                self.connection.execute("""CREATE TABLE IF NOT EXISTS
                    exact_legacy_delivery_evidence_archive (
                      cycle TEXT NOT NULL, company TEXT NOT NULL,
                      evidence TEXT NOT NULL, archived_at TEXT NOT NULL,
                      PRIMARY KEY(cycle,company))""")
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
            return self._cycle_ids(self.connection, include_blocked)

    @staticmethod
    def _cycle_ids(connection, include_blocked):
        return [row[0] for row in connection.execute(
            "SELECT DISTINCT cycle FROM inventories" + ("" if include_blocked else " WHERE blocked=0"))]

    @classmethod
    def saved_cycle_ids(cls, path, *, include_blocked=False):
        """Select saved inventory scope before opening any writer."""
        path = Path(path)
        if not path.is_file():
            return []
        connection = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
        try:
            return cls._cycle_ids(connection, include_blocked)
        finally:
            connection.close()

    def _require_exact_local_acknowledgement(self, local, cycle, company,
                                             plan_digest, receipt_id,
                                             acknowledgement_id,
                                             expected_apply_id=None):
        with self.lock:
            return self._verify_exact_local_acknowledgement(
                self.connection, local, cycle, company, plan_digest, receipt_id,
                acknowledgement_id, expected_apply_id=expected_apply_id,
            )

    @staticmethod
    def _verify_exact_local_acknowledgement(connection, local, cycle, company,
                                            plan_digest, receipt_id, acknowledgement_id,
                                            expected_apply_id=None):
        """Prove the concrete job DB durably acknowledged this exact receipt."""
        from .sqlite_repository import SQLiteRepository
        if not isinstance(local, SQLiteRepository):
            raise ValueError('Exact v2 finalization requires its SQLite repository.')
        destination = connection.execute('SELECT id FROM destination').fetchone()
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
            migration_state = self.connection.execute(
                'SELECT state FROM exact_legacy_plan_migrations '
                'WHERE cycle=? AND company=?', (cycle, company)).fetchone()
            selected_state = self.connection.execute(
                'SELECT state FROM exact_selected_legacy_recoveries '
                'WHERE cycle=? AND company=?', (cycle, company)).fetchone()
            control_before_prefix_state = self.connection.execute(
                'SELECT state FROM exact_control_before_prefix_recoveries '
                'WHERE cycle=? AND company=?', (cycle, company)).fetchone()
            if (migration_state is not None
                    and migration_state[0] != 'REMOTE_PLAN_FROZEN'):
                raise ValueError(
                    'Exact legacy migration cannot be cleaned up before successor freeze.')
            if (selected_state is not None
                    and selected_state[0] != 'REMOTE_PLAN_FROZEN'):
                raise ValueError(
                    'Selected legacy recovery cannot be cleaned up before remote intent freeze.')
            if control_before_prefix_state is not None:
                raise ValueError(
                    'Control-before-prefix recovery cannot be cleaned up before a dedicated release gate.')
            if local_exact is not None and exact is None:
                raise ValueError(
                    'Exact v2 cleanup requires a registered, terminal remote plan.')
            if exact is not None:
                receipt = self.connection.execute(
                    'SELECT acknowledgement_id,state,binding FROM publication_receipts '
                    'WHERE receipt_id=?', (exact[1],)).fetchone()
                if (exact[3] != 'LOCAL_ACKNOWLEDGED'
                        or not exact[2]
                        or receipt is None
                        or receipt[:2] != (exact[2], publication_receipts.SYNC_CONFIRMED)):
                    raise ValueError(
                        'Exact v2 cleanup requires a locally acknowledged, '
                        'durably confirmed receipt.')
                self._require_exact_local_acknowledgement(
                    local, cycle, company, exact[0], exact[1], exact[2],
                    expected_apply_id=local_exact[1] if local_exact else None)
                self._archive_selected_retry_publication(cycle, company, exact)
                self._archive_ordinary_event_publication(cycle, company, local, json.loads(receipt[2]))
            self.connection.execute("DELETE FROM inventories WHERE cycle=? AND company=?", (cycle, company))
            self.connection.execute("DELETE FROM exact_sync_chunks WHERE cycle=? AND company=?", (cycle, company))
            self.connection.execute("DELETE FROM exact_remote_plans WHERE cycle=? AND company=?", (cycle, company))
            migration = self.connection.execute(
                'SELECT * FROM exact_legacy_plan_migrations '
                'WHERE cycle=? AND company=?', (cycle, company)).fetchone()
            if migration is not None:
                columns = [row[1] for row in self.connection.execute(
                    'PRAGMA table_info(exact_legacy_plan_migrations)')]
                evidence = json.dumps(
                    dict(zip(columns, migration)), ensure_ascii=False,
                    sort_keys=True, separators=(',', ':'))
                archived = self.connection.execute(
                    'SELECT evidence FROM exact_legacy_plan_migration_archive '
                    'WHERE cycle=? AND company=?', (cycle, company)).fetchone()
                if archived is not None and archived[0] != evidence:
                    raise ValueError('Exact legacy migration archive conflicts with cleanup.')
                self.connection.execute(
                    'INSERT OR IGNORE INTO exact_legacy_plan_migration_archive '
                    'VALUES (?,?,?,datetime(\'now\'))',
                    (cycle, company, evidence))
                delivery = self.connection.execute(
                    'SELECT * FROM exact_legacy_delivery_evidence '
                    'WHERE cycle=? AND company=?', (cycle, company)).fetchone()
                if delivery is not None:
                    delivery_columns = [row[1] for row in self.connection.execute(
                        'PRAGMA table_info(exact_legacy_delivery_evidence)')]
                    delivery_evidence = json.dumps(
                        dict(zip(delivery_columns, delivery)), ensure_ascii=False,
                        sort_keys=True, separators=(',', ':'))
                    archived_delivery = self.connection.execute(
                        'SELECT evidence FROM exact_legacy_delivery_evidence_archive '
                        'WHERE cycle=? AND company=?', (cycle, company)).fetchone()
                    if (archived_delivery is not None
                            and archived_delivery[0] != delivery_evidence):
                        raise ValueError(
                            'Exact legacy delivery archive conflicts with cleanup.')
                    self.connection.execute(
                        'INSERT OR IGNORE INTO exact_legacy_delivery_evidence_archive '
                        'VALUES (?,?,?,datetime(\'now\'))',
                        (cycle, company, delivery_evidence))
                    self.connection.execute(
                        'DELETE FROM exact_legacy_delivery_evidence '
                        'WHERE cycle=? AND company=?', (cycle, company))
            self.connection.execute("DELETE FROM exact_legacy_plan_migrations WHERE cycle=? AND company=?",
                                    (cycle, company))
            selected = self.connection.execute(
                'SELECT * FROM exact_selected_legacy_recoveries '
                'WHERE cycle=? AND company=?', (cycle, company)).fetchone()
            if selected is not None:
                columns = [row[1] for row in self.connection.execute(
                    'PRAGMA table_info(exact_selected_legacy_recoveries)')]
                evidence = json.dumps(
                    dict(zip(columns, selected)), ensure_ascii=False,
                    sort_keys=True, separators=(',', ':'))
                archived = self.connection.execute(
                    'SELECT evidence FROM exact_selected_legacy_recovery_archive '
                    'WHERE cycle=? AND company=?', (cycle, company)).fetchone()
                if archived is not None and archived[0] != evidence:
                    raise ValueError('Selected legacy recovery archive conflicts with cleanup.')
                self.connection.execute(
                    'INSERT OR IGNORE INTO exact_selected_legacy_recovery_archive '
                    'VALUES (?,?,?,datetime(\'now\'))',
                    (cycle, company, evidence))
                self.connection.execute(
                    'DELETE FROM exact_selected_legacy_recoveries '
                    'WHERE cycle=? AND company=?', (cycle, company))
            self.connection.execute("DELETE FROM exact_plan_local_state WHERE cycle=? AND company=?",
                                    (cycle, company))
            self.connection.execute("DELETE FROM sync_plans WHERE cycle=? AND company=?", (cycle, company))

    def _archive_selected_retry_publication(self, cycle, company, exact):
        """Retain the lineaged receipt in the same transaction as exact cleanup."""
        row = self.connection.execute(
            'SELECT payload FROM sync_plans WHERE cycle=? AND company=?', (cycle, company),
        ).fetchone()
        if row is None:
            return
        plan = json.loads(row[0])
        binding = plan.get('selected_retry_receipt_binding')
        if binding is None:
            return

        from .exact_cycle_planner import _exact_plan_digest
        plan_digest, receipt_id, acknowledgement_id, _state = exact
        remote = self.connection.execute(
            'SELECT projection_digest,intent_id FROM exact_remote_plans WHERE cycle=? AND company=?',
            (cycle, company),
        ).fetchone()
        receipt = publication_receipts.receipt(self.connection, binding)
        if (plan['plan_digest'] != plan_digest or _exact_plan_digest(plan) != plan_digest
                or binding['company_id'] != company or receipt is None or receipt['receipt_id'] != receipt_id
                or receipt['binding'] != binding or receipt['records'] != plan['remote_records']
                or receipt['acknowledgement_id'] != acknowledgement_id):
            raise ValueError('Exact selected retry archive disagrees with the verified receipt.')
        evidence = {
            'cycle_id': cycle, 'company_id': company, 'binding': binding,
            'plan_digest': plan_digest, 'inventory_sha256': plan['inventory_payload_digest'],
            'projection_digest': remote[0], 'intent_id': remote[1],
            'receipt_id': receipt_id, 'acknowledgement_id': acknowledgement_id,
        }
        encoded = json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        self.connection.execute(
            'CREATE TABLE IF NOT EXISTS selected_retry_publication_archive ('
            'cycle TEXT NOT NULL, company TEXT NOT NULL, evidence TEXT NOT NULL, PRIMARY KEY(cycle,company))')
        original = self.connection.execute(
            'SELECT evidence FROM selected_retry_publication_archive WHERE cycle=? AND company=?',
            (cycle, company),
        ).fetchone()
        if original is not None and original != (encoded,):
            raise ValueError('Exact selected retry publication archive conflicts with cleanup.')
        self.connection.execute(
            'INSERT OR IGNORE INTO selected_retry_publication_archive VALUES (?,?,?)', (cycle, company, encoded),
        )

    def _archive_ordinary_event_publication(self, cycle, company, local, receipt_binding):
        saved = self.plan(cycle, company)
        plan = saved[0] if saved else None
        binding = plan.get('ordinary_company_event') if isinstance(plan, dict) else None
        event_receipt = receipt_binding.get('authority') == 'ordinary-company-event-exact-v2'
        if binding is None and not event_receipt:
            return
        if not event_receipt or binding != receipt_binding:
            raise ValueError('Ordinary event cleanup has a mismatched plan or Sheets receipt.')
        from .ordinary_event_publication_archive import archive_before_cleanup
        if not self.connection.in_transaction:
            self.connection.execute('BEGIN IMMEDIATE')
        archive_before_cleanup(self, local, cycle, company, plan, binding=binding)

    def block(self, cycle, company):
        with self.lock, self.connection:
            if self.connection.execute(
                    'SELECT 1 FROM exact_legacy_plan_migrations '
                    'WHERE cycle=? AND company=?', (cycle, company)).fetchone():
                raise ValueError('Exact legacy migration inventory state is immutable.')
            if self.connection.execute(
                    'SELECT 1 FROM exact_selected_legacy_recoveries '
                    'WHERE cycle=? AND company=?', (cycle, company)).fetchone():
                raise ValueError('Selected legacy recovery inventory state is immutable.')
            if self.connection.execute(
                    'SELECT 1 FROM exact_control_before_prefix_recoveries '
                    'WHERE cycle=? AND company=?', (cycle, company)).fetchone():
                raise ValueError('Control-before-prefix recovery inventory state is immutable.')
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
                or plan.get('record_fingerprint_version', 1) not in {1, 2}
                or plan.get('local_expected_records') != record_fingerprints(
                    plan.get('local_operations', []),
                    include_guard_only=plan.get('record_fingerprint_version', 1) == 2)
                or plan.get('local_expected_records_digest') != _digest(plan.get('local_expected_records'))
                or plan.get('remote_projection_digest') != _digest(plan.get('remote_projection'))
                or plan.get('remote_records') != record_fingerprints(
                    plan.get('remote_projection', []),
                    include_guard_only=plan.get('record_fingerprint_version', 1) == 2)
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

    @staticmethod
    def _legacy_migration_binding(plan):
        migration = plan.get('legacy_migration') if isinstance(plan, dict) else None
        keys = (
            'cycle_id', 'company_id', 'workbook_id_digest',
            'legacy_plan_digest', 'inventory_payload_digest',
            'legacy_operation_count', 'original_local_cursor',
            'inventory_blocked', 'current_local_snapshot_digest',
            'selected_fields_readback_digest', 'protected_guard_digest',
            'approved_conflicts', 'publication_profile',
            'publication_schema_digest',
        )
        if (not isinstance(migration, dict)
                or migration.get('version') != 'legacy-exact-plan-migration-v1'
                or migration.get('protected_fields') != ['Decision', 'Review Status']
                or migration.get('protected_conflicts') != migration.get('approved_conflicts')
                or any(key not in migration for key in keys)):
            raise ValueError('Exact legacy migration evidence is incomplete.')
        return {key: migration[key] for key in keys}

    def begin_exact_legacy_migration(self, cycle, company, plan, binding, *, timestamp):
        """Persist immutable legacy/successor evidence without replacing work."""
        from .exact_cycle_planner import _digest, _exact_plan_digest
        expected = self._legacy_migration_binding(plan)
        if (not isinstance(binding, dict) or binding != expected
                or expected['cycle_id'] != cycle
                or expected['company_id'] != company
                or expected['inventory_blocked'] is not False
                or expected['workbook_id_digest'] != _digest(
                    self.connection.execute('SELECT id FROM destination').fetchone()[0])
                or plan.get('plan_digest') != _exact_plan_digest(plan)
                or not isinstance(timestamp, str) or not timestamp.strip()):
            raise ValueError('Exact legacy migration binding is invalid.')
        encoded_successor = json.dumps(
            plan, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        with self.lock, self.connection:
            inventory = self.connection.execute(
                'SELECT payload,blocked FROM inventories WHERE cycle=? AND company=?',
                (cycle, company)).fetchone()
            existing = self.connection.execute(
                'SELECT state,legacy_plan,successor_plan,successor_plan_digest,'
                'workbook_id_digest,current_local_snapshot_digest,'
                'selected_fields_readback_digest,protected_guard_digest,'
                'approved_conflicts FROM exact_legacy_plan_migrations '
                'WHERE cycle=? AND company=?', (cycle, company)).fetchone()
            if self.connection.execute(
                    'SELECT 1 FROM exact_selected_legacy_recoveries '
                    'WHERE cycle=? AND company=?', (cycle, company)).fetchone():
                raise ValueError(
                    'Exact legacy migration conflicts with selected recovery.')
            if self.connection.execute(
                    'SELECT 1 FROM exact_control_before_prefix_recoveries '
                    'WHERE cycle=? AND company=?', (cycle, company)).fetchone():
                raise ValueError(
                    'Exact legacy migration conflicts with control-before-prefix recovery.')
            if existing is not None:
                if inventory is None:
                    raise ValueError('Exact legacy migration retained work is missing.')
                try:
                    inventory_payload = json.loads(inventory[0])
                    retained_legacy = json.loads(existing[1])
                except (TypeError, ValueError) as error:
                    raise ValueError(
                        'Exact legacy migration retained JSON is invalid.') from error
                conflicts = json.dumps(
                    expected['approved_conflicts'], ensure_ascii=False,
                    sort_keys=True, separators=(',', ':'))
                evidence = (
                    encoded_successor, plan['plan_digest'],
                    expected['workbook_id_digest'],
                    expected['current_local_snapshot_digest'],
                    expected['selected_fields_readback_digest'],
                    expected['protected_guard_digest'], conflicts)
                if (_digest(inventory_payload) != expected['inventory_payload_digest']
                        or bool(inventory[1]) != expected['inventory_blocked']
                        or _digest(retained_legacy) != expected['legacy_plan_digest']
                        or tuple(existing[2:]) != evidence):
                    raise ValueError(
                        'Exact legacy migration journal conflicts with retry.')
                return {'cycle_id': cycle, 'company_id': company,
                        'state': existing[0], 'created': False}
            legacy = self.connection.execute(
                'SELECT payload,cursor FROM sync_plans WHERE cycle=? AND company=?',
                (cycle, company)).fetchone()
            if inventory is None or legacy is None:
                raise ValueError('Exact legacy migration retained work is missing.')
            try:
                inventory_payload = json.loads(inventory[0])
                legacy_plan = json.loads(legacy[0])
            except (TypeError, ValueError) as error:
                raise ValueError('Exact legacy migration retained JSON is invalid.') from error
            if (_digest(inventory_payload) != expected['inventory_payload_digest']
                    or bool(inventory[1]) != expected['inventory_blocked']
                    or _digest(legacy_plan) != expected['legacy_plan_digest']
                    or not isinstance(legacy_plan.get('operations'), list)
                    or len(legacy_plan['operations']) != expected['legacy_operation_count']
                    or legacy[1] != expected['original_local_cursor']
                    or legacy[1] != len(legacy_plan['operations'])):
                raise ValueError('Exact legacy retained evidence changed before migration.')
            if self.connection.execute(
                    'SELECT 1 FROM exact_plan_local_state WHERE cycle=? AND company=?',
                    (cycle, company)).fetchone() or self.connection.execute(
                    'SELECT 1 FROM exact_remote_plans WHERE cycle=? AND company=?',
                    (cycle, company)).fetchone() or self.connection.execute(
                    'SELECT 1 FROM exact_sync_chunks WHERE cycle=? AND company=?',
                    (cycle, company)).fetchone():
                raise ValueError('Exact legacy migration conflicts with exact durable work.')
            for raw_binding, state in self.connection.execute(
                    'SELECT binding,state FROM publication_receipts'):
                try:
                    receipt_binding = json.loads(raw_binding)
                except (TypeError, ValueError) as error:
                    raise ValueError('Exact legacy migration receipt binding is invalid.') from error
                if (receipt_binding.get('request_id') == cycle
                        and receipt_binding.get('company_id') == company):
                    raise ValueError(
                        'Exact legacy migration conflicts with a publication receipt.')
            encoded_legacy = json.dumps(
                legacy_plan, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
            conflicts = json.dumps(
                expected['approved_conflicts'], ensure_ascii=False,
                sort_keys=True, separators=(',', ':'))
            evidence = (
                encoded_legacy, encoded_successor, plan['plan_digest'],
                expected['workbook_id_digest'],
                expected['current_local_snapshot_digest'],
                expected['selected_fields_readback_digest'],
                expected['protected_guard_digest'], conflicts)
            self.connection.execute(
                'INSERT INTO exact_legacy_plan_migrations('
                'cycle,company,legacy_plan_digest,inventory_payload_digest,'
                'operation_count,original_local_cursor,verified_local_cursor,'
                'row_scope,remote_projection,remote_projection_digest,state,'
                'created_at,updated_at,legacy_plan,successor_plan,'
                'successor_plan_digest,workbook_id_digest,'
                'current_local_snapshot_digest,selected_fields_readback_digest,'
                'protected_guard_digest,approved_conflicts,local_apply_id,'
                'local_records_digest) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (cycle, company, expected['legacy_plan_digest'],
                 expected['inventory_payload_digest'],
                 expected['legacy_operation_count'],
                 expected['original_local_cursor'], 0, None, None,
                 plan['remote_projection_digest'], 'FROZEN', timestamp.strip(),
                 timestamp.strip(), *evidence, None, None))
        return {'cycle_id': cycle, 'company_id': company,
                'state': 'FROZEN', 'created': True}

    def bind_exact_legacy_delivery_evidence(self, cycle, company, plan,
                                            evidence, *, timestamp):
        """Bind approved local delivery classification without resealing work."""
        from .exact_cycle_planner import _digest
        from .exact_legacy_migration import (
            DELIVERY_EVIDENCE_VERSION, OBSERVATION_ONLY, WRITE_ONCE,
        )
        if (not isinstance(evidence, dict)
                or evidence.get('version') != DELIVERY_EVIDENCE_VERSION
                or evidence.get('delivery_mode') not in {
                    OBSERVATION_ONLY, WRITE_ONCE}
                or evidence.get('evidence_digest') != _digest({
                    key: value for key, value in evidence.items()
                    if key != 'evidence_digest'})
                or not isinstance(timestamp, str) or not timestamp.strip()):
            raise ValueError('Exact legacy delivery evidence is invalid.')
        encoded = json.dumps(evidence, ensure_ascii=False, sort_keys=True,
                             separators=(',', ':'))
        migration = plan.get('legacy_migration') if isinstance(plan, dict) else None
        if not isinstance(migration, dict):
            raise ValueError('Exact legacy delivery plan binding is missing.')
        expected = (evidence['version'], evidence['delivery_mode'],
                    plan.get('plan_digest'), migration.get('legacy_plan_digest'),
                    evidence['evidence_digest'], encoded, 'BOUND')
        if not all(str(value or '').strip() for value in expected):
            raise ValueError('Exact legacy delivery plan binding is incomplete.')
        with self.lock, self.connection:
            journal = self.connection.execute(
                'SELECT state,successor_plan_digest,legacy_plan_digest,'
                'local_apply_id FROM exact_legacy_plan_migrations '
                'WHERE cycle=? AND company=?', (cycle, company)).fetchone()
            if (journal is None or journal[1] != plan.get('plan_digest')
                    or journal[2] != migration.get('legacy_plan_digest')):
                raise ValueError('Exact legacy delivery journal binding changed.')
            existing = self.connection.execute(
                'SELECT version,delivery_mode,plan_digest,legacy_plan_digest,'
                'evidence_digest,evidence,state FROM exact_legacy_delivery_evidence '
                'WHERE cycle=? AND company=?', (cycle, company)).fetchone()
            if existing is not None:
                if tuple(existing) != expected:
                    raise ValueError('Exact legacy delivery evidence conflicts with retry.')
                return {'cycle_id': cycle, 'company_id': company,
                        'state': 'BOUND', 'created': False,
                        'delivery_mode': evidence['delivery_mode']}
            if journal[0] != 'FROZEN' or journal[3] is not None:
                raise ValueError('Exact legacy delivery evidence arrived after local adoption.')
            self.connection.execute(
                'INSERT INTO exact_legacy_delivery_evidence VALUES '
                '(?,?,?,?,?,?,?,?,?,?,?)',
                (cycle, company, *expected[:-1], 'BOUND',
                 timestamp.strip(), timestamp.strip()))
        return {'cycle_id': cycle, 'company_id': company,
                'state': 'BOUND', 'created': True,
                'delivery_mode': evidence['delivery_mode']}

    def exact_legacy_delivery_evidence(self, cycle, company):
        with self.lock:
            row = self.connection.execute(
                'SELECT version,delivery_mode,plan_digest,legacy_plan_digest,'
                'evidence_digest,evidence,state,created_at,updated_at '
                'FROM exact_legacy_delivery_evidence '
                'WHERE cycle=? AND company=?', (cycle, company)).fetchone()
        if row is None:
            return None
        keys = ('version', 'delivery_mode', 'plan_digest', 'legacy_plan_digest',
                'evidence_digest', 'evidence', 'state', 'created_at', 'updated_at')
        result = dict(zip(keys, row))
        result['evidence'] = json.loads(result['evidence'])
        return {'cycle_id': cycle, 'company_id': company, **result}

    def mark_exact_legacy_local_complete(self, cycle, company, plan, local,
                                         *, timestamp):
        """Record the separately verified local adoption; create no receipt."""
        from .exact_local_plan import VERIFIED, exact_local_plan
        if not isinstance(timestamp, str) or not timestamp.strip():
            raise ValueError('Exact legacy local completion requires a timestamp.')
        application = exact_local_plan(local, cycle, company)
        if (application is None or application['state'] != VERIFIED
                or application['plan_digest'] != plan.get('plan_digest')):
            raise ValueError('Exact legacy local adoption is not verified.')
        records_digest = plan.get('local_expected_records_digest')
        row_scope = json.dumps(
            application['row_scope'], ensure_ascii=False,
            sort_keys=True, separators=(',', ':'))
        projection = json.dumps(
            plan.get('remote_projection'), ensure_ascii=False,
            sort_keys=True, separators=(',', ':'))
        with self.lock, self.connection:
            row = self.connection.execute(
                'SELECT state,successor_plan_digest,row_scope,remote_projection,'
                'remote_projection_digest,local_apply_id,local_records_digest '
                'FROM exact_legacy_plan_migrations WHERE cycle=? AND company=?',
                (cycle, company)).fetchone()
            expected = (plan.get('plan_digest'), row_scope, projection,
                        plan.get('remote_projection_digest'),
                        application['apply_id'], records_digest)
            if row is None:
                raise ValueError('Exact legacy migration journal is missing.')
            if row[0] in {'LOCAL_COMPLETE', 'REMOTE_PLAN_FROZEN'}:
                if tuple(row[1:]) != expected:
                    raise ValueError('Exact legacy local completion evidence changed.')
                return {'cycle_id': cycle, 'company_id': company,
                        'state': row[0], 'recovered': True}
            if row[0] not in {'FROZEN', 'PREFIX_VERIFIED'} or row[1] != expected[0]:
                raise ValueError('Exact legacy migration state cannot accept local evidence.')
            updated = self.connection.execute(
                "UPDATE exact_legacy_plan_migrations SET state='LOCAL_COMPLETE',"
                'verified_local_cursor=?,row_scope=?,remote_projection=?,'
                'remote_projection_digest=?,local_apply_id=?,local_records_digest=?,'
                'updated_at=? WHERE cycle=? AND company=? AND state IN '
                "('FROZEN','PREFIX_VERIFIED')",
                (len(plan['local_operations']), row_scope, projection,
                 plan['remote_projection_digest'], application['apply_id'],
                 records_digest, timestamp.strip(), cycle, company)).rowcount
            if updated != 1:
                raise ValueError('Exact legacy local completion changed concurrently.')
        return {'cycle_id': cycle, 'company_id': company,
                'state': 'LOCAL_COMPLETE', 'recovered': False}

    def freeze_exact_legacy_successor(self, cycle, company, plan, local,
                                      *, timestamp):
        """Atomically replace only the retained legacy plan with its successor."""
        from .exact_local_plan import VERIFIED, exact_local_plan
        application = exact_local_plan(local, cycle, company)
        if (application is None or application['state'] != VERIFIED
                or application['plan_digest'] != plan['plan_digest']):
            raise ValueError('Exact legacy successor lacks verified local adoption.')
        # Hold the local writer boundary for the entire inbox promotion.  This
        # prevents a full-row edit from landing after the final snapshot but
        # before the separately durable successor is committed.
        with local.transaction():
            return self._freeze_exact_legacy_successor_locked(
                cycle, company, plan, local, application,
                timestamp=timestamp)

    def _freeze_exact_legacy_successor_locked(
            self, cycle, company, plan, local, application, *, timestamp):
        from .exact_cycle_planner import _digest, _exact_plan_digest
        from .exact_legacy_migration import (
            OBSERVATION_ONLY, _capture_full_snapshot,
            validate_legacy_delivery_evidence,
        )
        if (not isinstance(timestamp, str) or not timestamp.strip()
                or plan.get('plan_digest') != _exact_plan_digest(plan)):
            raise ValueError('Exact legacy successor evidence is invalid.')
        _rows, snapshot_digest = _capture_full_snapshot(
            local, plan.get('local_operations', []))
        if snapshot_digest != plan.get('legacy_migration', {}).get(
                'current_local_snapshot_digest'):
            raise ValueError('Exact legacy successor snapshot changed before freeze.')
        # Clean-field migrations bind a separate immutable evidence record.
        # Revalidate it while the local writer transaction is still held, on
        # both first freeze and retries, so no stale evidence can cross the
        # successor-freeze boundary.
        with self.lock:
            delivery = self.connection.execute(
                'SELECT delivery_mode,plan_digest,state,evidence '
                'FROM exact_legacy_delivery_evidence '
                'WHERE cycle=? AND company=?', (cycle, company)).fetchone()
        if delivery is not None:
            if tuple(delivery[:3]) != (
                    OBSERVATION_ONLY, plan.get('plan_digest'), 'BOUND'):
                raise ValueError('Exact legacy delivery evidence changed before freeze.')
            try:
                delivery_evidence = json.loads(delivery[3])
            except (TypeError, ValueError) as error:
                raise ValueError(
                    'Exact legacy delivery evidence is invalid before freeze.') from error
            validate_legacy_delivery_evidence(
                local, plan.get('remote_projection', []), delivery_evidence)
        encoded = json.dumps(
            plan, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        with self.lock, self.connection:
            migration = self.connection.execute(
                'SELECT state,legacy_plan,successor_plan,successor_plan_digest,'
                'operation_count,original_local_cursor,local_apply_id,'
                'local_records_digest FROM exact_legacy_plan_migrations '
                'WHERE cycle=? AND company=?', (cycle, company)).fetchone()
            if migration is None or migration[2] != encoded or migration[3] != plan['plan_digest']:
                raise ValueError('Exact legacy successor conflicts with its migration journal.')
            if migration[0] == 'REMOTE_PLAN_FROZEN':
                stored = self.connection.execute(
                    'SELECT payload,cursor FROM sync_plans WHERE cycle=? AND company=?',
                    (cycle, company)).fetchone()
                mirrored = self.connection.execute(
                    'SELECT plan_digest,state,local_apply_id,local_records_digest '
                    'FROM exact_plan_local_state WHERE cycle=? AND company=?',
                    (cycle, company)).fetchone()
                if (stored != (encoded, len(plan['local_operations']))
                        or mirrored != (plan['plan_digest'], 'LOCAL_VERIFIED',
                                        migration[6], migration[7])):
                    raise ValueError('Exact legacy frozen successor changed after adoption.')
                return {'cycle_id': cycle, 'company_id': company,
                        'state': migration[0], 'recovered': True}
            if migration[0] != 'LOCAL_COMPLETE':
                raise ValueError('Exact legacy successor requires local completion.')
            _rows, final_snapshot_digest = _capture_full_snapshot(
                local, plan.get('local_operations', []))
            if final_snapshot_digest != snapshot_digest:
                raise ValueError('Exact legacy successor snapshot changed during freeze.')
            current = self.connection.execute(
                'SELECT payload,cursor FROM sync_plans WHERE cycle=? AND company=?',
                (cycle, company)).fetchone()
            try:
                current_plan = json.loads(current[0]) if current is not None else None
                legacy_plan = json.loads(migration[1])
            except (TypeError, ValueError) as error:
                raise ValueError('Exact legacy successor source plan is invalid.') from error
            if (current is None or current[1] != migration[5]
                    or _digest(current_plan) != _digest(legacy_plan)
                    or len(legacy_plan.get('operations', [])) != migration[4]
                    or self.connection.execute(
                        'SELECT 1 FROM exact_plan_local_state WHERE cycle=? AND company=?',
                        (cycle, company)).fetchone()
                    or self.connection.execute(
                        'SELECT 1 FROM exact_remote_plans WHERE cycle=? AND company=?',
                        (cycle, company)).fetchone()):
                raise ValueError('Exact legacy successor source evidence changed.')
            self.connection.execute(
                'UPDATE sync_plans SET payload=?,cursor=? WHERE cycle=? AND company=?',
                (encoded, len(plan['local_operations']), cycle, company))
            self.connection.execute(
                'INSERT INTO exact_plan_local_state VALUES (?,?,?,?,?,?,?,?,?,?)',
                (cycle, company, plan['plan_digest'],
                 plan['local_operations_digest'], plan['remote_projection_digest'],
                 'LOCAL_VERIFIED', migration[6], migration[7],
                 timestamp.strip(), timestamp.strip()))
            updated = self.connection.execute(
                "UPDATE exact_legacy_plan_migrations SET state='REMOTE_PLAN_FROZEN',"
                'verified_local_cursor=?,updated_at=? '
                "WHERE cycle=? AND company=? AND state='LOCAL_COMPLETE'",
                (len(plan['local_operations']), timestamp.strip(), cycle, company)).rowcount
            if updated != 1:
                raise ValueError('Exact legacy successor state changed concurrently.')
        return {'cycle_id': cycle, 'company_id': company,
                'state': 'REMOTE_PLAN_FROZEN', 'recovered': False}

    def exact_legacy_migration_state(self, cycle, company):
        with self.lock:
            row = self.connection.execute(
                'SELECT state,legacy_plan_digest,inventory_payload_digest,'
                'operation_count,original_local_cursor,verified_local_cursor,'
                'successor_plan_digest,current_local_snapshot_digest,'
                'local_apply_id,local_records_digest,created_at,updated_at '
                'FROM exact_legacy_plan_migrations WHERE cycle=? AND company=?',
                (cycle, company)).fetchone()
        if row is None:
            return None
        keys = ('state', 'legacy_plan_digest', 'inventory_payload_digest',
                'operation_count', 'original_local_cursor',
                'verified_local_cursor', 'successor_plan_digest',
                'current_local_snapshot_digest', 'local_apply_id',
                'local_records_digest', 'created_at', 'updated_at')
        return {'cycle_id': cycle, 'company_id': company, **dict(zip(keys, row))}

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

    def begin_control_before_prefix_recovery(self, cycle, company, plan, authorization,
                                             verifier, *, timestamp,
                                             allow_test_verifier=False):
        """Durably hold one signed late-control successor, locally only.

        This is intentionally *not* a local-plan adoption routine.  Its sole
        transition records immutable signed proof after all retained ownership
        checks succeed.  A later dedicated implementation must define any
        local application or release transition; generic exact-v2 publishing
        refuses this marker.
        """
        from .control_before_prefix_authorization import (
            required_control_before_prefix_claims,
            verify_control_before_prefix_authorization,
        )
        from .exact_cycle_planner import _digest, _exact_plan_digest
        from .exact_local_plan import _validate_plan
        _validate_plan(plan, cycle, company)
        recovery = plan.get('selected_legacy_control_before_prefix_recovery')
        if (not isinstance(recovery, dict)
                or recovery.get('version') != 'selected-legacy-control-before-prefix-recovery-v3'
                or recovery.get('cycle_id') != cycle or recovery.get('company_id') != company
                or recovery.get('local_only') is not True
                or recovery.get('remote_release_authorized') is not False):
            raise ValueError('Control-before-prefix recovery plan evidence is invalid.')
        ownership = recovery.get('job_ownership_manifest')
        if (not isinstance(ownership, list) or not ownership
                or recovery.get('job_ownership_manifest_digest') != _digest(ownership)):
            raise ValueError('Control-before-prefix recovery ownership evidence is invalid.')
        envelope = authorization if isinstance(authorization, dict) else None
        payload = envelope.get('payload') if envelope is not None else None
        expires_at = payload.get('expires_at') if isinstance(payload, dict) else None
        claims = required_control_before_prefix_claims(
            cycle_id=cycle, company_id=company, plan=plan, recovery=recovery,
            expires_at=expires_at)
        # This public durable boundary independently authenticates the full
        # envelope.  A caller cannot manufacture the compact evidence dict
        # returned by an earlier verification and freeze arbitrary plan data.
        verified = verify_control_before_prefix_authorization(
            envelope, claims, verifier,
            allow_test_verifier=allow_test_verifier)
        expected = {
            'original_legacy_plan_digest': recovery.get('original_legacy_plan_digest'),
            'inventory_payload_digest': recovery.get('inventory_payload_digest'),
            'successor_plan_digest': plan.get('plan_digest'),
            'remote_projection_digest': plan.get('remote_projection_digest'),
        }
        cursor = recovery.get('original_verified_prefix_cursor')
        control_index = recovery.get('control_original_index')
        absent_manifest = recovery.get('absent_suffix_manifest')
        if (type(cursor) is not int or cursor < 1 or type(control_index) is not int
                or control_index < cursor
                or type(recovery.get('absent_suffix_count')) is not int
                or recovery.get('absent_suffix_count') < 0
                or not isinstance(absent_manifest, list)
                or len(absent_manifest) != recovery.get('absent_suffix_count')
                or _digest(absent_manifest) != recovery.get('absent_suffix_manifest_digest')
                or any(not isinstance(value, str) or len(value) != 64
                       for value in expected.values())):
            raise ValueError('Control-before-prefix immutable evidence is invalid.')
        encoded = json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        evidence = json.dumps({'authorization_digest': verified['authorization_digest'],
                               'claims_digest': verified['claims_digest'],
                               'key_id': verified['key_id'],
                               'expires_at': verified['expires_at'],
                               'recovery': recovery}, ensure_ascii=False,
                              sort_keys=True, separators=(',', ':'))
        values = (verified['authorization_digest'], verified['claims_digest'],
                  verified['key_id'], verified['expires_at'],
                  expected['original_legacy_plan_digest'], expected['inventory_payload_digest'],
                  expected['successor_plan_digest'], expected['remote_projection_digest'],
                  cursor, control_index, encoded, evidence)
        with self.lock, self.connection:
            inventory = self.connection.execute(
                'SELECT payload,blocked FROM inventories WHERE cycle=? AND company=?',
                (cycle, company)).fetchone()
            source = self.connection.execute(
                'SELECT payload,cursor FROM sync_plans WHERE cycle=? AND company=?',
                (cycle, company)).fetchone()
            destination = self.connection.execute('SELECT id FROM destination').fetchall()
            conflicts = any(self.connection.execute(query, (cycle, company)).fetchone()
                            for query in (
                                'SELECT 1 FROM exact_plan_local_state WHERE cycle=? AND company=?',
                                'SELECT 1 FROM exact_remote_plans WHERE cycle=? AND company=?',
                                'SELECT 1 FROM exact_sync_chunks WHERE cycle=? AND company=?',
                                'SELECT 1 FROM exact_selected_legacy_recoveries WHERE cycle=? AND company=?'))
            if (inventory is None or inventory[1] or source is None or conflicts
                    or len(destination) != 1
                    or recovery.get('workbook_id_digest') != _digest(destination[0][0])):
                raise ValueError('Control-before-prefix retained ownership is unavailable.')
            try:
                source_plan = json.loads(source[0])
            except (TypeError, ValueError) as error:
                raise ValueError('Control-before-prefix retained source plan is invalid.') from error
            if (_digest(json.loads(inventory[0])) != expected['inventory_payload_digest']
                    or _digest(source_plan) != expected['original_legacy_plan_digest']
                    or source[1] != cursor
                    or _exact_plan_digest(plan) != expected['successor_plan_digest']):
                raise ValueError('Control-before-prefix retained evidence changed.')
            receipts = self.connection.execute('SELECT binding FROM publication_receipts').fetchall()
            if any((lambda binding: binding.get('request_id') == cycle
                   and binding.get('company_id') == company)(json.loads(row[0]))
                   for row in receipts):
                raise ValueError('Control-before-prefix receipt ownership already exists.')
            existing = self.connection.execute(
                'SELECT authorization_digest,claims_digest,key_id,authorization_expires_at,'
                'original_legacy_plan_digest,inventory_payload_digest,successor_plan_digest,'
                'remote_projection_digest,original_verified_prefix_cursor,control_original_index,'
                'candidate,evidence,state FROM exact_control_before_prefix_recoveries '
                'WHERE cycle=? AND company=?', (cycle, company)).fetchone()
            if existing is not None:
                if tuple(existing[:12]) != values:
                    raise ValueError('Control-before-prefix journal conflicts with frozen evidence.')
                return {'cycle_id': cycle, 'company_id': company,
                        'state': existing[12], 'recovered': True}
            self.connection.execute(
                'INSERT INTO exact_control_before_prefix_recoveries('
                'cycle,company,authorization_digest,claims_digest,key_id,authorization_expires_at,'
                'original_legacy_plan_digest,inventory_payload_digest,successor_plan_digest,'
                'remote_projection_digest,original_verified_prefix_cursor,control_original_index,'
                'candidate,state,evidence,created_at,updated_at) '
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'LOCAL_ONLY_FROZEN',?,?,?)",
                (cycle, company, *values[:-1], values[-1], timestamp, timestamp))
        return {'cycle_id': cycle, 'company_id': company,
                'state': 'LOCAL_ONLY_FROZEN', 'recovered': False}

    def begin_selected_legacy_recovery(self, cycle, company, plan, authorization,
                                       *, timestamp):
        """Freeze one externally authorized legacy prefix/suffix successor.

        This is a local inbox boundary only.  It accepts no caller-selected
        cursor or source plan: both are re-read from the retained inbox row and
        compared with the sealed selected-recovery evidence before a journal
        row is written.  It deliberately does not create receipt or remote
        intent ownership.
        """
        from .exact_cycle_planner import _digest, _exact_plan_digest
        from .exact_local_plan import _validate_plan
        if not isinstance(plan, dict):
            raise ValueError('Selected recovery requires an immutable v2 plan.')
        _validate_plan(plan, cycle, company)
        recovery = plan.get('selected_legacy_recovery')
        if (not isinstance(recovery, dict)
                or recovery.get('version') != 'selected-legacy-prefix-recovery-v1'
                or recovery.get('cycle_id') != cycle
                or recovery.get('company_id') != company):
            raise ValueError('Selected recovery plan evidence is invalid.')
        if (not isinstance(authorization, dict)
                or not all(isinstance(authorization.get(key), str)
                           and authorization[key] for key in
                           ('authorization_digest', 'claims_digest', 'key_id', 'expires_at'))):
            raise ValueError('Selected recovery authorization evidence is incomplete.')
        prefix = recovery.get('verified_prefix_cursor')
        if type(prefix) is not int or not 1 <= prefix <= len(plan['local_operations']):
            raise ValueError('Selected recovery prefix cursor is invalid.')
        expected = {
            'legacy_plan_digest': recovery.get('legacy_plan_digest'),
            'inventory_payload_digest': recovery.get('inventory_payload_digest'),
            'successor_plan_digest': plan.get('plan_digest'),
            'remote_projection_digest': plan.get('remote_projection_digest'),
        }
        if any(not isinstance(value, str) or len(value) != 64 for value in expected.values()):
            raise ValueError('Selected recovery immutable digest is invalid.')
        encoded = json.dumps(plan, ensure_ascii=False, sort_keys=True,
                             separators=(',', ':'))
        evidence = json.dumps({
            'authorization_digest': authorization['authorization_digest'],
            'claims_digest': authorization['claims_digest'],
            'key_id': authorization['key_id'], 'expires_at': authorization['expires_at'],
            'recovery': recovery,
        }, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        values = (authorization['authorization_digest'], authorization['claims_digest'],
                  authorization['key_id'], authorization['expires_at'], expected['legacy_plan_digest'],
                  expected['inventory_payload_digest'], expected['successor_plan_digest'],
                  expected['remote_projection_digest'], prefix, encoded, evidence)
        with self.lock, self.connection:
            inventory = self.connection.execute(
                'SELECT payload,blocked FROM inventories WHERE cycle=? AND company=?',
                (cycle, company)).fetchone()
            source = self.connection.execute(
                'SELECT payload,cursor FROM sync_plans WHERE cycle=? AND company=?',
                (cycle, company)).fetchone()
            destination = self.connection.execute(
                'SELECT id FROM destination').fetchall()
            conflicts = any(self.connection.execute(query, (cycle, company)).fetchone()
                            for query in (
                                'SELECT 1 FROM exact_plan_local_state WHERE cycle=? AND company=?',
                                'SELECT 1 FROM exact_remote_plans WHERE cycle=? AND company=?',
                                'SELECT 1 FROM exact_sync_chunks WHERE cycle=? AND company=?',
                                'SELECT 1 FROM exact_legacy_plan_migrations WHERE cycle=? AND company=?'))
            if (inventory is None or inventory[1] or source is None or conflicts
                    or len(destination) != 1
                    or recovery.get('workbook_id_digest') != _digest(destination[0][0])):
                raise ValueError('Selected recovery retained ownership is unavailable.')
            try:
                source_plan = json.loads(source[0])
            except (TypeError, ValueError) as error:
                raise ValueError('Selected recovery retained source plan is invalid.') from error
            if (_digest(json.loads(inventory[0])) != expected['inventory_payload_digest']
                    or _digest(source_plan) != expected['legacy_plan_digest']
                    or source[1] != prefix
                    or _exact_plan_digest(plan) != expected['successor_plan_digest']):
                raise ValueError('Selected recovery retained evidence changed.')
            # A receipt is an ownership claim even before a remote plan exists.
            receipt_bindings = self.connection.execute(
                'SELECT binding FROM publication_receipts').fetchall()
            if any((lambda binding: binding.get('request_id') == cycle
                   and binding.get('company_id') == company)(json.loads(row[0]))
                   for row in receipt_bindings):
                raise ValueError('Selected recovery receipt ownership already exists.')
            existing = self.connection.execute(
                'SELECT authorization_digest,claims_digest,key_id,authorization_expires_at,legacy_plan_digest,'
                'inventory_payload_digest,successor_plan_digest,remote_projection_digest,'
                'verified_prefix_cursor,candidate,evidence,state '
                'FROM exact_selected_legacy_recoveries WHERE cycle=? AND company=?',
                (cycle, company)).fetchone()
            if existing is not None:
                if tuple(existing[:11]) != values:
                    raise ValueError('Selected recovery journal conflicts with frozen evidence.')
                return {'cycle_id': cycle, 'company_id': company,
                        'state': existing[11], 'recovered': True}
            self.connection.execute(
                'INSERT INTO exact_selected_legacy_recoveries('
                'cycle,company,authorization_digest,claims_digest,key_id,authorization_expires_at,legacy_plan_digest,'
                'inventory_payload_digest,successor_plan_digest,remote_projection_digest,'
                'verified_prefix_cursor,candidate,state,evidence,created_at,updated_at) '
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'FROZEN',?,?,?)",
                (cycle, company, *values[:-1], values[-1], timestamp, timestamp))
        return {'cycle_id': cycle, 'company_id': company,
                'state': 'FROZEN', 'recovered': False}

    def selected_legacy_recovery_state(self, cycle, company):
        """Return exactly one selected-recovery journal; never discover work."""
        with self.lock:
            row = self.connection.execute(
                'SELECT authorization_digest,claims_digest,key_id,authorization_expires_at,legacy_plan_digest,'
                'inventory_payload_digest,successor_plan_digest,remote_projection_digest,'
                'verified_prefix_cursor,candidate,state,evidence,created_at,updated_at '
                'FROM exact_selected_legacy_recoveries WHERE cycle=? AND company=?',
                (cycle, company)).fetchone()
        if row is None:
            return None
        keys = ('authorization_digest', 'claims_digest', 'key_id', 'authorization_expires_at', 'legacy_plan_digest',
                'inventory_payload_digest', 'successor_plan_digest',
                'remote_projection_digest', 'verified_prefix_cursor', 'candidate',
                'state', 'evidence', 'created_at', 'updated_at')
        result = dict(zip(keys, row))
        try:
            result['candidate'] = json.loads(result['candidate'])
            result['evidence'] = json.loads(result['evidence'])
        except (TypeError, ValueError) as error:
            raise ValueError('Selected recovery journal evidence is corrupt.') from error
        return {'cycle_id': cycle, 'company_id': company, **result}

    def cancel_frozen_selected_legacy_recovery(
            self, cycle, company, local, *, cancellation_authorization,
            frozen_authorization_digest, frozen_claims_digest, frozen_key_id,
            successor_plan_digest, reason, timestamp):
        """Archive only an untouched selected candidate for a safer handoff."""
        from .sqlite_repository import SQLiteRepository
        strings = (frozen_authorization_digest, frozen_claims_digest,
                   frozen_key_id, successor_plan_digest, reason, timestamp)
        if (not isinstance(local, SQLiteRepository)
                or any(not isinstance(value, str) or not value.strip()
                       for value in strings)
                or any(len(value) != 64 for value in strings[:2])
                or not isinstance(cancellation_authorization, dict)
                or any(not isinstance(cancellation_authorization.get(key), str)
                       or not cancellation_authorization[key]
                       for key in ('authorization_digest', 'claims_digest', 'key_id', 'expires_at'))):
            raise ValueError('Selected recovery cancellation evidence is invalid.')
        with self.lock:
            destination = self.connection.execute('SELECT id FROM destination').fetchall()
        if destination != [(local.spreadsheet_id,)]:
            raise ValueError('Selected recovery cancellation belongs to another workbook.')

        def local_is_untouched():
            application = local.db.execute(
                'SELECT 1 FROM exact_local_applications '
                'WHERE cycle=? AND company=? LIMIT 1', (cycle, company)).fetchone()
            chunk = local.db.execute(
                'SELECT 1 FROM exact_local_apply_chunks c '
                'JOIN exact_local_applications a ON a.apply_id=c.apply_id '
                'WHERE a.cycle=? AND a.company=? LIMIT 1',
                (cycle, company)).fetchone()
            return application is None and chunk is None

        with self.lock, self.connection:
            archived = self.connection.execute(
                'SELECT evidence FROM exact_selected_legacy_recovery_archive '
                'WHERE cycle=? AND company=?', (cycle, company)).fetchone()
            row = self.connection.execute(
                'SELECT authorization_digest,claims_digest,key_id,'
                'authorization_expires_at,legacy_plan_digest,'
                'inventory_payload_digest,successor_plan_digest,'
                'remote_projection_digest,verified_prefix_cursor,candidate,'
                'state,evidence,created_at,updated_at '
                'FROM exact_selected_legacy_recoveries '
                'WHERE cycle=? AND company=?', (cycle, company)).fetchone()
            cancellation = {
                'authorization_digest': cancellation_authorization['authorization_digest'],
                'claims_digest': cancellation_authorization['claims_digest'],
                'key_id': cancellation_authorization['key_id'],
                'expires_at': cancellation_authorization['expires_at'],
                'frozen_adoption_authorization_digest': frozen_authorization_digest,
                'frozen_adoption_claims_digest': frozen_claims_digest,
                'frozen_adoption_key_id': frozen_key_id,
                'successor_plan_digest': successor_plan_digest,
                'reason': reason,
                'cancelled_at': timestamp.strip(),
            }
            if row is None:
                if archived is None:
                    raise ValueError('Selected recovery cancellation has no frozen candidate.')
                try:
                    prior = json.loads(archived[0])
                except (TypeError, ValueError) as error:
                    raise ValueError('Selected recovery cancellation archive is invalid.') from error
                prior_cancellation = prior.get('cancellation', {})
                if ({key: prior_cancellation.get(key) for key in cancellation
                     if key != 'cancelled_at'}
                        != {key: value for key, value in cancellation.items()
                            if key != 'cancelled_at'}):
                    raise ValueError('Selected recovery cancellation archive conflicts with retry.')
                return {'cycle_id': cycle, 'company_id': company,
                        'state': 'CANCELLED', 'recovered': True,
                        'cancelled_at': prior_cancellation.get('cancelled_at')}
            if archived is not None:
                raise ValueError('Selected recovery cancellation archive already exists.')
            if (row[10] != 'FROZEN'
                    or row[0] != frozen_authorization_digest
                    or row[1] != frozen_claims_digest
                    or row[2] != frozen_key_id
                    or row[6] != successor_plan_digest):
                raise ValueError('Selected recovery cancellation scope changed.')
            if any(self.connection.execute(query, (cycle, company)).fetchone()
                   for query in (
                       'SELECT 1 FROM exact_plan_local_state WHERE cycle=? AND company=?',
                       'SELECT 1 FROM exact_remote_plans WHERE cycle=? AND company=?',
                       'SELECT 1 FROM exact_sync_chunks WHERE cycle=? AND company=?',
                       'SELECT 1 FROM exact_legacy_plan_migrations WHERE cycle=? AND company=?',
                       'SELECT 1 FROM exact_control_before_prefix_recoveries '
                       'WHERE cycle=? AND company=?')):
                raise ValueError('Selected recovery cancellation conflicts with durable work.')
            for raw_binding, _state in self.connection.execute(
                    'SELECT binding,state FROM publication_receipts'):
                try:
                    binding = json.loads(raw_binding)
                except (TypeError, ValueError) as error:
                    raise ValueError('Selected recovery receipt binding is invalid.') from error
                if (binding.get('request_id') == cycle
                        and binding.get('company_id') == company):
                    raise ValueError('Selected recovery cancellation conflicts with a receipt.')
            if not local_is_untouched():
                raise ValueError('Selected recovery cancellation conflicts with local work.')
            keys = ('authorization_digest', 'claims_digest', 'key_id',
                    'authorization_expires_at', 'legacy_plan_digest',
                    'inventory_payload_digest', 'successor_plan_digest',
                    'remote_projection_digest', 'verified_prefix_cursor',
                    'candidate', 'state', 'evidence', 'created_at', 'updated_at')
            selected = dict(zip(keys, row))
            selected['candidate'] = json.loads(selected['candidate'])
            selected['evidence'] = json.loads(selected['evidence'])
            archive = json.dumps({
                'version': 'selected-recovery-cancellation-v1',
                'cancellation': cancellation,
                'selected_recovery': selected,
            }, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
            self.connection.execute(
                'INSERT INTO exact_selected_legacy_recovery_archive '
                'VALUES (?,?,?,?)', (cycle, company, archive, timestamp.strip()))
            deleted = self.connection.execute(
                'DELETE FROM exact_selected_legacy_recoveries '
                'WHERE cycle=? AND company=? AND state=? '
                'AND authorization_digest=? AND claims_digest=? '
                'AND successor_plan_digest=?',
                (cycle, company, 'FROZEN', frozen_authorization_digest,
                 frozen_claims_digest, successor_plan_digest)).rowcount
            if deleted != 1 or not local_is_untouched():
                raise ValueError('Selected recovery cancellation changed during archive.')
        return {'cycle_id': cycle, 'company_id': company,
                'state': 'CANCELLED', 'recovered': False}

    def mark_selected_legacy_prefix_verified(self, cycle, company, plan, local,
                                              *, timestamp):
        """Mirror only the already-read-back prefix into the inbox journal."""
        from .exact_cycle_planner import _digest
        from .exact_local_plan import _apply_id, _validate_plan, VERIFIED
        _validate_plan(plan, cycle, company)
        recovery = plan.get('selected_legacy_recovery', {})
        prefix = recovery.get('verified_prefix_cursor')
        if type(prefix) is not int or prefix < 1:
            raise ValueError('Selected recovery prefix evidence is invalid.')
        apply_id = _apply_id(cycle, company, plan['plan_digest'])
        row = local.db.execute(
            'SELECT operation_count,operations_digest,expected_records_digest,state '
            'FROM exact_local_apply_chunks WHERE apply_id=? AND start_cursor=0',
            (apply_id,)).fetchone()
        expected = (_digest(plan['local_operations'][:prefix]),
                    recovery.get('prefix_records_digest'))
        if (row is None or row[0] != prefix or row[1] != expected[0]
                or row[2] != expected[1] or row[3] != VERIFIED):
            raise ValueError('Selected recovery local prefix is not verified.')
        with self.lock, self.connection:
            journal = self.connection.execute(
                'SELECT successor_plan_digest,state FROM exact_selected_legacy_recoveries '
                'WHERE cycle=? AND company=?', (cycle, company)).fetchone()
            if journal is None or journal[0] != plan['plan_digest']:
                raise ValueError('Selected recovery journal is missing or changed.')
            if journal[1] == 'PREFIX_VERIFIED':
                return {'cycle_id': cycle, 'company_id': company,
                        'state': journal[1], 'recovered': True}
            if journal[1] != 'FROZEN':
                raise ValueError('Selected recovery journal cannot accept a prefix.')
            updated = self.connection.execute(
                "UPDATE exact_selected_legacy_recoveries SET state='PREFIX_VERIFIED',updated_at=? "
                "WHERE cycle=? AND company=? AND state='FROZEN'",
                (timestamp, cycle, company)).rowcount
            if updated != 1:
                raise ValueError('Selected recovery prefix changed concurrently.')
        return {'cycle_id': cycle, 'company_id': company,
                'state': 'PREFIX_VERIFIED', 'recovered': False}

    def mark_selected_legacy_local_verified(self, cycle, company, plan, local,
                                             *, timestamp):
        """Bind a fully verified local successor without freezing remote work."""
        from .exact_local_plan import VERIFIED, exact_local_plan
        application = exact_local_plan(local, cycle, company)
        if (application is None or application['state'] != VERIFIED
                or application['plan_digest'] != plan.get('plan_digest')):
            raise ValueError('Selected recovery local successor is not verified.')
        records = plan.get('local_expected_records_digest')
        with self.lock, self.connection:
            row = self.connection.execute(
                'SELECT successor_plan_digest,state FROM exact_selected_legacy_recoveries '
                'WHERE cycle=? AND company=?', (cycle, company)).fetchone()
            if row is None or row[0] != plan.get('plan_digest'):
                raise ValueError('Selected recovery journal is missing or changed.')
            if row[1] == 'SELECTED_LOCAL_VERIFIED':
                return {'cycle_id': cycle, 'company_id': company,
                        'state': row[1], 'recovered': True}
            if row[1] != 'PREFIX_VERIFIED':
                raise ValueError('Selected recovery local successor is out of order.')
            updated = self.connection.execute(
                "UPDATE exact_selected_legacy_recoveries SET state='SELECTED_LOCAL_VERIFIED',updated_at=? "
                "WHERE cycle=? AND company=? AND state='PREFIX_VERIFIED'",
                (timestamp, cycle, company)).rowcount
            if updated != 1:
                raise ValueError('Selected recovery local successor changed concurrently.')
        return {'cycle_id': cycle, 'company_id': company,
                'state': 'SELECTED_LOCAL_VERIFIED', 'apply_id': application['apply_id'],
                'records_digest': records, 'recovered': False}

    def freeze_selected_legacy_successor(self, cycle, company, plan, local,
                                         *, timestamp):
        """Atomically expose one verified selected successor to exact-v2 only."""
        from .exact_cycle_planner import _digest, _exact_plan_digest
        from .exact_local_plan import VERIFIED, exact_local_plan
        application = exact_local_plan(local, cycle, company)
        if (application is None or application['state'] != VERIFIED
                or application['plan_digest'] != plan.get('plan_digest')):
            raise ValueError('Selected recovery successor lacks verified local work.')
        encoded = json.dumps(plan, ensure_ascii=False, sort_keys=True,
                             separators=(',', ':'))
        with local.transaction():
            with self.lock, self.connection:
                row = self.connection.execute(
                    'SELECT legacy_plan_digest,inventory_payload_digest,successor_plan_digest,'
                    'remote_projection_digest,verified_prefix_cursor,candidate,state '
                    'FROM exact_selected_legacy_recoveries WHERE cycle=? AND company=?',
                    (cycle, company)).fetchone()
                if row is None or row[2] != plan.get('plan_digest') or row[5] != encoded:
                    raise ValueError('Selected recovery frozen successor changed.')
                current = self.connection.execute(
                    'SELECT payload,cursor FROM sync_plans WHERE cycle=? AND company=?',
                    (cycle, company)).fetchone()
                inventory = self.connection.execute(
                    'SELECT payload,blocked FROM inventories WHERE cycle=? AND company=?',
                    (cycle, company)).fetchone()
                if (current is None or inventory is None or inventory[1]
                        or _digest(json.loads(current[0])) != row[0]
                        or current[1] != row[4]
                        or _digest(json.loads(inventory[0])) != row[1]
                        or _exact_plan_digest(plan) != row[2]
                        or plan.get('remote_projection_digest') != row[3]):
                    raise ValueError('Selected recovery retained source changed before freeze.')
                if row[6] == 'V2_PLAN_FROZEN':
                    mirrored = self.connection.execute(
                        'SELECT plan_digest,state,local_apply_id,local_records_digest '
                        'FROM exact_plan_local_state WHERE cycle=? AND company=?',
                        (cycle, company)).fetchone()
                    expected = (plan['plan_digest'], 'LOCAL_VERIFIED',
                                application['apply_id'],
                                plan['local_expected_records_digest'])
                    if (current != (encoded, len(plan['local_operations']))
                            or mirrored != expected):
                        raise ValueError('Selected recovery frozen v2 successor changed.')
                    return {'cycle_id': cycle, 'company_id': company,
                            'state': row[6], 'recovered': True}
                if (row[6] != 'SELECTED_LOCAL_VERIFIED'
                        or self.connection.execute(
                            'SELECT 1 FROM exact_plan_local_state WHERE cycle=? AND company=?',
                            (cycle, company)).fetchone()
                        or self.connection.execute(
                            'SELECT 1 FROM exact_remote_plans WHERE cycle=? AND company=?',
                            (cycle, company)).fetchone()):
                    raise ValueError('Selected recovery cannot freeze a competing successor.')
                self.connection.execute(
                    'UPDATE sync_plans SET payload=?,cursor=? WHERE cycle=? AND company=?',
                    (encoded, len(plan['local_operations']), cycle, company))
                self.connection.execute(
                    'INSERT INTO exact_plan_local_state VALUES (?,?,?,?,?,?,?,?,?,?)',
                    (cycle, company, plan['plan_digest'],
                     plan['local_operations_digest'], plan['remote_projection_digest'],
                     'LOCAL_VERIFIED', application['apply_id'],
                     plan['local_expected_records_digest'], timestamp, timestamp))
                updated = self.connection.execute(
                    "UPDATE exact_selected_legacy_recoveries SET state='V2_PLAN_FROZEN',updated_at=? "
                    "WHERE cycle=? AND company=? AND state='SELECTED_LOCAL_VERIFIED'",
                    (timestamp, cycle, company)).rowcount
                if updated != 1:
                    raise ValueError('Selected recovery successor changed concurrently.')
        return {'cycle_id': cycle, 'company_id': company,
                'state': 'V2_PLAN_FROZEN', 'recovered': False}

    def require_selected_legacy_publication(self, cycle, company, plan, *, now=None):
        """Reject selected-successor publication unless its signed gate remains live."""
        recovery = plan.get('selected_legacy_recovery')
        if not recovery:
            return None
        state = self.selected_legacy_recovery_state(cycle, company)
        if (state is None
                or state['successor_plan_digest'] != plan.get('plan_digest')
                or state['remote_projection_digest'] != plan.get('remote_projection_digest')
                or state['state'] not in {'V2_PLAN_FROZEN', 'REMOTE_PLAN_FROZEN'}):
            raise ValueError('Selected recovery is not frozen for exact publication.')
        from .selected_recovery_authorization import _expiry
        _expiry(state['authorization_expires_at'], now)
        return state

    def mark_selected_legacy_remote_plan_frozen(self, cycle, company, plan,
                                                 *, timestamp):
        """Bind the existing exact remote intent after, never before, it exists."""
        with self.lock, self.connection:
            journal = self.connection.execute(
                'SELECT successor_plan_digest,remote_projection_digest,state '
                'FROM exact_selected_legacy_recoveries WHERE cycle=? AND company=?',
                (cycle, company)).fetchone()
            remote = self.connection.execute(
                'SELECT local_plan_digest,projection_digest FROM exact_remote_plans '
                'WHERE cycle=? AND company=?', (cycle, company)).fetchone()
            expected = (plan.get('plan_digest'), plan.get('remote_projection_digest'))
            if (journal is None or tuple(journal[:2]) != expected
                    or remote != expected):
                raise ValueError('Selected recovery remote intent is missing or changed.')
            if journal[2] == 'REMOTE_PLAN_FROZEN':
                return {'cycle_id': cycle, 'company_id': company,
                        'state': journal[2], 'recovered': True}
            if journal[2] != 'V2_PLAN_FROZEN':
                raise ValueError('Selected recovery remote intent is out of order.')
            updated = self.connection.execute(
                "UPDATE exact_selected_legacy_recoveries SET state='REMOTE_PLAN_FROZEN',updated_at=? "
                "WHERE cycle=? AND company=? AND state='V2_PLAN_FROZEN'",
                (timestamp, cycle, company)).rowcount
            if updated != 1:
                raise ValueError('Selected recovery remote intent changed concurrently.')
        return {'cycle_id': cycle, 'company_id': company,
                'state': 'REMOTE_PLAN_FROZEN', 'recovered': False}

    def ensure_receipt(self, receipt):
        """Recover a legacy frozen plan without changing it or its cursor."""
        with self.lock, self.connection:
            return publication_receipts.local_committed(
                self.connection, receipt['binding'], receipt['records'], receipt['schedule'],
                timestamp=receipt['timestamp'])

    def mark_receipt_pending(self, receipt, *, timestamp):
        with self.lock, self.connection:
            return publication_receipts.mark_sync_pending(
                self.connection, receipt['binding'], timestamp=timestamp)

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
                self.connection, receipt['binding'], observed_records, acknowledgement_id,
                timestamp=timestamp)

    def receipt(self, receipt):
        with self.lock:
            return publication_receipts.receipt(self.connection, receipt['binding'])

    def discard_preflight_rejected_receipt(self, receipt, *, cursor):
        with self.lock, self.connection:
            return publication_receipts.discard_preflight_rejected(
                self.connection, receipt['binding'], receipt['records'], cursor=cursor)

    def find_receipt(self, company_id, records):
        """Find the one existing receipt bound to this frozen plan's records.

        This is intentionally an exact fingerprint match, not a cycle-wide
        scan or a best-effort row match. Legacy plans without a receipt simply
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
                'created_at,updated_at,delivery_mode,observed_at '
                'FROM exact_remote_plans WHERE cycle=? AND company=?',
                (cycle, company)).fetchone()
        if row is None:
            return None
        keys = ('local_plan_digest', 'projection', 'projection_digest', 'receipt_id',
                'intent_id', 'remote_cursor', 'state', 'first_attempt_claimed',
                'attempted_at', 'acknowledgement_id', 'created_at', 'updated_at',
                'delivery_mode', 'observed_at')
        result = dict(zip(keys, row))
        result['projection'] = json.loads(result['projection'])
        result['first_attempt_claimed'] = bool(result['first_attempt_claimed'])
        return {'cycle_id': cycle, 'company_id': company, **result}

    def freeze_exact_remote_plan(self, cycle, company, *, local_plan_digest,
                                 projection, projection_digest, receipt_id,
                                 intent_id, timestamp,
                                 delivery_mode='write_once'):
        """Bind an immutable Sheets projection to its receipt and intent."""
        from .exact_cycle_planner import _digest
        from .exact_cycle_receipt import REPAIR_RETRY_PLAN_BINDING
        values = tuple(str(value).strip() for value in (
            local_plan_digest, projection_digest, receipt_id, intent_id, timestamp))
        if (not all(values) or not isinstance(projection, list)
                or delivery_mode not in {'write_once', 'observation_only'}):
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
            plan = json.loads(local[3])
            retry_binding = plan.get('selected_retry_receipt_binding')
            event_binding = plan.get('ordinary_company_event')
            if REPAIR_RETRY_PLAN_BINDING in plan:
                from .exact_cycle_planner import _exact_plan_digest
                from .sheet_profile import COMPACT_PROFILE

                binding = plan[REPAIR_RETRY_PLAN_BINDING]
                fields = {'request_id', 'company_id', 'source_revision',
                          'release_id', 'release_binding_sha256'}
                if (not isinstance(binding, dict) or set(binding) != fields
                        or not all(isinstance(value, str) and value == value.strip() and value
                                   for value in binding.values())
                        or re.fullmatch(r'company-retry:RTRY-[0-9a-f]{24}', binding['request_id']) is None
                        or re.fullmatch(r'[0-9a-f]{64}', binding['source_revision']) is None
                        or binding['company_id'] != company or receipt_binding != binding
                        or plan.get('exact_plan_version') != 2
                        or plan.get('publication_profile') != COMPACT_PROFILE
                        or plan.get('cycle_id') != cycle or plan.get('company_id') != company
                        or plan.get('plan_digest') != values[0] or _exact_plan_digest(plan) != values[0]
                        or any(key in plan for key in ('ordinary_company_event', 'selected_retry_receipt_binding',
                                                       'retained_membership_only', 'selected_legacy_control_before_prefix_recovery'))
                        or publication_receipts._receipt_id(binding) != values[2]
                        or delivery_mode != 'write_once'):
                    raise ValueError('Exact remote receipt does not match the repair retry plan.')
            elif event_binding is not None:
                from .exact_cycle_planner import _exact_plan_digest
                if (retry_binding is not None or _exact_plan_digest(plan) != values[0]
                        or receipt_binding != event_binding or event_binding.get('cycle_id') != cycle
                        or event_binding.get('company_id') != company
                        or event_binding.get('authority') != 'ordinary-company-event-exact-v2'
                        or delivery_mode != 'write_once'):
                    raise ValueError('Exact remote receipt does not match the ordinary event plan.')
            elif retry_binding is None:
                if (receipt_binding.get('request_id') != cycle
                        or receipt_binding.get('company_id') != company):
                    raise ValueError('Exact remote receipt names another request or company.')
            else:
                from .exact_cycle_planner import _exact_plan_digest
                if (_exact_plan_digest(plan) != values[0] or receipt_binding != retry_binding
                        or retry_binding.get('company_id') != company):
                    raise ValueError('Exact remote receipt does not match the selected retry plan.')
            row = self.connection.execute(
                'SELECT local_plan_digest,projection,projection_digest,receipt_id,intent_id,'
                'delivery_mode '
                'FROM exact_remote_plans WHERE cycle=? AND company=?',
                (cycle, company)).fetchone()
            expected = (values[0], encoded, values[1], values[2], values[3],
                        delivery_mode)
            if row is None:
                if receipt[1] == publication_receipts.SYNC_CONFIRMED:
                    raise ValueError('Exact remote registration rejects a pre-confirmed receipt.')
                self.connection.execute(
                    'INSERT INTO exact_remote_plans('
                    'cycle,company,local_plan_digest,projection,projection_digest,'
                    'receipt_id,intent_id,remote_cursor,state,first_attempt_claimed,'
                    'attempted_at,acknowledgement_id,created_at,updated_at,'
                    'delivery_mode,observed_at) '
                    "VALUES (?,?,?,?,?,?,?,0,'FROZEN',0,NULL,NULL,?,?,?,NULL)",
                    (cycle, company, *expected[:5], values[4], values[4],
                     delivery_mode))
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
                'remote_cursor,state,first_attempt_claimed,projection,delivery_mode '
                'FROM exact_remote_plans '
                'WHERE cycle=? AND company=?', (cycle, company)).fetchone()
            if remote is None or tuple(remote[:4]) != binding[:4]:
                raise ValueError('Exact remote attempt does not match its frozen intent.')
            if remote[8] != 'write_once':
                raise ValueError('Observation-only remote intent cannot claim a write.')
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

    def begin_exact_remote_observation(self, cycle, company, *,
                                       local_plan_digest, projection_digest,
                                       receipt_id, intent_id, cursor, count,
                                       chunk_digest, timestamp):
        """Journal a fresh read-only observation; never authorize a write."""
        from .exact_cycle_planner import _digest
        if type(cursor) is not int or type(count) is not int or cursor < 0 or count < 1:
            raise ValueError('Exact observation cursor/count is invalid.')
        binding = tuple(str(value).strip() for value in (
            local_plan_digest, projection_digest, receipt_id, intent_id,
            chunk_digest, timestamp))
        if not all(binding):
            raise ValueError('Exact observation binding is incomplete.')
        with self.lock, self.connection:
            remote = self.connection.execute(
                'SELECT local_plan_digest,projection_digest,receipt_id,intent_id,'
                'remote_cursor,state,first_attempt_claimed,projection,delivery_mode '
                'FROM exact_remote_plans WHERE cycle=? AND company=?',
                (cycle, company)).fetchone()
            if remote is None or tuple(remote[:4]) != binding[:4]:
                raise ValueError('Exact observation does not match its frozen intent.')
            if remote[8] != 'observation_only' or remote[6]:
                raise ValueError('Exact observation intent is not read-only.')
            if remote[4] != cursor or remote[5] not in {'FROZEN', 'SYNC_PENDING'}:
                raise ValueError('Exact observation cursor/state is invalid.')
            projection = json.loads(remote[7])
            if (cursor + count > len(projection)
                    or _digest(projection[cursor:cursor + count]) != binding[4]):
                raise ValueError('Exact observation projection slice changed.')
            receipt = self.connection.execute(
                'SELECT binding,state FROM publication_receipts WHERE receipt_id=?',
                (binding[2],)).fetchone()
            if receipt is None or receipt[1] not in {
                    publication_receipts.LOCAL_COMMITTED,
                    publication_receipts.SYNC_PENDING}:
                raise ValueError('Exact observation requires an unconfirmed receipt.')
            existing = self.connection.execute(
                'SELECT count,digest,state FROM exact_sync_chunks '
                'WHERE cycle=? AND company=? AND cursor=?',
                (cycle, company, cursor)).fetchone()
            if existing is not None and tuple(existing[:2]) != (count, binding[4]):
                raise ValueError('Exact observation chunk conflicts with durable evidence.')
            if receipt[1] == publication_receipts.LOCAL_COMMITTED:
                publication_receipts.mark_sync_pending(
                    self.connection, json.loads(receipt[0]), timestamp=binding[5])
            self.connection.execute(
                'INSERT OR IGNORE INTO exact_sync_chunks'
                '(cycle,company,cursor,count,digest,state) VALUES (?,?,?,?,?,?)',
                (cycle, company, cursor, count, binding[4], 'PENDING'))
            first_observation = existing is None
            self.connection.execute(
                "UPDATE exact_remote_plans SET state='SYNC_PENDING',"
                'observed_at=?,updated_at=? WHERE cycle=? AND company=? '
                "AND delivery_mode='observation_only' AND first_attempt_claimed=0",
                (binding[5], binding[5], cycle, company))
        return {**self.exact_remote_state(cycle, company),
                'first_observation': first_observation}

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
            if self.connection.execute(
                    'SELECT 1 FROM exact_legacy_plan_migrations '
                    'WHERE cycle=? AND company=?',
                    (cycle, company)).fetchone():
                raise ValueError('Exact legacy migration plans are immutable and cannot be discarded.')
            self.connection.execute("DELETE FROM sync_plans WHERE cycle=? AND company=?", (cycle, company))

    def unblock(self, cycle, company):
        with self.lock, self.connection:
            self.connection.execute("UPDATE inventories SET blocked=0 WHERE cycle=? AND company=?",
                                    (cycle, company))

    def close(self):
        self.connection.close()
