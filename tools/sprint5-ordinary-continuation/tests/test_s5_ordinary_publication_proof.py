"""Fixture-only ordinary exact-v2 proof and cleanup tests."""
from contextlib import ExitStack, closing
from copy import deepcopy
import fcntl
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

from job_search_helper import exact_cycle_planner as planner, publication_receipts
from job_search_helper import ordinary_verification_pending as pending
from job_search_helper.batching import PlanningRepository
from job_search_helper.cli import writer_lock
from job_search_helper.engine import Engine
from job_search_helper.exact_cycle_recovery import _prepare_exact_v2_local, _recover_exact_cycle_locked
from job_search_helper.exact_cycle_sync import _bounded_exact_chunks, _company_guard, _fallback_receipt, publish_exact_cycle
from job_search_helper.ordinary_verification_publication import bind_publication, read_publication_proof
from job_search_helper.repository import SCHEMAS, RepositoryError
from job_search_helper.runtime_mapping_facts import _open_store
from job_search_helper.sheet_profile import COMPACT_PROFILE, COMPACT_SCHEMAS
from job_search_helper.sheets_sync import SheetsSynchronizer
from job_search_helper.sqlite_repository import SQLiteRepository
from test_exact_cycle_recovery import RecordingRemote
from test_ordinary_verification_pending import attempt, COMPANY, COMPANY_ID, CYCLE_ID, prepare


WORKBOOK = "fixture-workbook"
BASE = Path("/tmp/jsh-s5-ordinary-company-proof.h9DoUArv/src/job_search_helper")


def _prepare_marker(attempt):
    stores, owner, admission, _payload = attempt
    pending.arm(stores, owner, admission)
    prepare(attempt)
    return stores


def _set_profile(local):
    local.ensure_columns("Opportunities", ["Opportunity ID"])
    for tab in SCHEMAS:
        if tab != "Companies":
            local.import_rows(tab, [])
    local.set_meta("sheets_profile", COMPACT_PROFILE)


@pytest.fixture
def publication(attempt):
    stores = _prepare_marker(attempt)
    directory = Path(stores.state.path).parent
    with ExitStack() as stack:
        stack.enter_context(writer_lock(directory / "scraper.lock"))
        stack.enter_context(writer_lock(directory / "writer.lock"))
        local = _open_store(stack, Path(stores.jobs.path), lambda path: SQLiteRepository(path, WORKBOOK), "db")
        _set_profile(local)
        stores = pending.VerificationStores(stores.state, local, stores.inbox)
        remote = RecordingRemote([COMPANY], schemas=COMPACT_SCHEMAS)
        remote.spreadsheet_id = WORKBOOK
        engine = Engine(local, stores.state, inbox=stores.inbox)
        yield stores, local, remote, engine


def _guard(local, remote):
    return lambda cid, requested: _company_guard(local, remote, cid, requested)


def _freeze(publication, *, bind=True):
    stores, local, remote, engine = publication
    if bind:
        first = bind_publication(stores, CYCLE_ID, COMPANY_ID)
        assert bind_publication(stores, CYCLE_ID, COMPANY_ID) == first
    plan_report = planner.freeze_exact_cycle_plans(
        engine, CYCLE_ID, [COMPANY_ID], company_guard=_guard(local, remote),
        ordinary_verification_stores=stores if bind else None)
    assert plan_report["planned"] == [COMPANY_ID], plan_report
    plan, _ = stores.inbox.plan(CYCLE_ID, COMPANY_ID)
    return plan


def _apply(publication, plan):
    stores, _, _, engine = publication
    _prepare_exact_v2_local(engine, CYCLE_ID, COMPANY_ID, plan, stores.inbox.get(CYCLE_ID, COMPANY_ID)[0],
                            ordinary_verification_stores=stores)


def _publish(publication):
    stores, local, remote, _ = publication
    return publish_exact_cycle(stores.inbox, CYCLE_ID, remote, company_ids=[COMPANY_ID],
                               state=stores.state, company_guard=_guard(local, remote), local=local,
                               ordinary_verification_stores=stores)


