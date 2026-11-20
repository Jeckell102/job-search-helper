"""Read-only proof of the exact local and receipt boundaries after Samtec."""
from contextlib import closing
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import sys

from job_search_helper.exact_local_plan import _rows_for_operations
from job_search_helper.publication_receipts import record_fingerprints
from job_search_helper.retained_operator_journal import RetainedOperatorJournal, SETTLED
from job_search_helper.retained_operator_run import _stored_session, _terminal_evidence
from job_search_helper.retained_work_exception import digest
from job_search_helper.sqlite_repository import SQLiteRepository
from pilot_data_witness import snapshot
from state_witness import fingerprint


def check(project, evidence_dir, install_before):
    root = project / ".state"
    terminal = json.loads((evidence_dir / "execution.json").read_bytes())
    consumption = terminal.pop("consumption")
    reservation = terminal["reservation_digest"]
    request_hash = consumption["request_sha256"]
    journal = RetainedOperatorJournal(root)
    path = journal.archive_directory / f"{request_hash}-{reservation}.json"
    archived = json.loads(path.read_bytes())
    binding = archived["binding"]
    if (journal.read_archived(binding) != archived or archived["state"] != SETTLED
            or archived["consumption"] != consumption or journal.inspect() is not None):
        raise ValueError("The exact pilot journal is not durably settled")

    historical = json.loads(install_before.read_bytes())
    for name in ("state.db", "state.db-wal", "inventories.sqlite3", "inventories.sqlite3-wal",
                 "integration-release-journal.json", "company-intake-dispatch.sqlite3"):
        if fingerprint(root / name) != historical[name]:
            raise ValueError(f"A protected historical authority changed: {name}")
    for name in historical:
        if name.startswith("operator-company-requests/") and fingerprint(root / name) != historical[name]:
            raise ValueError("The original operator request receipt changed")
    before_jobs = json.loads((evidence_dir / "local-before.json").read_bytes())
    after_jobs = snapshot(root)
    if before_jobs["outside"] != after_jobs["outside"] or after_jobs["dirty_count"] != 0:
        raise ValueError("Out-of-scope local records changed or dirty fields remain")
    for tab, rows in before_jobs["selected"].items():
        for number, row in rows.items():
            if not row["closed"] and after_jobs["selected"][tab][int(number)]["closed"]:
                raise ValueError("The selected pilot closed a previously open job")

    claims = binding["claims"]
    if (claims["company_id"], claims["request_id"]) != ("COMP-0739", "operator-samtec-m1-20261119"):
        raise ValueError("The terminal proof is outside the selected Samtec request")
    jobs_path = root / "jobs.sqlite3"
    with closing(sqlite3.connect(jobs_path.as_uri() + "?mode=ro", uri=True)) as database:
        workbook, = database.execute("SELECT value FROM meta WHERE key='spreadsheet_id'").fetchone()
    with closing(SQLiteRepository(jobs_path, workbook, readonly=True)) as jobs:
        proven = _terminal_evidence(root, jobs, binding, archived["inventory_sha256"])
        if proven != terminal or proven != archived["settlement_evidence"]:
            raise ValueError("The operator result does not match the exact archived receipt")
        session = _stored_session(root, reservation)
        plan = json.loads(session["plan"])
        records = record_fingerprints(
            plan["local_operations"], _rows_for_operations(jobs, plan["local_operations"]),
            include_guard_only=plan.get("record_fingerprint_version", 1) == 2,
        )
        if records != plan["local_expected_records"] or digest(records) != plan["local_expected_records_digest"]:
            raise ValueError("Selected records do not match the frozen local receipt")
        counts = {}
        for operation in plan["local_operations"]:
            counts[operation["tab"]] = counts.get(operation["tab"], 0) + 1
            if operation["tab"] == "Job Evidence":
                values = {**operation.get("on_insert", {}), **operation.get("values", {})}
                if not values.get("Job Description"):
                    raise ValueError("Selected new evidence lacks a full local posting description")
    request_path = root / "company-event-bridge/consumed-requests" / f"{request_hash}.json"
    request = json.loads(request_path.read_bytes())
    if digest(request) != request_hash or (root / "next-scan.json").exists():
        raise ValueError("The original request was not cleanly consumed")
    inventory = archived["inventory"]
    enqueued = datetime.fromisoformat(request["enqueued_at"])
    started = datetime.fromisoformat(inventory["fetch_started_at"])
    finished = datetime.fromisoformat(inventory["fetched_at"])
    if not enqueued <= started <= finished:
        raise ValueError("The recorded fetch timing is inconsistent")
    return {"state": terminal["state"], "company_id": terminal["company_id"], "request_id": terminal["request_id"],
            "protected_records": sum(row["count"] for row in after_jobs["outside"].values()),
            "raw_postings": len(inventory["jobs"]), "local_operations_by_tab": counts,
            "remote_operations": len(plan["remote_projection"]),
            "queue_age_at_start_seconds": round((started - enqueued).total_seconds(), 3),
            "provider_elapsed_seconds": round((finished - started).total_seconds(), 3),
            "receipt_id": terminal["receipt_id"], "acknowledgement_id": terminal["acknowledgement_id"]}


if __name__ == "__main__":
    print(json.dumps(check(*(Path(value).resolve() for value in sys.argv[1:])), indent=2, sort_keys=True))
