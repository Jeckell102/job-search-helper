"""Exercise the production-shaped archive with simulated remote evidence only."""
import base64
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from job_search_helper.control_before_prefix_runner import _checkpointed_inputs
from job_search_helper.exact_control_before_prefix_recovery import preview_control_before_prefix_source_transition
from job_search_helper.exact_cycle_planner import _digest
from job_search_helper.exact_local_plan import commit_exact_local_plan
from job_search_helper.exact_legacy_migration_runner import _controls
from job_search_helper.inbox import InventoryInbox
from job_search_helper.late_control_continuation_journal import (
    freeze_late_control_continuation,
    late_control_continuation_claims,
)
from job_search_helper.selected_recovery_authorization import Ed25519AuthorizationVerifier, canonical
from job_search_helper.sqlite_repository import REVIEW_FIELDS, SQLiteRepository


def deny_external(event, args):
    if event.startswith(("socket.", "subprocess.", "os.exec", "os.fork", "os.posix_spawn")):
        raise RuntimeError("This offline test does not use external services.")


def rehearse_local(source, plan, identity):
    history, evidence = plan["local_operations"]
    assert [history["tab"], evidence["tab"]] == ["Job History", "Job Evidence"]
    key = history["identity"]["Job Key"]
    saved_history = source.matches("Job History", {"Job Key": key})
    saved_evidence = source.matches("Job Evidence", {"Job Key": key})
    saved_company = source.matches("Companies", {"Company ID": identity[1]})
    assert len(saved_history) == len(saved_company) == 1
    with tempfile.TemporaryDirectory(prefix="jsh-recovery-selected-rows-") as root:
        with closing(SQLiteRepository(Path(root) / "jobs.sqlite3", source.spreadsheet_id, initialize=True)) as target:
            with target.transaction():
                target.db.execute("DELETE FROM tabs")
                target.db.executemany("INSERT INTO tabs VALUES (?,?)", source.db.execute("SELECT * FROM tabs"))
                target.schemas = source.schemas.copy()
                target.set_meta("sheets_profile", source.get_meta("sheets_profile"))
                for tab, entries in (("Companies", saved_company), ("Job History", saved_history),
                                     ("Job Evidence", saved_evidence)):
                    for row_id, _row in entries:
                        for table in ("records", "lookups", "baseline", "dirty", "manual_choices",
                                      "conflicts", "delivery_attempts"):
                            rows = source.db.execute(
                                f"SELECT * FROM {table} WHERE tab=? AND row_id=?", (tab, row_id),
                            ).fetchall()
                            if rows:
                                placeholders = ",".join("?" for _ in rows[0])
                                target.db.executemany(f"INSERT INTO {table} VALUES ({placeholders})", rows)
            first = commit_exact_local_plan(target, *identity, plan, max_operations=1)
            replay = commit_exact_local_plan(target, *identity, plan, max_operations=1)
            assert first["state"] == replay["state"] == "VERIFIED"
            assert first["records_digest"] == replay["records_digest"] and replay["recovered"] is True
            old, new = saved_history[0][1], target.matches("Job History", {"Job Key": key})[0][1]
            assert all(old.get(field, "") == new.get(field, "") for field in REVIEW_FIELDS)
            assert new["Source Hash"] == history["values"]["Source Hash"] != old["Source Hash"]
            assert target.matches("Job Evidence", evidence["identity"])
            assert all(target.row("Job Evidence", row_id) == row for row_id, row in saved_evidence)
            assert target.matches("Companies", {"Company ID": identity[1]}) == saved_company
    return {"state": "VERIFIED", "replay_readback": True, "manual_review_fields_preserved": len(REVIEW_FIELDS),
            "existing_job_evidence_unchanged": True, "company_unchanged": True}


sys.addaudithook(deny_external)
backup = Path(sys.argv[1]).resolve(strict=True)
jobs = backup / "jobs.sqlite3"
inventory = backup / "inventories.sqlite3"
before = _checkpointed_inputs(jobs, inventory)
identity = "CYC-B639C6D864EC", "COMP-0054"
with closing(sqlite3.connect(inventory.as_uri() + "?mode=ro&immutable=1", uri=True)) as original:
    original.execute("PRAGMA query_only=ON")
    original_plan = original.execute(
        "SELECT * FROM sync_plans WHERE cycle=? AND company=?", identity,
    ).fetchone()
    original_inventory = original.execute(
        "SELECT * FROM inventories WHERE cycle=? AND company=?", identity,
    ).fetchone()
    destination, = original.execute("SELECT id FROM destination").fetchone()
    competing_count, = original.execute(
        "SELECT count(*) FROM publication_receipts WHERE json_extract(binding,'$.company_id')=? "
        "AND (json_extract(binding,'$.cycle_id')=? OR json_extract(binding,'$.request_id')=?)",
        (identity[1], identity[0], identity[0]),
    ).fetchone()
    assert competing_count == 0
