"""The signed delta can be admitted without moving a legacy cursor or writing jobs."""
import base64
import hashlib
import json
from datetime import datetime, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from job_search_helper.exact_control_before_prefix_recovery import preview_control_before_prefix_source_transition
from job_search_helper.exact_cycle_planner import _digest
from job_search_helper.exact_local_plan import commit_exact_local_plan
from job_search_helper.inbox import InventoryInbox
from job_search_helper.late_control_continuation_journal import (
    freeze_late_control_continuation,
    late_control_continuation_claims,
)
from job_search_helper.selected_recovery_authorization import Ed25519AuthorizationVerifier, canonical
import test_control_before_prefix_source_transition as source_fixture


CYCLE, COMPANY, URL = source_fixture.CYCLE, source_fixture.COMPANY, source_fixture.URL
NOW = datetime(2026, 11, 21, 11, 30, tzinfo=timezone.utc)
IDENTITY = CYCLE, COMPANY


@pytest.fixture
def saved(tmp_path):
    repository, posting, legacy, controls, key, source = source_fixture.SourceTransitionPreviewTests().fixture(tmp_path)
    inbox = InventoryInbox(tmp_path / "inbox.sqlite3", "fixture")
    try:
        payload = {"inventory_status": "complete", "jobs": [posting], "requested_url": URL}
        inbox.save(*IDENTITY, payload)
        inbox.save_plan(*IDENTITY, legacy)
        inbox.save("other-cycle", COMPANY, {"jobs": []})
        with inbox.connection:
            inbox.connection.execute("UPDATE sync_plans SET cursor=1 WHERE cycle=? AND company=?", IDENTITY)
        preview = preview_control_before_prefix_source_transition(
            repository, cycle_id=CYCLE, company_id=COMPANY, payload=payload,
            legacy_plan=legacy, cursor=1, controls=controls,
        )
        scope = {"cycle_id": CYCLE, "company_id": COMPANY, "controls": controls}
        evidence = {"cycle_id": CYCLE, "company_id": COMPANY, "destination_id": "fixture"}
        scope["remote_prefix"] = dict(
            evidence, version="late-control-verified-prefix-observation-v1",
            original_indices=[0], readback_digest=_digest({"fixture-observed": "unchanged"}),
        )
        scope["pending_baseline"] = dict(
            evidence, version="late-control-pending-write-baseline-v1",
            original_indices=[1, 2], readback_digest=_digest({"fixture-before-write": "old"}),
        )
        scope["disposition"] = {
            "version": "late-control-pending-disposition-v1",
            "preview_binding_digest": _digest(preview["plan"]["binding"]),
            "observed_prefix_indices": [0], "pending_original_indices": [1, 2],
            "held_original_indices": [3],
            "remote_prefix_observation_digest": _digest(scope["remote_prefix"]),
            "pending_write_baseline_digest": _digest(scope["pending_baseline"]),
        }
        private = Ed25519PrivateKey.generate()
        public = private.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw,
        )
        verifier = Ed25519AuthorizationVerifier({"fixture": public})

        def sign(claims):
            return {"key_id": "fixture", "payload": claims,
                    "signature": base64.b64encode(private.sign(canonical(claims))).decode("ascii")}

        def claims():
            return late_control_continuation_claims(
                inbox, repository, issued_at="2026-11-21T11:00:00Z",
                expires_at="2026-11-21T12:00:00Z", **scope,
            )

        def freeze(envelope):
            return freeze_late_control_continuation(
                inbox, repository, envelope=envelope, verifier=verifier, now=NOW, **scope,
            )

        yield inbox.connection, repository, scope, key, source, claims, sign, freeze
    finally:
        inbox.close()
        repository.close()


