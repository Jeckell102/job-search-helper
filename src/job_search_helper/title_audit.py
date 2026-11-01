"""Read-only queue evidence for titles skipped before Google Sheets insertion."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3

from .core import job_key, material_hash
from .efficiency import classify_title

TITLE_AUDIT_SCHEMA = """CREATE TABLE IF NOT EXISTS title_filter_audits (
    company TEXT PRIMARY KEY, payload TEXT NOT NULL)"""


def remember_title_audit(connection, company, payload):
    """Retain the latest complete title-filter snapshot in the existing inbox DB.

    Called inside the inventory-save transaction. Acknowledging sync does not
    erase this evidence. Incomplete/failed inventories never erase sightings.
    """
    if payload.get("inventory_status") != "complete":
        return
    previous = connection.execute(
        "SELECT payload FROM title_filter_audits WHERE company=?", (company,)
    ).fetchone()
    if previous and json.loads(previous[0]).get("fetched_at", "") > payload.get("fetched_at", ""):
        return
    saved = dict(payload, jobs=[job for job in payload.get("jobs", [])
                               if classify_title(job.get("title", "")) == "reject"])
    connection.execute(
        "INSERT INTO title_filter_audits VALUES (?,?) ON CONFLICT(company) "
        "DO UPDATE SET payload=excluded.payload", (company, json.dumps(saved, ensure_ascii=False)),
    )


def load_title_audits(path=None, spreadsheet_id=None):
    """Return raw local evidence and coverage metadata; never create/change DBs.

    Raw postings include practical fields for later hydration, not AI inputs.
    Callers must select the company-free projection for the FIRST PASS queue.
    """
    metadata = {"title_audit_snapshots": 0, "title_audit_invalid_identities": 0,
                "title_audit_retention_available": False}
    if path is None or not Path(path).is_file():
        return [], metadata
    connection = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        destination = connection.execute("SELECT id FROM destination").fetchone()
        if spreadsheet_id and (not destination or destination[0] != spreadsheet_id):
            raise ValueError("Title audit inbox belongs to a different spreadsheet.")
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        snapshots = []
        if "title_filter_audits" in tables:
            metadata["title_audit_retention_available"] = True
            snapshots.extend(connection.execute("SELECT company,payload FROM title_filter_audits"))
        if "inventories" in tables:
            snapshots.extend(connection.execute("SELECT company,payload FROM inventories"))
    finally:
        connection.close()
    from .adp_myjobs import repair_saved_urls
    decoded = [(company, repair_saved_urls(json.loads(payload))) for company, payload in snapshots]
    decoded.sort(key=lambda pair: pair[1].get("fetched_at", ""))
    candidates = {}
    observed_companies = set()
    for company, payload in decoded:
        status = payload.get("inventory_status")
        if status not in {"complete", "partial"}:
            continue
        observed_companies.add(company)
        if status == "complete":
            candidates = {key: value for key, value in candidates.items() if key[0] != company}
        for posting in payload.get("jobs", []):
            if posting.get("is_listed") is False or classify_title(posting.get("title", "")) != "reject":
                continue
            try:
                key = job_key(company, posting.get("ats") or payload.get("ats", ""),
                              posting.get("posting_id", ""), posting.get("url", ""))
            except (ValueError, TypeError, AttributeError):
                metadata["title_audit_invalid_identities"] += 1
                continue
            candidates[(company, key)] = {
                "job_key": key, "source_hash": material_hash(posting),
                "posting": posting, "observed_at": payload.get("fetched_at", ""),
            }
    metadata["title_audit_snapshots"] = len(observed_companies)
    return list(candidates.values()), metadata
