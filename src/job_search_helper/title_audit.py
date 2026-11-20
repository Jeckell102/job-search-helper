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


def _replay_company(company, snapshots):
    """Replay one company's evidence, preserving complete/partial semantics."""
    from .adp_myjobs import repair_saved_urls
    decoded = [(order, repair_saved_urls(json.loads(payload)), archived)
               for order, payload, archived in snapshots]
    decoded.sort(key=lambda item: (item[1].get("fetched_at", ""), item[0]))
    archived_postings = {
        (job.get("ats") or payload.get("ats", ""), job.get("posting_id", ""), job.get("url", ""))
        for _, payload, archived in decoded if archived for job in payload.get("jobs", [])}
    candidates = {}
    invalid = 0
    observed = False
    for order, payload, archived in decoded:
        status = payload.get("inventory_status")
        if status not in {"complete", "partial"}:
            continue
        observed = True
        if status == "complete":
            candidates.clear()
        for number, posting in enumerate(payload.get("jobs", [])):
            if posting.get("is_listed") is False:
                continue
            identity = (posting.get("ats") or payload.get("ats", ""),
                        posting.get("posting_id", ""), posting.get("url", ""))
            if not (archived or identity in archived_postings
                    or classify_title(posting.get("title", "")) == "reject"):
                continue
            try:
                key = job_key(company, *identity)
            except (ValueError, TypeError, AttributeError):
                invalid += 1
                continue
            # Updating an existing sighting preserves its original insertion
            # order, exactly as the global replay did before grouping by company.
            position = candidates[key][0] if key in candidates else [payload.get("fetched_at", ""), *order, number]
            candidates[key] = [position, {
                "job_key": key, "source_hash": material_hash(posting),
                "posting": posting, "observed_at": payload.get("fetched_at", ""),
            }]
    return {"candidates": list(candidates.values()), "invalid": invalid, "observed": observed}


def load_title_audits(path=None, spreadsheet_id=None, *, cache=None, policy=""):
    """Read retained evidence without changing the source DB.

    Per-company calculations are disposable and keyed by every source payload
    plus current policy. History/manual decisions are checked by the caller on
    every queue build. Partial inventories never erase earlier sightings.
    """
    metadata = {"title_audit_snapshots": 0, "title_audit_invalid_identities": 0,
                "title_audit_retention_available": False}
    if path is None or not Path(path).is_file():
        return [], metadata
    if cache is not None and not policy:
        from .review_refresh import policy_fingerprint
        policy = json.dumps(policy_fingerprint(), sort_keys=True)
    connection = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    candidates = []
    try:
        connection.execute('BEGIN')
        destination = connection.execute("SELECT id FROM destination").fetchone()
        if spreadsheet_id and (not destination or destination[0] != spreadsheet_id):
            raise ValueError("Title audit inbox belongs to a different spreadsheet.")
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        metadata["title_audit_retention_available"] = "title_filter_audits" in tables
        companies = {}
        for index, table in enumerate(('title_filter_audits', 'inventories')):
            if table in tables:
                for rowid, company in connection.execute(f'SELECT rowid,company FROM {table} ORDER BY rowid'):
                    companies.setdefault(company, []).append((index, rowid))
        for company, rows in companies.items():
            snapshots = []
            for index in (0, 1):
                ids = [rowid for kind, rowid in rows if kind == index]
                table = ('title_filter_audits', 'inventories')[index]
                # Bound parameters for older SQLite builds and long histories.
                for start in range(0, len(ids), 500):
                    group = ids[start:start + 500]
                    query = f'SELECT rowid,payload FROM {table} WHERE rowid IN (' + ','.join('?' for _ in group) + ') ORDER BY rowid'
                    snapshots.extend(((index, rowid), payload, index == 0)
                                     for rowid, payload in connection.execute(query, group))
            inputs = [policy, str(Path(path).resolve()), json.dumps(destination), company]
            for order, payload, archived in snapshots:
                inputs.extend([json.dumps(order), payload])
            compute = lambda: _replay_company(company, snapshots)
            result = cache.calculate('title_audit', company, inputs, compute) if cache else compute()
            candidates.extend(result['candidates'])
            metadata['title_audit_snapshots'] += int(result['observed'])
            metadata['title_audit_invalid_identities'] += result['invalid']
    finally:
        connection.close()
    candidates.sort(key=lambda item: item[0])
    return [record for _, record in candidates], metadata
