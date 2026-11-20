"""Local authoritative records with transactional, coalesced Sheets delivery.

No Google client is constructed here. A separate synchronizer is the only
remote writer. Existing repository validation and keyed operation semantics
are retained, including protected application fields and literal ATS text.
"""
from __future__ import annotations

import copy
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
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
                self._ensure_exact_local_schema()
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
        CREATE TABLE IF NOT EXISTS scrape_outcome_delivery_receipts (
          consumer TEXT NOT NULL, outcome_id TEXT NOT NULL, record_sha256 TEXT NOT NULL,
          receipt TEXT NOT NULL, receipt_sha256 TEXT NOT NULL, created_at TEXT NOT NULL,
          PRIMARY KEY(consumer,outcome_id),
          FOREIGN KEY(outcome_id) REFERENCES scrape_outcomes(outcome_id));
        CREATE TABLE IF NOT EXISTS scrape_outcome_delivery_attempts (
          consumer TEXT NOT NULL, outcome_id TEXT NOT NULL, record_sha256 TEXT NOT NULL,
          attempt_count INTEGER NOT NULL, state TEXT NOT NULL, next_attempt_at REAL,
          error_code TEXT, updated_at TEXT NOT NULL,
          PRIMARY KEY(consumer,outcome_id),
          FOREIGN KEY(outcome_id) REFERENCES scrape_outcomes(outcome_id));
        ''')

    def _ensure_exact_local_schema(self):
        """Install additive exact-application journals without touching rows."""
        if self.readonly:
            raise RepositoryError('Exact local schema requires a writable repository.')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS exact_local_applications (
          apply_id TEXT PRIMARY KEY,
          cycle TEXT NOT NULL,
          company TEXT NOT NULL,
          plan_digest TEXT NOT NULL UNIQUE,
          inventory_payload_digest TEXT NOT NULL,
          local_operations_digest TEXT NOT NULL,
          remote_projection_digest TEXT NOT NULL,
          row_scope TEXT NOT NULL,
          created_at TEXT NOT NULL,
          verified_at TEXT,
          state TEXT NOT NULL CHECK(state IN ('APPLYING','VERIFIED'))
        );
        CREATE UNIQUE INDEX IF NOT EXISTS exact_local_application_company
          ON exact_local_applications(cycle,company);
        CREATE TABLE IF NOT EXISTS exact_local_apply_chunks (
          apply_id TEXT NOT NULL,
          start_cursor INTEGER NOT NULL,
          operation_count INTEGER NOT NULL,
          operations_digest TEXT NOT NULL,
          before_records TEXT NOT NULL,
          expected_records TEXT NOT NULL,
          expected_records_digest TEXT NOT NULL,
          dirty_before TEXT NOT NULL,
          applied_at TEXT NOT NULL,
          verified_at TEXT,
          state TEXT NOT NULL CHECK(state IN ('APPLIED','VERIFIED')),
          PRIMARY KEY(apply_id,start_cursor),
          FOREIGN KEY(apply_id) REFERENCES exact_local_applications(apply_id)
        );
        CREATE TABLE IF NOT EXISTS exact_local_acknowledgements (
          apply_id TEXT NOT NULL,
          receipt_id TEXT NOT NULL,
          acknowledgement_id TEXT NOT NULL,
          selected_fields_digest TEXT NOT NULL,
          acknowledged_at TEXT NOT NULL,
          PRIMARY KEY(apply_id,receipt_id),
          FOREIGN KEY(apply_id) REFERENCES exact_local_applications(apply_id)
        );
        ''')

    def apply_exact_local_plan(self, cycle_id, company_id, plan, cursor,
                               *, max_operations=100, reservation_digest=None):
        """Apply one explicit exact chunk; never discover another company."""
        from .exact_local_plan import apply_exact_local_chunk
        return apply_exact_local_chunk(
            self, cycle_id, company_id, plan, cursor,
            max_operations=max_operations,
            reservation_digest=reservation_digest)

    def verify_exact_local_plan(self, cycle_id, company_id, plan, cursor=None):
        """Verify one chunk or the complete explicit exact application."""
        from .exact_local_plan import verify_exact_local_chunk, verify_exact_local_plan
        if cursor is None:
            return verify_exact_local_plan(self, cycle_id, company_id, plan)
        return verify_exact_local_chunk(self, cycle_id, company_id, plan, cursor)

    def adopt_verified_legacy_local_plan(self, cycle_id, company_id, plan,
                                         *, timestamp_value,
                                         delivery_evidence=None):
        """Journal a reviewed completed legacy prefix without replaying it."""
        from .exact_local_plan import adopt_verified_legacy_local_plan
        return adopt_verified_legacy_local_plan(
            self, cycle_id, company_id, plan,
            timestamp_value=timestamp_value,
            delivery_evidence=delivery_evidence)

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

    def read_company_columns(self, tab, headers, company):
        """Reload one company's planning inputs without scanning other companies."""
        _tab(tab)
        if set(headers) - set(self.schemas[tab]):
            raise RepositoryError(f'{tab}: unknown requested columns.')
        expressions = ','.join('json_extract(data,?)' for _ in headers)
        paths = ['$.' + json.dumps(h) for h in headers]
        rows = self.db.execute(
            f'SELECT row_id,{expressions} FROM records WHERE tab=? AND row_id IN '
            '(SELECT row_id FROM lookups WHERE tab=? AND header=? AND value=?) ORDER BY row_id',
            (*paths, tab, tab, 'Company', _identity_key('Company', company)))
        return [(values[0] + 1, {h: '' if v is None else v for h, v in zip(headers, values[1:])})
                for values in rows]

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

    def prepare_external_company_event_bootstrap(self, numbered_rows):
        """Durably freeze the first observed Sheets Company watermark.

        The snapshot is written *before* its rows are merged locally.  A crash
        between import and baseline completion therefore resumes from this
        original external watermark and reconciles the later pull as a real
        change, rather than silently treating it as history.
        """
        if self.readonly:
            raise RepositoryError('This repository was opened read-only.')
        if not self._company_event_tables_present():
            raise RepositoryError('Company event schema is unavailable; reopen writable to migrate first.')
        if self.get_meta('company_event_external_baseline') == 'yes':
            return {'prepared': False, 'companies': 0}
        from .company_events import INELIGIBLE_STATUSES, canonical_company_fact, source_revision
        frozen = {}
        # Ineligible rows do not need an external ID to be safely excluded
        # from initial intake.  Keep their frozen source fields separately so
        # the locally assigned helper ID can be seeded at finish, not emitted
        # as a brand-new withdrawal/ineligible event.
        excluded = {}
        for _number, row in numbered_rows:
            company_id = str(row.get('Company ID', '') or '').strip()
            status = str(row.get('Company Status', 'Active') or 'Active').strip().casefold()
            careers_url = str(row.get('Official Careers URL', '') or '').strip()
            if not company_id and careers_url and status not in INELIGIBLE_STATUSES:
                # A local helper assignment is not an external identity.  Do
                # not merge or watermark this eligible historical record: it
                # could otherwise be promoted as a newly added Company.
                raise RepositoryError('External Company bootstrap requires a stable Company ID for every eligible row.')
            if not company_id:
                name = str(row.get('Company', '') or '').strip()
                if name:
                    item = {
                        'company': name,
                        'company_status': status,
                        'official_careers_url': careers_url,
                        'ats_source': str(row.get('ATS / Source', '') or '').strip().casefold(),
                    }
                    identity = 'name:' + _identity_key('Company', name)
                    if identity in excluded:
                        raise RepositoryError('External Company bootstrap has duplicate ID-less Company names.')
                    excluded[identity] = item
                continue
            fact = canonical_company_fact(row)
            item = {'company_id': company_id, 'source_revision': source_revision(row), 'fact': fact}
            identity = 'id:' + company_id
            # A repeated external identifier is ambiguous even when the
            # currently visible fields happen to be identical.  Refuse to
            # establish a baseline rather than silently choose a row.
            if identity in frozen:
                raise RepositoryError('External Company bootstrap has duplicate Company IDs.')
            frozen[identity] = item
        key = 'company_event_external_bootstrap_pending'
        excluded_key = 'company_event_external_bootstrap_excluded'
        encoded = encode([frozen[identity] for identity in sorted(frozen)])
        encoded_excluded = encode([excluded[identity] for identity in sorted(excluded)])
        with self.transaction():
            if self.get_meta('company_event_external_baseline') == 'yes':
                return {'prepared': False, 'companies': 0}
            existing = self.get_meta(key)
            if existing is None:
                self.set_meta(key, encoded)
                self.set_meta(excluded_key, encoded_excluded)
                self.event('company_event_external_bootstrap_prepared', 'Companies', 0,
                           {'companies': len(frozen), 'excluded': len(excluded)})
            elif existing != encoded:
                # Keep the first observed snapshot.  The caller's newer read
                # is deliberately merged and later reconciled against it.
                try:
                    parsed = json.loads(existing)
                except (TypeError, ValueError) as error:
                    raise RepositoryError('External Company bootstrap watermark is corrupt.') from error
                return {'prepared': False, 'companies': len(parsed), 'resumed': True}
        return {'prepared': True, 'companies': len(frozen)}

    def finish_external_company_event_bootstrap(self):
        """Install the frozen watermark; never enqueue its historical rows."""
        if self.readonly:
            raise RepositoryError('This repository was opened read-only.')
        key = 'company_event_external_bootstrap_pending'
        excluded_key = 'company_event_external_bootstrap_excluded'
        if self.get_meta('company_event_external_baseline') == 'yes':
            return {'bootstrapped': False, 'seeded': 0}
        with self.transaction():
            raw = self.get_meta(key)
            if raw is None:
                raise RepositoryError('External Company bootstrap watermark is missing.')
            try:
                snapshot = json.loads(raw)
            except (TypeError, ValueError) as error:
                raise RepositoryError('External Company bootstrap watermark is corrupt.') from error
            if not isinstance(snapshot, list):
                raise RepositoryError('External Company bootstrap watermark is corrupt.')
            raw_excluded = self.get_meta(excluded_key)
            if raw_excluded is None:
                raise RepositoryError('External Company bootstrap watermark is corrupt.')
            try:
                excluded = json.loads(raw_excluded)
            except (TypeError, ValueError) as error:
                raise RepositoryError('External Company bootstrap watermark is corrupt.') from error
            if not isinstance(excluded, list):
                raise RepositoryError('External Company bootstrap watermark is corrupt.')
            # Validate duplicate stable identities before inserting even the
            # first revision.  A tampered pending snapshot must roll back as a
            # whole, including when the duplicate carries identical facts.
            pending_ids = set()
            for item in snapshot:
                if isinstance(item, dict) and isinstance(item.get('company_id'), str):
                    company_id = item['company_id']
                    if company_id in pending_ids:
                        raise RepositoryError('External Company bootstrap watermark is corrupt.')
                    pending_ids.add(company_id)
            seeded = 0
            from .company_events import canonical_company_fact, source_revision
            for item in snapshot:
                if (not isinstance(item, dict) or set(item) != {'company_id', 'source_revision', 'fact'}
                        or not isinstance(item['company_id'], str) or not item['company_id']
                        or not isinstance(item['source_revision'], str)
                        or len(item['source_revision']) != 64
                        or any(char not in '0123456789abcdef' for char in item['source_revision'])
                        or not isinstance(item['fact'], dict)):
                    raise RepositoryError('External Company bootstrap watermark is corrupt.')
                company_id = item['company_id']
                fact = item['fact']
                try:
                    reconstructed = canonical_company_fact({
                        'Company ID': company_id,
                        'Company Status': fact.get('company_status'),
                        'Official Careers URL': fact.get('official_careers_url'),
                        'ATS / Source': fact.get('ats_source'),
                    })
                except (RepositoryError, TypeError, ValueError) as error:
                    raise RepositoryError('External Company bootstrap watermark is corrupt.') from error
                if reconstructed != fact or source_revision({
                        'Company ID': company_id,
                        'Company Status': fact.get('company_status'),
                        'Official Careers URL': fact.get('official_careers_url'),
                        'ATS / Source': fact.get('ats_source'),
                }) != item['source_revision']:
                    raise RepositoryError('External Company bootstrap watermark is corrupt.')
                exists = self.db.execute(
                    'SELECT 1 FROM company_revisions WHERE company_id=? LIMIT 1',
                    (company_id,)).fetchone()
                if exists:
                    continue
                self.db.execute(
                    'INSERT INTO company_revisions(company_id,revision,source_revision,eligible,fact,created_at) '
                    'VALUES (?,?,?,?,?,?)',
                    (company_id, 1, item['source_revision'], int(fact['eligible']), encode(fact), timestamp()),
                )
                seeded += 1
            seen_excluded = set()
            for item in excluded:
                if (not isinstance(item, dict)
                        or set(item) != {'company', 'company_status', 'official_careers_url', 'ats_source'}
                        or not all(isinstance(item[field], str) for field in item)
                        or not item['company'].strip()):
                    raise RepositoryError('External Company bootstrap watermark is corrupt.')
                identity = _identity_key('Company', item['company'])
                if identity in seen_excluded:
                    raise RepositoryError('External Company bootstrap watermark is corrupt.')
                seen_excluded.add(identity)
                matches = self.matches('Companies', {'Company': item['company']})
                if len(matches) != 1:
                    raise RepositoryError('External Company bootstrap excluded row is ambiguous.')
                current = matches[0][1]
                company_id = str(current.get('Company ID', '') or '').strip()
                if not company_id:
                    raise RepositoryError('External Company bootstrap excluded row lacks assigned ID.')
                frozen_company = {
                    'Company ID': company_id,
                    'Company Status': item['company_status'],
                    'Official Careers URL': item['official_careers_url'],
                    'ATS / Source': item['ats_source'],
                }
                try:
                    fact = canonical_company_fact(frozen_company)
                    digest = source_revision(frozen_company)
                except (RepositoryError, TypeError, ValueError) as error:
                    raise RepositoryError('External Company bootstrap watermark is corrupt.') from error
                if fact['eligible']:
                    raise RepositoryError('External Company bootstrap watermark is corrupt.')
                exists = self.db.execute(
                    'SELECT 1 FROM company_revisions WHERE company_id=? LIMIT 1',
                    (company_id,)).fetchone()
                if exists:
                    continue
                self.db.execute(
                    'INSERT INTO company_revisions(company_id,revision,source_revision,eligible,fact,created_at) '
                    'VALUES (?,?,?,?,?,?)',
                    (company_id, 1, digest, int(fact['eligible']), encode(fact), timestamp()),
                )
                seeded += 1
            self.set_meta('company_event_external_baseline', 'yes')
            self.db.execute('DELETE FROM meta WHERE key=?', (key,))
            self.db.execute('DELETE FROM meta WHERE key=?', (excluded_key,))
            self.event('company_event_external_baseline', 'Companies', 0,
                       {'seeded': seeded, 'watermark': 'frozen-external-snapshot'})
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
        """Public generic outcome writer; closed mapping evidence is sealed."""
        if (isinstance(facts, dict) and isinstance(facts.get('cycle_id'), str)
                and facts['cycle_id'].startswith('CYC-R')):
            raise RepositoryError('Retained outcomes require the sealed event writer.')
        reserved = {'capability_id', 'capability_digest', 'mapping_digest', 'configuration_digest'}
        if (isinstance(facts, dict) and (reserved & set(facts)
                or isinstance(facts.get('failure'), dict)
                and facts['failure'].get('category') == 'same_provider_source_mapping')):
            raise RepositoryError('Source-configuration mapping outcomes require the sealed ordinary writer.')
        return self._record_scrape_outcome(facts)

    def record_retained_event_outcome(self, request_sha256, reservation_digest):
        """Record a retained event only from its durable archived authorities."""
        from contextlib import closing
        from .retained_event_outcome import retained_event_outcome_facts

        with closing(SQLiteRepository(self.path, self.spreadsheet_id, readonly=True)) as reader:
            facts, existing = retained_event_outcome_facts(reader, request_sha256, reservation_digest)
        if existing is not None:
            return existing
        return self._record_scrape_outcome(facts, owned_company_event=True)['outcome']

    def record_sealed_source_configuration_outcome(self, cycle_id, company_id, *, storage_confirmed):
        """Build and persist a sealed ordinary outcome from durable evidence.

        This intentionally takes no outcome facts, digest, callback, or
        caller-supplied readback.  It imports the closed producer only after
        entering the repository boundary, so a generic producer cannot forge
        the new category or its immutable identity fields.
        """
        if type(storage_confirmed) is not bool:
            raise RepositoryError('Sealed source-configuration storage confirmation must be explicit.')
        from .scrape_outcome_producer import _sealed_mapping_evidence, normal_cycle_outcome_facts
        try:
            loaded = self._source_configuration_evidence(cycle_id, company_id)
            if not isinstance(loaded, tuple) or len(loaded) != 2:
                raise RepositoryError('Owned source-configuration evidence is unavailable.')
            cycle, item = loaded
            rows = self.matches('Companies', {'Company ID': company_id})
            if len(rows) != 1:
                raise RepositoryError('Current Company identity is unavailable.')
            _row_number, company = rows[0]
            sealed = _sealed_mapping_evidence(self, cycle, company, item)
            if sealed is None:
                raise RepositoryError('Sealed source-configuration evidence is unavailable.')
            facts = normal_cycle_outcome_facts(cycle, company, item,
                                               storage_confirmed=storage_confirmed)
            facts.update(sealed)
        except (TypeError, ValueError, KeyError) as exc:
            raise RepositoryError('Sealed source-configuration outcome is malformed.') from exc
        identity = (facts['request_id'], facts['company_id'], facts['source_revision'], facts['cycle_id'])
        # A terminal unknown is deliberately sticky for this exact cycle and
        # frozen source.  A reopened process cannot improve it after a later
        # matrix/snapshot observation appears.
        rows = self.db.execute('SELECT payload FROM scrape_outcomes WHERE company_id=? AND source_revision=?',
                               (identity[1], identity[2])).fetchall()
        for (payload,) in rows:
            try:
                stored = json.loads(payload)
                stored_identity = stored.get('identity', {})
            except (TypeError, ValueError):
                continue
            if (stored.get('outcome') == 'UNKNOWN_CAPABILITY_HOLD'
                    and tuple(stored_identity.get(key) for key in (
                        'request_id', 'company_id', 'source_revision', 'cycle_id')) == identity):
                return {'outcome_id': stored.get('outcome_id'), 'recorded': False,
                        'outcome': stored}
        return self._record_scrape_outcome(facts)

    def _source_configuration_evidence(self, cycle_id, company_id):
        """Read one owned cycle item from the fixed sibling State database.

        No path, connection, callback, cycle, item, or evidence object is
        accepted from the sealed-writer caller.  Non-default deployments that
        do not use the fixed sibling State layout safely remain unqualified.
        """
        if (not isinstance(cycle_id, str) or not cycle_id
                or not isinstance(company_id, str) or not company_id):
            return None
        state_path = self.path.parent / 'state.db'
        if not state_path.is_file() or state_path.is_symlink():
            return None
        connection = None
        try:
            connection = sqlite3.connect(state_path.resolve().as_uri() + '?mode=ro', uri=True, timeout=5)
            connection.execute('PRAGMA query_only=ON')
            row = connection.execute('SELECT data FROM cycles WHERE id=?', (cycle_id,)).fetchone()
            cycle = json.loads(row[0]) if row else None
        except (OSError, sqlite3.Error, TypeError, ValueError):
            return None
        finally:
            if connection is not None:
                connection.close()
        item = cycle.get('companies', {}).get(company_id) if isinstance(cycle, dict) else None
        if (not isinstance(item, dict) or cycle.get('id') != cycle_id
                or cycle.get('company_event') is not None):
            return None
        return cycle, item

    def _record_scrape_outcome(self, facts, *, owned_company_event=False):
        """Classify bounded facts and persist the resulting outcome, without dispatch.

        Callers cannot supply their own outcome ID, action, or identity.  The
        local classifier reconstructs that immutable record, so the audit log
        never becomes a carrier for raw/private details or invented actions.
        """
        if self.readonly:
            raise RepositoryError('This repository was opened read-only.')
        with self.transaction():
            return self._record_scrape_outcome_in_transaction(facts, owned_company_event=owned_company_event)

    def _record_scrape_outcome_in_transaction(self, facts, *, owned_company_event=False,
                                              owned_selected_retry=False, recorded_at=None):
        """Write the classified outcome as part of its owner's Jobs transaction."""
        if not self.db.in_transaction:
            raise RepositoryError('Scrape outcome storage requires an active transaction.')
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
        if not owned_selected_retry:
            from .selected_retry_lifecycle import assert_generic_outcome_not_selected
            assert_generic_outcome_not_selected(self, identity)
        public_identity = dict(identity)
        payload = {
            'outcome_id': outcome['outcome_id'], 'outcome': outcome['outcome'],
            'action': outcome['action'], 'identity': public_identity,
            'failure_fingerprint': outcome['failure_fingerprint'],
        }
        if outcome.get('repair_category') == 'same_provider_source_mapping':
            capability_fields = ('capability_id', 'capability_digest', 'mapping_digest',
                                 'configuration_digest')
            if any(key not in outcome for key in capability_fields):
                raise RepositoryError('Sealed mapping outcome has incomplete immutable identity.')
            for key in capability_fields:
                public_identity.pop(key, None)
            payload.update({key: outcome[key] for key in capability_fields})
        # New M4 profile selection needs the deterministic repair category,
        # while existing category-less M3 records remain a valid held/manual
        # intake format.  The classifier, not a caller, supplies this field.
        if 'repair_category' in outcome:
            payload['repair_category'] = outcome['repair_category']
        if 'comparison' in outcome:
            payload['comparison'] = outcome['comparison']
        from .outcomes import validate_public_outcome_record
        encoded = encode(payload)
        request_id = identity['request_id']
        request_event = request_id.removeprefix('company-event:') if request_id.startswith('company-event:') else None
        declared_event = identity.get('company_event_id')
        event = None
        if request_event is not None or declared_event is not None:
            event = self.db.execute(
                'SELECT company_id,source_revision,kind FROM company_event_outbox WHERE event_id IN (?,?)',
                (request_event, declared_event),
            ).fetchone()
        if event is not None and not owned_company_event:
            raise RepositoryError('Company-event outcomes require a sealed event writer.')
        if owned_company_event:
            if (event != (identity['company_id'], identity['source_revision'], 'company.eligible')
                    or declared_event != request_event
                    or self.db.execute(
                        'SELECT 1 FROM scrape_outcomes WHERE request_id=? AND outcome_id<>?',
                        (identity['request_id'], outcome['outcome_id']),
                    ).fetchone()):
                raise RepositoryError('Company-event outcome conflicts with its durable ownership.')
        if validate_public_outcome_record(payload) is None:
            raise RepositoryError('Scrape outcome public record is malformed.')
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
             identity['source_revision'], outcome['outcome'], outcome['action'], encoded,
             recorded_at or timestamp()))
        self.event('scrape_outcome_recorded', '', 0,
                   {'outcome_id': outcome['outcome_id'], 'company_id': identity['company_id'],
                    'source_revision': identity['source_revision'], 'outcome': outcome['outcome']})
        return {'outcome_id': outcome['outcome_id'], 'recorded': True, 'outcome': payload}

    def scrape_outcomes(self, *, company_id=None, limit=100):
        """Read durable outcomes for review; this method never dispatches repairs."""
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 or limit > 1000:
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
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise RepositoryError('Scrape outcome limit must be between 1 and 1000.')
        # This is the only reserved repair handoff consumer. Stale evidence is
        # retained in the immutable ledger for audit, but may never be handed
        # to a repair coordinator or silently acknowledged/deleted.
        stale_filter = ''
        if consumer.strip() == 'repair-coordinator':
            stale_filter = " AND o.outcome != 'STALE_OR_PAUSED'"
        rows = self.db.execute(
            'SELECT o.payload FROM scrape_outcomes o LEFT JOIN scrape_outcome_deliveries d '
            'ON d.outcome_id=o.outcome_id AND d.consumer=? WHERE d.outcome_id IS NULL '
            + stale_filter + ' ORDER BY o.recorded_at,o.outcome_id LIMIT ?', (consumer.strip(), limit),
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
            row = self.db.execute('SELECT outcome FROM scrape_outcomes WHERE outcome_id=?',
                                  (outcome_id.strip(),)).fetchone()
            if not row:
                raise RepositoryError('Unknown scrape outcome.')
            if consumer.strip() == 'repair-coordinator' and row[0] == 'STALE_OR_PAUSED':
                raise RepositoryError('Repair coordinator may not acknowledge stale scrape outcomes.')
            self.db.execute('INSERT OR IGNORE INTO scrape_outcome_deliveries(outcome_id,consumer,acknowledged_at) '
                            'VALUES (?,?,?)', (outcome_id.strip(), consumer.strip(), timestamp()))
        return {'outcome_id': outcome_id.strip(), 'consumer': consumer.strip(), 'acknowledged': True}

    # Private source-neutral M3 delivery primitives.  They deliberately have
    # no knowledge of a coordinator, retry lineage, or scraper state.
    def _outcome_delivery_rows(self, consumer, *, outcome_id=None):
        query = (
            'SELECT o.outcome_id,o.payload,o.outcome,o.recorded_at,d.acknowledged_at,'
            'r.record_sha256,r.receipt,r.receipt_sha256,a.record_sha256,a.attempt_count,a.state,a.next_attempt_at,a.error_code '
            'FROM scrape_outcomes o LEFT JOIN scrape_outcome_deliveries d '
            'ON d.outcome_id=o.outcome_id AND d.consumer=? LEFT JOIN scrape_outcome_delivery_receipts r '
            'ON r.outcome_id=o.outcome_id AND r.consumer=? LEFT JOIN scrape_outcome_delivery_attempts a '
            'ON a.outcome_id=o.outcome_id AND a.consumer=?')
        parameters = (consumer, consumer, consumer)
        if outcome_id is not None:
            query += ' WHERE o.outcome_id=?'
            parameters += (outcome_id,)
        return self.db.execute(query + ' ORDER BY o.recorded_at,o.outcome_id', parameters).fetchall()

    def _reserve_outcome_delivery(self, consumer, outcome_id, digest, now, stamp):
        """Atomically reserve/reclaim one transport attempt; caller preflights."""
        with self.transaction():
            payload = self.db.execute('SELECT payload FROM scrape_outcomes WHERE outcome_id=?',
                                      (outcome_id,)).fetchone()
            if payload is None or hashlib.sha256(payload[0].encode('utf-8')).hexdigest() != digest:
                raise RepositoryError('Outcome delivery payload changed before reservation.')
            ack = self.db.execute('SELECT 1 FROM scrape_outcome_deliveries WHERE outcome_id=? AND consumer=?',
                                  (outcome_id, consumer)).fetchone()
            receipt = self.db.execute('SELECT 1 FROM scrape_outcome_delivery_receipts WHERE outcome_id=? AND consumer=?',
                                      (outcome_id, consumer)).fetchone()
            if ack or receipt:
                raise RepositoryError('Outcome delivery terminal state changed before reservation.')
            row = self.db.execute('SELECT record_sha256,attempt_count,state,next_attempt_at FROM scrape_outcome_delivery_attempts '
                                  'WHERE consumer=? AND outcome_id=?', (consumer, outcome_id)).fetchone()
            if row is None:
                self.db.execute('INSERT INTO scrape_outcome_delivery_attempts VALUES (?,?,?,?,?,?,?,?)',
                                (consumer, outcome_id, digest, 1, 'IN_FLIGHT', now + 300, None, stamp))
                return {'attempt_count': 1, 'reclaimed': False}
            old_digest, count, state, due = row
            if (old_digest != digest or type(count) is not int or not 1 <= count <= 16
                    or isinstance(due, bool) or state not in {'IN_FLIGHT', 'WAITING', 'HELD_RETRY_CAP'}
                    or (state in {'IN_FLIGHT', 'WAITING'}
                        and (not isinstance(due, (int, float)) or not math.isfinite(due)))
                    or (state == 'HELD_RETRY_CAP' and (count != 16 or due is not None))
                    or (state == 'WAITING' and count >= 16)):
                raise RepositoryError('Outcome delivery attempt changed before reservation.')
            if state == 'HELD_RETRY_CAP':
                return None
            if state == 'IN_FLIGHT':
                if due is None or due > now:
                    return None
                self.db.execute('UPDATE scrape_outcome_delivery_attempts SET next_attempt_at=?,updated_at=? '
                                'WHERE consumer=? AND outcome_id=?', (now + 300, stamp, consumer, outcome_id))
                return {'attempt_count': count, 'reclaimed': True}
            if state != 'WAITING' or due is None or due > now or count >= 16:
                return None
            self.db.execute('UPDATE scrape_outcome_delivery_attempts SET attempt_count=?,state=?,next_attempt_at=?,error_code=NULL,updated_at=? '
                            'WHERE consumer=? AND outcome_id=?',
                            (count + 1, 'IN_FLIGHT', now + 300, stamp, consumer, outcome_id))
            return {'attempt_count': count + 1, 'reclaimed': False}

    def _settle_outcome_delivery_failure(self, consumer, outcome_id, digest, now, stamp, error_code):
        with self.transaction():
            payload = self.db.execute('SELECT payload FROM scrape_outcomes WHERE outcome_id=?',
                                      (outcome_id,)).fetchone()
            terminal = self.db.execute('SELECT 1 FROM scrape_outcome_deliveries WHERE outcome_id=? AND consumer=?',
                                       (outcome_id, consumer)).fetchone()
            receipt = self.db.execute('SELECT 1 FROM scrape_outcome_delivery_receipts WHERE outcome_id=? AND consumer=?',
                                      (outcome_id, consumer)).fetchone()
            if (payload is None or hashlib.sha256(payload[0].encode('utf-8')).hexdigest() != digest
                    or terminal or receipt or error_code not in {'sink_unavailable', 'invalid_receipt'}):
                raise RepositoryError('Outcome delivery state changed before failure settlement.')
            row = self.db.execute('SELECT record_sha256,attempt_count,state FROM scrape_outcome_delivery_attempts '
                                  'WHERE consumer=? AND outcome_id=?', (consumer, outcome_id)).fetchone()
            if (row is None or row[0] != digest or type(row[1]) is not int
                    or not 1 <= row[1] <= 16 or row[2] != 'IN_FLIGHT'):
                raise RepositoryError('Outcome delivery reservation changed before failure settlement.')
            count = row[1]
            if count >= 16:
                values = ('HELD_RETRY_CAP', None, error_code, stamp, consumer, outcome_id)
            else:
                delay = min(3600, 30 * (2 ** (count - 1)))
                values = ('WAITING', now + delay, error_code, stamp, consumer, outcome_id)
            self.db.execute('UPDATE scrape_outcome_delivery_attempts SET state=?,next_attempt_at=?,error_code=?,updated_at=? '
                            'WHERE consumer=? AND outcome_id=?', values)

    def _complete_outcome_delivery(self, consumer, outcome_id, digest, receipt, receipt_sha256, stamp,
                                   *, expected_attempt_count=None):
        with self.transaction():
            payload = self.db.execute('SELECT payload,outcome FROM scrape_outcomes WHERE outcome_id=?',
                                      (outcome_id,)).fetchone()
            acknowledged = self.db.execute('SELECT 1 FROM scrape_outcome_deliveries WHERE outcome_id=? AND consumer=?',
                                           (outcome_id, consumer)).fetchone()
            existing = self.db.execute('SELECT record_sha256,receipt,receipt_sha256 FROM scrape_outcome_delivery_receipts '
                                       'WHERE consumer=? AND outcome_id=?', (consumer, outcome_id)).fetchone()
            attempt = self.db.execute('SELECT record_sha256,attempt_count,state FROM scrape_outcome_delivery_attempts '
                                      'WHERE consumer=? AND outcome_id=?', (consumer, outcome_id)).fetchone()
            try:
                decoded_receipt = json.loads(receipt)
                decoded_payload = json.loads(payload[0]) if payload is not None else None
            except (TypeError, ValueError) as exc:
                raise RepositoryError('Outcome delivery receipt is not canonical.') from exc
            # Enforce the complete receipt grammar again at the atomic trust
            # boundary.  Callers cannot fabricate an acknowledgement by
            # bypassing the public delivery adapter with merely canonical JSON.
            from .scrape_outcome_delivery import _valid_receipt
            from .outcomes import validate_public_outcome_record
            stale = payload is not None and payload[1] == 'STALE_OR_PAUSED'
            if (payload is None or validate_public_outcome_record(decoded_payload) is None
                    or payload[0] != encode(decoded_payload)
                    or hashlib.sha256(payload[0].encode('utf-8')).hexdigest() != digest
                    or receipt != encode(decoded_receipt)
                    or hashlib.sha256(receipt.encode('utf-8')).hexdigest() != receipt_sha256
                    or _valid_receipt(decoded_receipt, consumer, outcome_id, digest,
                                      stale=stale) is None):
                raise RepositoryError('Outcome delivery state changed before completion.')
            if acknowledged or existing:
                if acknowledged and existing == (digest, receipt, receipt_sha256) and attempt is None:
                    return False
                raise RepositoryError('Outcome delivery receipt and acknowledgement disagree.')
            suppression = decoded_receipt['disposition'] == 'STALE_SUPPRESSED'
            if suppression:
                if payload[1] != 'STALE_OR_PAUSED' or expected_attempt_count is not None or attempt is not None:
                    raise RepositoryError('Stale suppression has incompatible delivery state.')
            elif (payload[1] == 'STALE_OR_PAUSED' or type(expected_attempt_count) is not int
                    or attempt != (digest, expected_attempt_count, 'IN_FLIGHT')):
                raise RepositoryError('Accepted delivery does not match its exact reservation.')
            self.db.execute('INSERT INTO scrape_outcome_delivery_receipts VALUES (?,?,?,?,?,?)',
                            (consumer, outcome_id, digest, receipt, receipt_sha256, stamp))
            self.db.execute('INSERT OR IGNORE INTO scrape_outcome_deliveries(outcome_id,consumer,acknowledged_at) VALUES (?,?,?)',
                            (outcome_id, consumer, stamp))
            self.db.execute('DELETE FROM scrape_outcome_delivery_attempts WHERE consumer=? AND outcome_id=?',
                            (consumer, outcome_id))
            return True

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