def _proof(stores):
    return read_publication_proof(stores, CYCLE_ID, COMPANY_ID)


def test_exact_publication_retains_original_dispatch_and_distinguishes_receipt_source(publication):
    stores, local, remote, _ = publication
    plan = _freeze(publication)
    assert _proof(stores) is None
    _apply(publication, plan)
    result = _publish(publication)
    assert result["confirmed"] == [COMPANY_ID], result
    assert stores.inbox.get(CYCLE_ID, COMPANY_ID) is None
    assert stores.inbox.plan(CYCLE_ID, COMPANY_ID) is None
    assert stores.inbox.exact_remote_state(CYCLE_ID, COMPANY_ID) is None
    final = stores.state.cycle(CYCLE_ID)["companies"][COMPANY_ID]
    assert final["stage"] == "partial" and final[pending.MARKER]["state"] == "PREPARED"
    proof = _proof(stores)
    assert proof["owner"]["dispatch_sha256"] == final[pending.MARKER]["dispatch_sha256"]
    assert proof["owner"]["inventory_sha256"] == plan["inventory_payload_digest"]
    assert proof["owner"]["source_revision"] == final["outcome_source_revision"]
    assert proof["receipt_binding"]["source_revision"] == "frozen-inventory:" + plan["inventory_payload_digest"]
    assert proof["receipt_binding"]["request_id"] == CYCLE_ID
    assert proof["receipt_binding"]["request_id"] != proof["owner"]["request_id"]
    assert proof["plan_digest"] == plan["plan_digest"]
    assert publication_receipts.receipt(stores.inbox.connection, proof["receipt_binding"])["state"] == "SYNC_CONFIRMED"
    assert len(remote.commits) == 1
    assert _proof(stores) == proof


def test_retained_proof_reopens_in_a_fresh_process(publication):
    stores, _, _, _ = publication
    plan = _freeze(publication)
    _apply(publication, plan)
    assert _publish(publication)["confirmed"] == [COMPANY_ID]
    overlay = Path(__file__).parents[1] / "src/job_search_helper"
    script = """
import json
import sys
sys.path.insert(0, sys.argv[1])
import job_search_helper
job_search_helper.__path__.insert(0, sys.argv[2])
from job_search_helper.ordinary_verification_pending import open_verification_stores
from job_search_helper.ordinary_verification_publication import read_publication_proof
with open_verification_stores(*sys.argv[3:7]) as stores:
    print(json.dumps(read_publication_proof(stores, *sys.argv[7:])))
"""
    result = subprocess.run([
        sys.executable, "-I", "-B", "-c", script, str(BASE.parent), str(overlay),
        str(stores.state.path), str(stores.jobs.path), str(stores.inbox.path), WORKBOOK, CYCLE_ID, COMPANY_ID,
    ], check=True, capture_output=True, timeout=15)
    assert json.loads(result.stdout) == _proof(stores)


def test_completed_publication_remains_historical_after_live_company_drifts(publication):
    stores, local, _, _ = publication
    plan = _freeze(publication)
    _apply(publication, plan)
    assert _publish(publication)["confirmed"] == [COMPANY_ID]
    proof = _proof(stores)
    local.commit([{"tab": "Companies", "identity": {"Company ID": COMPANY_ID},
                   "values": {"Company Status": "Paused"}}])
    with pytest.raises(RepositoryError, match="outside the exact reviewed projection"):
        pending.company_source_sha256(stores, COMPANY_ID)
    assert _proof(stores) == proof


def test_bound_plan_refuses_wrong_remote_workbook_before_any_write(publication):
    stores, _, remote, _ = publication
    plan = _freeze(publication)
    _apply(publication, plan)
    remote.spreadsheet_id = "other-workbook"
    result = _publish(publication)
    assert "foreign stores" in result["held"][0]["reason"] and not remote.commits
    assert _proof(stores) is None


