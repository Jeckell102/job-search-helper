"""Preview or append local assessments without editing source/application state."""
from __future__ import annotations

import json

from .local_screening import EVALUATOR_VERSION, RESULT_LABELS, evaluate
from .models import canonical_json, new_id, utc_now
from .policy import POLICY_VERSION, Policy


SCREENING_COLUMNS = """
sc.assessment_id AS screening_assessment_id, sc.result AS screening_result,
sc.reason AS screening_reason, sc.policy_fingerprint AS screening_policy_fingerprint,
sc.evaluator_version AS screening_evaluator_version, sc.evaluated_at AS screening_evaluated_at,
sc.stale AS screening_stale
"""
SCREENING_JOIN = " LEFT JOIN current_screening sc ON sc.job_id=j.job_id "


def screening_summary(row) -> dict:
    result = dict(row)
    stale = bool(result["screening_assessment_id"] and
                 (result["screening_stale"] or result["screening_evaluator_version"] != EVALUATOR_VERSION))
    result["screening_stale"] = stale
    result["screening_status"] = "Needs Reassessment" if stale else RESULT_LABELS.get(result["screening_result"], "Not Evaluated")
    if stale:
        result["screening_reason"] = "Saved evidence or evaluator changed; previous assessment is historical. " + result["screening_reason"]
    return result


class AssessmentService:
    def __init__(self, database):
        self.database = database
        self.connection = database.connection

    def screen(self, policy: Policy, *, all_jobs=False, job_ids=(), apply=False):
        ids = tuple(sorted(set(job_ids)))
        if bool(all_jobs) == bool(ids):
            raise ValueError("Choose all jobs or explicit job IDs")
        with self.database.transaction(immediate=apply):
            if ids:
                found = {row[0] for row in self.connection.execute(
                    "SELECT job_id FROM jobs WHERE job_id IN (" + ",".join("?" for _ in ids) + ")", ids)}
                if found != set(ids):
                    raise ValueError("Unknown job IDs: " + ", ".join(sorted(set(ids) - found)))
            sql = """
SELECT j.job_id, j.current_version_id, c.company_name, v.title, v.work_arrangement, v.compensation_text,
       sc.assessment_id, sc.version_id AS assessed_version_id, sc.policy_fingerprint, sc.evaluator_version
FROM jobs j JOIN companies c USING(company_id)
LEFT JOIN job_versions v ON v.version_id=j.current_version_id
LEFT JOIN current_screening sc ON sc.job_id=j.job_id
"""
            if ids:
                sql += " WHERE j.job_id IN (" + ",".join("?" for _ in ids) + ")"
            sql += " ORDER BY c.company_name COLLATE NOCASE, j.job_id"
            result = {"ok": True, "applied": apply, "policy_fingerprint": policy.fingerprint,
                      "evaluator_version": EVALUATOR_VERSION, "enabled": policy.enabled,
                      "counts": {"new": 0, "unchanged": 0, "skipped": 0}, "items": []}
            for row in self.connection.execute(sql, ids).fetchall():
                evidence = dict(row)
                decision = evaluate(evidence, policy)
                if not row["current_version_id"]:
                    decision = {"result": "not_evaluated", "reason": "No saved job evidence to evaluate.", "evidence": []}
                if decision["result"] == "not_evaluated":
                    action = "skipped"
                elif (row["current_version_id"] == row["assessed_version_id"] and
                      row["policy_fingerprint"] == policy.fingerprint and row["evaluator_version"] == EVALUATOR_VERSION):
                    action = "unchanged"
                else:
                    action = "new"
                identity = row["assessment_id"] if action == "unchanged" else None
                if apply and action == "new":
                    stamp, identity = utc_now(), new_id()
                    self.connection.execute("INSERT INTO policy_profiles VALUES (?, ?, ?, ?) ON CONFLICT(policy_fingerprint) DO NOTHING",
                                            (policy.fingerprint, POLICY_VERSION, policy.document, stamp))
                    self.connection.execute("""INSERT INTO assessments
                        (assessment_id, job_id, version_id, policy_fingerprint, evaluator_version, result, reason,
                         evidence_json, actor, evaluated_at, supersedes_assessment_id)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'local-screen', ?, ?)""",
                        (identity, row["job_id"], row["current_version_id"], policy.fingerprint, EVALUATOR_VERSION,
                         decision["result"], decision["reason"], canonical_json(decision["evidence"]), stamp, row["assessment_id"]))
                result["counts"][action] += 1
                result["items"].append({"job_id": row["job_id"], "version_id": row["current_version_id"],
                    "title": row["title"], "company_name": row["company_name"], "action": action,
                    "assessment_id": identity, **decision})
            return result

    def history(self, *, job_id=None, limit=100, offset=0):
        if type(limit) is not int or not 1 <= limit <= 1000 or type(offset) is not int or offset < 0:
            raise ValueError("Limit must be 1-1000 and offset must be zero or greater")
        with self.database.transaction(immediate=False):
            if job_id is not None and not self.connection.execute("SELECT 1 FROM jobs WHERE job_id=?", (job_id,)).fetchone():
                raise ValueError("Job not found: " + job_id)
            clause, parameters = (" WHERE a.job_id=?", (job_id,)) if job_id is not None else ("", ())
            total = self.connection.execute("SELECT count(*) FROM assessments a" + clause, parameters).fetchone()[0]
            rows = self.connection.execute("""SELECT a.*, v.title, c.company_name FROM assessments a
                JOIN job_versions v ON v.version_id=a.version_id JOIN jobs j ON j.job_id=a.job_id
                JOIN companies c ON c.company_id=j.company_id""" + clause +
                " ORDER BY a.assessment_sequence DESC LIMIT ? OFFSET ?", (*parameters, limit, offset))
            return {"ok": True, "total": total, "limit": limit, "offset": offset,
                    "items": [self._decode(row) for row in rows]}

    def show(self, identity):
        row = self.connection.execute("""SELECT a.*, p.rules_json, p.format_version, v.title, c.company_name,
            j.current_version_id, sc.assessment_id AS current_assessment_id
            FROM assessments a JOIN policy_profiles p USING(policy_fingerprint)
            JOIN job_versions v ON v.version_id=a.version_id JOIN jobs j ON j.job_id=a.job_id
            JOIN companies c ON c.company_id=j.company_id
            LEFT JOIN current_screening sc ON sc.job_id=a.job_id WHERE a.assessment_id=?""", (identity,)).fetchone()
        if row is None:
            raise ValueError("Assessment not found: " + identity)
        result = self._decode(row)
        result["policy"] = json.loads(result.pop("rules_json"))
        result["stale"] = result["version_id"] != result["current_version_id"] or result["evaluator_version"] != EVALUATOR_VERSION
        result["current"] = result["assessment_id"] == result["current_assessment_id"]
        return result

    @staticmethod
    def _decode(row):
        result = dict(row)
        result["evidence"] = json.loads(result.pop("evidence_json"))
        return result
