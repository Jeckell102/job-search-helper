"""Guarded cleanup of clearly overseas Pending jobs; preserve user decisions."""
from collections import Counter
from datetime import datetime, timezone

from .closed_jobs import opportunity_identities, _url
from .locations import check_location
from .repository import RepositoryError, _equivalent

MARKER = "[US location cleanup]"
FIELDS = ["Company", "Job Key", "Job Title", "Official Job URL", "Location", "Source Hash", "Salary / Range",
          "Job Status", "Added to Opportunities?", "Review Status", "Review Started At",
          "Review Notes", "Decision", "Fit Level", "Rejection Reason", "Last Evaluated", "Description Hash"]
WRITE_FIELDS = {"Added to Opportunities?", "Review Status", "Decision", "Fit Level",
                "Rejection Reason", "Last Evaluated", "Description Hash", "Review Notes"}


def location_reason(row, evidence=None):
    proof = (evidence or {}).get(row.get("Job Key"), {})
    if (proof.get("source_hash") == row.get("Source Hash")
            and proof.get("original_location") == row.get("Location")
            and proof.get("official_url") == row.get("Official Job URL")
            and proof.get("reason", "").startswith("Location exclusion:")):
        return proof["reason"]
    return check_location(row.get("Location")).rejection_reason


def cleanup_operation(row, opportunities, *, evidence=None, reason_fn=location_reason, marker=MARKER):
    reason = reason_fn(row, evidence)
    if not reason or row.get("Added to Opportunities?") != "Pending" or row.get("Review Status") != "Needs Review":
        return None
    if row.get("Review Started At") or not row.get("Job Key") or not row.get("Source Hash"):
        return None
    identity = (str(row.get("Company", "")).strip().casefold(), _url(row.get("Official Job URL", "")))
    if not identity[1] or identity in opportunities:
        return None
    return {"tab": "Job History", "identity": {"Job Key": row["Job Key"]}, "append_if_missing": False,
            "expected": {h: row.get(h, "") for h in FIELDS},
            "values": {"Added to Opportunities?": "No", "Review Status": "Reviewed", "Decision": "Reject",
                       "Fit Level": "", "Rejection Reason": reason, "Description Hash": row["Source Hash"],
                       "Last Evaluated": datetime.now(timezone.utc).isoformat(timespec="seconds")},
            "append_notes": {"Review Notes": marker + " " + reason}}


def plan_cleanup(repo, *, limit=100, job_keys=None, protected_keys=(), evidence=None,
                 reason_fn=location_reason, marker=MARKER):
    if not 1 <= limit <= 100:
        raise ValueError("Location cleanup limit must be 1–100.")
    rows = list(repo.read_columns("Job History", FIELDS))
    counts = Counter(row.get("Job Key") for _, row in rows)
    opportunities = opportunity_identities(repo)
    operations, targets, skipped = [], [], []
    for number, row in rows:
        key = row.get("Job Key")
        if job_keys is not None and key not in job_keys:
            continue
        if row.get("Added to Opportunities?") != "Pending" or not reason_fn(row, evidence):
            continue
        op = cleanup_operation(row, opportunities, evidence=evidence, reason_fn=reason_fn, marker=marker)
        if counts[key] != 1 or key in protected_keys or not op:
            skipped.append({"job_key": key, "reason": "Protected choice, Opportunity, review claim or identity"})
        elif len(operations) < limit:
            operations.append(op)
            targets.append((number, row))
    return operations, targets, skipped


def active_review_keys(path):
    """Do not create or modify the review coordination database."""
    import sqlite3
    import time
    if not path.exists():
        return set()
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        return {r[0] for r in db.execute(
            "SELECT DISTINCT job_key FROM tasks WHERE active=1 AND state='claimed' AND lease_until>?", (time.time(),))}