def test_bound_workbook_controls_are_rechecked_before_exact_remote_commit(publication):
    stores, local, remote, _ = publication
    plan = _freeze(publication)
    _apply(publication, plan)
    seen = []

    def guard(cid, requested):
        controls = _guard(local, remote)(cid, requested)
        seen.append(cid)
        return {**controls, "company_status": "Paused"} if len(seen) > 1 else controls

    result = publish_exact_cycle(stores.inbox, CYCLE_ID, remote, company_ids=[COMPANY_ID],
                                 state=stores.state, company_guard=guard, local=local,
                                 ordinary_verification_stores=stores)
    assert seen == [COMPANY_ID, COMPANY_ID] and result["held"]
    assert not remote.commits and _proof(stores) is None


def test_bound_inventory_refuses_public_generic_cleanup_and_legacy_plan(publication):
    stores, _, _, _ = publication
    bind_publication(stores, CYCLE_ID, COMPANY_ID)
    with pytest.raises(ValueError, match="exact custody"):
        stores.inbox.acknowledge(CYCLE_ID, COMPANY_ID)
    with pytest.raises(ValueError, match="requires exact v2"):
        stores.inbox.save_plan(CYCLE_ID, COMPANY_ID, {"operations": []})
    assert stores.inbox.get(CYCLE_ID, COMPANY_ID)[1] is False
    assert _proof(stores) is None


def test_cleanup_retains_legacy_receipt_fence_for_both_request_spellings(publication):
    stores, _, _, _ = publication
    plan = _freeze(publication)
    _apply(publication, plan)
    assert _publish(publication)["confirmed"] == [COMPANY_ID]
    proof = _proof(stores)
    stamp = "2026-11-20T21:01:00+00:00"
    for request_id in (proof["owner"]["request_id"], proof["receipt_binding"]["request_id"]):
        forged = {
            "binding": {**proof["receipt_binding"], "request_id": request_id, "release_id": "f" * 64},
            "records": plan["remote_records"], "schedule": {"boundary": "idle", "enqueued_at": stamp},
            "timestamp": stamp,
        }
        with pytest.raises(ValueError, match="original dispatch authority"):
            stores.inbox.ensure_receipt(forged)
        # Reproduce a pre-existing rejected legacy row using the fixture DB.
        with stores.inbox.connection as db:
            publication_receipts.local_committed(db, forged["binding"], forged["records"],
                                                 forged["schedule"], timestamp=stamp)
            publication_receipts.mark_sync_pending(db, forged["binding"], timestamp=stamp)
        with pytest.raises(ValueError, match="exact remote attempt"):
            stores.inbox.mark_receipt_pending(forged, timestamp=stamp)
        with pytest.raises(ValueError, match="original exact receipt"):
            stores.inbox.discard_preflight_rejected_receipt(forged, cursor=0)
        with pytest.raises(ValueError, match="trusted Sheets confirmation"):
            stores.inbox.reconcile_receipt(forged, forged["records"], "8" * 64, timestamp=stamp)
        assert stores.inbox.receipt(forged)["state"] == publication_receipts.SYNC_PENDING
    assert _proof(stores) == proof


def test_marked_exact_plan_refuses_unscoped_freeze_before_read_or_write(publication):
    stores, _, remote, engine = publication

    def no_read(*args):
        pytest.fail("Company controls were read before proving the plan owner")

    for bound in (False, True):
        if bound:
            bind_publication(stores, CYCLE_ID, COMPANY_ID)
        report = planner.freeze_exact_cycle_plans(
            engine, CYCLE_ID, [COMPANY_ID], company_guard=no_read)
        assert report["planned"] == []
        assert "original dispatch authority" in report["held"][0]["reason"]
        assert stores.inbox.plan(CYCLE_ID, COMPANY_ID) is None
        assert not remote.commits


def test_private_marker_cannot_be_adopted_from_a_contaminated_plan(publication):
    stores, _, remote, _ = publication
    plan = _freeze(publication)
    contaminant = deepcopy(plan)
    contaminant["final"][pending.MARKER] = {"private": "should not enter F6"}
    contaminant["local_finalization"] = deepcopy(contaminant["final"])
    contaminant["local_finalization_digest"] = planner._digest(
        {"operations": contaminant["local_operations"], "final": contaminant["final"]},
    )
    contaminant["final_projection"] = deepcopy(contaminant["final"])
    contaminant["final_projection_digest"] = planner._digest(contaminant["final_projection"])
    contaminant["plan_digest"] = planner._exact_plan_digest(contaminant)
    stores.inbox.connection.execute("UPDATE sync_plans SET payload=?", (planner.json.dumps(contaminant),))
    stores.inbox.connection.commit()
    report = _publish(publication)
    assert report["confirmed"] == [] and "private-field-free" in report["held"][0]["reason"]
    assert not remote.commits and _proof(stores) is None


