"""Human-oriented CSV exports from one committed catalog snapshot."""
from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

from .csv_format import ESCAPE_VERSION, EXPORT_FORMAT, TEXT_PREFIX, escape_cell, text_hash
from .database import SCHEMA_VERSION
from .dates import normalize_source_date, readable_timestamp
from .export_publish import publish_directory
from .models import utc_now
from .assessment_service import SCREENING_COLUMNS, SCREENING_JOIN, screening_summary


HEADERS = {
    "companies": ("Company Name", "Careers URL", "Status", "Last Successful Scan", "Last Scan", "Last Scan Result",
        "Updated At", "Created At", "Blocked / Error Reason", "Next Action", "Jobs Found In Last Scan", "Website",
        "Category", "Technology / Focus", "Priority", "Notes", "Why It Fits", "ATS Type", "Company ID", "Source ID"),
    "jobs": ("Job Title", "Company Name", "Location", "Work Arrangement", "Job Status", "Job URL", "Salary / Range",
        "Application Status", "Screening Result", "Review Status", "Fit Level", "Screening / Review Reason",
        "First Seen", "Last Seen", "Last Changed", "Closed At", "Closure Basis", "Department", "Job Description",
        "Source Last Modified", "Consecutive Missing Scans", "Publicly Listed", "Requisition ID", "ATS Type",
        "Company ID", "Source ID", "Source Job ID", "Job ID", "Material Hash", "Hash Version"),
    "applications": ("Company Name", "Job Title", "Application Status", "Date Applied", "Notes", "Resume Used",
        "Updated At", "Date Saved", "Created At", "Job URL", "Job Status", "Location", "Salary / Range",
        "Job URL At Application", "Company ID", "Job ID", "Application ID"),
    "cycles": ("Started At", "Completed At", "Status", "Companies Total", "Companies Completed", "Companies Partial",
        "Companies Blocked", "Companies Failed", "Companies Remaining", "Jobs Found", "Jobs New", "Jobs Changed",
        "Jobs Missing", "Jobs Closed", "Last Checkpoint At", "Notes", "Started By", "Cycle ID"),
}
FILENAMES = {"companies": "Companies.csv", "jobs": "Jobs.csv", "applications": "Applications.csv", "cycles": "Scan Cycles.csv"}


def _date(value):
    return readable_timestamp(value) if value else ""


def _source_modified(row):
    parsed = row["source_modified_at"] or normalize_source_date(
        row["source_modified_raw"] or "", epoch_milliseconds=(row["provider"] or "").lower() == "lever")
    return _date(parsed)


