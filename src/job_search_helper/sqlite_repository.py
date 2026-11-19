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
                self._ensure_company_event_schema()
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

    def _ensure_company_event_schema(self):
        """Additive integration schema; never changes workbook records."""
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS company_revisions (
          company_id TEXT NOT NULL, revision INTEGER NOT NULL,
          source_revision TEXT NOT NULL, eligible INTEGER NOT NULL,
          fact TEXT NOT NULL, created_at TEXT NOT NULL,
          PRIMARY KEY(company_id, revision));
        CREATE TABLE IF NOT EXISTS company_event_outbox (
          event_id TEXT PRIMARY KEY, company_id TEXT NOT NULL,
          revision INTEGER NOT NULL, source_revision TEXT NOT NULL,
          kind TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL,
          UNIQUE(company_id, revision),
          FOREIGN KEY(company_id, revision) REFERENCES company_revisions(company_id, revision));
        CREATE TABLE IF NOT EXISTS company_event_deliveries (
          event_id TEXT NOT NULL, consumer TEXT NOT NULL, acknowledged_at TEXT NOT NULL,
          PRIMARY KEY(event_id, consumer),
          FOREIGN KEY(event_id) REFERENCES company_event_outbox(event_id));
        CREATE TABLE IF NOT EXISTS company_event_watermarks (
          consumer TEXT NOT NULL, company_id TEXT NOT NULL, revision INTEGER NOT NULL,
          source_revision TEXT NOT NULL, acknowledged_at TEXT NOT NULL,
          PRIMARY KEY(consumer, company_id));
        CREATE INDEX IF NOT EXISTS company_event_outbox_company ON company_event_outbox(company_id, revision);
        CREATE TABLE IF NOT EXISTS scrape_outcomes (
          outcome_id TEXT PRIMARY KEY, request_id TEXT NOT NULL, company_id TEXT NOT NULL,
          source_revision TEXT NOT NULL, outcome TEXT NOT NULL, action TEXT NOT NULL,
          payload TEXT NOT NULL, recorded_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS scrape_outcomes_company ON scrape_outcomes(company_id, source_revision, recorded_at);
        CREATE TABLE IF NOT EXISTS scrape_outcome_deliveries (
          outcome_id TEXT NOT NULL, consumer TEXT NOT NULL, acknowledged_at TEXT NOT NULL,
          PRIMARY KEY(outcome_id, consumer),
          FOREIGN KEY(outcome_id) REFERENCES scrape_outcomes(outcome_id));
        ''')

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
        with self.transaction():
            count, _ = self._import_rows_in_transaction(tab, numbered_rows, policies=policies,
                                                        protect_existing_choices=protect_existing_choices)
            return count

    def _import_rows_in_transaction(self, tab, numbered_rows, *, policies=None,
                                    protect_existing_choices=False, event_origin=None):
        _tab(tab)
        count = 0
        events = []
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
            before = self.row(tab, row_id) if matches else None
            self._put(tab, row_id, row, (policies or {}).get(remote_number, {}))
            self._baseline(tab, row_id, row)
            if event_origin and tab == 'Companies' and before != row:
                event = self._record_company_event(row, origin=event_origin)
                if event:
                    events.append(event)
            if protect_existing_choices and tab == 'Job History' and str(row.get('Added to Opportunities?', '')).casefold() in {'yes', 'no'}:
                self.db.execute('INSERT OR IGNORE INTO manual_choices VALUES (?,?,?,?)',
                                (tab, row_id, row['Added to Opportunities?'], timestamp()))
            count += 1
        return count, events

    def import_companies_with_events(self, numbered_rows, *, policies=None, origin='import'):
        """Import authoritative Company rows and outbox facts in one transaction.

        A caller must explicitly choose this API; plain bootstrap imports do
        not backfill the historical backlog into the live intake queue.
        """
        if self.readonly:
            raise RepositoryError('This repository was opened read-only.')
        if not isinstance(origin, str) or not origin.strip():
            raise RepositoryError('Company event origin is required.')
        if not self._company_event_tables_present():
            raise RepositoryError('Company event schema is unavailable; reopen writable to migrate first.')
        with self.transaction():
            count, events = self._import_rows_in_transaction('Companies', numbered_rows, policies=policies,
                                                               event_origin=origin)
        return {'imported': count, 'company_events': events}

    def bootstrap_company_event_reconciliation(self):
        """Seed external-intake revisions without treating old Companies as new.

        Sheets is an external source, so its first observed snapshot is a
        watermark, not a request to scrape the historical workbook. Later
        reconciliations compare against these durable revisions and create
        normal outbox events only for a real post-bootstrap change.
        """
        if self.readonly:
            raise RepositoryError('This repository was opened read-only.')
        if not self._company_event_tables_present():
            raise RepositoryError('Company event schema is unavailable; reopen writable to migrate first.')
        if self.get_meta('company_event_external_baseline') == 'yes':
            return {'bootstrapped': False, 'seeded': 0}
        seeded = 0
        with self.transaction():
            if self.get_meta('company_event_external_baseline') == 'yes':
                return {'bootstrapped': False, 'seeded': 0}
            from .company_events import canonical_company_fact, source_revision
            for company in self.read('Companies'):
                try:
                    fact = canonical_company_fact(company)
                except RepositoryError:
                    continue
                exists = self.db.execute(
                    'SELECT 1 FROM company_revisions WHERE company_id=? LIMIT 1',
                    (fact['company_id'],),
                ).fetchone()
                if exists:
                    continue
                digest = source_revision(company)
                self.db.execute(
                    'INSERT INTO company_revisions(company_id,revision,source_revision,eligible,fact,created_at) '
                    'VALUES (?,?,?,?,?,?)',
                    (fact['company_id'], 1, digest, int(fact['eligible']), encode(fact), timestamp()),
                )
                seeded += 1
            self.set_meta('company_event_external_baseline', 'yes')
            self.event('company_event_external_baseline', 'Companies', 0, {'seeded': seeded})
        return {'bootstrapped': True, 'seeded': seeded}

    def reconcile_external_company_events(self, *, origin='sheets-reconciliation'):
        """Emit durable events for authoritative Company rows changed after bootstrap."""
        if self.readonly:
            raise RepositoryError('This repository was opened read-only.')
        if not isinstance(origin, str) or not origin.strip():
            raise RepositoryError('Company event origin is required.')
        if not self._company_event_tables_present():
            raise RepositoryError('Company event schema is unavailable; reopen writable to migrate first.')
        if self.get_meta('company_event_external_baseline') != 'yes':
            raise RepositoryError('External Company reconciliation requires a completed baseline.')
        events = []
        with self.transaction():
            for company in self.read('Companies'):
                event = self._record_company_event(company, origin=origin)
                if event:
                    events.append(event)
        return {'reconciled': len(events), 'company_events': events}

    def commit(self, operations):
        operations = copy.deepcopy(list(operations))
        if not operations:
            return {'inserted': 0, 'updated': 0, 'new_jobs': [], 'requests': 0}
        with self.transaction():
            return self._commit_in_transaction(operations)

    def _commit_in_transaction(self, operations):
        """Apply normal repository operations inside an already-open transaction."""
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

    def _company_event_tables_present(self):
        return bool(self.db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='company_event_outbox'"
        ).fetchone())

    def _record_company_event(self, company, *, origin):
        """Record one semantic Company revision in the caller's transaction.

        The sequence is local and monotonic per Company ID.  The content hash
        is the portable source revision used by consumers to reject stale or
        reordered delivery; the sequence preserves a deliberate reactivation
        even when its content matches an older revision.
        """
        from .company_events import canonical_company_fact, event_kind, source_revision
        try:
            fact = canonical_company_fact(company)
        except RepositoryError:
            # Incomplete intake remains visible in Companies but cannot safely
            # enter the scrape queue.  A later complete mutation creates it.
            return None
        digest = source_revision(company)
        latest = self.db.execute(
            'SELECT revision,source_revision,eligible FROM company_revisions WHERE company_id=? '
            'ORDER BY revision DESC LIMIT 1', (fact['company_id'],)).fetchone()
        # A new incomplete entry waits for the required source fields.  Once a
        # Company has been eligible, however, removing its URL is a durable
        # withdrawal: an intake consumer must be able to supersede/cancel any
        # prior scoped request without guessing from a silent row mutation.
        if not fact['official_careers_url'] and (not latest or not latest[2]):
            return None
        if latest and latest[1] == digest:
            return None
        revision = (latest[0] + 1) if latest else 1
        event_id = 'CEV-' + uuid.uuid4().hex
        created_at = timestamp()
        payload = {'event_id': event_id, 'company_id': fact['company_id'], 'revision': revision,
                   'source_revision': digest, 'kind': event_kind(fact), 'origin': origin,
                   'company': str(company.get('Company', '') or '').strip(), 'fact': fact}
        self.db.execute('INSERT INTO company_revisions(company_id,revision,source_revision,eligible,fact,created_at) '
                        'VALUES (?,?,?,?,?,?)',
                        (fact['company_id'], revision, digest, int(fact['eligible']), encode(fact), created_at))
        self.db.execute('INSERT INTO company_event_outbox(event_id,company_id,revision,source_revision,kind,payload,created_at) '
                        'VALUES (?,?,?,?,?,?,?)',
                        (event_id, fact['company_id'], revision, digest, payload['kind'], encode(payload), created_at))
        self.event('company_event_enqueued', 'Companies', 0,
                   {'event_id': event_id, 'company_id': fact['company_id'], 'revision': revision,
                    'source_revision': digest, 'kind': payload['kind'], 'origin': origin})
        return payload

    def mutate_company_with_event(self, operation, *, origin='application'):
        """Atomically apply one supported Company mutation and enqueue its fact.

        This is intentionally opt-in: legacy ``commit`` and remote import
        callers keep their exact historical behavior until their reconciliation
        boundary is explicitly upgraded.  The mutation, Company revision, and
        outbox record either all commit or all roll back.
        """
        if self.readonly:
            raise RepositoryError('This repository was opened read-only.')
        if not self._company_event_tables_present():
            raise RepositoryError('Company event schema is unavailable; reopen writable to migrate first.')
        operation = copy.deepcopy(operation)
        if operation.get('tab') != 'Companies':
            raise RepositoryError('Company event mutations require the Companies tab.')
        if not isinstance(origin, str) or not origin.strip():
            raise RepositoryError('Company event origin is required.')
        with self.transaction():
            result = self._commit_in_transaction([operation])
            rows = self._committed_rows.get('Companies', [])
            if len(rows) > 1:
                raise RepositoryError('Company event mutation must resolve to one Company record.')
            event = self._record_company_event(rows[0], origin=origin) if rows else None
        return {**result, 'company_event': event}

    def record_scrape_outcome(self, facts):
        """Classify bounded facts and persist the resulting outcome, without dispatch.

        Callers cannot supply their own outcome ID, action, or identity.  The
        local classifier reconstructs that immutable record, so the audit log
        never becomes a carrier for raw/private details or invented actions.
        """
        if self.readonly:
            raise RepositoryError('This repository was opened read-only.')
        from .outcomes import OutcomeFactsError, classify_outcome
        try:
            outcome = classify_outcome(facts)
        except OutcomeFactsError as exc:
            raise RepositoryError(f'Invalid scrape outcome facts: {exc}') from exc
        identity = outcome.get('identity')
        required = ('outcome_id', 'outcome', 'action', 'failure_fingerprint')
        if (not isinstance(identity, dict)
                or any(not isinstance(outcome.get(key), str) or not outcome[key].strip() for key in required)
                or any(not isinstance(identity.get(key), str) or not identity[key].strip()
                       for key in ('request_id', 'company_id', 'source_revision'))):
            raise RepositoryError('Scrape outcome has incomplete immutable identity.')
        payload = {
            'outcome_id': outcome['outcome_id'], 'outcome': outcome['outcome'],
            'action': outcome['action'], 'identity': identity,
            'failure_fingerprint': outcome['failure_fingerprint'],
        }
        # New M4 profile selection needs the deterministic repair category,
        # while existing category-less M3 records remain a valid held/manual
        # intake format.  The classifier, not a caller, supplies this field.
        if 'repair_category' in outcome:
            payload['repair_category'] = outcome['repair_category']
        encoded = encode(payload)
        with self.transaction():
            existing = self.db.execute('SELECT payload FROM scrape_outcomes WHERE outcome_id=?',
                                       (outcome['outcome_id'],)).fetchone()
            if existing:
                if existing[0] != encoded:
                    raise RepositoryError('Scrape outcome ID conflicts with immutable stored evidence.')
                return {'outcome_id': outcome['outcome_id'], 'recorded': False, 'outcome': payload}
            self.db.execute(
                'INSERT INTO scrape_outcomes(outcome_id,request_id,company_id,source_revision,outcome,action,payload,recorded_at) '
                'VALUES (?,?,?,?,?,?,?,?)',
                (outcome['outcome_id'], identity['request_id'], identity['company_id'],
                 identity['source_revision'], outcome['outcome'], outcome['action'], encoded, timestamp()))
            self.event('scrape_outcome_recorded', '', 0,
                       {'outcome_id': outcome['outcome_id'], 'company_id': identity['company_id'],
                        'source_revision': identity['source_revision'], 'outcome': outcome['outcome']})
        return {'outcome_id': outcome['outcome_id'], 'recorded': True, 'outcome': payload}

    def scrape_outcomes(self, *, company_id=None, limit=100):
        """Read durable outcomes for review; this method never dispatches repairs."""
        if not isinstance(limit, int) or limit < 1 or limit > 1000:
            raise RepositoryError('Scrape outcome limit must be between 1 and 1000.')
        if company_id is not None and (not isinstance(company_id, str) or not company_id.strip()):
            raise RepositoryError('Company ID filter must be non-empty text.')
        # A read-only legacy database cannot be migrated.  Treat the additive
        # M3 ledger as absent rather than failing a status or audit read.
        present = self.db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='scrape_outcomes'"
        ).fetchone()
        if not present:
            return []
        if company_id is None:
            rows = self.db.execute('SELECT payload FROM scrape_outcomes ORDER BY recorded_at,outcome_id LIMIT ?',
                                   (limit,)).fetchall()
        else:
            rows = self.db.execute('SELECT payload FROM scrape_outcomes WHERE company_id=? '
                                   'ORDER BY recorded_at,outcome_id LIMIT ?', (company_id.strip(), limit)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def pending_scrape_outcomes(self, consumer, *, limit=100):
        """Return unacknowledged immutable outcomes for one repair consumer.

        Reading this outbox is non-mutating. A caller must acknowledge the
        exact immutable outcome only after the receiving system accepts it.
        """
        if not isinstance(consumer, str) or not consumer.strip():
            raise RepositoryError('Scrape outcome consumer is required.')
        if not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise RepositoryError('Scrape outcome limit must be between 1 and 1000.')
        rows = self.db.execute(
            'SELECT o.payload FROM scrape_outcomes o LEFT JOIN scrape_outcome_deliveries d '
            'ON d.outcome_id=o.outcome_id AND d.consumer=? WHERE d.outcome_id IS NULL '
            'ORDER BY o.recorded_at,o.outcome_id LIMIT ?', (consumer.strip(), limit),
        ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def acknowledge_scrape_outcome(self, outcome_id, consumer):
        """Record a consumer acknowledgement without changing the outcome."""
        if self.readonly:
            raise RepositoryError('This repository was opened read-only.')
        if not isinstance(outcome_id, str) or not outcome_id.strip():
            raise RepositoryError('Scrape outcome ID is required.')
        if not isinstance(consumer, str) or not consumer.strip():
            raise RepositoryError('Scrape outcome consumer is required.')
        with self.transaction():
            if not self.db.execute('SELECT 1 FROM scrape_outcomes WHERE outcome_id=?',
                                   (outcome_id.strip(),)).fetchone():
                raise RepositoryError('Unknown scrape outcome.')
            self.db.execute('INSERT OR IGNORE INTO scrape_outcome_deliveries(outcome_id,consumer,acknowledged_at) '
                            'VALUES (?,?,?)', (outcome_id.strip(), consumer.strip(), timestamp()))
        return {'outcome_id': outcome_id.strip(), 'consumer': consumer.strip(), 'acknowledged': True}

    def pending_company_events(self, consumer, *, limit=100):
        """Return unacknowledged outbox events in immutable per-company order."""
        if not isinstance(consumer, str) or not consumer.strip():
            raise RepositoryError('Company event consumer is required.')
        if not isinstance(limit, int) or limit < 1 or limit > 1000:
            raise RepositoryError('Company event limit must be between 1 and 1000.')
        if not self._company_event_tables_present():
            return []
        rows = self.db.execute(
            'SELECT o.payload FROM company_event_outbox o LEFT JOIN company_event_deliveries d '
            'ON d.event_id=o.event_id AND d.consumer=? LEFT JOIN company_event_watermarks w '
            'ON w.consumer=? AND w.company_id=o.company_id WHERE d.event_id IS NULL '
            'AND (w.revision IS NULL OR o.revision>w.revision) '
            'ORDER BY o.created_at,o.company_id,o.revision LIMIT ?',
            (consumer.strip(), consumer.strip(), limit)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def pending_latest_company_events(self, consumer, *, limit=100):
        """Return only the newest pending revision for each Company.

        This is deliberately separate from ``pending_company_events``. Other
        consumers may need history, while a scan request must never be created
        from an old page when a newer durable revision already exists.
        """
        if not isinstance(consumer, str) or not consumer.strip():
            raise RepositoryError('Company event consumer is required.')
        if not isinstance(limit, int) or limit < 1 or limit > 1000:
            raise RepositoryError('Company event limit must be between 1 and 1000.')
        if not self._company_event_tables_present():
            return []
        rows = self.db.execute(
            'WITH pending AS ('
            ' SELECT o.payload,o.company_id,o.revision,o.created_at FROM company_event_outbox o '
            ' LEFT JOIN company_event_deliveries d ON d.event_id=o.event_id AND d.consumer=? '
            ' LEFT JOIN company_event_watermarks w ON w.consumer=? AND w.company_id=o.company_id '
            ' WHERE d.event_id IS NULL AND (w.revision IS NULL OR o.revision>w.revision)'
            '), latest AS ('
            ' SELECT p.payload,p.company_id,p.revision,p.created_at FROM pending p '
            ' WHERE NOT EXISTS (SELECT 1 FROM pending newer '
            '                   WHERE newer.company_id=p.company_id AND newer.revision>p.revision)'
            ') SELECT payload FROM latest ORDER BY created_at,company_id,revision LIMIT ?',
            (consumer.strip(), consumer.strip(), limit),
        ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def acknowledge_company_event(self, event_id, consumer, *, source_revision=None):
        """Durably acknowledge a consumer only when its immutable event matches."""
        if self.readonly:
            raise RepositoryError('This repository was opened read-only.')
        if not isinstance(event_id, str) or not event_id.strip() or not isinstance(consumer, str) or not consumer.strip():
            raise RepositoryError('Company event ID and consumer are required.')
        if not self._company_event_tables_present():
            raise RepositoryError('Company event schema is unavailable; reopen writable to migrate first.')
        with self.transaction():
            row = self.db.execute('SELECT company_id,revision,source_revision FROM company_event_outbox WHERE event_id=?',
                                  (event_id,)).fetchone()
            if not row:
                raise RepositoryError('Unknown company event.')
            company_id, revision, actual_source_revision = row
            if source_revision is not None and source_revision != actual_source_revision:
                raise RepositoryError('Company event acknowledgement has a stale source revision.')
            watermark = self.db.execute(
                'SELECT revision,source_revision FROM company_event_watermarks WHERE consumer=? AND company_id=?',
                (consumer.strip(), company_id)).fetchone()
            if watermark and watermark[0] > revision:
                raise RepositoryError('Company event acknowledgement is stale for this consumer revision.')
            self.db.execute('INSERT OR IGNORE INTO company_event_deliveries(event_id,consumer,acknowledged_at) VALUES (?,?,?)',
                            (event_id, consumer.strip(), timestamp()))
            self.db.execute(
                'INSERT INTO company_event_watermarks(consumer,company_id,revision,source_revision,acknowledged_at) '
                'VALUES (?,?,?,?,?) ON CONFLICT(consumer,company_id) DO UPDATE SET '
                'revision=excluded.revision,source_revision=excluded.source_revision,acknowledged_at=excluded.acknowledged_at '
                'WHERE excluded.revision>company_event_watermarks.revision',
                (consumer.strip(), company_id, revision, actual_source_revision, timestamp()))
        return {'event_id': event_id, 'consumer': consumer.strip(), 'acknowledged': True}

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