def test_generic_exact_recovery_and_local_preparation_hold_before_writing(publication):
    stores, local, remote, engine = publication
    plan = _freeze(publication)
    before = local.db.total_changes
    with pytest.raises(ValueError, match="dedicated exact publication"):
        _recover_exact_cycle_locked(engine, remote, CYCLE_ID, [COMPANY_ID])
    with pytest.raises(ValueError, match="original dispatch authority"):
        _prepare_exact_v2_local(engine, CYCLE_ID, COMPANY_ID, plan, stores.inbox.get(CYCLE_ID, COMPANY_ID)[0])
    assert local.db.total_changes == before and not remote.commits
    assert stores.inbox.exact_local_state(CYCLE_ID, COMPANY_ID)["state"] == "FROZEN"


def test_same_path_jobs_writer_without_descriptor_proof_cannot_apply(publication):
    stores, local, _, engine = publication
    plan = _freeze(publication)
    with closing(SQLiteRepository(local.path, WORKBOOK)) as unmanaged:
        engine.repo = unmanaged
        before = unmanaged.db.total_changes
        with pytest.raises(ValueError, match="descriptor-proven writable Jobs"):
            _apply(publication, plan)
        assert unmanaged.db.total_changes == before


def test_open_scope_without_held_writer_lease_cannot_apply(publication):
    stores, local, _, _ = publication
    plan = _freeze(publication)
    writer_path = Path(stores.state.path).parent / "writer.lock"
    descriptor, = [int(item.name) for item in Path("/proc/self/fd").iterdir()
                   if item.is_symlink() and item.readlink() == writer_path]
    fcntl.flock(descriptor, fcntl.LOCK_UN)
    try:
        before = local.db.total_changes
        with pytest.raises(ValueError, match="held scraper and writer leases"):
            _apply(publication, plan)
        assert local.db.total_changes == before
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _remote_request(publication, plan):
    stores, local, remote, _ = publication
    intent = stores.inbox.exact_remote_state(CYCLE_ID, COMPANY_ID)
    return SheetsSynchronizer(local, remote), {
        "inbox": stores.inbox, "cycle_id": CYCLE_ID, "company_id": COMPANY_ID, "plan_digest": plan["plan_digest"],
        "receipt_id": intent["receipt_id"], "intent_id": intent["intent_id"],
    }


def test_direct_sheets_publication_refuses_even_a_callback_before_attempt_claim(publication, monkeypatch):
    stores, local, remote, _ = publication
    plan = _freeze(publication)
    _apply(publication, plan)
    with monkeypatch.context() as patch:
        patch.setattr(SheetsSynchronizer, "publish_exact_scope", lambda *args, **kwargs: None)
        assert _publish(publication)["held"]
    sync, request = _remote_request(publication, plan)
    intent = stores.inbox.exact_remote_state(CYCLE_ID, COMPANY_ID)
    exact_plan = sync._durable_exact_plan(**request)
    start, chunk = _bounded_exact_chunks(exact_plan)[0]
    def callback():
        pytest.fail("The caller callback cannot establish enrolled authority.")
    before = local.db.total_changes
    with pytest.raises(ValueError, match="original dispatch authority"):
        sync.publish_exact_scope(chunk, **request, pre_commit_guard=callback, remote_cursor=start,
                                 remote_projection_digest=intent["projection_digest"])
    with pytest.raises(ValueError, match="original dispatch authority"):
        stores.inbox.claim_exact_remote_attempt(
            CYCLE_ID, COMPANY_ID, local_plan_digest=plan["plan_digest"],
            projection_digest=intent["projection_digest"], receipt_id=intent["receipt_id"],
            intent_id=intent["intent_id"], cursor=start, count=len(chunk["operations"]),
            chunk_digest=chunk["projection_digest"], timestamp="2026-11-20T21:01:00+00:00")
    assert stores.inbox.exact_remote_state(CYCLE_ID, COMPANY_ID) == intent
    assert not remote.commits and local.db.total_changes == before
    assert _publish(publication)["confirmed"] == [COMPANY_ID]


