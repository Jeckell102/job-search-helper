"""Local authoritative records with transactional, coalesced Sheets delivery.

No Google client is constructed here. A separate synchronizer is the only
remote writer. Existing repository validation and keyed operation semantics
are retained, including protected application fields and literal ATS text.
"""
from __future__ import annotations

import copy
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import uuid

from .repository import (SCHEMAS, RepositoryError, _Sheet, _encoded, _equivalent,
                         _identity_key, _prepare, _scalar, _tab, _validate_headers)

IDENTIFIERS = {'Company', 'Company ID', 'Job Key', 'Source Hash', 'Official Job URL',
               'Job URL', 'Cycle ID', 'Opportunity ID'}
REVIEW_FIELDS = {'Added to Opportunities?', 'Review Status', 'Review Started At',
                 'Decision', 'Fit Level', 'Rejection Reason', 'Reconsideration Status'}


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), sort_keys=True)


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def identity_for(tab, row):
    if tab == 'Opportunities' and str(row.get('Opportunity ID', '')).strip():
        return {'Opportunity ID': row['Opportunity ID']}
    if tab == 'Companies':
        keys = ('Company ID',) if row.get('Company ID') else ('Company',)
    else:
        keys = {'Job History': ('Job Key',), 'Job Evidence': ('Job Key', 'Source Hash'),
                'Opportunities': ('Company', 'Job URL'), 'Scan Cycles': ('Cycle ID',)}[tab]
    identity = {key: row.get(key, '') for key in keys}
    if not all(str(value).strip() for value in identity.values()):
        raise RepositoryError(f'{tab}: incomplete stable identity; no row-number fallback is allowed.')
    if tab == 'Opportunities':
        # One posting can have several deliberately retained application records.
        # Never use mutable application decisions to distinguish those records.
        identity.update({h: row[h] for h in ('Job Title', 'Location', 'Work Arrangement')
                         if str(row.get(h, '')).strip()})
    return identity


