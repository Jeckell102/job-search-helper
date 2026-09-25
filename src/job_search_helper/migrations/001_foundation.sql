CREATE TABLE app_metadata (
    key TEXT PRIMARY KEY NOT NULL,
    value TEXT NOT NULL
);

CREATE TABLE companies (
    company_id TEXT PRIMARY KEY NOT NULL CHECK (length(trim(company_id)) > 0),
    company_name TEXT NOT NULL CHECK (length(trim(company_name)) > 0),
    website_url TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused', 'archived')),
    category TEXT NOT NULL DEFAULT '',
    technology_focus TEXT NOT NULL DEFAULT '',
    priority TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    personal_rationale TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    row_version INTEGER NOT NULL DEFAULT 1 CHECK (typeof(row_version) = 'integer' AND row_version > 0)
);

CREATE TABLE job_sources (
    source_id TEXT PRIMARY KEY NOT NULL,
    company_id TEXT NOT NULL REFERENCES companies(company_id),
    provider TEXT NOT NULL CHECK (length(trim(provider)) > 0),
    provider_namespace TEXT NOT NULL CHECK (length(trim(provider_namespace)) > 0),
    careers_url TEXT NOT NULL CHECK (length(trim(careers_url)) > 0),
    is_current INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0, 1)),
    created_at TEXT NOT NULL,
    UNIQUE (source_id, company_id),
    UNIQUE (company_id, provider, provider_namespace)
);
CREATE UNIQUE INDEX one_current_source ON job_sources(company_id) WHERE is_current = 1;

CREATE TABLE source_scopes (
    scope_id TEXT PRIMARY KEY NOT NULL,
    source_id TEXT NOT NULL REFERENCES job_sources(source_id),
    canonical_inventory_url TEXT NOT NULL,
    scope_parameters_json TEXT NOT NULL,
    scope_fingerprint TEXT NOT NULL,
    adapter_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (source_id, scope_fingerprint),
    UNIQUE (scope_id, source_id)
);
CREATE TRIGGER source_scopes_immutable_update BEFORE UPDATE ON source_scopes
BEGIN
    SELECT RAISE(ABORT, 'Source scopes are immutable; create a revision');
END;
CREATE TRIGGER source_scopes_immutable_delete BEFORE DELETE ON source_scopes
BEGIN
    SELECT RAISE(ABORT, 'Source scopes preserve comparison history');
END;

CREATE TABLE jobs (
    job_id TEXT PRIMARY KEY NOT NULL,
    company_id TEXT NOT NULL REFERENCES companies(company_id),
    source_id TEXT,
    source_job_id TEXT CHECK (source_job_id IS NULL OR length(trim(source_job_id)) > 0),
    requisition_id TEXT NOT NULL DEFAULT '',
    current_version_id TEXT,
    origin TEXT NOT NULL CHECK (origin IN ('scraped', 'manual', 'imported')),
    first_seen_at TEXT,
    last_seen_at TEXT,
    last_material_change_at TEXT,
    lifecycle_status TEXT NOT NULL DEFAULT 'unknown' CHECK (lifecycle_status IN ('active', 'missing', 'closed', 'unknown')),
    closure_basis TEXT,
    closed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    row_version INTEGER NOT NULL DEFAULT 1 CHECK (typeof(row_version) = 'integer' AND row_version > 0),
    CHECK (source_job_id IS NULL OR source_id IS NOT NULL),
    CHECK (origin != 'scraped' OR source_id IS NOT NULL),
    UNIQUE (job_id, source_id),
    UNIQUE (source_id, source_job_id),
    FOREIGN KEY (source_id, company_id) REFERENCES job_sources(source_id, company_id),
    FOREIGN KEY (current_version_id, job_id) REFERENCES job_versions(version_id, job_id)
        DEFERRABLE INITIALLY DEFERRED
);
CREATE INDEX jobs_company_lifecycle ON jobs(company_id, lifecycle_status);

CREATE TABLE job_versions (
    version_id TEXT PRIMARY KEY NOT NULL,
    job_id TEXT NOT NULL REFERENCES jobs(job_id),
    title TEXT NOT NULL,
    location TEXT NOT NULL,
    work_arrangement TEXT NOT NULL,
    compensation_text TEXT NOT NULL,
    description TEXT NOT NULL,
    department TEXT NOT NULL,
    job_url TEXT NOT NULL,
    is_listed INTEGER NOT NULL CHECK (is_listed IN (0, 1)),
    source_created_raw TEXT NOT NULL,
    source_modified_raw TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    material_hash TEXT NOT NULL,
    hash_version TEXT NOT NULL,
    evidence_hash TEXT NOT NULL,
    normalizer_version TEXT NOT NULL,
    source_metadata_json TEXT NOT NULL,
    UNIQUE (version_id, job_id),
    UNIQUE (job_id, evidence_hash, normalizer_version, hash_version)
);
CREATE INDEX versions_job_observed ON job_versions(job_id, observed_at);
CREATE TRIGGER job_versions_immutable_update BEFORE UPDATE ON job_versions
BEGIN
    SELECT RAISE(ABORT, 'Job evidence is immutable; create a version');
