"""Verify visible first-pass jobs against SQLite while a queue refresh runs."""
from contextlib import contextmanager

from .review_queue import DEFAULT_THRESHOLD, build_review_queues
from .review_refresh import fingerprint
from .review_runtime import safe_payload


class _JobColumns:
    """Give the existing router the same column view, limited to one job."""

    def __init__(self, repo, history, key):
        self.repo = repo
        self.history = history
        self.key = key

    def read_columns(self, tab, headers):
        rows = self.history if tab == "Job History" else self.repo.matches(tab, {"Job Key": self.key})
        return [(number + 1, {header: row.get(header, "") for header in headers})
                for number, row in rows]


class FirstPassSource:
    def __init__(self, repo, published, current):
        self.repo = repo
        self.same_revision = published["revision"] == current["revision"]

    def accepts(self, item):
        key = item["job_key"]
        history = self.repo.matches("Job History", {"Job Key": key})
        if len(history) != 1:
            return False
        number, row = history[0]
        if (
            number + 1 != item.get("row_number")
            or row.get("Job Key") != key
            or row.get("Source Hash") != item["source_hash"]
            or row.get("Job Title", "") != item["job_title"]
            or str(row.get("Added to Opportunities?", "")).strip().casefold() != "pending"
            or str(row.get("Review Status", "")).strip().casefold() != "needs review"
        ):
            return False
        if self.same_revision:
            return True
        # Even evidence edits that leave Source Hash unchanged can alter routing.
        # Compare the effective title-only inputs using the normal queue builder.
        current = build_review_queues(_JobColumns(self.repo, history, key))["first_pass"]
        return len(current) == 1 and safe_payload(current[0]) == item


@contextmanager
def first_pass_source(published, *, fence_writes=False):
    """A local source snapshot, or None for an unverified or incompatible queue."""
    if not isinstance(published, dict):
        yield None
        return
    from .cli import get_repository

    repo = get_repository(write=fence_writes, interactive=False)
    try:
        if not getattr(repo, "is_local", False):
            yield None
            return
        # Take the local lock before the runtime transaction, as controls do.
        # Only submissions fence scraper commits through the decision commit.
        repo.db.execute("BEGIN IMMEDIATE" if fence_writes else "BEGIN")
        try:
            current = fingerprint(repo, DEFAULT_THRESHOLD, None)
            keys = ("version", "database", "spreadsheet_id", "threshold", "policies")
            revision = published.get("revision")
            compatible = (
                current is not None
                and isinstance(revision, list)
                and len(revision) == 2
                and revision[0] == current["revision"][0]
                and all(published.get(key) == current[key] for key in keys)
            )
            yield FirstPassSource(repo, published, current) if compatible else None
        finally:
            repo.db.execute("ROLLBACK")
    finally:
        if getattr(repo, "is_local", False):
            repo.close()