def publish_cleanup(local, remote, *, limit=100, protected_keys=(), evidence=None,
                    reason_fn=location_reason, marker=MARKER):
    """Caller owns writer/review locks; publish only this cleanup's cells."""
    from .sheets_sync import SheetsSynchronizer, unique_rows
    sync = SheetsSynchronizer(local, remote)
    opportunities = opportunity_identities(remote)
    remote_fields = [h for h in FIELDS if h in remote.schemas["Job History"]]
    live = unique_rows("Job History", list(remote.read_columns("Job History", remote_fields)))
    selected, skipped = [], []
    for number, row in live:
        identity = (str(row.get("Company", "")).strip().casefold(), _url(row.get("Official Job URL", "")))
        if (row.get("Job Key") in protected_keys or not identity[1] or identity in opportunities
                or row.get("Added to Opportunities?") != "Pending" or row.get("Review Status") != "Needs Review"
                or row.get("Review Started At")):
            continue
        matches = local.matches("Job History", {"Job Key": row["Job Key"]})
        if len(matches) != 1:
            continue
        rid, current = matches[0]
        if not reason_fn(current, evidence):
            continue
        if any(not _equivalent(h, current.get(h, ""), row.get(h, "")) for h in
               [h for h in ("Company", "Job Title", "Official Job URL", "Location", "Source Hash", "Job Status", "Salary / Range") if h in remote_fields]):
            skipped.append({"job_key": row["Job Key"], "reason": "Live/local source differs"})
            continue
        if len(selected) < limit:
            selected.append((number, row, rid))
    if not selected:
        return {"changed": 0, "verified": 0, "skipped": skipped}
    # Live controls and personal notes win over a stale local snapshot. Normal
    # merge/outbox handling recognizes our own delivery after a lost response.
    controls = ("Job Key", "Added to Opportunities?", "Review Notes")
    sync.merge_remote("Job History", [(n, {h: r.get(h, "") for h in controls}) for n, r, _ in selected], complete_snapshot=False)
    keys = {r["Job Key"] for _, r, _ in selected}
    operations, targets, local_skips = plan_cleanup(local, limit=limit, job_keys=keys, protected_keys=protected_keys, evidence=evidence, reason_fn=reason_fn, marker=marker)
    if operations:
        local.commit(operations)
    accepted = {r["Job Key"] for _, r in targets}
    # An earlier attempt may have staged the local change and then lost the
    # network response. Resume its pending delivery without treating it as a
    # manual No or applying a fresh assessment.
    for _, row, rid in selected:
        current = local.row("Job History", rid)
        if (current.get("Added to Opportunities?") == "No" and current.get("Review Status") == "Reviewed"
                and marker in str(current.get("Review Notes", ""))
                and reason_fn(current, evidence) == current.get("Rejection Reason")):
            accepted.add(row["Job Key"])
    active = [(n, r, rid) for n, r, rid in selected if r["Job Key"] in accepted]
    scope = {("Job History", rid): WRITE_FIELDS for _, _, rid in active}
    guards = [{"tab": "Job History", "identity": {"Job Key": r["Job Key"]}, "values": {},
               "expected": {h: r.get(h, "") for h in remote_fields}} for _, r, _ in active]
    error = None
    try:
        if active:
            sync.publish_batch(limit=limit, row_scope=scope, guards=guards)
    except Exception as exc:
        error = str(exc)
    numbers = [n for n, _, _ in active]
    actual = remote.read_rows("Job History", numbers) if hasattr(remote, "read_rows") else {n: remote.read_row("Job History", n) for n in numbers}
    verified = []
    for number, before, _ in active:
        row = actual.get(number, {})
        okay = (row.get("Job Key") == before["Job Key"]
                and row.get("Location") == before["Location"] and row.get("Added to Opportunities?") == "No"
                and row.get("Review Status") == "Reviewed"
                and marker in str(row.get("Review Notes", "")))
        verified.append({"job_key": before["Job Key"], "verified": okay})
    sync.merge_remote("Job History", [(n, {h: r.get(h, "") for h in controls}) for n, r in actual.items()], complete_snapshot=False)
    with local.transaction():
        local.event("location_cleanup", detail={"identities": verified, "error": error})
    return {"changed": len(operations), "verified": sum(v["verified"] for v in verified),
            "identities": verified, "skipped": skipped + local_skips, "error": error}


def execute_cleanup(args):
    from .cli import get_repository, get_remote_repository, print_json, state_path, scraper_lock_name
    from .review_writeback import sheet_writer_lock
    from .sheet_profile import profile_schemas
    state = state_path().parent
    protected = active_review_keys(state / "review-queue/concurrent/review-runtime.sqlite3")
    local = get_repository(write=args.apply, interactive=args.authenticate)
    try:
        if not args.apply:
            operations, targets, skipped = plan_cleanup(local, limit=args.limit, protected_keys=protected)
            print_json({"dry_run": True, "planned": len(operations), "skipped": skipped,
                        "targets": [{h: r.get(h, "") for h in ("Job Key", "Company", "Job Title", "Location")} for _, r in targets]})
            return
        with sheet_writer_lock(state / scraper_lock_name()), sheet_writer_lock(state / "review-writeback.lock"):
            protected = active_review_keys(state / "review-queue/concurrent/review-runtime.sqlite3")
            if getattr(local, "is_local", False):
                with sheet_writer_lock(state / "writer.lock"):
                    remote = get_remote_repository(write=True, interactive=args.authenticate,
                        schemas=profile_schemas(local.get_meta("sheets_profile")), evidence_archives=False)
                    if remote.spreadsheet_id != local.spreadsheet_id:
                        raise RepositoryError("Location cleanup workbook differs from local storage.")
                    report = publish_cleanup(local, remote, limit=args.limit, protected_keys=protected)
            else:
                operations, _, skipped = plan_cleanup(local, limit=args.limit, protected_keys=protected)
                if operations:
                    local.commit(operations)
                report = {"changed": len(operations), "skipped": skipped}
            print_json(report)
    finally:
        if getattr(local, "is_local", False):
            local.close()
