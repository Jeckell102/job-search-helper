"""Durable MuleLab task state and write-ahead tool receipts."""
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import sqlite3
import time
import uuid
from urllib.parse import urlsplit
from contextlib import contextmanager
import threading
from coordinator_inference import InferenceStore
from coordinator_campaign import CampaignStore, next_action
from coordinator_identity import bind_identity, validate_bound_identity
from coordinator_acceptance import initial_scope, validate_scope, exact_paths, digest as scope_digest


DEFAULT_CAMPAIGN_ID = 'integration-backlog-20261118'
HELD_FOR_CAMPAIGN = 'HELD_FOR_CAMPAIGN'
SELECTED = 'SELECTED'
USER_PAUSED = 'USER_PAUSED'
EXCLUDED = 'EXCLUDED'
# Group 6 will replace this coarse terminal bucket with reconciled outcomes.
# It is needed now so a completed selection cannot coexist with the next one.
CAMPAIGN_FINISHED = 'CAMPAIGN_FINISHED'
CAMPAIGN_DISPOSITIONS = frozenset({
    HELD_FOR_CAMPAIGN, SELECTED, USER_PAUSED, EXCLUDED, CAMPAIGN_FINISHED,
})
OPERATOR_GATE_STATUSES = frozenset({
    'AWAITING_LIVE_VALIDATION',
    'REVIEW_COMPLETE_LIVE_NOT_VALIDATED',
    'LIVE_VALIDATED',
})

OUTCOME_ACTIONS = {
    'STALE_OR_PAUSED': 'stop_stale_work',
    'STORAGE_OR_SYNC_FAILURE': 'reconcile_storage_only',
    'COMPLETE': 'save_without_repair',
    'BLOCKED': 'hold_for_policy_or_new_evidence',
    'TEMPORARY': 'retry_with_bounded_backoff',
    'QUALIFIED_INTEGRATION_REPAIR': 'upsert_qualified_repair',
    'UNKNOWN_CAPABILITY_HOLD': 'hold_for_engineering',
    'UNCLASSIFIED_HOLD': 'hold_without_invented_repair',
}
OUTCOME_IDENTITY_REQUIRED = frozenset({'request_id', 'company_id', 'source_revision'})
OUTCOME_IDENTITY_OPTIONAL = frozenset({
    'company_event_id', 'cycle_id', 'attempt_id', 'failed_request_id',
    'provider', 'adapter_version', 'release_version', 'release_binding_sha256', 'retained_reservation_sha256',
})
CONFIGURATION_IDENTITY_FIELDS = (
    'capability_id', 'capability_digest', 'mapping_digest', 'configuration_digest',
)
SOURCE_CONFIGURATION_MAPPING = 'same_provider_source_mapping'

# This ledger is deliberately an observation boundary.  It is not a release
# controller, a retry dispatcher, or a scraper control path.  Its only side
# effect is append-only coordinator evidence and a conservative derived state
# for an operator to inspect.
RETRY_LIFECYCLE_STATES = frozenset({
    'VALIDATED_COMPLETE', 'OBSERVED_HELD', 'ROLLBACK_REQUIRED',
    'RECONCILIATION_REQUIRED',
})

OUTCOME_DELIVERY_CONSUMER = 'repair-coordinator'
OUTCOME_DELIVERY_SCHEMA = 'outcome-delivery-receipt-v1'
OUTCOME_DELIVERY_STATUSES = frozenset({
    'RECORDED_NO_REPAIR', 'SUPERSEDED_BY_REPAIRED_RETRY',
    'HELD_FOR_REPAIR_TRIAGE', 'HELD_MISSING_REPAIR_CAPABILITY',
    'VALIDATED_COMPLETE', 'OBSERVED_HELD', 'ROLLBACK_REQUIRED',
    'RECONCILIATION_REQUIRED',
})


