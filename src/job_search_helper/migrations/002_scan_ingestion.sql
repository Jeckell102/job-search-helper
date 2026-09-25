ALTER TABLE job_versions ADD COLUMN source_created_at TEXT;
ALTER TABLE job_versions ADD COLUMN source_modified_at TEXT;
ALTER TABLE job_versions ADD COLUMN date_parser_version TEXT;
ALTER TABLE jobs ADD COLUMN latest_observation_sequence INTEGER NOT NULL DEFAULT 0;

CREATE TABLE cycle_companies (
    cycle_id TEXT NOT NULL REFERENCES scan_cycles(cycle_id),
    company_id TEXT NOT NULL REFERENCES companies(company_id),
    source_id TEXT NOT NULL,
    scope_id TEXT NOT NULL,
    company_name_at_start TEXT NOT NULL,
    careers_url_at_start TEXT NOT NULL,
    provider_at_start TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('queued', 'fetching', 'pending_apply', 'complete', 'partial', 'blocked', 'failed', 'unsupported')),
    selected_attempt_id TEXT,
    last_checkpoint_at TEXT,
    PRIMARY KEY (cycle_id, company_id),
    UNIQUE (cycle_id, company_id, scope_id, source_id),
    FOREIGN KEY (source_id, company_id) REFERENCES job_sources(source_id, company_id),
    FOREIGN KEY (scope_id, source_id) REFERENCES source_scopes(scope_id, source_id),
    FOREIGN KEY (selected_attempt_id, cycle_id, company_id) REFERENCES scan_attempts(attempt_id, cycle_id, company_id)
        DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE scan_attempts (
    attempt_id TEXT PRIMARY KEY NOT NULL,
    cycle_id TEXT NOT NULL,
    company_id TEXT NOT NULL,
    scope_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    attempt_number INTEGER NOT NULL CHECK (attempt_number > 0),
    observation_sequence INTEGER NOT NULL UNIQUE CHECK (observation_sequence > 0),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    applied_at TEXT,
    fetch_status TEXT CHECK (fetch_status IN ('complete', 'partial', 'blocked', 'failed', 'unsupported', 'interrupted')),
    apply_status TEXT NOT NULL CHECK (apply_status IN ('awaiting_fetch', 'pending', 'applied', 'quarantined')),
    error_message TEXT NOT NULL DEFAULT '',
    UNIQUE (cycle_id, company_id, attempt_number),
    UNIQUE (attempt_id, cycle_id, company_id),
    UNIQUE (attempt_id, scope_id, source_id),
    FOREIGN KEY (cycle_id, company_id, scope_id, source_id)
        REFERENCES cycle_companies(cycle_id, company_id, scope_id, source_id)
);
CREATE INDEX attempts_cycle ON scan_attempts(cycle_id, company_id);

CREATE TABLE inventory_batches (
    attempt_id TEXT PRIMARY KEY NOT NULL REFERENCES scan_attempts(attempt_id),
    payload_schema_version INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    saved_at TEXT NOT NULL,
    apply_state TEXT NOT NULL CHECK (apply_state IN ('pending', 'applied', 'quarantined'))
);
CREATE INDEX batches_pending ON inventory_batches(apply_state);
CREATE TRIGGER inventory_payload_immutable BEFORE UPDATE OF payload_schema_version, payload_json, payload_hash, saved_at ON inventory_batches
BEGIN
    SELECT RAISE(ABORT, 'Fetched evidence is immutable');
END;
CREATE TRIGGER inventory_payload_preserved BEFORE DELETE ON inventory_batches
BEGIN
    SELECT RAISE(ABORT, 'Fetched evidence must be preserved');
END;

CREATE TABLE source_scan_state (
    source_id TEXT PRIMARY KEY NOT NULL REFERENCES job_sources(source_id),
    scope_id TEXT NOT NULL,
    latest_observation_sequence INTEGER NOT NULL,
    FOREIGN KEY (scope_id, source_id) REFERENCES source_scopes(scope_id, source_id)
);

CREATE TABLE job_scope_state (
    job_id TEXT NOT NULL,
    scope_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    last_seen_cycle_id TEXT REFERENCES scan_cycles(cycle_id),
    last_missing_cycle_id TEXT REFERENCES scan_cycles(cycle_id),
    consecutive_missing INTEGER NOT NULL DEFAULT 0 CHECK (consecutive_missing >= 0),
    last_reconciled_sequence INTEGER NOT NULL,
    PRIMARY KEY (job_id, scope_id),
    FOREIGN KEY (job_id, source_id) REFERENCES jobs(job_id, source_id),
    FOREIGN KEY (scope_id, source_id) REFERENCES source_scopes(scope_id, source_id)
);

CREATE TABLE job_observations (
    attempt_id TEXT NOT NULL,
    job_id TEXT NOT NULL,
    scope_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    version_id TEXT,
    presence TEXT NOT NULL CHECK (presence IN ('present', 'absent')),
    observed_at TEXT NOT NULL,
    change_kind TEXT NOT NULL CHECK (change_kind IN ('new', 'changed', 'unchanged', 'reopened', 'missing', 'closed', 'historical')),
    applied_sequence INTEGER NOT NULL,
    PRIMARY KEY (attempt_id, job_id),
    FOREIGN KEY (attempt_id, scope_id, source_id) REFERENCES scan_attempts(attempt_id, scope_id, source_id),
    FOREIGN KEY (job_id, source_id) REFERENCES jobs(job_id, source_id),
    FOREIGN KEY (version_id, job_id) REFERENCES job_versions(version_id, job_id)
);
CREATE INDEX observations_job ON job_observations(job_id, applied_sequence);
CREATE TRIGGER observations_immutable_update BEFORE UPDATE ON job_observations
BEGIN
    SELECT RAISE(ABORT, 'Observations are immutable');
END;
CREATE TRIGGER observations_immutable_delete BEFORE DELETE ON job_observations
BEGIN
    SELECT RAISE(ABORT, 'Observations must be preserved');
END;
