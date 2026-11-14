"""Recheck saved Pending jobs after pay/employment screening improvements."""
from collections import Counter

from .core import material_hash, unpack_snapshot, reconsiderations
from .location_cleanup import active_review_keys, plan_cleanup, publish_cleanup
from .screening import screen_posting

MARKER = "[pay/employment screening cleanup]"


def saved_screening_evidence(repo):
    """Use only unique Pending identities with an exact full-source snapshot."""
    fields = ["Job Key", "Added to Opportunities?", "Review Status", "Review Notes"]
    rows = list(repo.read_columns("Job History", fields))
    counts = Counter(row.get("Job Key") for _, row in rows)
    evidence = {}
    for number, control in rows:
        key = control.get("Job Key")
        pending = control.get("Added to Opportunities?") == "Pending" and control.get("Review Status") == "Needs Review"
        staged = (control.get("Added to Opportunities?") == "No" and control.get("Review Status") == "Reviewed"
                  and MARKER in str(control.get("Review Notes", "")))
        if not key or counts[key] != 1 or not (pending or staged):
            continue
        row = repo.read_row("Job History", number)
        if row.get("Job Key") != key or row.get("Review Started At") or reconsiderations(row) >= 2:
            continue
        if row.get("Job Status") != "Open and verified":
            continue
        try:
            posting = unpack_snapshot(row.get("Current Snapshot", "")).get("pending")
            if not posting or material_hash(posting) != row.get("Source Hash"):
                continue
        except (ValueError, TypeError, KeyError):
            continue
        if any(posting.get(p, "") != row.get(h, "") for p, h in (
            ("title", "Job Title"), ("url", "Official Job URL"), ("location", "Location"),
            ("compensation", "Salary / Range"))):
            continue
        result = screen_posting(posting, skip_title_filter=True)
        if not result.reason or not result.reason.startswith(("Employment exclusion:", "Compensation exclusion:")):
            continue
        evidence[key] = {"source_hash": row["Source Hash"], "official_url": row["Official Job URL"],
                         "original_location": row.get("Location", ""), "title": row["Job Title"],
                         "compensation": row.get("Salary / Range", ""), "reason": result.reason}
    return evidence


def screening_reason(row, evidence=None):
    proof = (evidence or {}).get(row.get("Job Key"), {})
    if (proof.get("source_hash") == row.get("Source Hash")
            and proof.get("official_url") == row.get("Official Job URL")
            and proof.get("original_location") == row.get("Location", "")
            and proof.get("title") == row.get("Job Title")
            and proof.get("compensation") == row.get("Salary / Range", "")
            and str(proof.get("reason", "")).startswith(("Employment exclusion:", "Compensation exclusion:"))):
        return proof["reason"]
    return None


def execute_cleanup(args):
    from .cli import get_repository, get_remote_repository, print_json, state_path, scraper_lock_name
    from .review_writeback import sheet_writer_lock
    from .sheet_profile import profile_schemas
    from .repository import RepositoryError
    state = state_path().parent
    local = get_repository(write=args.apply, interactive=False)
    try:
        if not args.apply:
            evidence = saved_screening_evidence(local)
            protected = active_review_keys(state / "review-queue/concurrent/review-runtime.sqlite3")
            operations, _, skipped = plan_cleanup(local, limit=args.limit, protected_keys=protected,
                evidence=evidence, reason_fn=screening_reason, marker=MARKER)
            print_json({"dry_run": True, "planned": len(operations), "skipped": skipped,
                        "targets": [{"job_key": op["identity"]["Job Key"],
                                     "reason": op["values"]["Rejection Reason"]} for op in operations]})
            return
        with sheet_writer_lock(state / scraper_lock_name()), sheet_writer_lock(state / "review-writeback.lock"), sheet_writer_lock(state / "writer.lock"):
            protected = active_review_keys(state / "review-queue/concurrent/review-runtime.sqlite3")
            evidence = saved_screening_evidence(local)
            remote = get_remote_repository(write=True, interactive=False,
                schemas=profile_schemas(local.get_meta("sheets_profile")), evidence_archives=False)
            if remote.spreadsheet_id != local.spreadsheet_id:
                raise RepositoryError("Screening cleanup workbook differs from local storage.")
            print_json(publish_cleanup(local, remote, limit=args.limit, protected_keys=protected,
                evidence=evidence, reason_fn=screening_reason, marker=MARKER))
    finally:
        local.close()


def main():
    import argparse
    from .cli import load_environment
    load_environment()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--limit", type=int, default=100)
    execute_cleanup(parser.parse_args())


if __name__ == "__main__":
    main()