def _canonical_json(value):
    """The v1 delivery grammar is UTF-8 JSON, not a caller-provided blob."""
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def _sha256_text(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _outcome_delivery_receipt_id(consumer, outcome_id, record_sha256):
    material = _canonical_json({
        'schema': OUTCOME_DELIVERY_SCHEMA, 'consumer': consumer,
        'outcome_id': outcome_id, 'record_sha256': record_sha256,
    })
    return 'ODR-' + _sha256_text(material)[:24]


def campaign_manifest_digest(state):
    """Stable digest for the reviewed assignment entry, not runtime state."""
    entry = {key: state.get(key) for key in ('objective', 'tests', 'integration')}
    encoded = json.dumps(entry, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(encoded).hexdigest()


def task_state_digest(state):
    encoded = json.dumps(state, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(encoded).hexdigest()


def reached_operator_gate(state):
    """Terminal work cannot be reopened by pause/resume control transitions."""
    return (state.get('status') in OPERATOR_GATE_STATUSES
            or state.get('campaign_disposition') == CAMPAIGN_FINISHED and not state.get('campaign_outcome', '').startswith('PAUSED_'))


def canonical_scrape_outcome(value):
    """Verify the bounded M3 classifier record before coordinator intake.

    The coordinator receives a record, never arbitrary error text.  It verifies
    the deterministic identifier and action mapping before holding a possible
    repair for later reviewed assignment.  This method never creates a task.
    """
    legacy_keys = ({
            'outcome_id', 'outcome', 'action', 'identity', 'failure_fingerprint'}, {
            'outcome_id', 'outcome', 'action', 'identity', 'failure_fingerprint', 'repair_category'})
    mapping_keys = frozenset({
        'outcome_id', 'outcome', 'action', 'identity', 'failure_fingerprint',
        'repair_category', *CONFIGURATION_IDENTITY_FIELDS,
    })
    if not isinstance(value, dict) or set(value) not in (*legacy_keys, mapping_keys):
        raise ValueError('Scrape outcome has unsupported fields.')
    identity = value['identity']
    if not isinstance(identity, dict) or not OUTCOME_IDENTITY_REQUIRED <= set(identity) <= (
            OUTCOME_IDENTITY_REQUIRED | OUTCOME_IDENTITY_OPTIONAL):
        raise ValueError('Scrape outcome has invalid identity fields.')
    bounded = {}
    for key, item in identity.items():
        if not isinstance(item, str) or not item.strip() or len(item.strip()) > 256:
            raise ValueError('Scrape outcome identity must be bounded text.')
        bounded[key] = item.strip()
    if 'retained_reservation_sha256' in bounded or bounded.get('cycle_id', '').startswith('CYC-R'):
        from job_search_helper.outcomes import valid_retained_outcome_identity
        if not valid_retained_outcome_identity(bounded):
            raise ValueError('Scrape outcome retained event or reservation identity is invalid.')
    if 'company_event_id' in bounded or bounded['request_id'].startswith('company-event:'):
        from job_search_helper.outcomes import valid_company_event_outcome_identity
        if not valid_company_event_outcome_identity(bounded):
            raise ValueError('Scrape outcome Company event does not match its request ID.')
    retry_fields = ('attempt_id', 'failed_request_id', 'release_version',
                    'release_binding_sha256')
    present = [key for key in retry_fields if key in bounded]
    if present and set(present) != set(retry_fields):
        raise ValueError('Scrape outcome retry identity must bind attempt, failed request, release, and release binding together.')
    if all(key in bounded for key in retry_fields) and bounded['request_id'] == bounded['failed_request_id']:
        raise ValueError('Scrape outcome retry must use a fresh request identity.')
    if 'release_binding_sha256' in bounded and not re.fullmatch(r'[0-9a-f]{64}', bounded['release_binding_sha256']):
        raise ValueError('Scrape outcome retry release binding must be a lowercase SHA-256.')
    outcome, action, fingerprint = value['outcome'], value['action'], value['failure_fingerprint']
    if (not isinstance(outcome, str) or OUTCOME_ACTIONS.get(outcome) != action
            or not isinstance(fingerprint, str) or not re.fullmatch(r'[0-9a-f]{64}', fingerprint)):
        raise ValueError('Scrape outcome classification is invalid.')
    repair_category = value.get('repair_category')
    if repair_category is not None:
        if (outcome != 'QUALIFIED_INTEGRATION_REPAIR' or not isinstance(repair_category, str)
                or not re.fullmatch(r'[a-z_]{1,64}', repair_category)):
            raise ValueError('Scrape outcome repair category is invalid.')
    mapping = repair_category == SOURCE_CONFIGURATION_MAPPING
    configuration_present = [field for field in CONFIGURATION_IDENTITY_FIELDS if field in value]
    if mapping:
        if (outcome != 'QUALIFIED_INTEGRATION_REPAIR'
                or set(configuration_present) != set(CONFIGURATION_IDENTITY_FIELDS)):
            raise ValueError('Source-configuration mapping identity is incomplete.')
        capability_id = value['capability_id']
        if not isinstance(capability_id, str) or not re.fullmatch(r'[a-z0-9][a-z0-9._-]{0,95}', capability_id):
            raise ValueError('Source-configuration capability ID is invalid.')
        if any(not isinstance(value[field], str) or not re.fullmatch(r'[0-9a-f]{64}', value[field])
               for field in CONFIGURATION_IDENTITY_FIELDS[1:]):
            raise ValueError('Source-configuration digest is invalid.')
    elif configuration_present:
        raise ValueError('Source-configuration identity is reserved for mapping outcomes.')
    immutable = {'identity': bounded, 'failure_fingerprint': fingerprint, 'outcome': outcome}
    if repair_category is not None:
        immutable['repair_category'] = repair_category
    if mapping:
        immutable.update({field: value[field] for field in CONFIGURATION_IDENTITY_FIELDS})
    expected = 'OUT-' + hashlib.sha256(json.dumps(immutable, sort_keys=True, separators=(',', ':')).encode()).hexdigest()[:24]
    if value['outcome_id'] != expected:
        raise ValueError('Scrape outcome ID does not match immutable evidence.')
    result = {'outcome_id': expected, 'outcome': outcome, 'action': action,
              'identity': bounded, 'failure_fingerprint': fingerprint}
    if repair_category is not None:
        result['repair_category'] = repair_category
    if mapping:
        result.update({field: value[field] for field in CONFIGURATION_IDENTITY_FIELDS})
    return result


class Store(CampaignStore, InferenceStore):
    def __init__(self, base, *, company_revision_resolver=None):
        self.base = Path(base)
        # Provided only by the Job Search Helper boundary.  An operator command
        # cannot substitute an old revision for a fresh Company lookup.
        self.company_revision_resolver = company_revision_resolver
        self.base.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.base / 'tasks.sqlite3'
        self.export_lock = threading.Lock()
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, state TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS receipts(
                    id INTEGER PRIMARY KEY, task TEXT NOT NULL, phase TEXT NOT NULL,
                    name TEXT NOT NULL, arguments TEXT NOT NULL, result TEXT,
                    signature TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS inference_receipts(
                    request_id TEXT PRIMARY KEY, task TEXT NOT NULL, status TEXT NOT NULL, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS batches(digest TEXT PRIMARY KEY, task_ids TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS campaigns(campaign_id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS campaign_seals(campaign_id TEXT PRIMARY KEY, membership_digest TEXT NOT NULL, sealed_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS campaign_snapshots(campaign_id TEXT NOT NULL, revision INTEGER NOT NULL, data TEXT NOT NULL, PRIMARY KEY(campaign_id, revision));
                CREATE TABLE IF NOT EXISTS campaign_company_registry(
                    campaign_id TEXT NOT NULL, company_id TEXT NOT NULL,
                    current_task_id TEXT NOT NULL, identity_digest TEXT NOT NULL,
                    import_digest TEXT NOT NULL, retry_of TEXT,
                    PRIMARY KEY(campaign_id, company_id));
                CREATE TABLE IF NOT EXISTS scrape_outcome_intake(
                    outcome_id TEXT PRIMARY KEY, company_id TEXT NOT NULL,
                    source_revision TEXT NOT NULL, outcome TEXT NOT NULL,
                    payload TEXT NOT NULL, received REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS scrape_outcome_delivery_receipts(
                    consumer TEXT NOT NULL, outcome_id TEXT NOT NULL,
                    record_sha256 TEXT NOT NULL, receipt_id TEXT NOT NULL,
                    receipt TEXT NOT NULL, receipt_sha256 TEXT NOT NULL,
                    sink_status TEXT NOT NULL, created REAL NOT NULL,
                    PRIMARY KEY(consumer, outcome_id),
                    UNIQUE(receipt_id));
                CREATE TABLE IF NOT EXISTS repair_intake(
                    repair_key TEXT PRIMARY KEY, outcome_id TEXT NOT NULL,
                    company_id TEXT NOT NULL, source_revision TEXT NOT NULL,
                    status TEXT NOT NULL, task_id TEXT, payload TEXT NOT NULL, received REAL NOT NULL,
                    FOREIGN KEY(outcome_id) REFERENCES scrape_outcome_intake(outcome_id));
                CREATE TABLE IF NOT EXISTS repair_intake_evidence(
                    repair_key TEXT NOT NULL, outcome_id TEXT NOT NULL,
                    PRIMARY KEY(repair_key, outcome_id),
                    FOREIGN KEY(repair_key) REFERENCES repair_intake(repair_key),
                    FOREIGN KEY(outcome_id) REFERENCES scrape_outcome_intake(outcome_id));
                CREATE TABLE IF NOT EXISTS repair_retry_lineage(
                    failed_request_id TEXT PRIMARY KEY,
                    successor_request_id TEXT NOT NULL,
                    company_id TEXT NOT NULL,
                    source_revision TEXT NOT NULL,
                    attempt_id TEXT NOT NULL,
                    release_version TEXT NOT NULL,
                    outcome_id TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS repair_retry_outcome_events(
                    outcome_id TEXT PRIMARY KEY,
                    attempt_id TEXT NOT NULL,
                    failed_request_id TEXT NOT NULL,
                    release_version TEXT NOT NULL,
                    release_binding_sha256 TEXT NOT NULL,
                    event_kind TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    received REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS repair_retry_lifecycles(
                    attempt_id TEXT PRIMARY KEY,
                    failed_request_id TEXT NOT NULL,
                    release_version TEXT NOT NULL,
                    release_binding_sha256 TEXT NOT NULL,
                    state TEXT NOT NULL,
                    first_outcome_id TEXT NOT NULL,
                    latest_outcome_id TEXT NOT NULL,
                    updated REAL NOT NULL);
            ''')
            columns = {row[1] for row in db.execute('PRAGMA table_info(repair_intake)')}
            if 'task_id' not in columns:
                db.execute('ALTER TABLE repair_intake ADD COLUMN task_id TEXT')
            lineage_columns = {row[1] for row in db.execute('PRAGMA table_info(repair_retry_lineage)')}
            if 'release_binding_sha256' not in lineage_columns:
                # Legacy rows predate complete release provenance.  They remain
                # readable evidence, but cannot match a new retry assertion.
                db.execute('ALTER TABLE repair_retry_lineage ADD COLUMN release_binding_sha256 TEXT')

    @staticmethod
    def _retry_lifecycle_state(outcome):
        if outcome == 'COMPLETE':
            return 'VALIDATED_COMPLETE'
        if outcome == 'QUALIFIED_INTEGRATION_REPAIR':
            return 'ROLLBACK_REQUIRED'
        return 'OBSERVED_HELD'

    def _record_retry_lifecycle(self, db, canonical, encoded):
        """Append one retry fact and conservatively derive its lifecycle state.

        This is intentionally called inside the same transaction as intake so
        no delivery acknowledgement can observe an outcome without its receipt.
        A second nonidentical fact never replaces the first; it only makes the
        lifecycle require operator reconciliation.
        """
        identity = canonical['identity']
        attempt = identity['attempt_id']
        provenance = (identity['failed_request_id'], identity['release_version'],
                      identity['release_binding_sha256'])
        db.execute('INSERT INTO repair_retry_outcome_events VALUES (?,?,?,?,?,?,?,?)', (
            canonical['outcome_id'], attempt, *provenance, canonical['outcome'],
            encoded, time.time()))
        previous = db.execute(
            'SELECT failed_request_id,release_version,release_binding_sha256,state,first_outcome_id '
            'FROM repair_retry_lifecycles WHERE attempt_id=?', (attempt,)).fetchone()
        if previous is None:
            state = self._retry_lifecycle_state(canonical['outcome'])
            db.execute('INSERT INTO repair_retry_lifecycles VALUES (?,?,?,?,?,?,?,?)', (
                attempt, *provenance, state, canonical['outcome_id'],
                canonical['outcome_id'], time.time()))
            return state
        # A duplicate outcome was returned before this method.  Every event
        # reaching here is therefore a distinct immutable statement for the
        # attempt, whether it changes the result or only its release pin.
        if previous[:3] != provenance or previous[4] != canonical['outcome_id']:
            state = 'RECONCILIATION_REQUIRED'
        else:
            state = previous[3]
        db.execute('UPDATE repair_retry_lifecycles SET state=?,latest_outcome_id=?,updated=? '
                   'WHERE attempt_id=?', (state, canonical['outcome_id'], time.time(), attempt))
        return state

    def retry_lifecycle(self, attempt_id):
        """Return a read-only lifecycle snapshot; never dispatch or repair."""
        if not isinstance(attempt_id, str) or not attempt_id.strip() or len(attempt_id.strip()) > 256:
            raise ValueError('Retry attempt ID is required.')
        with self.connect() as db:
            row = db.execute(
                'SELECT attempt_id,failed_request_id,release_version,release_binding_sha256,state,'
                'first_outcome_id,latest_outcome_id,updated FROM repair_retry_lifecycles WHERE attempt_id=?',
                (attempt_id.strip(),)).fetchone()
            if not row:
                return None
            events = db.execute(
                'SELECT outcome_id,event_kind,payload,received FROM repair_retry_outcome_events '
                'WHERE attempt_id=? ORDER BY received,outcome_id', (attempt_id.strip(),)).fetchall()
        return dict(attempt_id=row[0], failed_request_id=row[1], release_version=row[2],
                    release_binding_sha256=row[3], state=row[4], first_outcome_id=row[5],
                    latest_outcome_id=row[6], updated=row[7],
                    events=[dict(outcome_id=item[0], outcome=item[1],
                                 record=json.loads(item[2]), received=item[3]) for item in events])

    def ingest_scrape_outcome(self, facts):
        """Classify trusted bounded facts, then hold the M3 result here.

        Qualified defects upsert one held repair key.  No task is created or
        claimed here: a later reviewed M4 assignment supplies the source scope,
        tests, capability, and explicit campaign controls.
        """
        try:
            from job_search_helper.outcomes import OutcomeFactsError, classify_outcome
        except ImportError as exc:
            raise ValueError(f'Invalid trusted scrape outcome facts: {exc}') from exc
        try:
            canonical = canonical_scrape_outcome(classify_outcome(facts))
        except OutcomeFactsError as exc:
            raise ValueError(f'Invalid trusted scrape outcome facts: {exc}') from exc
        return self.ingest_scrape_outcome_record(canonical)

    def ingest_scrape_outcome_record(self, record):
        """Persist a previously classified immutable outcome without reclassifying it."""
        canonical = canonical_scrape_outcome(record)
        encoded = json.dumps(canonical, sort_keys=True, separators=(',', ':'))
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            return self._ingest_scrape_outcome_record_tx(db, canonical, encoded)

    def _ingest_scrape_outcome_record_tx(self, db, canonical, encoded):
        """The legacy intake mutation, run by either legacy or v1 entrypoints."""
        identity = canonical['identity']
        retry = all(identity.get(key) for key in (
                'attempt_id', 'failed_request_id', 'release_version', 'release_binding_sha256'))
        lineage = db.execute(
                'SELECT successor_request_id,company_id,source_revision FROM repair_retry_lineage '
                'WHERE failed_request_id=?', (identity['request_id'],)).fetchone()
        superseded = bool(lineage and lineage[1:] == (
                identity['company_id'], identity['source_revision']))
        repair_key = None
        status = 'SUPERSEDED_BY_REPAIRED_RETRY' if superseded else 'RECORDED_NO_REPAIR'
        prior = db.execute('SELECT payload FROM scrape_outcome_intake WHERE outcome_id=?',
                               (canonical['outcome_id'],)).fetchone()
        if prior:
            if prior[0] != encoded:
                raise ValueError('Scrape outcome conflicts with immutable coordinator intake.')
                # A duplicate delivery must return the original held repair
                # identity.  Otherwise a durable qualified outcome could be
                # acknowledged yet a caller could no longer idempotently
                # promote the same repair after a delivery restart.
            held = db.execute(
                    'SELECT repair_key,status FROM repair_intake WHERE outcome_id=?',
                    (canonical['outcome_id'],)).fetchone()
            return {'outcome_id': canonical['outcome_id'], 'recorded': False,
                        'repair_key': held[0] if held else repair_key,
                        'status': held[1] if held else status}
        db.execute('INSERT INTO scrape_outcome_intake VALUES (?,?,?,?,?,?)',
                       (canonical['outcome_id'], identity['company_id'], identity['source_revision'],
                        canonical['outcome'], encoded, time.time()))
        lifecycle_state = self._record_retry_lifecycle(db, canonical, encoded) if retry else None
        if retry:
            existing = db.execute(
                    'SELECT successor_request_id,company_id,source_revision,attempt_id,release_version,release_binding_sha256 '
                    'FROM repair_retry_lineage WHERE failed_request_id=?',
                    (identity['failed_request_id'],)).fetchone()
            expected = (identity['request_id'], identity['company_id'], identity['source_revision'],
                            identity['attempt_id'], identity['release_version'], identity['release_binding_sha256'])
            if existing and existing != expected:
                    # The first successor pin remains immutable lineage.  A
                    # later event using the same retry request and attempt but
                    # a different full release pin is evidence, not authority
                    # to replace it.  _record_retry_lifecycle already retained
                    # it and made the derived state reconciliation-required.
                    # A genuinely competing successor remains fail-closed.
                if existing[:4] != expected[:4]:
                    raise ValueError('A different repaired retry already owns this failed request lineage.')
            db.execute('INSERT OR IGNORE INTO repair_retry_lineage('
                           'failed_request_id,successor_request_id,company_id,source_revision,attempt_id,'
                           'release_version,release_binding_sha256,outcome_id) VALUES (?,?,?,?,?,?,?,?)',
                           (identity['failed_request_id'], *expected, canonical['outcome_id']))
                # An original failure may have reached intake before its
                # repaired retry.  Retain its evidence but prevent it from
                # reopening work after the successor is authoritative.
            old_ids = []
            for outcome_id, payload in db.execute(
                        'SELECT outcome_id,payload FROM scrape_outcome_intake '
                        'WHERE company_id=? AND source_revision=?',
                        (identity['company_id'], identity['source_revision'])).fetchall():
                prior_identity = json.loads(payload).get('identity', {})
                if prior_identity.get('request_id') == identity['failed_request_id']:
                    old_ids.append(outcome_id)
            for outcome_id in old_ids:
                db.execute('UPDATE repair_intake SET status=? WHERE outcome_id=?',
                               ('SUPERSEDED_BY_REPAIRED_RETRY', outcome_id))
        if lifecycle_state:
            status = lifecycle_state
        if (not superseded and canonical['outcome'] == 'QUALIFIED_INTEGRATION_REPAIR'
                    and (not retry or lifecycle_state == 'ROLLBACK_REQUIRED')):
            provider, adapter = identity.get('provider'), identity.get('adapter_version')
            if provider and adapter:
                repair_identity = {
                        'company_id': identity['company_id'], 'source_revision': identity['source_revision'],
                        'provider': provider, 'adapter_version': adapter,
                        'failure_fingerprint': canonical['failure_fingerprint'],
                    }
                if canonical.get('repair_category') == SOURCE_CONFIGURATION_MAPPING:
                    if any(field not in canonical for field in CONFIGURATION_IDENTITY_FIELDS):
                        raise ValueError('Source-configuration repair lacks immutable identity.')
                    repair_identity.update({field: canonical[field]
                                            for field in CONFIGURATION_IDENTITY_FIELDS})
                if retry:
                    repair_identity['attempt_id'] = identity['attempt_id']
                    repair_identity['release_binding_sha256'] = identity['release_binding_sha256']
                repair_key = hashlib.sha256(json.dumps(
                        repair_identity, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
                if not lifecycle_state:
                    status = 'HELD_FOR_REPAIR_TRIAGE'
            elif not lifecycle_state:
                status = 'HELD_MISSING_REPAIR_CAPABILITY'
        if repair_key:
            db.execute('INSERT OR IGNORE INTO repair_intake('
                           'repair_key,outcome_id,company_id,source_revision,status,payload,received) '
                           'VALUES (?,?,?,?,?,?,?)',
                           (repair_key, canonical['outcome_id'], identity['company_id'],
                            identity['source_revision'], status, encoded, time.time()))
                # A later attempt can carry fresh evidence for the same
                # defect.  Retain it without creating another repair owner.
            db.execute('INSERT OR IGNORE INTO repair_intake_evidence VALUES (?,?)',
                           (repair_key, canonical['outcome_id']))
        return {'outcome_id': canonical['outcome_id'], 'recorded': True,
                'repair_key': repair_key, 'status': status}

    @staticmethod
    def _validate_delivery_receipt(row, *, consumer, canonical, record_sha256):
        """Validate stored bytes instead of trusting a row merely because it keys."""
        stored_digest, receipt_id, stored_text, receipt_digest, status = row
        if stored_digest != record_sha256 or status not in OUTCOME_DELIVERY_STATUSES:
            raise ValueError('Stored outcome-delivery receipt is corrupt.')
        if not isinstance(stored_text, str) or _sha256_text(stored_text) != receipt_digest:
            raise ValueError('Stored outcome-delivery receipt is corrupt.')
        try:
            receipt = json.loads(stored_text)
        except (TypeError, ValueError) as exc:
            raise ValueError('Stored outcome-delivery receipt is corrupt.') from exc
        expected_id = _outcome_delivery_receipt_id(consumer, canonical['outcome_id'], record_sha256)
        expected = {
            'schema': OUTCOME_DELIVERY_SCHEMA, 'consumer': consumer,
            'outcome_id': canonical['outcome_id'], 'record_sha256': record_sha256,
            'disposition': 'ACCEPTED', 'sink_receipt_id': expected_id,
            'sink_status': status,
        }
        if receipt != expected or stored_text != _canonical_json(expected) or receipt_id != expected_id:
            raise ValueError('Stored outcome-delivery receipt is corrupt.')
        return receipt

    @staticmethod
    def _validate_delivery_intake(row, *, canonical, legacy_text, record_sha256):
        """Bind receipt authority to exact intake bytes and indexed identity."""
        if not row:
            raise ValueError('Stored outcome-delivery receipt lacks its intake record.')
        company_id, source_revision, outcome, payload = row
        identity = canonical['identity']
        if ((company_id, source_revision, outcome) != (
                identity['company_id'], identity['source_revision'], canonical['outcome'])
                or payload != legacy_text):
            raise ValueError('Stored outcome intake conflicts with immutable delivery evidence.')
        try:
            stored = canonical_scrape_outcome(json.loads(payload))
        except (TypeError, ValueError) as exc:
            raise ValueError('Stored outcome intake is corrupt.') from exc
        if (stored != canonical
                or _sha256_text(_canonical_json(stored)) != record_sha256):
            raise ValueError('Stored outcome intake conflicts with immutable delivery evidence.')
        return stored

    def ingest_scrape_outcome_delivery_v1(self, consumer, record):
        """Atomically freeze bounded coordinator intake behind a v1 receipt.

        This is evidence-only: it shares the legacy ledger transaction but has
        no authority to queue, claim, promote, or dispatch a repair.
        """
        if consumer != OUTCOME_DELIVERY_CONSUMER:
            raise ValueError('Outcome-delivery consumer is not allowed.')
        if isinstance(record, dict) and record.get('outcome') == 'STALE_OR_PAUSED':
            raise ValueError('Stale or paused outcomes are not accepted for delivery.')
        canonical = canonical_scrape_outcome(record)
        if record != canonical:
            raise ValueError('Outcome-delivery record must be exactly canonical.')
        canonical_text = _canonical_json(canonical)
        record_sha256 = _sha256_text(canonical_text)
        legacy_text = json.dumps(canonical, sort_keys=True, separators=(',', ':'))
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            prior_receipt = db.execute(
                'SELECT record_sha256,receipt_id,receipt,receipt_sha256,sink_status '
                'FROM scrape_outcome_delivery_receipts WHERE consumer=? AND outcome_id=?',
                (consumer, canonical['outcome_id'])).fetchone()
            prior_intake = db.execute(
                'SELECT company_id,source_revision,outcome,payload FROM scrape_outcome_intake WHERE outcome_id=?',
                (canonical['outcome_id'],)).fetchone()
            if prior_receipt:
                self._validate_delivery_intake(
                    prior_intake, canonical=canonical, legacy_text=legacy_text,
                    record_sha256=record_sha256)
                return self._validate_delivery_receipt(
                    prior_receipt, consumer=consumer, canonical=canonical,
                    record_sha256=record_sha256)
            if prior_intake:
                self._validate_delivery_intake(
                    prior_intake, canonical=canonical, legacy_text=legacy_text,
                    record_sha256=record_sha256)
            result = self._ingest_scrape_outcome_record_tx(db, canonical, legacy_text)
            status = result['status']
            if status not in OUTCOME_DELIVERY_STATUSES:
                raise ValueError('Outcome-delivery status cannot be frozen.')
            receipt_id = _outcome_delivery_receipt_id(consumer, canonical['outcome_id'], record_sha256)
            receipt = {
                'schema': OUTCOME_DELIVERY_SCHEMA, 'consumer': consumer,
                'outcome_id': canonical['outcome_id'], 'record_sha256': record_sha256,
                'disposition': 'ACCEPTED', 'sink_receipt_id': receipt_id,
                'sink_status': status,
            }
            receipt_text = _canonical_json(receipt)
            db.execute(
                'INSERT INTO scrape_outcome_delivery_receipts '
                '(consumer,outcome_id,record_sha256,receipt_id,receipt,receipt_sha256,sink_status,created) '
                'VALUES (?,?,?,?,?,?,?,?)',
                (consumer, canonical['outcome_id'], record_sha256, receipt_id,
                 receipt_text, _sha256_text(receipt_text), status, time.time()))
            return receipt

    def held_repair_intake(self):
        """Review held repairs; this is deliberately not a scheduling API."""
        with self.connect() as db:
            rows = db.execute(
                'SELECT r.repair_key,r.outcome_id,r.company_id,r.source_revision,r.status,r.task_id,r.payload,'
                'GROUP_CONCAT(e.outcome_id) FROM repair_intake r '
                'LEFT JOIN repair_intake_evidence e ON e.repair_key=r.repair_key '
                'GROUP BY r.repair_key,r.outcome_id,r.company_id,r.source_revision,r.status,r.task_id,r.payload '
                'ORDER BY r.received,r.repair_key').fetchall()
        return [dict(repair_key=row[0], outcome_id=row[1], company_id=row[2],
                     source_revision=row[3], status=row[4], task_id=row[5], outcome=json.loads(row[6]),
                     evidence_outcome_ids=sorted(item for item in (row[7] or '').split(',') if item)) for row in rows]

    def promote_held_repair(self, repair_key, spec, *, source_revision):
        """Create one fully scoped *paused* task for an approved held repair.

        This is a durable ownership handoff, not a dispatch action.  The
        caller supplies a Coordinator-validated specification with exact
        source/test scope.  The task remains paused until an explicit later
        resume, so a running queue cannot claim it in the promotion window.
        """
        if not isinstance(repair_key, str) or not re.fullmatch(r'[0-9a-f]{64}', repair_key):
            raise ValueError('Use a held repair key.')
        if not isinstance(source_revision, str) or not source_revision.strip() or len(source_revision.strip()) > 256:
            raise ValueError('Held repair promotion requires its exact source revision.')
        source_revision = source_revision.strip()
        state = self.new_state(**spec)
        identity = state.get('integration_identity') or {}
        if not identity:
            raise ValueError('Held repair promotion requires canonical integration identity.')
        import coding_tools as code
        from coordinator_acceptance import files
        from coordinator_baseline import binding, files as baseline_files
        state['acceptance_baseline_manifest'] = files(code.root())
        state['assignment_baseline'] = binding(baseline_files(code.root()))
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT outcome_id,company_id,source_revision,status,task_id FROM repair_intake WHERE repair_key=?',
                             (repair_key,)).fetchone()
            if not row:
                raise ValueError('Held repair was not found.')
            outcome_id, company_id, held_revision, status, existing_task = row
            if identity['company_id'] != company_id or source_revision != held_revision:
                raise ValueError('Held repair does not match the proposed company assignment.')
            if existing_task:
                return self.get(existing_task)
            if status != 'HELD_FOR_REPAIR_TRIAGE':
                raise ValueError('Held repair is not available for promotion.')
            state.update(status='PAUSED', stop_requested=True, held_repair_key=repair_key,
                         repair_provenance={'repair_key': repair_key, 'outcome_id': outcome_id,
                                            'company_id': company_id, 'source_revision': held_revision},
                         reason='Promoted from held repair; explicit resume and review are required.')
            db.execute('INSERT INTO tasks VALUES (?,?)', (state['id'], json.dumps(state)))
            db.execute('UPDATE repair_intake SET task_id=?,status=? WHERE repair_key=?',
                       (state['id'], 'PROMOTED_PAUSED', repair_key))
        return state

    def _repair_revision_is_current(self, state):
        """Return whether an M4 repair still matches the authoritative Company.

        A missing/unavailable resolver is deliberately unsafe for a promoted
        repair.  Generic pre-existing coordinator tasks retain their original
        behavior because they are not owned by this Company-event handoff.
        """
        provenance = state.get('repair_provenance')
        if not provenance:
            return True
        if not isinstance(provenance, dict):
            return False
        company_id = provenance.get('company_id')
        expected = provenance.get('source_revision')
        if (not isinstance(company_id, str) or not company_id
                or not isinstance(expected, str) or not expected):
            return False
        identity = state.get('integration_identity') or {}
        if identity.get('company_id') != company_id:
            return False
        resolver = self.company_revision_resolver
        if not callable(resolver):
            return False
        try:
            actual = resolver(company_id)
        except Exception:
            return False
        return isinstance(actual, str) and actual == expected

    def _require_current_repair_revision(self, state):
        if state.get('repair_provenance') and not self._repair_revision_is_current(state):
            raise ValueError('Held repair cannot resume until an authoritative current Company revision matches its promotion record.')

    def ensure_current_repair_revision(self, task_id):
        """Pause a stale held repair before any direct worker step can run."""
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT state FROM tasks WHERE id=?', (task_id,)).fetchone()
            if not row:
                raise ValueError('Task not found.')
            state = json.loads(row[0])
            if not state.get('repair_provenance') or self._repair_revision_is_current(state):
                return True
            state.update(status='PAUSED', stop_requested=True,
                         reason='Company revision is no longer current; obtain a new held repair from the current Company record.')
            db.execute('UPDATE tasks SET state=? WHERE id=?', (json.dumps(state), task_id))
            self._bump_control_generation(db)
            return False

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.execute('PRAGMA synchronous=FULL')
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, objective, tests, mode, max_sessions=10, *, authorization_version=0,
               evidence_requirements=None, workflow_version=1, integration=None):
        state = self.new_state(objective, tests, mode, max_sessions, authorization_version,
                               evidence_requirements, workflow_version, integration)
        # Direct tasks execute in the active checkout; imported campaign tasks
        # instead pin the frozen batch source used for isolated workspaces.
        import coding_tools as code
        from coordinator_acceptance import files
        state['acceptance_baseline_manifest'] = files(code.root())
        from coordinator_baseline import binding, files as baseline_files
        state['assignment_baseline'] = binding(baseline_files(code.root()))
        with self.connect() as db:
            db.execute('INSERT INTO tasks VALUES (?,?)', (state['id'], json.dumps(state)))
        return state

    def new_state(self, objective, tests, mode, max_sessions, authorization_version,
                  evidence_requirements, workflow_version, integration=None):
        task_id = 'WRAP-' + uuid.uuid4().hex[:10]
        state = dict(id=task_id, objective=objective, tests=tests, mode=mode,
                     status='QUEUED', phase='baseline', created=time.time(),
                     time_budget_policy='wall_time_from_creation_including_queue_and_pause',
                     sessions=0, calls=0, tokens=0, max_sessions=max_sessions,
                     checkpoint={}, manifest={}, stop_requested=False, reason='',
                     no_progress=0, errors=0, phase_start=0,
                     authorization_version=authorization_version, evidence_requirements=evidence_requirements or {},
                     workflow_version=workflow_version, workflow={}, integration=integration or {},
                     campaign_id=None, campaign_company_id=None,
                     campaign_disposition=None, campaign_selected_at=None,
                     campaign_run_id=None, campaign_manifest_digest=None)
        if workflow_version == 2:
            state.update(activated_at=None, time_budget_policy='one_hour_from_first_assignment_including_pauses')
        state = bind_identity(state)
        state['edit_scope'] = initial_scope(state)
        from coordinator_workspace import batch_source
        from coordinator_acceptance import files
        state['acceptance_baseline_manifest'] = files(batch_source())
        from coordinator_baseline import binding, files as baseline_files
        state['assignment_baseline'] = binding(baseline_files(batch_source()))
        return state

    def enqueue_batch(self, digest, specs, held=False, campaign_id=DEFAULT_CAMPAIGN_ID):
        """Import a complete batch or reject it without changing any task."""
        scoped_digest = hashlib.sha256(json.dumps([campaign_id if held else None, digest]).encode()).hexdigest()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT task_ids FROM batches WHERE digest=?', (scoped_digest,)).fetchone()
            states = [self.new_state(**spec) for spec in specs]
            if held and (not isinstance(campaign_id, str) or not campaign_id.strip()):
                raise ValueError('Held campaign imports require a stable campaign ID.')
            for state in states:
                state['isolated_workspace'] = True
                if held:
                    company_id = state.get('integration', {}).get('company_id')
                    if not company_id:
                        raise ValueError('Held campaign imports require structured company identity.')
                    state.update(status='PAUSED', stop_requested=False,
                                 reason='Held for one-company campaign selection.',
                                 campaign_id=campaign_id, campaign_company_id=company_id,
                                 campaign_disposition=HELD_FOR_CAMPAIGN,
                                 campaign_manifest_digest=campaign_manifest_digest(state))
                    state.update(bind_identity(state))
            if existing:
                ids = json.loads(existing[0])
                if len(ids) != len(states):
                    raise ValueError('Batch provenance conflicts with imported assignments.')
                for task_id, proposed in zip(ids, states):
                    row = db.execute('SELECT state FROM tasks WHERE id=?', (task_id,)).fetchone()
                    old = json.loads(row[0]) if row else {}
                    validate_bound_identity(old)
                    if (campaign_manifest_digest(old) != campaign_manifest_digest(proposed)
                            or old.get('campaign_id') != proposed.get('campaign_id')
                            or any(old.get(key) != proposed.get(key) for key in ('mode', 'max_sessions', 'authorization_version', 'workflow_version'))):
                        raise ValueError('Batch provenance conflicts with imported assignments.')
                    self._require_current_identity(db, old)
                    if held:
                        provenance = db.execute('SELECT import_digest FROM campaign_company_registry WHERE campaign_id=? AND company_id=?', (campaign_id, old['campaign_company_id'])).fetchone()
                        if not provenance or provenance[0] != scoped_digest:
                            raise ValueError('Registry import provenance conflicts with batch replay.')
                return ids, True
            if held and db.execute('SELECT 1 FROM campaign_seals WHERE campaign_id=?', (campaign_id,)).fetchone():
                raise ValueError('Campaign membership is sealed; use a new reviewed campaign for additional companies.')
            for state in states:
                if held:
                    if db.execute('SELECT 1 FROM campaign_company_registry WHERE campaign_id=? AND company_id=?',
                                  (campaign_id, state['campaign_company_id'])).fetchone():
                        raise ValueError('Campaign company already imported; changed batch duplicates require explicit retry.')
                    db.execute('INSERT INTO campaign_company_registry VALUES (?,?,?,?,?,?)',
                               (campaign_id, state['campaign_company_id'], state['id'],
                                state['integration_identity_digest'], scoped_digest, None))
                db.execute('INSERT INTO tasks VALUES (?,?)', (state['id'], json.dumps(state)))
            ids = [s['id'] for s in states]
            db.execute('INSERT INTO batches VALUES (?,?)', (scoped_digest, json.dumps(ids)))
            return ids, False

    @staticmethod
    def _require_current_identity(db, state):
        validate_bound_identity(state)
        validate_scope(state)
        if state.get('campaign_id'):
            if state.get('campaign_manifest_digest') != campaign_manifest_digest(state):
                raise ValueError('Campaign manifest binding changed.')
            row = db.execute('SELECT current_task_id,identity_digest FROM campaign_company_registry WHERE campaign_id=? AND company_id=?',
                             (state['campaign_id'], state.get('campaign_company_id'))).fetchone()
            if not row or row != (state['id'], state.get('integration_identity_digest')):
                raise ValueError('Campaign assignment is unregistered or superseded; reviewed identity migration or retry required.')

    def retry_campaign_task(self, task_id, *, investigation_targets=None, expected_state_digest=None):
        """Explicit operator transition; keep predecessor and receipts untouched."""
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT state FROM tasks WHERE id=?', (task_id,)).fetchone()
            if not row:
                raise ValueError('Task not found.')
            old = json.loads(row[0])
            if not old.get('campaign_id'):
                raise ValueError('Retry requires a campaign assignment.')
            self._require_current_identity(db, old)
            requirements = json.loads(json.dumps(old['evidence_requirements']))
            if investigation_targets is not None:
                if not expected_state_digest or task_state_digest(old) != expected_state_digest:
                    raise ValueError('Retry predecessor changed; review current state before refreshing evidence.')
                if not isinstance(investigation_targets, list) or not 1 <= len(investigation_targets) <= 32:
                    raise ValueError('Investigation refresh requires a bounded nonempty target list.')
                seen = set()
                for target in investigation_targets:
                    if not isinstance(target, dict) or set(target) != {'url', 'allowed_urls', 'identity_terms', 'purpose'}:
                        raise ValueError('Investigation refresh contains unsupported target fields.')
                    url = target['url']
                    if not isinstance(url, str) or len(url) > 2048 or any(c.isspace() or ord(c) < 32 for c in url):
                        raise ValueError('Investigation refresh requires a safe bound HTTPS URL.')
                    try:
                        parsed = urlsplit(url)
                        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
                                or parsed.fragment or parsed.port not in (None, 443)
                                or parsed.hostname.lower().rstrip('.') == 'localhost'):
                            raise ValueError('Unsafe URL.')
                        try:
                            address = ipaddress.ip_address(parsed.hostname)
                        except ValueError:
                            address = None
                        if address is not None and not address.is_global:
                            raise ValueError('Unsafe address.')
                    except ValueError as exc:
                        raise ValueError('Investigation refresh requires a safe bound HTTPS URL.') from exc
                    if (url in seen or target['allowed_urls'] != [url]
                            or target['purpose'] != 'configured_listing'):
                        raise ValueError('Investigation refresh has duplicate URLs or expanded target permissions.')
                    if not any(url in prior.get('allowed_urls', [])
                               and target['identity_terms'] == prior.get('identity_terms')
                               for prior in requirements.get('source_targets', [])):
                        raise ValueError('Investigation target URL and identity must match an existing bound source.')
                    seen.add(url)
                requirements['investigation_targets'] = json.loads(json.dumps(investigation_targets))
            elif expected_state_digest is not None and task_state_digest(old) != expected_state_digest:
                raise ValueError('Retry predecessor changed; review current state before retry.')
            controls = {key: json.loads(value) for key, value in db.execute('SELECT key,value FROM settings')}
            if (controls.get('queue_enabled', True) or controls.get('campaign_enabled', False)
                    or controls.get('pilot_task') is not None):
                raise ValueError('Stop queue, campaign and pilot before explicit retry.')
            if old['status'] in ('RUNNING', 'QUEUED', 'PAUSING'):
                raise ValueError('Active assignment cannot be retried.')
            if db.execute('SELECT 1 FROM receipts WHERE task=? AND result IS NULL', (task_id,)).fetchone():
                raise ValueError('Inspect unfinished receipts before retry.')
            arguments = {key: old[key] for key in (
                'objective', 'tests', 'mode', 'max_sessions', 'authorization_version',
                'evidence_requirements', 'workflow_version', 'integration')}
            arguments['evidence_requirements'] = requirements
            state = self.new_state(**arguments)
            state['assignment_baseline'] = old.get('assignment_baseline')
            state['acceptance_baseline_manifest'] = old.get('acceptance_baseline_manifest')
            state.update(campaign_id=old['campaign_id'], campaign_company_id=old['campaign_company_id'],
                         campaign_manifest_digest=old['campaign_manifest_digest'],
                         campaign_disposition=HELD_FOR_CAMPAIGN, isolated_workspace=True,
                         status='PAUSED', retry_of=task_id, reason='Explicit operator retry held for campaign selection.')
            state = bind_identity(state)
            self._reopen_campaign(db, old['campaign_id'])
            db.execute('INSERT INTO tasks VALUES (?,?)', (state['id'], json.dumps(state)))
            db.execute('UPDATE campaign_company_registry SET current_task_id=?, retry_of=? WHERE campaign_id=? AND company_id=?',
                       (state['id'], task_id, state['campaign_id'], state['campaign_company_id']))
            self._bump_control_generation(db)
            return state

    def record_acceptance_bundle(self, task_id, bundle):
        """Host-only first capture; never replace an existing acceptance bundle."""
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT state FROM tasks WHERE id=?', (task_id,)).fetchone()
            if not row:
                raise ValueError('Task not found.')
            state = json.loads(row[0])
            if state.get('acceptance_bundle'):
                raise ValueError('Acceptance bundle is already recorded.')
            if db.execute("SELECT 1 FROM receipts WHERE task=? AND name IN ('code_edit','code_create')", (task_id,)).fetchone():
                raise ValueError('Cannot capture acceptance after an edit attempt.')
            state['acceptance_bundle'] = bundle
            db.execute('UPDATE tasks SET state=? WHERE id=?', (json.dumps(state), task_id))
            return state

    def expand_edit_scope(self, task_id, paths, reason, *, expected_state_digest, expected_scope_digest):
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 2000:
            raise ValueError('Scope expansion requires a bounded operator reason.')
        added = exact_paths(paths)
        if len(added) != len(paths):
            raise ValueError('Scope expansion contains duplicate paths.')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT state FROM tasks WHERE id=?', (task_id,)).fetchone()
            if not row:
                raise ValueError('Task not found.')
            state = json.loads(row[0])
            self._require_current_identity(db, state)
            scope = validate_scope(state)
            if task_state_digest(state) != expected_state_digest or scope['digest'] != expected_scope_digest:
                raise ValueError('Task or scope changed; review current state before expansion.')
            controls = {k: json.loads(v) for k, v in db.execute('SELECT key,value FROM settings')}
            if (not state['status'].startswith('PAUSED') or reached_operator_gate(state)
                    or state.get('campaign_disposition') == SELECTED
                    or controls.get('queue_enabled', True) or controls.get('campaign_enabled', False)
                    or controls.get('pilot_task') is not None
                    or db.execute('SELECT 1 FROM receipts WHERE task=? AND result IS NULL', (task_id,)).fetchone()):
                raise ValueError('Scope expansion requires a stopped, paused safe boundary without unfinished receipts.')
            if any(path in scope['paths'] for path in added):
                raise ValueError('Scope expansion must add new exact paths.')
            # Filesystem validation uses this task checkout, never model input roots.
            import coding_tools as code
            from coordinator_workspace import workspace
            with workspace(self, state, create=True):
                for path in added:
                    code.path_for(path, create=True)
            paths = exact_paths(scope['paths'] + added)
            version = scope['version'] + 1
            audit = dict(added=added, reason=reason.strip(), at=time.time(), version=version,
                         previous_digest=scope['digest'], expected_task_digest=expected_state_digest)
            state.update(edit_scope=dict(paths=paths, digest=scope_digest(paths), version=version,
                                         history=scope['history'] + [audit]),
                         phase='baseline', baseline_passed=None, workflow={}, checkpoint={},
                         evidence_epoch=audit['at'],
                         reason='Operator expanded exact edit scope; baseline and inspection required.')
            db.execute('UPDATE tasks SET state=? WHERE id=?', (json.dumps(state), task_id))
            self._bump_control_generation(db)
            return state

    def queue_enabled(self):
        with self.connect() as db:
            value = db.execute("SELECT value FROM settings WHERE key='queue_enabled'").fetchone()
        return value is None or value[0] == 'true'

    @staticmethod
    def _control_generation(db):
        row = db.execute("SELECT value FROM settings WHERE key='control_generation'").fetchone()
        return int(json.loads(row[0])) if row else 0

    @classmethod
    def _bump_control_generation(cls, db):
        generation = cls._control_generation(db) + 1
        db.execute("INSERT INTO settings VALUES ('control_generation',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                   (json.dumps(generation),))
        return generation

    def control_generation(self):
        with self.connect() as db:
            return self._control_generation(db)

    def set_queue_enabled(self, enabled):
        self.configure_queue(enabled)

    def autopilot_enabled(self):
        return self.campaign_enabled()

    def set_autopilot_enabled(self, enabled):
        self.configure_campaign(enabled)

    def campaign_control(self):
        with self.connect() as db:
            values = dict(db.execute(
                "SELECT key,value FROM settings WHERE key IN ('campaign_enabled','active_campaign_id','autopilot_enabled')"
            ).fetchall())
        # Read the legacy flag only for staged database compatibility. New writes
        # always persist both explicit campaign settings.
        enabled = json.loads(values.get('campaign_enabled', values.get('autopilot_enabled', 'false')))
        campaign_id = json.loads(values['active_campaign_id']) if 'active_campaign_id' in values else None
        return {'enabled': bool(enabled), 'campaign_id': campaign_id}

    def campaign_enabled(self):
        return self.campaign_control()['enabled']

    def active_campaign_id(self):
        return self.campaign_control()['campaign_id']

    def configure_campaign(self, enabled, campaign_id=None):
        """Persist campaign identity and enabled state in one transaction.

        Queue state is kept for command compatibility, but campaign scheduling
        has its own selector and claim path and never falls through to it.
        """
        if campaign_id is not None and (not isinstance(campaign_id, str) or not campaign_id.strip()):
            raise ValueError('Campaign ID must be a nonempty string.')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if enabled and self._inference_pending(db):
                raise ValueError('Unresolved inference blocks the single model lane; inspect and reconcile its receipt before enabling work.')
            pilot = db.execute("SELECT value FROM settings WHERE key='pilot_task'").fetchone()
            if enabled and pilot and json.loads(pilot[0]) is not None:
                raise ValueError('Stop the single-company pilot before starting the backlog campaign.')
            current = db.execute("SELECT value FROM settings WHERE key='active_campaign_id'").fetchone()
            current_id = json.loads(current[0]) if current else None
            selected_id = campaign_id or current_id or DEFAULT_CAMPAIGN_ID
            if enabled and current_id not in (None, selected_id):
                raise ValueError('Stop the active campaign before selecting another campaign.')
            if not enabled and campaign_id is not None and current_id not in (None, campaign_id):
                raise ValueError('The requested campaign is not the active campaign.')
            if enabled:
                from coordinator_campaign import digest as membership_digest
                roster = db.execute('SELECT company_id,identity_digest FROM campaign_company_registry WHERE campaign_id=? ORDER BY company_id', (selected_id,)).fetchall()
                db.execute('INSERT OR IGNORE INTO campaign_seals VALUES (?,?,?)', (selected_id, membership_digest(roster), time.time()))
            for key, value in (('campaign_enabled', bool(enabled)),
                               ('active_campaign_id', selected_id),
                               ('autopilot_enabled', bool(enabled)),
                               ('queue_enabled', bool(enabled))):
                db.execute('INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                           (key, json.dumps(value)))
            self._bump_control_generation(db)
            if enabled:
                self._campaign_reconcile(db, selected_id)

    def configure_autopilot(self, enabled):
        self.configure_campaign(enabled)

    def configure_queue(self, enabled):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if enabled and self._inference_pending(db):
                raise ValueError('Unresolved inference blocks the single model lane; inspect and reconcile its receipt before enabling work.')
            pilot = db.execute("SELECT value FROM settings WHERE key='pilot_task'").fetchone()
            if enabled and pilot and json.loads(pilot[0]) is not None:
                raise ValueError('Stop the single-company pilot before resuming the global queue.')
            db.execute("INSERT INTO settings VALUES ('queue_enabled',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                       (json.dumps(bool(enabled)),))
            if not enabled:
                # The global pause is a stop control for every scheduler mode.
                # Retain active_campaign_id and SELECTED membership so an
                # explicit campaign restart resumes the same company.
                for key in ('campaign_enabled', 'autopilot_enabled'):
                    db.execute('INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                               (key, json.dumps(False)))
            self._bump_control_generation(db)

    def activation_snapshot(self, task_id):
        """Return the exact task/control generation to guard slow preparation."""
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT state FROM tasks WHERE id=?', (task_id,)).fetchone()
            if not row:
                raise ValueError('Task not found.')
            state = json.loads(row[0])
            return {'state': state, 'state_digest': task_state_digest(state),
                    'control_generation': self._control_generation(db)}

    def commit_activation(self, task_id, fields, *, expected_state_digest,
                          expected_control_generation, pilot=False,
                          max_calls=48, max_tokens=120000, max_seconds=3600):
        """CAS-style resume; validation and task/pilot publication are atomic."""
        if not isinstance(fields, dict):
            raise ValueError('Activation fields must be a dictionary.')
        allowed_fields = {'stop_requested', 'status', 'errors', 'reason', 'manifest',
                          'phase', 'baseline_passed', 'no_progress', 'workflow',
                          'evidence_requirements', 'checkpoint'}
        if set(fields) - allowed_fields:
            raise ValueError('Activation attempted to replace protected task identity or budget fields.')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT state FROM tasks WHERE id=?', (task_id,)).fetchone()
            if not row:
                raise ValueError('Task not found.')
            state = json.loads(row[0])
            self._require_current_identity(db, state)
            self._require_current_repair_revision(state)
            if (task_state_digest(state) != expected_state_digest
                    or self._control_generation(db) != expected_control_generation):
                raise ValueError('Task or scheduler controls changed during activation preparation; retry from current status.')
            if state['status'] in ('RUNNING', 'QUEUED', 'PAUSING'):
                raise ValueError('Task is already active or still pausing.')
            if self._inference_pending(db):
                raise ValueError('Uncertain inference requires inspection; automatic replay is blocked.')
            if reached_operator_gate(state):
                raise ValueError('This task reached its operator gate. Review the receipts before a new assignment.')
            if state['mode'] == 'develop' and state.get('authorization_version') != 1:
                raise ValueError('This older task lacks explicit development authorization.')
            from coordinator_baseline import verify_initial
            verify_initial(self, state)
            started = state.get('activated_at') if state.get('workflow_version') == 2 else state['created']
            exhausted = (state.get('sessions', 0) >= state.get('max_sessions', 0)
                         or state.get('calls', 0) >= max_calls
                         or state.get('tokens', 0) >= max_tokens
                         or started is not None and time.time() >= started + max_seconds)
            if exhausted:
                raise ValueError('Task budget exhausted. Review the checkpoint and start a new bounded assignment.')
            if db.execute('SELECT 1 FROM receipts WHERE task=? AND result IS NULL LIMIT 1',
                          (task_id,)).fetchone():
                raise ValueError('An interrupted action has no receipt. Inspect it before starting a new assignment; automatic replay is blocked.')
            rows = [(current_id, json.loads(raw)) for current_id, raw in
                    db.execute('SELECT id,state FROM tasks ORDER BY rowid').fetchall()]
            if any(current_id != task_id and other['status'] in ('RUNNING', 'PAUSING')
                   for current_id, other in rows):
                raise ValueError('Another task owns the execution lane.')
            controls = {key: json.loads(value) for key, value in db.execute(
                "SELECT key,value FROM settings WHERE key IN ('queue_enabled','campaign_enabled','active_campaign_id','pilot_task')"
            )}
            if pilot:
                if (controls.get('queue_enabled', True) or controls.get('campaign_enabled', False)
                        or controls.get('pilot_task') is not None):
                    raise ValueError('Pause queue and campaign controls before starting a single-company pilot.')
                if not state.get('isolated_workspace'):
                    raise ValueError('Pilot-only scheduling requires an isolated imported assignment.')
                active = [current_id for current_id, other in rows if current_id != task_id
                          and other['status'] in ('RUNNING', 'QUEUED', 'PAUSING')]
                if active:
                    raise ValueError('Other imported assignments are active; hold them before starting the pilot.')
            elif controls.get('pilot_task') not in (None, task_id):
                raise ValueError('Another task owns the single-company pilot lane.')

            if state.get('campaign_id'):
                if state.get('campaign_disposition') == EXCLUDED:
                    raise ValueError('Include the excluded campaign task before resuming it.')
                conflicts = [other['id'] for current_id, other in rows if current_id != task_id
                             and other.get('campaign_disposition') == SELECTED
                             and other['status'] in ('QUEUED', 'RUNNING', 'PAUSING', 'PAUSED')]
                if conflicts:
                    raise ValueError('Another task owns the campaign lane.')
                fields = dict(fields, campaign_disposition=SELECTED,
                              campaign_selected_at=time.time(),
                              campaign_run_id=uuid.uuid4().hex)
            self._reopen_campaign(db, state.get('campaign_id'))
            state.update(fields)
            state.update(status='QUEUED', stop_requested=False)
            # Activation fields must preserve the complete immutable binding.
            # Validate before publishing either task state or the pilot slot.
            validate_bound_identity(state)
            if pilot:
                db.execute("INSERT INTO settings VALUES ('pilot_task',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                           (json.dumps(task_id),))
            db.execute('UPDATE tasks SET state=? WHERE id=?', (json.dumps(state), task_id))
            self._bump_control_generation(db)
            return state

    def stop_pilot(self):
        """Clear the pilot slot and stop its task in one transaction."""
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT value FROM settings WHERE key='pilot_task'").fetchone()
            task_id = json.loads(row[0]) if row else None
            state = None
            if task_id:
                task_row = db.execute('SELECT state FROM tasks WHERE id=?', (task_id,)).fetchone()
                if task_row:
                    state = json.loads(task_row[0])
                    if state['status'] in ('RUNNING', 'QUEUED'):
                        state.update(status='PAUSING' if state['status'] == 'RUNNING' else 'PAUSED',
                                     stop_requested=state['status'] == 'RUNNING',
                                     reason='Pilot stop requested.')
                        db.execute('UPDATE tasks SET state=? WHERE id=?', (json.dumps(state), task_id))
            db.execute("INSERT INTO settings VALUES ('pilot_task','null') ON CONFLICT(key) DO UPDATE SET value='null'")
            self._bump_control_generation(db)
            return state

    def activate_next_campaign(self, campaign_id=None, *, require_enabled=True):
        """Select exactly one held member of the active campaign."""
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            controls = dict(db.execute(
                "SELECT key,value FROM settings WHERE key IN ('campaign_enabled','active_campaign_id','pilot_task')"
            ).fetchall())
            enabled = json.loads(controls.get('campaign_enabled', 'false'))
            active_campaign = json.loads(controls['active_campaign_id']) if 'active_campaign_id' in controls else None
            pilot = json.loads(controls['pilot_task']) if 'pilot_task' in controls else None
            selected_campaign = campaign_id or active_campaign or DEFAULT_CAMPAIGN_ID
            reconciled = self._campaign_reconcile(db, selected_campaign)
            if reconciled['state'] in ('PAUSED_RECONCILIATION', 'DRAINED', 'DRAINED_WITH_EXCEPTIONS'):
                return None
            if require_enabled and (not enabled or active_campaign != selected_campaign):
                return None
            if pilot is not None:
                return None
            rows = db.execute('SELECT id,state FROM tasks ORDER BY rowid').fetchall()
            active = []
            candidate = None
            selected = None
            selected_count = 0
            for task_id, raw in rows:
                state = json.loads(raw)
                if state.get('campaign_id') == selected_campaign and state.get('campaign_disposition') in (HELD_FOR_CAMPAIGN, SELECTED):
                    registry = db.execute('SELECT current_task_id FROM campaign_company_registry WHERE campaign_id=? AND company_id=?', (selected_campaign, state.get('campaign_company_id'))).fetchone()
                    if registry and registry[0] != task_id:
                        continue
                    self._require_current_identity(db, state)
                if state['status'] in ('RUNNING', 'PAUSING'):
                    active.append(task_id)
                if state.get('campaign_disposition') == SELECTED:
                    selected = state
                    selected_count += 1
                if (candidate is None and state.get('campaign_id') == selected_campaign
                        and state.get('campaign_disposition') == HELD_FOR_CAMPAIGN
                        and not state.get('stop_requested')
                        and state['status'] == 'PAUSED' and state['phase'] == 'baseline'
                        and state.get('activated_at') is None
                        and state.get('campaign_selected_at') is None
                        and state.get('selected_at') is None
                        and state.get('calls', 0) == 0 and state.get('sessions', 0) == 0
                        and state.get('tokens', 0) == 0
                        and state.get('authorization_version') == 1
                        and state.get('mode') == 'develop'
                        and state.get('integration')
                        and not db.execute('SELECT 1 FROM receipts WHERE task=? LIMIT 1',
                                           (task_id,)).fetchone()):
                    candidate = state
            if active:
                return None
            if selected is not None:
                if selected_count != 1:
                    return None
                if selected.get('campaign_id') != selected_campaign:
                    return None
                if selected['status'] == 'PAUSED' and not selected.get('stop_requested'):
                    from coordinator_baseline import verify_initial
                    verify_initial(self, selected)
                    selected.update(status='QUEUED', reason='Campaign restarted; retained selected company.')
                    db.execute('UPDATE tasks SET state=? WHERE id=?', (json.dumps(selected), selected['id']))
                    return selected
                return None
            if candidate is None:
                return None
            from coordinator_baseline import verify_initial
            verify_initial(self, candidate)
            candidate.update(status='QUEUED', stop_requested=False, errors=0,
                             campaign_disposition=SELECTED,
                             campaign_selected_at=time.time(),
                             campaign_run_id=uuid.uuid4().hex,
                             selected_at=time.time(), integration_run_id=uuid.uuid4().hex,
                             worker_context_policy='fresh_context_for_each_call_and_company',
                             reason='Selected by one-company campaign with a fresh integration worker.')
            db.execute('UPDATE tasks SET state=? WHERE id=?',
                       (json.dumps(candidate), candidate['id']))
            self._bump_control_generation(db)
            return candidate

    def activate_next_untouched(self):
        """Compatibility name for tests and saved callers; campaign-scoped."""
        return self.activate_next_campaign(DEFAULT_CAMPAIGN_ID)

    def claim_queued(self, task_id=None):
        """Atomically lease one queued task to a scheduler process.

        The status transition is the cross-process mutex.  A second service
        instance cannot observe the same task as QUEUED after this commit.
        Existing write-ahead receipt recovery remains the crash boundary.
        """
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if self._inference_pending(db):
                return None
            rows = db.execute('SELECT id,state FROM tasks ORDER BY rowid').fetchall()
            decoded = [(current_id, json.loads(raw)) for current_id, raw in rows]
            if any(state['status'] in ('RUNNING', 'PAUSING') for _, state in decoded):
                return None
            for current_id, state in decoded:
                if state['status'] != 'QUEUED' or task_id is not None and current_id != task_id:
                    continue
                if state.get('campaign_id') or state.get('campaign_disposition'):
                    continue
                self._require_current_identity(db, state)
                if not self._repair_revision_is_current(state):
                    state.update(status='PAUSED', stop_requested=True,
                                 reason='Company revision is no longer current; obtain a new held repair from the current Company record.')
                    db.execute('UPDATE tasks SET state=? WHERE id=?', (json.dumps(state), current_id))
                    self._bump_control_generation(db)
                    return None
                state.update(status='RUNNING', scheduler_claimed_at=time.time())
                db.execute('UPDATE tasks SET state=? WHERE id=?',
                           (json.dumps(state), current_id))
                self._bump_control_generation(db)
                return state
        return None

    def claim_campaign(self, campaign_id=None):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if self._inference_pending(db):
                return None
            controls = dict(db.execute(
                "SELECT key,value FROM settings WHERE key IN ('campaign_enabled','active_campaign_id')"
            ).fetchall())
            enabled = json.loads(controls.get('campaign_enabled', 'false'))
            active_campaign = json.loads(controls['active_campaign_id']) if 'active_campaign_id' in controls else None
            selected_campaign = campaign_id or active_campaign
            if not enabled or not selected_campaign or active_campaign != selected_campaign:
                return None
            rows = db.execute('SELECT id,state FROM tasks ORDER BY rowid').fetchall()
            decoded = [(task_id, json.loads(raw)) for task_id, raw in rows]
            if any(state['status'] in ('RUNNING', 'PAUSING') for _, state in decoded):
                return None
            matches = [(task_id, state) for task_id, state in decoded
                       if state.get('campaign_id') == selected_campaign
                       and state.get('campaign_disposition') == SELECTED
                       and state['status'] == 'QUEUED' and not state.get('stop_requested')]
            if len(matches) != 1:
                return None
            task_id, state = matches[0]
            self._require_current_identity(db, state)
            if not self._repair_revision_is_current(state):
                state.update(status='PAUSED', stop_requested=True,
                             reason='Company revision is no longer current; obtain a new held repair from the current Company record.')
                db.execute('UPDATE tasks SET state=? WHERE id=?', (json.dumps(state), task_id))
                self._bump_control_generation(db)
                return None
            state.update(status='RUNNING', scheduler_claimed_at=time.time())
            db.execute('UPDATE tasks SET state=? WHERE id=?', (json.dumps(state), task_id))
            self._bump_control_generation(db)
            return state

    def claim_pilot(self, task_id):
        """Targeted compatibility path; it never discovers another task."""
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if self._inference_pending(db):
                return None
            pilot = db.execute("SELECT value FROM settings WHERE key='pilot_task'").fetchone()
            if not pilot or json.loads(pilot[0]) != task_id:
                return None
            rows = db.execute('SELECT id,state FROM tasks ORDER BY rowid').fetchall()
            decoded = [(current_id, json.loads(raw)) for current_id, raw in rows]
            if any(state['status'] in ('RUNNING', 'PAUSING') for _, state in decoded):
                return None
            for current_id, state in decoded:
                if current_id == task_id and state['status'] == 'QUEUED' and not state.get('stop_requested'):
                    self._require_current_identity(db, state)
                    if not self._repair_revision_is_current(state):
                        state.update(status='PAUSED', stop_requested=True,
                                     reason='Company revision is no longer current; obtain a new held repair from the current Company record.')
                        db.execute('UPDATE tasks SET state=? WHERE id=?', (json.dumps(state), current_id))
                        self._bump_control_generation(db)
                        return None
                    state.update(status='RUNNING', scheduler_claimed_at=time.time())
                    db.execute('UPDATE tasks SET state=? WHERE id=?', (json.dumps(state), current_id))
                    self._bump_control_generation(db)
                    return state
            return None

    def set_campaign_disposition(self, task_id, disposition):
        if disposition not in CAMPAIGN_DISPOSITIONS:
            raise ValueError('Invalid campaign disposition.')
        state = self.get(task_id)
        if not state.get('campaign_id'):
            raise ValueError('Task is not a campaign member.')
        return self.update(task_id, campaign_disposition=disposition)

    def pause_task(self, task_id, reason='Pause requested.'):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT state FROM tasks WHERE id=?', (task_id,)).fetchone()
            if not row:
                raise ValueError('Task not found.')
            state = json.loads(row[0])
            terminal = reached_operator_gate(state)
            if state.get('campaign_id') and state.get('campaign_disposition') != CAMPAIGN_FINISHED:
                state['campaign_disposition'] = USER_PAUSED
            state.update(stop_requested=True, reason=reason)
            if not terminal:
                state['status'] = 'PAUSING' if state['status'] == 'RUNNING' else 'PAUSED'
            db.execute('UPDATE tasks SET state=? WHERE id=?', (json.dumps(state), task_id))
            self._bump_control_generation(db)
            return state

    def exclude_campaign_task(self, task_id):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT state FROM tasks WHERE id=?', (task_id,)).fetchone()
            if not row:
                raise ValueError('Task not found.')
            state = json.loads(row[0])
            if not state.get('campaign_id'):
                raise ValueError('Task is not a campaign member.')
            if state.get('campaign_disposition') == CAMPAIGN_FINISHED:
                raise ValueError('This task reached its operator gate and cannot be excluded or reopened.')
            terminal = reached_operator_gate(state)
            state.update(campaign_disposition=EXCLUDED, stop_requested=True,
                         reason='Excluded from campaign by operator.')
            if not terminal:
                state['status'] = 'PAUSING' if state['status'] == 'RUNNING' else 'PAUSED'
            db.execute('UPDATE tasks SET state=? WHERE id=?', (json.dumps(state), task_id))
            self._bump_control_generation(db)
            return state

    def include_campaign_task(self, task_id):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT state FROM tasks WHERE id=?', (task_id,)).fetchone()
            if not row:
                raise ValueError('Task not found.')
            state = json.loads(row[0])
            if state.get('campaign_disposition') != EXCLUDED:
                raise ValueError('Only an excluded campaign task can be included.')
            self._reopen_campaign(db, state.get('campaign_id'))
            if reached_operator_gate(state):
                state.update(campaign_disposition=USER_PAUSED, stop_requested=True,
                             reason='Included in campaign; operator gate retained.')
                db.execute('UPDATE tasks SET state=? WHERE id=?', (json.dumps(state), task_id))
                self._bump_control_generation(db)
                return state
            untouched = (state['phase'] == 'baseline' and state.get('activated_at') is None
                         and state.get('campaign_selected_at') is None
                         and state.get('calls', 0) == 0 and state.get('sessions', 0) == 0
                         and state.get('tokens', 0) == 0
                         and not db.execute('SELECT 1 FROM receipts WHERE task=? LIMIT 1',
                                            (task_id,)).fetchone())
            if untouched:
                state.update(campaign_disposition=HELD_FOR_CAMPAIGN,
                             stop_requested=False, status='PAUSED',
                             reason='Included in campaign; held for selection.')
            else:
                state.update(campaign_disposition=USER_PAUSED,
                             stop_requested=True, status='PAUSED',
                             reason='Included in campaign; explicit resume required for prior work.')
            db.execute('UPDATE tasks SET state=? WHERE id=?', (json.dumps(state), task_id))
            self._bump_control_generation(db)
            return state

    def resume_campaign_task(self, task_id, **fields):
        """Compatibility entry point using the canonical guarded activation."""
        snapshot = self.activation_snapshot(task_id)
        if not snapshot['state'].get('campaign_id'):
            raise ValueError('Task is not a campaign member.')
        return self.commit_activation(
            task_id, fields,
            expected_state_digest=snapshot['state_digest'],
            expected_control_generation=snapshot['control_generation'])

    def pilot_task(self):
        with self.connect() as db:
            value = db.execute("SELECT value FROM settings WHERE key='pilot_task'").fetchone()
        return json.loads(value[0]) if value else None

    def set_pilot_task(self, task_id):
        """Fixture cleanup helper; pilot publication requires commit_activation."""
        if task_id is not None:
            raise ValueError('Use commit_activation to publish a validated pilot task.')
        self.stop_pilot()

    def get(self, task_id):
        if not isinstance(task_id, str) or not re.fullmatch(r'WRAP-[a-f0-9]{10}', task_id):
            raise ValueError('Use a task ID from /wrapper list.')
        with self.connect() as db:
            row = db.execute('SELECT state FROM tasks WHERE id=?', (task_id,)).fetchone()
        if not row:
            raise ValueError('Task not found.')
        return json.loads(row[0])

    def update(self, task_id, **fields):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT state FROM tasks WHERE id=?', (task_id,)).fetchone()
            if not row:
                raise ValueError('Task not found.')
            state = json.loads(row[0])
            validate_bound_identity(state)
            protected = {'integration', 'integration_identity', 'integration_identity_digest', 'worker_assignment', 'worker_assignment_digest', 'identity_binding_digest', 'evidence_requirements_digest', 'edit_scope', 'acceptance_bundle', 'acceptance_baseline_manifest', 'assignment_baseline', 'evidence_epoch', 'objective', 'tests', 'campaign_manifest_digest', 'campaign_id', 'campaign_company_id', 'retry_of', 'held_repair_key', 'repair_provenance'}
            if any(key in fields and fields[key] != state.get(key) for key in protected):
                raise ValueError('Immutable assignment identity cannot be changed.')
            state.update(fields)
            validate_bound_identity(state)
            db.execute('UPDATE tasks SET state=? WHERE id=?', (json.dumps(state), task_id))
        return state

    def all(self):
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute('SELECT state FROM tasks ORDER BY rowid')]

    def intent(self, task_id, phase, name, args):
        encoded = json.dumps(args, sort_keys=True)
        signature = hashlib.sha256((name + encoded).encode()).hexdigest()
        with self.connect() as db:
            cursor = db.execute('INSERT INTO receipts(task,phase,name,arguments,signature,created) VALUES (?,?,?,?,?,?)',
                                (task_id, phase, name, encoded, signature, time.time()))
            return cursor.lastrowid

    def active_intent(self, task_id, phase, name, args):
        """Write the intent only while this task still owns the action lane."""
        encoded = json.dumps(args, sort_keys=True)
        signature = hashlib.sha256((name + encoded).encode()).hexdigest()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if self._inference_pending(db):
                return None
            row = db.execute('SELECT state FROM tasks WHERE id=?', (task_id,)).fetchone()
            if not row:
                raise ValueError('Task not found.')
            state = json.loads(row[0])
            self._require_current_identity(db, state)
            if state.get('repair_provenance') and not self._repair_revision_is_current(state):
                state.update(status='PAUSED', stop_requested=True,
                             reason='Company revision is no longer current; obtain a new held repair from the current Company record.')
                db.execute('UPDATE tasks SET state=? WHERE id=?', (json.dumps(state), task_id))
                self._bump_control_generation(db)
                return None
            if state['phase'] != phase or not self._inference_allowed(db, state):
                return None
            cursor = db.execute('INSERT INTO receipts(task,phase,name,arguments,signature,created) VALUES (?,?,?,?,?,?)',
                                (task_id, phase, name, encoded, signature, time.time()))
            return cursor.lastrowid

    def finish(self, receipt_id, result):
        with self.connect() as db:
            db.execute('UPDATE receipts SET result=? WHERE id=?', (json.dumps(result), receipt_id))

    def receipts(self, task_id):
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            rows = db.execute('SELECT * FROM receipts WHERE task=? ORDER BY id', (task_id,)).fetchall()
        return [{**dict(row), 'arguments': json.loads(row['arguments']),
                 'result': json.loads(row['result']) if row['result'] else None} for row in rows]

    def recover(self, reconcile_inference=None):
        if self.unresolved_inferences():
            self.configure_queue(False)
        for task in self.all():
            for receipt in self.inference_receipts(task['id']):
                if receipt['status'] in ('DISPATCHING', 'UNCERTAIN') and callable(reconcile_inference):
                    # Transport/status errors intentionally leave the durable
                    # hold in place.  A callback may settle only a matching
                    # remote terminal control receipt.
                    try:
                        reconcile_inference(receipt)
                    except Exception:
                        pass
                    receipt = next((item for item in self.inference_receipts(task['id'])
                                    if item['request_id'] == receipt['request_id']), receipt)
                if receipt['status'] == 'DISPATCHING':
                    self.finalize_inference(receipt['request_id'], terminal_error='Service restarted with dispatched inference; no replay.')
        for state in self.all():
            self.end_inference_session(state['id'], state.get('inference_session_id'))
            if any(r['status'] == 'UNCERTAIN' for r in self.inference_receipts(state['id'])):
                if not reached_operator_gate(state):
                    self.update(state['id'], status='PAUSED_RECOVERY', reason='Uncertain inference requires operator inspection; no replay.')
                continue
            uncertain = (state['status'] in ('RUNNING', 'PAUSING', 'QUEUED') and
                         any(r['result'] is None for r in self.receipts(state['id'])))
            if uncertain:
                self.update(state['id'], status='PAUSED_RECOVERY',
                            reason='Interrupted action needs inspection before resume; no action was replayed.')
            elif state['status'] == 'PAUSING':
                self.update(state['id'], status='PAUSED', reason='Pause preserved across service restart.')
            elif state['status'] == 'RUNNING':
                self.update(state['id'], status='QUEUED', reason='Recovered checkpoint.')

    def export(self, task_id):
        with self.export_lock:
            return self._export(task_id)

    def _export(self, task_id):
        state = self.get(task_id)
        folder = self.base / task_id
        folder.mkdir(exist_ok=True, mode=0o700)
        checkpoint = state['checkpoint']
        text = (f"# {task_id}\n\nStatus: {state['status']}\nPhase: {state['phase']}\n\n"
                f"Audited original objective: {state['objective']}\n\nCanonical assignment: {state.get('worker_assignment', state['objective'])}\n\nIdentity: {json.dumps(state.get('integration_identity'))}\nIdentity digest: {state.get('integration_identity_digest')}\n\nReason: {state['reason']}\n\n" +
                ('Budgets: One hour from first assignment, including pauses; initial queue wait is excluded. ' if state.get('workflow_version') == 2 else 'Budgets: One-hour lifetime from creation, including queued and paused time. ') +
                'Resume does not reset time, calls, sessions or tokens. Already-started actions may finish; the next action is checked before dispatch.\n\n' +
                f"Worker summary (model-authored, verify against receipts):\n{checkpoint.get('summary', '')}\n\n"
                f"Next action: {next_action(state)}\n\n"
                f"Python work plan: {json.dumps(state.get('workflow', {}).get('plan', {}))}\n\n"

                f"Inspect progress:\n\n`/wrapper status {task_id}`\n\n"
                "Live scraper validation, installation and GitHub delivery of generated wrappers require operator review.\n")
        for name, payload in [('checkpoint.json', json.dumps(state, indent=2)),
                              ('receipts.json', json.dumps(self.receipts(task_id), indent=2)),
                              ('inference_receipts.json', json.dumps(self.inference_receipts(task_id), indent=2)),
                              ('HANDOFF.md', text)]:
            temporary = folder / (name + '.new')
            temporary.write_text(payload)
            temporary.replace(folder / name)
        return text