END;
CREATE TRIGGER job_versions_immutable_delete BEFORE DELETE ON job_versions
BEGIN
    SELECT RAISE(ABORT, 'Job evidence must be preserved');
END;

CREATE TABLE job_identity_aliases (
    alias_id TEXT PRIMARY KEY NOT NULL,
    job_id TEXT NOT NULL REFERENCES jobs(job_id),
    source_id TEXT,
    kind TEXT NOT NULL CHECK (kind IN ('legacy_key', 'canonical_url', 'provider_id', 'browser_id')),
    value TEXT NOT NULL CHECK (length(trim(value)) > 0),
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    provenance TEXT NOT NULL,
    FOREIGN KEY (job_id, source_id) REFERENCES jobs(job_id, source_id)
);
CREATE INDEX aliases_lookup ON job_identity_aliases(source_id, kind, value);
CREATE INDEX aliases_job ON job_identity_aliases(job_id);

CREATE TABLE applications (
    application_id TEXT PRIMARY KEY NOT NULL,
    job_id TEXT NOT NULL REFERENCES jobs(job_id),
    application_status TEXT NOT NULL CHECK (application_status IN (
        'interested', 'preparing', 'applied', 'interviewing', 'offer', 'accepted',
        'rejected', 'withdrawn', 'archived', 'unknown'
    )),
    date_applied TEXT,
    date_saved TEXT,
    notes TEXT NOT NULL DEFAULT '',
    resume_used TEXT NOT NULL DEFAULT '',
    job_url_at_application TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    row_version INTEGER NOT NULL DEFAULT 1 CHECK (typeof(row_version) = 'integer' AND row_version > 0)
);
CREATE INDEX applications_job_status ON applications(job_id, application_status);
CREATE UNIQUE INDEX one_open_application ON applications(job_id)
    WHERE application_status IN ('interested', 'preparing', 'applied', 'interviewing', 'offer');

CREATE TABLE application_events (
    event_id TEXT PRIMARY KEY NOT NULL,
    application_id TEXT NOT NULL REFERENCES applications(application_id),
    occurred_at TEXT,
    recorded_at TEXT NOT NULL,
    old_status TEXT,
    new_status TEXT NOT NULL,
    note TEXT NOT NULL,
    actor TEXT NOT NULL CHECK (length(trim(actor)) > 0)
);
CREATE INDEX events_application_time ON application_events(application_id, recorded_at);
CREATE TRIGGER application_events_immutable_update BEFORE UPDATE ON application_events
BEGIN
    SELECT RAISE(ABORT, 'Application history is append-only');
END;
CREATE TRIGGER application_events_immutable_delete BEFORE DELETE ON application_events
BEGIN
    SELECT RAISE(ABORT, 'Application history must be preserved');
END;

CREATE TABLE scan_cycles (
    cycle_id TEXT PRIMARY KEY NOT NULL,
    cycle_sequence INTEGER NOT NULL UNIQUE CHECK (typeof(cycle_sequence) = 'integer' AND cycle_sequence > 0),
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('running', 'interrupted', 'completed', 'completed_with_exceptions', 'cancelled')),
    initiated_by TEXT NOT NULL,
    last_checkpoint_at TEXT,
    notes TEXT NOT NULL DEFAULT '',
    run_settings_json TEXT NOT NULL,
    application_version TEXT NOT NULL
);
CREATE INDEX cycles_status ON scan_cycles(status, cycle_sequence);

CREATE TABLE import_batches (
    import_id TEXT PRIMARY KEY NOT NULL,
    input_fingerprint TEXT NOT NULL,
    format_version TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'completed', 'failed')),
    started_at TEXT NOT NULL,
    completed_at TEXT
);
CREATE INDEX imports_fingerprint ON import_batches(input_fingerprint, format_version);

CREATE TABLE legacy_records (
    record_id TEXT PRIMARY KEY NOT NULL,
    import_id TEXT NOT NULL REFERENCES import_batches(import_id),
    source_location TEXT NOT NULL,
    raw_record_json TEXT NOT NULL,
    mapped_entity_id TEXT,
    conflict_reason TEXT,
    UNIQUE (import_id, source_location)
);
