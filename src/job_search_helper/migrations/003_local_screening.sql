CREATE TABLE policy_profiles (
    policy_fingerprint TEXT PRIMARY KEY NOT NULL,
    format_version TEXT NOT NULL,
    rules_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TRIGGER policy_profiles_immutable_update BEFORE UPDATE ON policy_profiles
BEGIN
    SELECT RAISE(ABORT, 'Policy profiles are immutable; create a revision');
END;
CREATE TRIGGER policy_profiles_immutable_delete BEFORE DELETE ON policy_profiles
BEGIN
    SELECT RAISE(ABORT, 'Policy history must be preserved');
END;

CREATE TABLE assessments (
    assessment_sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    assessment_id TEXT NOT NULL UNIQUE,
    job_id TEXT NOT NULL REFERENCES jobs(job_id),
    version_id TEXT NOT NULL,
    policy_fingerprint TEXT NOT NULL REFERENCES policy_profiles(policy_fingerprint),
    evaluator_version TEXT NOT NULL,
    result TEXT NOT NULL CHECK (result IN ('excluded', 'needs_review', 'no_exclusion')),
    reason TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    actor TEXT NOT NULL CHECK (length(trim(actor)) > 0),
    evaluated_at TEXT NOT NULL,
    supersedes_assessment_id TEXT,
    UNIQUE (assessment_id, job_id),
    FOREIGN KEY (version_id, job_id) REFERENCES job_versions(version_id, job_id),
    FOREIGN KEY (supersedes_assessment_id, job_id) REFERENCES assessments(assessment_id, job_id)
);
CREATE INDEX assessments_job_sequence ON assessments(job_id, assessment_sequence DESC);
CREATE TRIGGER assessments_immutable_update BEFORE UPDATE ON assessments
BEGIN
    SELECT RAISE(ABORT, 'Assessments are append-only; evaluate a new revision');
END;
CREATE TRIGGER assessments_immutable_delete BEFORE DELETE ON assessments
BEGIN
    SELECT RAISE(ABORT, 'Assessment history must be preserved');
END;

CREATE VIEW current_screening AS
SELECT a.*, CASE WHEN a.version_id=j.current_version_id THEN 0 ELSE 1 END AS stale
FROM assessments a JOIN jobs j USING(job_id)
WHERE a.assessment_sequence=(SELECT max(previous.assessment_sequence) FROM assessments previous WHERE previous.job_id=a.job_id);