class CatalogExporter:
    def __init__(self, database):
        self.database = database
        self.connection = database.connection

    def export(self, destination: str | Path, *, kinds=None, company_ids=(), encoding="utf-8-sig") -> dict:
        kinds = tuple(kinds) if kinds is not None else tuple(HEADERS)
        if not kinds or len(set(kinds)) != len(kinds) or any(kind not in HEADERS for kind in kinds):
            raise ValueError("Choose companies, jobs, applications or cycles once each")
        if encoding not in {"utf-8", "utf-8-sig"}:
            raise ValueError("CSV encoding must be utf-8 or utf-8-sig")
        if self.connection.in_transaction:
            raise ValueError("Finish the current transaction before exporting a committed snapshot")
        target = Path(destination).expanduser().absolute()
        if target.exists() or target.is_symlink():
            raise FileExistsError(f"Export destination already exists: {target}")
        ids = tuple(sorted(set(company_ids)))
        temporary = None
        try:
            with self.database.transaction(immediate=False):
                database_id = self.database.database_id
                if ids:
                    found = {row[0] for row in self.connection.execute(
                        "SELECT company_id FROM companies WHERE company_id IN (" + ",".join("?" for _ in ids) + ")", ids)}
                    if found != set(ids):
                        raise ValueError("Unknown company IDs: " + ", ".join(sorted(set(ids) - found)))
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                temporary = Path(tempfile.mkdtemp(prefix=".jsh-export-", dir=target.parent))
                manifest = {"format_version": EXPORT_FORMAT, "generated_at": utc_now(), "database_id": database_id,
                    "schema_version": SCHEMA_VERSION, "encoding": encoding, "filters": {"company_ids": list(ids), "kinds": list(kinds)},
                    "snapshot": "One committed SQLite read transaction; CSV files are not a database backup",
                    "timestamp_convention": "YYYY-MM-DD HH:MM:SS[.fraction] UTC; dates remain YYYY-MM-DD; unknown values are blank",
                    "source_dates": "Naive source times have no timezone suffix; unparseable source timestamps are blank",
                    "escape_rule": {"version": ESCAPE_VERSION, "prefix": TEXT_PREFIX, "row_numbering": "CSV records, header is row 1"},
                    "spreadsheet_import": "Import IDs as text. CSV cannot force cell types or spreadsheet cell-size limits.",
                    "screening": "Latest explicitly saved local assessment per job; changed evidence/evaluator needs reassessment. Screening is not a fit review or application decision.",
                    "cycle_metrics": {"companies_failed": "Includes failed, unsupported and quarantined outcomes",
                        "jobs": "Distinct observed jobs or transitions per cycle; retries do not add duplicate counts",
                        "unknown_history": "Metrics are blank for cycles without saved membership",
                        "company_filter": "Counts reflect selected companies; cycle status and times describe the full cycle"},
                    "files": []}
                for kind in kinds:
                    manifest["files"].append(self._write_csv(temporary, kind, ids, encoding))
                self._write_manifest(temporary / "manifest.json", manifest)
                _sync_directory(temporary)
            publish_directory(temporary, target)
            temporary = None
            return {"ok": True, "directory": str(target), "manifest": str(target / "manifest.json"),
                    "files": [{"name": item["name"], "rows": item["rows"], "escaped_cells": len(item["escaped_cells"])}
                              for item in manifest["files"]]}
        finally:
            if temporary is not None:
                shutil.rmtree(temporary)

    def _write_csv(self, directory, kind, ids, encoding):
        path, headers = directory / FILENAMES[kind], HEADERS[kind]
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        escaped, count = [], 0
        with os.fdopen(descriptor, "w", encoding=encoding, newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(headers)
            for count, values in enumerate(getattr(self, "_" + kind)(ids), 1):
                if len(values) != len(headers):
                    raise ValueError(f"Export column mismatch: {kind}")
                output = []
                for column, value in zip(headers, values):
                    text, changed = escape_cell(value)
                    output.append(text)
                    if changed:
                        escaped.append({"row": count + 1, "column": column, "original_sha256": text_hash(str(value)),
                                        "exported_sha256": text_hash(text)})
                writer.writerow(output)
            handle.flush()
            os.fsync(handle.fileno())
        with path.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        return {"kind": kind, "name": path.name, "rows": count, "columns": list(headers), "sha256": digest, "escaped_cells": escaped}

    def _write_manifest(self, path, manifest):
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(manifest, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _filter(self, field, ids):
        return " WHERE " + field + " IN (" + ",".join("?" for _ in ids) + ")" if ids else ""

    def _companies(self, ids):
        sql = """
SELECT c.*, s.careers_url, s.provider, s.source_id, a.fetch_status, a.apply_status, a.error_message,
       coalesce(a.finished_at, a.started_at) AS last_scan,
       (SELECT max(g.finished_at) FROM scan_attempts g WHERE g.company_id=c.company_id
        AND g.fetch_status='complete' AND g.apply_status='applied') AS last_success,
       CASE WHEN a.apply_status='applied' THEN
         (SELECT count(*) FROM job_observations o WHERE o.attempt_id=a.attempt_id AND o.presence='present') END AS found,
       EXISTS(SELECT 1 FROM cycle_companies m JOIN scan_cycles cy USING(cycle_id) WHERE m.company_id=c.company_id
         AND cy.status IN ('running', 'interrupted') AND m.status IN ('queued', 'fetching', 'pending_apply')) AS unfinished
FROM companies c LEFT JOIN job_sources s ON s.company_id=c.company_id AND s.is_current=1
LEFT JOIN scan_attempts a ON a.attempt_id=(SELECT t.attempt_id FROM scan_attempts t
 WHERE t.company_id=c.company_id ORDER BY t.observation_sequence DESC LIMIT 1)
"""
        for row in self.connection.execute(sql + self._filter("c.company_id", ids) + " ORDER BY c.company_name COLLATE NOCASE, c.company_id", ids):
            if row["apply_status"] == "quarantined":
                action = "Inspect retained result"
            elif row["unfinished"]:
                action = "Resume unfinished cycle"
            elif row["status"] != "active":
                action = row["status"].capitalize()
            elif not row["source_id"]:
                action = "Add a verified careers source"
            else:
                action = {"complete": "Scan when ready", "partial": "Review partial result before retrying",
                          "blocked": "Review access issue before retrying", "failed": "Verify source before retrying",
                          "unsupported": "Set a supported official board URL", "interrupted": "Resume interrupted scan"}.get(row["fetch_status"], "Run a scan")
            yield (row["company_name"], row["careers_url"], row["status"], _date(row["last_success"]), _date(row["last_scan"]),
                row["fetch_status"], _date(row["updated_at"]), _date(row["created_at"]), row["error_message"], action, row["found"],
                row["website_url"], row["category"], row["technology_focus"], row["priority"], row["notes"], row["personal_rationale"],
                row["provider"], row["company_id"], row["source_id"])

    def _jobs(self, ids):
        sql = """
SELECT j.*, c.company_name, v.title, v.location, v.work_arrangement, v.compensation_text, v.job_url, v.description,
       v.department, v.source_modified_at, v.source_modified_raw, v.is_listed, v.material_hash, v.hash_version,
       s.provider, st.consecutive_missing,
       (SELECT a.application_status FROM applications a WHERE a.job_id=j.job_id
        ORDER BY a.created_at DESC, a.application_id DESC LIMIT 1) AS application_status,
""" + SCREENING_COLUMNS + """
FROM jobs j JOIN companies c USING(company_id)
LEFT JOIN job_versions v ON v.version_id=j.current_version_id
LEFT JOIN job_sources s ON s.source_id=j.source_id
LEFT JOIN source_scan_state ss ON ss.source_id=j.source_id
LEFT JOIN job_scope_state st ON st.job_id=j.job_id AND st.scope_id=ss.scope_id
""" + SCREENING_JOIN
        for row in self.connection.execute(sql + self._filter("j.company_id", ids) + " ORDER BY c.company_name COLLATE NOCASE, v.title COLLATE NOCASE, j.job_id", ids):
            row = screening_summary(row)
            yield (row["title"], row["company_name"], row["location"], row["work_arrangement"], row["lifecycle_status"],
                row["job_url"], row["compensation_text"], row["application_status"], row["screening_status"], "Not Evaluated", "", row["screening_reason"],
                _date(row["first_seen_at"]), _date(row["last_seen_at"]), _date(row["last_material_change_at"]), _date(row["closed_at"]),
                row["closure_basis"], row["department"], row["description"], _source_modified(row), row["consecutive_missing"],
                "" if row["is_listed"] is None else "Yes" if row["is_listed"] else "No", row["requisition_id"], row["provider"],
                row["company_id"], row["source_id"], row["source_job_id"], row["job_id"], row["material_hash"], row["hash_version"])

    def _applications(self, ids):
        sql = """
SELECT a.*, c.company_id, c.company_name, v.title, v.job_url, v.location, v.compensation_text, j.lifecycle_status
FROM applications a JOIN jobs j USING(job_id) JOIN companies c ON c.company_id=j.company_id
LEFT JOIN job_versions v ON v.version_id=j.current_version_id
"""
        for row in self.connection.execute(sql + self._filter("c.company_id", ids) + " ORDER BY c.company_name COLLATE NOCASE, a.created_at, a.application_id", ids):
            yield (row["company_name"], row["title"], row["application_status"], _date(row["date_applied"]), row["notes"],
                row["resume_used"], _date(row["updated_at"]), _date(row["date_saved"]), _date(row["created_at"]), row["job_url"],
                row["lifecycle_status"], row["location"], row["compensation_text"], row["job_url_at_application"],
                row["company_id"], row["job_id"], row["application_id"])

    def _cycles(self, ids):
        # Metrics come from membership and committed observations, never from
        # today's job totals. Reopened postings can also have changed evidence.
        sql = """
WITH members AS (
 SELECT cycle_id, count(*) AS total, sum(status='complete') AS completed, sum(status='partial') AS partial,
        sum(status='blocked') AS blocked, sum(status IN ('failed', 'unsupported')) AS failed,
        sum(status IN ('queued', 'fetching', 'pending_apply')) AS remaining
 FROM cycle_companies
""" + self._filter("company_id", ids) + """
 GROUP BY cycle_id
), evidence AS (
 SELECT a.cycle_id, o.job_id, o.presence, o.change_kind, v.material_hash,
        (SELECT pv.material_hash FROM job_observations po JOIN job_versions pv ON pv.version_id=po.version_id
         WHERE po.job_id=o.job_id AND po.presence='present' AND po.change_kind!='historical'
           AND po.applied_sequence < o.applied_sequence ORDER BY po.applied_sequence DESC LIMIT 1) AS prior_hash
 FROM job_observations o JOIN scan_attempts a USING(attempt_id)
 LEFT JOIN job_versions v ON v.version_id=o.version_id
 WHERE a.apply_status='applied'
""" + (" AND a.company_id IN (" + ",".join("?" for _ in ids) + ")" if ids else "") + """
), metrics AS (
 SELECT cycle_id, count(DISTINCT CASE WHEN presence='present' THEN job_id END) AS found,
        count(DISTINCT CASE WHEN change_kind='new' THEN job_id END) AS added,
        count(DISTINCT CASE WHEN change_kind='changed' OR (change_kind='reopened' AND material_hash != prior_hash) THEN job_id END) AS changed,
        count(DISTINCT CASE WHEN change_kind='missing' THEN job_id END) AS missing,
        count(DISTINCT CASE WHEN change_kind='closed' THEN job_id END) AS closed
 FROM evidence GROUP BY cycle_id
)
SELECT c.*, m.total, m.completed, m.partial, m.blocked, m.failed, m.remaining,
       e.found, e.added, e.changed, e.missing, e.closed
FROM scan_cycles c LEFT JOIN members m USING(cycle_id) LEFT JOIN metrics e USING(cycle_id)
""" + (" WHERE m.total IS NOT NULL" if ids else "") + " ORDER BY c.cycle_sequence"
        for row in self.connection.execute(sql, (*ids, *ids)):
            metrics = tuple((row[field] or 0) if row["total"] is not None else None
                            for field in ("found", "added", "changed", "missing", "closed"))
            yield (_date(row["started_at"]), _date(row["completed_at"]), row["status"].replace("_", " "),
                row["total"], row["completed"], row["partial"], row["blocked"], row["failed"], row["remaining"], *metrics,
                _date(row["last_checkpoint_at"]), row["notes"], row["initiated_by"], row["cycle_id"])


def _sync_directory(path):
    if os.name != "nt":
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
