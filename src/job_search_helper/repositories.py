"""Narrow local catalog writes. Scan reconciliation is a separate service."""
from __future__ import annotations

from datetime import date

from .posting import canonicalize_url, job_key
from .database import Database
from .dates import DATE_PARSER_VERSION
from .models import (APPLICATION_STATUSES, COMPANY_STATUSES, OPEN_APPLICATION_STATUSES, JobPosting,
                     MATERIAL_HASH_VERSION, NORMALIZER_VERSION, SourceScope, new_id, utc_now)


class ConflictError(ValueError):
    """A stale edit must be refreshed before retrying."""


class CatalogRepository:
    def __init__(self, database: Database):
        self.database = database
        self.connection = database.connection

    def add_company(self, name: str, *, company_id: str | None = None, notes: str = "") -> str:
        identity, stamp = company_id or new_id(), utc_now()
        with self.database.transaction():
            self.connection.execute(
                "INSERT INTO companies(company_id, company_name, notes, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (identity, name, notes, stamp, stamp),
            )
        return identity

    def rename_company(self, company_id: str, name: str, *, expected_version: int) -> None:
        self.update_company(company_id, expected_version=expected_version, company_name=name)

    def update_company(self, company_id: str, *, expected_version: int, **changes) -> None:
        allowed = {"company_name", "website_url", "status", "category", "technology_focus", "priority",
                   "notes", "personal_rationale"}
        if not changes or changes.keys() - allowed or any(not isinstance(value, str) for value in changes.values()):
            raise ValueError("Specify editable company fields as text")
        if "company_name" in changes and not changes["company_name"].strip():
            raise ValueError("Company name cannot be blank")
        if "status" in changes and changes["status"] not in COMPANY_STATUSES:
            raise ValueError("Company status must be active, paused or archived")
        if changes.get("website_url"):
            from .discovery import public_careers_url
            from .ats import FetchError
            try:
                changes["website_url"] = public_careers_url(changes["website_url"])
            except FetchError as exc:
                raise ValueError("Website must be a public HTTPS URL") from exc
        with self.database.transaction():
            assignments = ", ".join(f"{key} = ?" for key in changes)
            result = self.connection.execute(
                f"UPDATE companies SET {assignments}, updated_at = ?, row_version = row_version + 1 "
                "WHERE company_id = ? AND row_version = ?", (*changes.values(), utc_now(), company_id, expected_version),
            )
            if result.rowcount != 1:
                raise ConflictError("Company changed or no longer exists; refresh before editing")

    def add_source(self, company_id: str, provider: str, namespace: str, careers_url: str) -> str:
        identity = new_id()
        url = canonicalize_url(careers_url)
        with self.database.transaction():
            self.connection.execute("UPDATE job_sources SET is_current = 0 WHERE company_id = ?", (company_id,))
            self.connection.execute(
                "INSERT INTO job_sources(source_id, company_id, provider, provider_namespace, careers_url, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)", (identity, company_id, provider.strip().lower(), namespace.strip(), url, utc_now()),
            )
        return identity

    def add_scope(self, scope: SourceScope) -> str:
        with self.database.transaction():
            existing = self.connection.execute(
                "SELECT scope_id FROM source_scopes WHERE source_id = ? AND scope_fingerprint = ?",
                (scope.source_id, scope.fingerprint),
            ).fetchone()
            if existing:
                return existing[0]
            identity = new_id()
            self.connection.execute(
                "INSERT INTO source_scopes VALUES (?, ?, ?, ?, ?, ?, ?)",
                (identity, scope.source_id, scope.canonical_inventory_url, scope.parameters_json,
                 scope.fingerprint, scope.adapter_version, utc_now()),
            )
            return identity

    def create_job(self, company_id: str, posting: JobPosting, *, source_id: str | None = None,
                   observed_at: str | None = None) -> str:
        """Create one initial record. Duplicate source identities require resolution."""
        identity, stamp = new_id(), observed_at or utc_now()
        with self.database.transaction():
            self.connection.execute(
                "INSERT INTO jobs(job_id, company_id, source_id, source_job_id, requisition_id, origin, "
                "first_seen_at, last_seen_at, last_material_change_at, lifecycle_status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (identity, company_id, source_id, (posting.posting_id.strip() or None) if source_id else None,
                 posting.requisition_id, "scraped" if source_id else "manual", stamp if source_id else None,
                 stamp if source_id else None, stamp, "active" if source_id else "unknown", stamp, stamp),
            )
            version = self.store_version(identity, posting, observed_at=stamp)
            self.connection.execute("UPDATE jobs SET current_version_id = ? WHERE job_id = ?", (version, identity))
            if posting.url:
                self.add_alias(identity, source_id, "canonical_url", canonicalize_url(posting.url), "adapter")
            if source_id:
                provider = self.connection.execute("SELECT provider FROM job_sources WHERE source_id = ?", (source_id,)).fetchone()[0]
                self.add_alias(identity, source_id, "legacy_key",
                               job_key(company_id, provider, posting.posting_id, posting.url), "legacy-v1")
        return identity

    def store_version(self, job_id: str, posting: JobPosting, *, observed_at: str) -> str:
        """Append immutable evidence; publishing a current version is separate."""
        with self.database.transaction():
            existing = self.connection.execute(
                "SELECT version_id FROM job_versions WHERE job_id = ? AND evidence_hash = ? "
                "AND normalizer_version = ? AND hash_version = ?",
                (job_id, posting.evidence_hash, NORMALIZER_VERSION, MATERIAL_HASH_VERSION),
            ).fetchone()
            if existing:
                return existing[0]
            identity = new_id()
            self.connection.execute(
                "INSERT INTO job_versions(version_id, job_id, title, location, work_arrangement, compensation_text, "
                "description, department, job_url, is_listed, source_created_raw, source_modified_raw, observed_at, "
                "material_hash, hash_version, evidence_hash, normalizer_version, source_metadata_json, "
                "source_created_at, source_modified_at, date_parser_version) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (identity, job_id, posting.title, posting.location, posting.work_arrangement, posting.compensation,
                 posting.description, posting.department, posting.url, int(posting.is_listed),
                 posting.source_created_raw, posting.source_modified_raw, observed_at, posting.material_hash,
                 MATERIAL_HASH_VERSION, posting.evidence_hash, NORMALIZER_VERSION, posting.metadata_json,
                 posting.source_created_at, posting.source_modified_at, DATE_PARSER_VERSION),
            )
            return identity

    def add_alias(self, job_id: str, source_id: str | None, kind: str, value: str, provenance: str) -> str:
        identity, stamp = new_id(), utc_now()
        with self.database.transaction():
            self.connection.execute("INSERT INTO job_identity_aliases VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                    (identity, job_id, source_id, kind, value, stamp, stamp, provenance))
        return identity

    def get_job(self, job_id: str) -> dict:
        row = self.connection.execute(
            "SELECT j.*, v.title, v.location, v.compensation_text, v.description, v.job_url, v.material_hash, "
            "v.source_created_raw, v.source_modified_raw, v.source_created_at, v.source_modified_at "
            "FROM jobs j JOIN job_versions v ON v.version_id = j.current_version_id WHERE j.job_id = ?", (job_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Job not found")
        return dict(row)


class ApplicationRepository:
    def __init__(self, database: Database):
        self.database = database
        self.connection = database.connection

    def add(self, job_id: str, *, status: str = "interested", date_applied: str | None = None,
            notes: str = "", resume_used: str = "", actor: str = "user") -> str:
        _date(date_applied)
        if status not in APPLICATION_STATUSES:
            raise ValueError("Unknown application status")
        identity, stamp = new_id(), utc_now()
        with self.database.transaction():
            job = CatalogRepository(self.database).get_job(job_id)
            self._check_open(job_id, status)
            self.connection.execute(
                "INSERT INTO applications(application_id, job_id, application_status, date_applied, date_saved, notes, "
                "resume_used, job_url_at_application, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (identity, job_id, status, date_applied, stamp[:10], notes, resume_used, job["job_url"], stamp, stamp),
            )
            self._event(identity, None, status, notes, actor, stamp)
        return identity

    def update(self, application_id: str, *, expected_version: int, actor: str = "user", **changes) -> None:
        allowed = {"application_status", "date_applied", "notes", "resume_used"}
        if not changes or changes.keys() - allowed:
            raise ValueError("Specify application_status, date_applied, notes or resume_used")
        if "date_applied" in changes:
            _date(changes["date_applied"])
        if "application_status" in changes and changes["application_status"] not in APPLICATION_STATUSES:
            raise ValueError("Unknown application status")
        stamp = utc_now()
        with self.database.transaction():
            previous = self.get(application_id)
            if "application_status" in changes:
                self._check_open(previous["job_id"], changes["application_status"], exclude=application_id)
            assignments = ", ".join(f"{key} = ?" for key in changes)
            result = self.connection.execute(
                f"UPDATE applications SET {assignments}, updated_at = ?, row_version = row_version + 1 "
                "WHERE application_id = ? AND row_version = ?",
                (*changes.values(), stamp, application_id, expected_version),
            )
            if result.rowcount != 1:
                raise ConflictError("Application changed; refresh before editing")
            self._event(application_id, previous["application_status"],
                        changes.get("application_status", previous["application_status"]),
                        changes.get("notes", ""), actor, stamp)

    def get(self, application_id: str) -> dict:
        row = self.connection.execute("SELECT * FROM applications WHERE application_id = ?", (application_id,)).fetchone()
        if row is None:
            raise ValueError("Application not found")
        return dict(row)

    def _event(self, identity: str, old_status: str | None, status: str, note: str, actor: str, stamp: str) -> None:
        self.connection.execute("INSERT INTO application_events VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                (new_id(), identity, stamp, stamp, old_status, status, note, actor))

    def _check_open(self, job_id, status, *, exclude=""):
        if status not in OPEN_APPLICATION_STATUSES:
            return
        existing = self.connection.execute(
            "SELECT application_id FROM applications WHERE job_id=? AND application_id!=? AND application_status IN "
            "('interested', 'preparing', 'applied', 'interviewing', 'offer')", (job_id, exclude),
        ).fetchone()
        if existing:
            raise ConflictError(f"This job already has an open application: {existing[0]}; update that record")


def _date(value: str | None) -> None:
    if value is None:
        return
    try:
        if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
            raise ValueError
    except ValueError:
        raise ValueError("Application date must be a valid YYYY-MM-DD or null") from None
