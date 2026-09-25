"""Joined, read-only views for local catalog commands."""
from __future__ import annotations

from .assessment_service import SCREENING_COLUMNS, SCREENING_JOIN, screening_summary


COMPANIES = """
SELECT c.*, s.source_id, s.provider, s.careers_url,
       a.finished_at AS last_scan_at, a.fetch_status AS last_scan_result,
       a.apply_status AS last_apply_result, a.error_message AS last_scan_reason,
       (SELECT max(g.finished_at) FROM scan_attempts g WHERE g.company_id=c.company_id
        AND g.fetch_status='complete' AND g.apply_status='applied') AS last_successful_scan_at
FROM companies c LEFT JOIN job_sources s ON s.company_id=c.company_id AND s.is_current=1
LEFT JOIN scan_attempts a ON a.attempt_id=(SELECT t.attempt_id FROM scan_attempts t
    WHERE t.company_id=c.company_id ORDER BY t.observation_sequence DESC LIMIT 1)
"""
JOBS = """
SELECT j.*, c.company_name, v.title, v.location, v.work_arrangement, v.compensation_text,
       v.description, v.department, v.job_url, v.is_listed, v.source_created_raw, v.source_modified_raw,
       v.source_created_at, v.source_modified_at, s.provider,
       a.application_id, a.application_status,
""" + SCREENING_COLUMNS + """
FROM jobs j JOIN companies c USING(company_id)
JOIN job_versions v ON v.version_id=j.current_version_id
LEFT JOIN job_sources s ON s.source_id=j.source_id
LEFT JOIN applications a ON a.application_id=(SELECT t.application_id FROM applications t
    WHERE t.job_id=j.job_id ORDER BY t.created_at DESC, t.application_id DESC LIMIT 1)
""" + SCREENING_JOIN
APPLICATIONS = """
SELECT a.*, c.company_id, c.company_name, v.title, v.job_url, j.lifecycle_status AS job_status
FROM applications a JOIN jobs j USING(job_id) JOIN companies c ON c.company_id=j.company_id
JOIN job_versions v ON v.version_id=j.current_version_id
"""


class CatalogQueries:
    def __init__(self, database):
        self.database = database
        self.connection = database.connection

    def companies(self, *, status=None, search=None, limit=100, offset=0):
        clauses, values = [], []
        if status is not None:
            clauses.append("c.status=?")
            values.append(status)
        if search:
            clauses.append("instr(lower(c.company_name), lower(?)) > 0")
            values.append(search)
        return self._list(COMPANIES, clauses, values, "c.company_name COLLATE NOCASE, c.company_id", limit, offset)

    def company(self, company_id):
        return self._one(COMPANIES + " WHERE c.company_id=?", company_id, "Company")

    def jobs(self, *, company_id=None, status=None, search=None, limit=100, offset=0):
        clauses, values = [], []
        for field, value in (("j.company_id", company_id), ("j.lifecycle_status", status)):
            if value is not None:
                clauses.append(field + "=?")
                values.append(value)
        if search:
            clauses.append("(instr(lower(v.title), lower(?)) > 0 OR instr(lower(c.company_name), lower(?)) > 0)")
            values.extend([search, search])
        return self._list(JOBS, clauses, values, "c.company_name COLLATE NOCASE, v.title COLLATE NOCASE, j.job_id", limit, offset)

    def job(self, job_id):
        return self._one(JOBS + " WHERE j.job_id=?", job_id, "Job")

    def applications(self, *, company_id=None, job_id=None, status=None, limit=100, offset=0):
        clauses, values = [], []
        for field, value in (("c.company_id", company_id), ("a.job_id", job_id), ("a.application_status", status)):
            if value is not None:
                clauses.append(field + "=?")
                values.append(value)
        return self._list(APPLICATIONS, clauses, values, "a.created_at DESC, a.application_id DESC", limit, offset)

    def application(self, application_id):
        with self.database.transaction(immediate=False):
            result = self._one(APPLICATIONS + " WHERE a.application_id=?", application_id, "Application")
            result["events"] = [dict(row) for row in self.connection.execute(
                "SELECT * FROM application_events WHERE application_id=? ORDER BY recorded_at, event_id", (application_id,))]
            return result

    def _list(self, sql, clauses, values, order, limit, offset):
        if type(limit) is not int or not 1 <= limit <= 1000 or type(offset) is not int or offset < 0:
            raise ValueError("Limit must be 1-1000 and offset must be zero or greater")
        sql += (" WHERE " + " AND ".join(clauses)) if clauses else ""
        with self.database.transaction(immediate=False):
            total = self.connection.execute("SELECT count(*) FROM (" + sql + ")", values).fetchone()[0]
            rows = self.connection.execute(sql + " ORDER BY " + order + " LIMIT ? OFFSET ?", (*values, limit, offset)).fetchall()
        return {"ok": True, "total": total, "limit": limit, "offset": offset,
                "items": [screening_summary(row) if "screening_result" in row.keys() else dict(row) for row in rows]}

    def _one(self, sql, identity, label):
        row = self.connection.execute(sql, (identity,)).fetchone()
        if row is None:
            raise ValueError(f"{label} not found: {identity}")
        return screening_summary(row) if "screening_result" in row.keys() else dict(row)