class SQLiteRepository:
    """One connection per process; short IMMEDIATE transactions serialize writers."""
    is_local = True
    _committed_partial = True

    def __init__(self, path, spreadsheet_id, *, initialize=False, readonly=False,
                 require_ready=True):
        self.path = Path(path).resolve()
        self.spreadsheet_id = spreadsheet_id
        self.readonly = readonly
        self.metrics = {'local_transactions': 0, 'local_cell_changes': 0}
        self._committed_rows = {}
        if initialize and readonly:
            raise ValueError('Cannot initialize a read-only repository.')
        if not initialize and not self.path.is_file():
            raise RepositoryError('Local job database is missing. Run the explicit migration first.')
        if initialize:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        uri = self.path.as_uri() + ('?mode=ro' if readonly else '?mode=rwc' if initialize else '?mode=rw')
        self.db = sqlite3.connect(uri, uri=True, isolation_level=None, timeout=15)
        self.db.execute('PRAGMA busy_timeout=15000')
        self.db.execute('PRAGMA foreign_keys=ON')
        try:
            if initialize:
                self.db.execute('PRAGMA journal_mode=WAL')
                self.db.execute('PRAGMA synchronous=FULL')
                self._initialize()
            elif not readonly:
                self.db.execute('PRAGMA synchronous=FULL')
            if self.get_meta('version') != '1' or self.get_meta('spreadsheet_id') != spreadsheet_id:
                raise RepositoryError('Local database version or destination does not match this workbook.')
            if require_ready and not initialize and self.get_meta('ready') != 'yes':
                raise RepositoryError('Local migration is incomplete; refusing to use a partial database.')
            self.schemas = {tab: json.loads(headers) for tab, headers in self.db.execute('SELECT tab,headers FROM tabs')}
            self.validate_schema()
            if not readonly:
                from .review_revisions import install
                install(self.db)
                self.path.chmod(0o600)
        except BaseException:
            self.db.close()
            raise

    def _initialize(self):
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS tabs (tab TEXT PRIMARY KEY, headers TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS records (
          tab TEXT NOT NULL, row_id INTEGER NOT NULL, data TEXT NOT NULL,
          policies TEXT NOT NULL DEFAULT '{}', PRIMARY KEY(tab,row_id));
        CREATE TABLE IF NOT EXISTS lookups (
          tab TEXT NOT NULL, header TEXT NOT NULL, value TEXT NOT NULL, row_id INTEGER NOT NULL,
          PRIMARY KEY(tab,header,value,row_id),
          FOREIGN KEY(tab,row_id) REFERENCES records(tab,row_id) ON DELETE CASCADE);
        CREATE INDEX IF NOT EXISTS lookup_row ON lookups(tab,row_id);
        CREATE TABLE IF NOT EXISTS baseline (
          tab TEXT NOT NULL, row_id INTEGER NOT NULL, data TEXT NOT NULL,
          PRIMARY KEY(tab,row_id), FOREIGN KEY(tab,row_id) REFERENCES records(tab,row_id));
        CREATE TABLE IF NOT EXISTS dirty (
          tab TEXT NOT NULL, row_id INTEGER NOT NULL, header TEXT NOT NULL,
          PRIMARY KEY(tab,row_id,header), FOREIGN KEY(tab,row_id) REFERENCES records(tab,row_id));
        CREATE TABLE IF NOT EXISTS manual_choices (
          tab TEXT NOT NULL, row_id INTEGER NOT NULL, value TEXT NOT NULL, at TEXT NOT NULL,
          PRIMARY KEY(tab,row_id), FOREIGN KEY(tab,row_id) REFERENCES records(tab,row_id));
        CREATE TABLE IF NOT EXISTS conflicts (
          tab TEXT NOT NULL, row_id INTEGER NOT NULL, header TEXT NOT NULL,
          detail TEXT NOT NULL, at TEXT NOT NULL, PRIMARY KEY(tab,row_id,header));
        CREATE TABLE IF NOT EXISTS events (
          sequence INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL,
          kind TEXT NOT NULL, tab TEXT, row_id INTEGER, detail TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS delivery_attempts (
          tab TEXT NOT NULL, row_id INTEGER NOT NULL, data TEXT NOT NULL,
          PRIMARY KEY(tab,row_id));
        CREATE TABLE IF NOT EXISTS import_progress (
          source TEXT NOT NULL, tab TEXT NOT NULL, next_row INTEGER NOT NULL,
          complete INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(source,tab));
        ''')
        with self.transaction():
            old = self.get_meta('spreadsheet_id')
            if old and old != self.spreadsheet_id:
                raise RepositoryError('Refusing to initialize a database for another destination.')
            self.set_meta('version', '1')
            self.set_meta('spreadsheet_id', self.spreadsheet_id)
            for tab, headers in SCHEMAS.items():
                self.db.execute('INSERT OR IGNORE INTO tabs VALUES (?,?)', (tab, encode(headers)))

    @contextmanager
    def transaction(self):
        if self.readonly:
            raise RepositoryError('This repository was opened read-only.')
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def close(self):
        self.db.close()

    def get_meta(self, key):
        row = self.db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
        return row[0] if row else None

    def set_meta(self, key, value):
        self.db.execute('INSERT INTO meta VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                        (key, str(value)))

    def event(self, kind, tab='', row_id=0, detail=None):
        self.db.execute('INSERT INTO events(at,kind,tab,row_id,detail) VALUES (?,?,?,?,?)',
                        (timestamp(), kind, tab, row_id, encode(detail or {})))

    def conflict(self, tab, row_id, header, detail):
        self.db.execute('INSERT INTO conflicts VALUES (?,?,?,?,?) ON CONFLICT(tab,row_id,header) '
                        'DO UPDATE SET detail=excluded.detail,at=excluded.at',
                        (tab, row_id, header, detail, timestamp()))

    def validate_schema(self):
        for tab, required in SCHEMAS.items():
            _validate_headers(tab, self.schemas.get(tab, []), required)
        return True

    def ensure_tab(self, tab):
        _tab(tab)
        self.validate_schema()
        return {'created': False, 'added_headers': []}

    def ensure_columns(self, tab, headers):
        _tab(tab)
        added = [h for h in headers if h not in self.schemas[tab]]
        if added:
            with self.transaction():
                combined = [*self.schemas[tab], *added]
                _validate_headers(tab, combined, SCHEMAS[tab])
                self.db.execute('UPDATE tabs SET headers=? WHERE tab=?', (encode(combined), tab))
            self.schemas[tab] = combined
        return added

    def row(self, tab, row_id):
        result = self.db.execute('SELECT data FROM records WHERE tab=? AND row_id=?', (tab, row_id)).fetchone()
        return json.loads(result[0]) if result else None

    def matches(self, tab, identity):
        _tab(tab)
        if not identity or set(identity) - set(self.schemas[tab]):
            raise RepositoryError('Invalid lookup identity.')
        indexed = [(h, v) for h, v in identity.items() if h in IDENTIFIERS]
        if indexed:
            # Choose the most selective identity column, not a common Company label.
            order = {'Job Key': 0, 'Company ID': 0, 'Cycle ID': 0, 'Job URL': 1,
                     'Official Job URL': 1, 'Source Hash': 2, 'Company': 3}
            header, value = min(indexed, key=lambda pair: order.get(pair[0], 4))
            ids = [r[0] for r in self.db.execute('SELECT row_id FROM lookups WHERE tab=? AND header=? AND value=?',
                                                (tab, header, _identity_key(header, value)))]
            candidates = [(rid, self.row(tab, rid)) for rid in ids]
        else:
            candidates = [(rid, json.loads(data)) for rid, data in self.db.execute(
                'SELECT row_id,data FROM records WHERE tab=?', (tab,))]
        return [(rid, row) for rid, row in candidates if all(
            _equivalent(h, row.get(h, ''), value) for h, value in identity.items())]

    def _put(self, tab, row_id, row, policies=None):
        self.db.execute('INSERT INTO records(tab,row_id,data) VALUES (?,?,?) '
                        'ON CONFLICT(tab,row_id) DO UPDATE SET data=excluded.data', (tab, row_id, encode(row)))
        if policies is not None:
            self.db.execute('UPDATE records SET policies=? WHERE tab=? AND row_id=?', (encode(policies), tab, row_id))
        self.db.execute('DELETE FROM lookups WHERE tab=? AND row_id=?', (tab, row_id))
        self.db.executemany('INSERT INTO lookups VALUES (?,?,?,?)',
            [(tab, h, _identity_key(h, value), row_id) for h, value in row.items() if h in IDENTIFIERS and str(value).strip()])

    def _baseline(self, tab, row_id, row):
        self.db.execute('INSERT INTO baseline VALUES (?,?,?) ON CONFLICT(tab,row_id) DO UPDATE SET data=excluded.data',
                        (tab, row_id, encode(row)))

    def baseline(self, tab, row_id):
        result = self.db.execute('SELECT data FROM baseline WHERE tab=? AND row_id=?', (tab, row_id)).fetchone()
        return json.loads(result[0]) if result else None

    def mark_dirty(self, tab, row_id, headers):
        from .sheet_profile import profile_schemas
        publication = profile_schemas(self.get_meta('sheets_profile'))
        if publication is not None:
            headers = [h for h in headers if h in publication.get(tab, [])]
        self.db.executemany('INSERT OR IGNORE INTO dirty VALUES (?,?,?)', [(tab, row_id, h) for h in headers])

    def read(self, tab):
        _tab(tab)
        return [json.loads(data) for (data,) in self.db.execute('SELECT data FROM records WHERE tab=? ORDER BY row_id', (tab,))]

    def read_many(self, tabs):
        return {tab: self.read(tab) for tab in tabs}

    def read_columns(self, tab, headers):
        _tab(tab)
        if set(headers) - set(self.schemas[tab]):
            raise RepositoryError(f'{tab}: unknown requested columns.')
        expressions = ','.join('json_extract(data,?)' for _ in headers)
        paths = ['$.' + json.dumps(h) for h in headers]
        rows = self.db.execute(f'SELECT row_id,{expressions} FROM records WHERE tab=? ORDER BY row_id', (*paths, tab))
        result = []
        for values in rows:
            subset = {header: '' if value is None else value for header, value in zip(headers, values[1:])}
            if any(v != '' for v in subset.values()):
                result.append((values[0] + 1, subset))
        return result

    read_cached_columns = read_columns

    def read_row(self, tab, row_number):
        _tab(tab)
        if not isinstance(row_number, int) or row_number < 2:
            raise RepositoryError('Data row numbers must be >= 2.')
        return self.row(tab, row_number - 1) or {h: '' for h in self.schemas[tab]}

    def import_rows(self, tab, numbered_rows, *, policies=None, protect_existing_choices=False):
        """Idempotent bootstrap ONLY. Refuse to overwrite locally dirty records."""
        _tab(tab)
        count = 0
        with self.transaction():
            for remote_number, supplied in numbered_rows:
                row = {h: supplied.get(h, '') for h in self.schemas[tab]}
                for value in row.values():
                    _scalar(value)
                identity = identity_for(tab, row)
                matches = self.matches(tab, identity)
                if len(matches) > 1:
                    raise RepositoryError(f'{tab}: duplicate import identity.')
                row_id = matches[0][0] if matches else self.db.execute(
                    'SELECT COALESCE(MAX(row_id),0)+1 FROM records WHERE tab=?', (tab,)).fetchone()[0]
                if self.db.execute('SELECT 1 FROM dirty WHERE tab=? AND row_id=?', (tab, row_id)).fetchone():
                    raise RepositoryError('Bootstrap would overwrite local changes; stop and reconcile.')
                self._put(tab, row_id, row, (policies or {}).get(remote_number, {}))
                self._baseline(tab, row_id, row)
                if protect_existing_choices and tab == 'Job History' and str(row.get('Added to Opportunities?', '')).casefold() in {'yes', 'no'}:
                    self.db.execute('INSERT OR IGNORE INTO manual_choices VALUES (?,?,?,?)',
                                    (tab, row_id, row['Added to Opportunities?'], timestamp()))
                count += 1
        return count

    def commit(self, operations):
        operations = copy.deepcopy(list(operations))
        if not operations:
            return {'inserted': 0, 'updated': 0, 'new_jobs': [], 'requests': 0}
        with self.transaction():
            expanded = []
            for op in operations:
                if op.get('tab') == 'Opportunities' and 'Opportunity ID' in self.schemas['Opportunities']:
                    matches = self.matches('Opportunities', op.get('identity', {}))
                    if matches:
                        for _, row in matches:
                            if not row.get('Opportunity ID'):
                                raise RepositoryError('Opportunity is missing its permanent ID; reconcile before writing.')
                            scoped = copy.deepcopy(op)
                            scoped['identity'] = {'Opportunity ID': row['Opportunity ID']}
                            scoped['append_if_missing'] = False
                            expanded.append(scoped)
                        continue
                    if op.get('append_if_missing'):
                        op.setdefault('on_insert', {}).setdefault('Opportunity ID', 'OPP-' + uuid.uuid4().hex)
                expanded.append(op)
            operations = expanded
            sheets = {}
            for op in operations:
                tab = op.get('tab'); _tab(tab)
                if tab not in sheets:
                    tail = self.db.execute('SELECT COALESCE(MAX(row_id),0) FROM records WHERE tab=?', (tab,)).fetchone()[0]
                    sheets[tab] = _Sheet(list(self.schemas[tab]), append_floor=tail)
                matches = self.matches(tab, op.get('identity', {}))
                # Also include aliases that _prepare must examine before appending.
                proposed = {**op.get('on_insert', {}), **op.get('identity', {}), **op.get('values', {})}
                if tab == 'Job History' and proposed.get('Company') and proposed.get('Official Job URL'):
                    matches += self.matches(tab, {h: proposed[h] for h in ('Company', 'Official Job URL')})
                for rid, row in matches:
                    pin = self.db.execute('SELECT value FROM manual_choices WHERE tab=? AND row_id=?', (tab, rid)).fetchone()
                    if pin and tab == 'Job History':
                        proposed_values = op.get('values', {})
                        if proposed_values.get('Review Status') in {'In Progress', 'Reviewed', 'Manual Review'} and any(
                            h in proposed_values and not _equivalent(h, proposed_values[h], row.get(h, ''))
                            for h in ('Added to Opportunities?', 'Decision')):
                            raise RepositoryError('Manual Yes/No decision prevents automated review writeback.')
                        for group in ('values', 'expected'):
                            op[group] = {h: v for h, v in op.get(group, {}).items() if h not in REVIEW_FIELDS}
                    policies = json.loads(self.db.execute('SELECT policies FROM records WHERE tab=? AND row_id=?', (tab, rid)).fetchone()[0])
                    for col, header in enumerate(self.schemas[tab]):
                        encoded = _encoded(row.get(header, ''))
                        cell = {'userEnteredValue': encoded, 'effectiveValue': encoded}
                        cell.update(copy.deepcopy(policies.get(header, {})))
                        sheets[tab].cells[(rid, col)] = cell
            changed, _, result = _prepare(sheets, self.schemas, operations)
            touched = {(tab, rid) for tab, rid, col in changed}
            self._committed_rows = {}
            for tab, rid in touched:
                sheet = sheets[tab]
                from .repository import _value
                row = {h: _value(sheet.cells.get((rid, col), {}), h) for col, h in enumerate(sheet.headers)}
                self._put(tab, rid, row)
                self.mark_dirty(tab, rid, [sheet.headers[col] for t, r, col in changed if t == tab and r == rid])
                self._committed_rows.setdefault(tab, []).append(row)
            self.metrics['local_transactions'] += 1
            self.metrics['local_cell_changes'] += len(changed)
        return {**result, 'requests': 0, 'local_changes': len(changed)}

    def status(self):
        return {'ready': self.get_meta('ready') == 'yes', 'spreadsheet_id': self.spreadsheet_id,
                'records': dict(self.db.execute('SELECT tab,COUNT(*) FROM records GROUP BY tab')),
                'pending_cells': self.db.execute('SELECT COUNT(*) FROM dirty').fetchone()[0],
                'pending_rows': self.db.execute('SELECT COUNT(*) FROM (SELECT DISTINCT tab,row_id FROM dirty)').fetchone()[0],
                'conflicts': self.db.execute('SELECT COUNT(*) FROM conflicts').fetchone()[0],
                'last_sync': self.get_meta('last_sync'), 'last_error': self.get_meta('last_error')}

    def backup(self, destination):
        target = Path(destination).resolve()
        if target == self.path or target.exists():
            raise RepositoryError('Backup destination must be a new, separate file.')
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        connection = sqlite3.connect(target)
        try:
            self.db.backup(connection, pages=512, sleep=.01)
            if connection.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise RepositoryError('Backup integrity check failed.')
        finally:
            connection.close()
            target.chmod(0o600)
        return str(target)