@pytest.mark.parametrize("method", ["confirm_exact_scope", "confirm_and_acknowledge_exact_scope"])
def test_direct_sheets_confirmation_cannot_mutate_receipt_or_jobs(publication, monkeypatch, method):
    stores, local, remote, _ = publication
    plan = _freeze(publication)
    _apply(publication, plan)
    with monkeypatch.context() as patch:
        patch.setattr(SheetsSynchronizer, "confirm_and_acknowledge_exact_scope", lambda *args, **kwargs: None)
        assert _publish(publication)["held"]
    sync, request = _remote_request(publication, plan)
    receipt = _fallback_receipt(stores.state.cycle(CYCLE_ID), COMPANY_ID, plan,
                                stores.inbox.get(CYCLE_ID, COMPANY_ID)[0])
    assert stores.inbox.receipt(receipt)["state"] == publication_receipts.SYNC_PENDING
    before = local.db.total_changes
    with pytest.raises(ValueError, match="original dispatch authority"):
        getattr(sync, method)(**request)
    assert stores.inbox.receipt(receipt)["state"] == publication_receipts.SYNC_PENDING
    assert local.db.total_changes == before and len(remote.commits) == 1
    assert _publish(publication)["confirmed"] == [COMPANY_ID]
    assert len(remote.commits) == 1


def test_direct_cleanup_is_refused_until_whole_final_state_is_durable(publication, monkeypatch):
    stores, _, remote, _ = publication
    plan = _freeze(publication)
    _apply(publication, plan)
    with monkeypatch.context() as patch:
        patch.setattr("job_search_helper.exact_cycle_sync._finalize_exact_company", lambda *args, **kwargs: None)
        assert _publish(publication)["confirmed"] == [COMPANY_ID]
    assert stores.state.cycle(CYCLE_ID)["companies"][COMPANY_ID]["stage"] == "inventory"
    with pytest.raises(ValueError, match="State is not finalized"):
        stores.inbox.acknowledge(CYCLE_ID, COMPANY_ID, local=stores.jobs, _verification_stores=stores)
    assert stores.inbox.get(CYCLE_ID, COMPANY_ID) is not None and _proof(stores) is None
    assert _publish(publication)["confirmed"] == [COMPANY_ID] and len(remote.commits) == 1
    assert _proof(stores)["plan_digest"] == plan["plan_digest"]


def test_cleanup_failure_rolls_back_archive_then_exact_replay_does_not_write_again(publication):
    stores, _, remote, _ = publication
    plan = _freeze(publication)
    _apply(publication, plan)
    stores.inbox.connection.execute(
        "CREATE TRIGGER refuse_cleanup BEFORE DELETE ON inventories "
        "BEGIN SELECT RAISE(ABORT, 'fixture cleanup cut'); END"
    )
    failing = _publish(publication)
    assert not failing["confirmed"] and failing["held"]
    assert _proof(stores) is None
    assert stores.inbox.exact_remote_state(CYCLE_ID, COMPANY_ID)["state"] == "LOCAL_ACKNOWLEDGED"
    assert stores.inbox.get(CYCLE_ID, COMPANY_ID) is not None
    stores.inbox.connection.execute("DROP TRIGGER refuse_cleanup")
    recovered = _publish(publication)
    assert recovered["confirmed"] == [COMPANY_ID], recovered
    assert len(remote.commits) == 1 and _proof(stores)["plan_digest"] == plan["plan_digest"]