def test_freeze_archives_exact_bytes_without_job_or_inbox_effects(saved):
    db, repository, _, _, _, claims, sign, freeze = saved
    before = {table: db.execute(f"SELECT * FROM {table}").fetchall()
              for table in ("sync_plans", "inventories", "publication_receipts", "exact_remote_plans")}
    jobs_before = tuple(repository.db.iterdump())
    expected = claims()
    assert expected["original_legacy_plan_raw_sha256"] == hashlib.sha256(
        before["sync_plans"][0][2].encode("utf-8"),
    ).hexdigest()
    assert expected["original_inventory_payload_raw_sha256"] == hashlib.sha256(
        before["inventories"][0][2].encode("utf-8"),
    ).hexdigest()
    envelope = sign(expected)
    assert db.execute("SELECT 1 FROM sqlite_master WHERE name='late_control_continuations'").fetchone() is None
    result = freeze(envelope)
    assert result["recovered"] is False
    assert freeze(envelope) == dict(result, recovered=True)
    archive = json.loads(db.execute("SELECT archive FROM late_control_continuations").fetchone()[0])
    assert (archive["original_plan"], archive["original_cursor"]) == before["sync_plans"][0][2:]
    assert archive["original_inventory"] == before["inventories"][0][2]
    assert archive["plan"]["plan_digest"] == result["plan_digest"]
    assert archive["plan"]["selected_legacy_control_before_prefix_recovery"]["remote_release_authorized"] is False
    assert {table: db.execute(f"SELECT * FROM {table}").fetchall() for table in before} == before
    assert tuple(repository.db.iterdump()) == jobs_before


@pytest.mark.parametrize("edit", [
    "baseline", "claimed-cursor", "signed-wrong", "competing-receipt", "competing-legacy-receipt",
    "sync_plans", "inventories",
])
def test_wrong_or_stale_authority_cannot_leave_a_freeze(saved, edit):
    db, _, scope, _, _, claims, sign, freeze = saved
    signed = claims()
    if edit == "baseline":
        scope["pending_baseline"]["original_indices"] = [2]
    elif edit == "claimed-cursor":
        with db:
            db.execute("UPDATE sync_plans SET cursor=2 WHERE cycle=? AND company=?", IDENTITY)
    elif edit == "signed-wrong":
        signed["delta_plan_digest"] = "a" * 64
    elif edit in ("sync_plans", "inventories"):
        with db:
            db.execute(f"UPDATE {edit} SET payload=payload || ' ' WHERE cycle=? AND company=?", IDENTITY)
    else:
        id_field = "request_id" if edit == "competing-legacy-receipt" else "cycle_id"
        with db:
            db.execute(
                "INSERT INTO publication_receipts VALUES ('conflict',?,'{}','{}','LOCAL_COMMITTED',NULL,'a','a')",
                (json.dumps({id_field: CYCLE, "company_id": COMPANY}),),
            )
    with pytest.raises(ValueError):
        freeze(sign(signed))
    assert db.execute("SELECT 1 FROM sqlite_master WHERE name='late_control_continuations'").fetchone() is None


def test_tampered_archive_is_not_replaced_on_retry(saved):
    db, _, _, _, _, claims, sign, freeze = saved
    envelope = sign(claims())
    freeze(envelope)
    with db:
        db.execute("UPDATE late_control_continuations SET archive='{}' WHERE cycle=? AND company=?", IDENTITY)
    with pytest.raises(ValueError, match="frozen_record_changed"):
        freeze(envelope)
    assert db.execute("SELECT archive FROM late_control_continuations").fetchone()[0] == "{}"


def test_frozen_delta_runs_through_existing_exact_local_primitive_on_copy(saved):
    db, repository, _, key, source, claims, sign, freeze = saved
    freeze(sign(claims()))
    plan = json.loads(db.execute("SELECT archive FROM late_control_continuations").fetchone()[0])["plan"]
    first = commit_exact_local_plan(repository, *IDENTITY, plan, max_operations=1)
    replay = commit_exact_local_plan(repository, *IDENTITY, plan, max_operations=1)
    assert first["state"] == "VERIFIED"
    assert replay["recovered"] is True
    assert first["records_digest"] == replay["records_digest"]
    row = repository.matches("Job History", {"Job Key": key})[0][1]
    assert (row["Source Hash"], row["Salary / Range"], row["Decision"], row["Review Status"]) == (
        source, "$100k", "Keep", "Human Reviewed",
    )
    assert repository.matches("Job Evidence", {"Job Key": key, "Source Hash": source})
    assert db.execute("SELECT cursor FROM sync_plans").fetchone() == (1,)
    assert db.execute("SELECT COUNT(*) FROM publication_receipts").fetchone() == (0,)
