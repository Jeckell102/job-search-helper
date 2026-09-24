"""Idempotent cleanup for blacklisted titles already present in Job History."""
from __future__ import annotations

from collections import Counter

from .core import canonicalize_url
from .efficiency import classify_title, load_title_blacklist


FIELDS = (
    "Company", "Job Title", "Added to Opportunities?", "Job Key",
    "Official Job URL", "Review Status",
)


def _value(value):
    return str(value or "").strip()


def _job_key(value):
    return _value(value)


def _url(value):
    value = _value(value)
    if not value:
        return ""
    try:
        return canonicalize_url(value)
    except (TypeError, ValueError):
        return ""


def _company_title(row):
    return (_value(row.get("Company")).casefold(), _value(row.get("Job Title")))


def plan_blacklist_cleanup(repo):
    """Return cell-precise operations and a user-safe summary.

    Every operation includes the observed title and status fields in its
    identity. A concurrent edit therefore aborts the atomic commit instead of
    applying a decision made from stale row data.
    """
    load_title_blacklist()
    rows = repo.read_columns("Job History", list(FIELDS))
    key_counts = Counter(_job_key(row.get("Job Key")) for _, row in rows if _job_key(row.get("Job Key")))
    url_counts = Counter(_url(row.get("Official Job URL")) for _, row in rows if _url(row.get("Official Job URL")))
    pair_counts = Counter(_company_title(row) for _, row in rows)
    operations, proposed, locked, unresolved = [], [], [], []
    blacklisted = already_no = 0

    for row_number, row in rows:
        title = _value(row.get("Job Title"))
        if classify_title(title) != "reject":
            continue
        blacklisted += 1
        added = _value(row.get("Added to Opportunities?"))
        if added.casefold() == "no":
            already_no += 1
            continue
        item = {"row": row_number, "company": _value(row.get("Company")),
                "title": title, "from": added or "(blank)", "to": "No"}
        review_status = _value(row.get("Review Status"))
        if review_status == "In Progress":
            locked.append(item)
            continue

        key, url, pair = _job_key(row.get("Job Key")), _url(row.get("Official Job URL")), _company_title(row)
        if key and key_counts[key] == 1:
            identity = {"Job Key": key}
        elif url and url_counts[url] == 1:
            identity = {"Official Job URL": _value(row.get("Official Job URL"))}
        elif all(pair) and pair_counts[pair] == 1:
            identity = {"Company": _value(row.get("Company")), "Job Title": title}
        else:
            unresolved.append(item)
            continue

        identity["Job Title"] = title
        if review_status:
            identity["Review Status"] = review_status
        operations.append({"tab": "Job History", "row_number": row_number, "identity": identity,
                           "values": {"Added to Opportunities?": "No"}})
        proposed.append(item)

    summary = {
        "rows_scanned": len(rows),
        "blacklisted_titles": blacklisted,
        "already_no": already_no,
        "proposed_updates": len(operations),
        "locked_in_progress": len(locked),
        "unresolved_identity": len(unresolved),
        "matches": proposed,
        "locked": locked,
        "unresolved": unresolved,
    }
    return operations, summary


def cleanup_blacklisted_history(repo, *, apply=False):
    operations, summary = plan_blacklist_cleanup(repo)
    if not apply:
        return {"mode": "dry-run", **summary, "spreadsheet_changes": 0}
    if hasattr(repo, "commit_existing_job_history_flags"):
        result = repo.commit_existing_job_history_flags(operations)
    else:
        result = repo.commit([{key: value for key, value in operation.items() if key != "row_number"}
                              for operation in operations])
    return {"mode": "apply", **summary, "spreadsheet_changes": result["requests"],
            "updated": result["requests"]}