legacy, cursor = json.loads(original_plan[2]), original_plan[3]
payload = json.loads(original_inventory[2])
with closing(SQLiteRepository(jobs, destination, readonly=True, immutable=True)) as repo:
    repo.db.execute("PRAGMA query_only=ON")
    repo.db.execute("BEGIN")
    controls = _controls(repo, identity[1], legacy["requested_url"])
    preview = preview_control_before_prefix_source_transition(
        repo, cycle_id=identity[0], company_id=identity[1], payload=payload,
        legacy_plan=legacy, cursor=cursor, controls=controls,
    )
    pending = [preview["report"]["history_index"], preview["report"]["evidence_index"]]
    assert pending == [193, 194] and cursor == 67 and len(legacy["operations"]) == 208

    with closing(InventoryInbox(":memory:", destination)) as inbox:
        with inbox.connection:
            inbox.connection.execute("INSERT INTO inventories VALUES (?,?,?,?)", original_inventory)
            inbox.connection.execute("INSERT INTO sync_plans VALUES (?,?,?,?)", original_plan)
        scope = {"cycle_id": identity[0], "company_id": identity[1], "controls": controls}
        artifacts = {"cycle_id": identity[0], "company_id": identity[1], "destination_id": destination}
        scope["remote_prefix"] = dict(
            artifacts, version="late-control-verified-prefix-observation-v1",
            original_indices=[0], readback_digest=_digest({"simulated": "prefix-observed"}),
        )
        scope["pending_baseline"] = dict(
            artifacts, version="late-control-pending-write-baseline-v1",
            original_indices=pending, readback_digest=_digest({"simulated": "pending-baseline"}),
        )
        scope["disposition"] = {
            "version": "late-control-pending-disposition-v1",
            "preview_binding_digest": _digest(preview["plan"]["binding"]),
            "observed_prefix_indices": [0], "pending_original_indices": pending,
            "held_original_indices": [i for i in range(cursor, len(legacy["operations"])) if i not in pending],
            "remote_prefix_observation_digest": _digest(scope["remote_prefix"]),
            "pending_write_baseline_digest": _digest(scope["pending_baseline"]),
        }
        now = datetime.now(timezone.utc)
        claims = late_control_continuation_claims(
            inbox, repo, issued_at="2026-11-21T13:00:00Z", expires_at="2026-11-22T00:00:00Z", **scope,
        )
        private = Ed25519PrivateKey.generate()
        public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        envelope = {"key_id": "in-memory-rehearsal", "payload": claims,
                    "signature": base64.b64encode(private.sign(canonical(claims))).decode("ascii")}
        verifier = Ed25519AuthorizationVerifier({"in-memory-rehearsal": public})
        first = freeze_late_control_continuation(inbox, repo, envelope=envelope, verifier=verifier, now=now, **scope)
        second = freeze_late_control_continuation(inbox, repo, envelope=envelope, verifier=verifier, now=now, **scope)
        assert first["recovered"] is False and second == dict(first, recovered=True)
        archive = json.loads(inbox.connection.execute("SELECT archive FROM late_control_continuations").fetchone()[0])
        assert (archive["original_plan"], archive["original_cursor"]) == original_plan[2:]
        assert archive["original_inventory"] == original_inventory[2]
        count, = inbox.connection.execute("SELECT count(*) FROM publication_receipts").fetchone()
        assert count == 0
        assert inbox.connection.execute("SELECT * FROM sync_plans").fetchone() == original_plan
        assert inbox.connection.execute("SELECT * FROM inventories").fetchone() == original_inventory
        local = rehearse_local(repo, archive["plan"], identity)
        assert _checkpointed_inputs(jobs, inventory) == before
        print(json.dumps({
            "mode": "read-only-backup-with-in-memory-inbox-and-simulated-remote-evidence",
            "result": "FROZEN_WITH_IDEMPOTENT_REPLAY", "original_positions": len(legacy["operations"]),
            "original_cursor": cursor, "pending_one_based_positions": [index + 1 for index in pending],
            "other_suffix_positions_held": len(scope["disposition"]["held_original_indices"]),
            "saved_plan_bytes": len(archive["original_plan"].encode("utf-8")),
            "saved_inventory_bytes": len(archive["original_inventory"].encode("utf-8")),
            "original_rows_unchanged": True, "backup_files_unchanged": True,
            "network_allowed": False, "receipt_count": count, "scoped_copy_exact_local": local,
        }, indent=2, sort_keys=True))