@pytest.mark.parametrize("change", ["dispatch", "observation", "receipt", "jobs_ack", "plan_tail"])
def test_archived_proof_rejects_wrong_identity_and_missing_terminal_evidence(publication, change):
    stores, local, _, _ = publication
    plan = _freeze(publication)
    _apply(publication, plan)
    assert _publish(publication)["confirmed"] == [COMPANY_ID]
    record = _proof(stores)
    if change in {"dispatch", "observation"}:
        cycle = stores.state.cycle(CYCLE_ID)
        mark = cycle["companies"][COMPANY_ID][pending.MARKER]
        if change == "dispatch":
            mark["owner"]["observation_generation"] += 1
            mark["dispatch_sha256"] = pending._dispatch_sha256(mark)
        else:
            mark["observation"]["response_sha256"] = "f" * 64
        stores.state.save_cycle(cycle)
    elif change == "receipt":
        with stores.inbox.connection:
            stores.inbox.connection.execute("DELETE FROM publication_receipts WHERE receipt_id=?",
                                            (record["receipt_id"],))
    elif change == "jobs_ack":
        with local.db:
            local.db.execute("DELETE FROM exact_local_acknowledgements WHERE apply_id=?", (record["apply_id"],))
    else:
        with stores.inbox.connection:
            stores.inbox.connection.execute("INSERT INTO sync_plans VALUES (?,?,?,0)", (CYCLE_ID, COMPANY_ID, "{}"))
    with pytest.raises(ValueError):
        _proof(stores)


def test_private_marker_leaves_legacy_bytes_and_exact_v2_binding_identical(publication, monkeypatch):
    stores, local, remote, engine = publication
    import job_search_helper.engine as engine_module
    monkeypatch.setattr(engine_module, "now", lambda: "2026-11-20T20:01:00+00:00")
    spec = importlib.util.spec_from_file_location("job_search_helper._fixture_original_exact_cycle_planner",
                                                BASE / "exact_cycle_planner.py")
    original = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(original)
    cycle = stores.state.cycle(CYCLE_ID)
    plain = deepcopy(cycle)
    plain["companies"][COMPANY_ID].pop(pending.MARKER)
    payload = stores.inbox.get(CYCLE_ID, COMPANY_ID)[0]
    original_plan = original._freeze(engine, PlanningRepository(local), plain, COMPANY_ID, payload)
    marked_plan = planner._freeze(engine, PlanningRepository(local), cycle, COMPANY_ID, payload)
    plain_plan = planner._freeze(engine, PlanningRepository(local), plain, COMPANY_ID, payload)
    control, digest = planner._control_evidence(_guard(local, remote)(COMPANY_ID, payload["requested_url"]),
                                               COMPANY_ID, payload["requested_url"])
    for plan in (original_plan, marked_plan, plain_plan):
        plan.update(control_evidence=control, control_evidence_version=1, control_evidence_digest=digest)
    old_legacy, new_legacy = deepcopy(original_plan), deepcopy(plain_plan)
    with closing(SQLiteRepository(local.path, WORKBOOK)) as legacy:
        legacy.set_meta("sheets_profile", "")
        original._seal_plan(old_legacy, payload, legacy)
        planner._seal_plan(new_legacy, payload, legacy)
        legacy.set_meta("sheets_profile", COMPACT_PROFILE)
    assert json.dumps(old_legacy, ensure_ascii=False) == json.dumps(new_legacy, ensure_ascii=False)
    marked = planner._seal_exact_plan_v2(marked_plan, payload, local, CYCLE_ID, COMPANY_ID)
    unmarked = planner._seal_exact_plan_v2(plain_plan, payload, local, CYCLE_ID, COMPANY_ID)
    assert marked == unmarked
    assert _fallback_receipt(cycle, COMPANY_ID, marked, payload)["binding"] == _fallback_receipt(
        plain, COMPANY_ID, unmarked, payload)["binding"]


def test_bound_exact_plan_direct_replay_requires_same_owner(publication):
    stores, _, _, _ = publication
    plan = _freeze(publication)
    with pytest.raises(ValueError, match="original dispatch authority"):
        stores.inbox.save_exact_plan(CYCLE_ID, COMPANY_ID, plan, timestamp="2026-11-20T21:01:00+00:00")
    assert stores.inbox.plan(CYCLE_ID, COMPANY_ID) == (plan, 0)
