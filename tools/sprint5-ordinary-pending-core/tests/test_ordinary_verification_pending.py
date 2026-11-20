from copy import deepcopy

import pytest

from job_search_helper import ordinary_verification_pending as pending
from job_search_helper.company_events import canonical_company_fact
from job_search_helper.engine import State, inventory_payload
from job_search_helper.ats import Inventory, outcome_failure
from job_search_helper.inbox import InventoryInbox
from job_search_helper.repository import RepositoryError
from job_search_helper.sqlite_repository import SQLiteRepository
from job_search_helper.source_configuration_snapshot import _PATHS


COMPANY_ID = "COMP-4510"
CYCLE_ID = "CYC-6A8E0912F333"
CONFIGURED = "https://ats.rippling.com/stale-tenant/jobs"
COMPANY = {"Company": "Forterra", "Company ID": COMPANY_ID, "Company Status": "Active",
           "ATS / Source": "Rippling", "Official Careers URL": "https://example.test/careers"}
OBSERVATION = {"schema": "rippling-tenant-mismatch-v1", "configured_url": CONFIGURED,
               "expected_slug": "stale-tenant", "observed_slug": "different-tenant",
               "response_sha256": "6" * 64}


@pytest.fixture
def attempt(tmp_path):
    state_path, jobs_path, inbox_path = (tmp_path / name for name in ("state.db", "jobs.db", "inbox.db"))
    state = State(state_path)
    inbox = InventoryInbox(inbox_path, "fixture-workbook")
    jobs = SQLiteRepository(jobs_path, "fixture-workbook", initialize=True)
    jobs.set_meta("ready", "yes")
    jobs.close()
    inbox.close()
    fact = canonical_company_fact(COMPANY)
    revision = pending.digest(fact)
    runtime = {"reviewed_runtime": "synthetic custody"}
    sources = [{"path": path, "sha256": "7" * 64} for path in _PATHS]
    capability = {"capability_id": "rippling-shared-v1", "provider": "rippling",
                  "source_paths": list(_PATHS)}
    snapshot = {
        "schema": "installed-source-configuration-v1",
        "company_id": COMPANY_ID, "source_revision": revision, "company": COMPANY["Company"],
        "official_careers_url": fact["official_careers_url"], "ats_source": "rippling",
        "configured_provider": "rippling", "configured_url": CONFIGURED,
        "capability_id": capability["capability_id"], "capability_sources": sources,
        "capability_digest": pending.digest({"capability": capability, "sources": sources}),
        "mapping_digest": "2" * 64,
    }
    snapshot["configuration_digest"] = pending.digest(snapshot)
    state.save_cycle({
        "id": CYCLE_ID, "started_at": "2026-11-20T21:00:00+00:00",
        "start_request_id": "test-ordinary-request", "request_fingerprint": "1" * 64,
        "all": False, "status": "In Progress", "runtime_binding": runtime,
        "companies": {COMPANY_ID: {"company": COMPANY["Company"], "stage": "queued",
                                  "outcome_source_revision": revision, "outcome_source_fact": fact,
                                  "installed_source_configuration": snapshot}},
    })
    owner = {
        "cycle_id": CYCLE_ID, "cycle_started_at": "2026-11-20T21:00:00+00:00",
        "request_id": "test-ordinary-request", "request_fingerprint": "1" * 64,
        "company_id": COMPANY_ID, "source_revision": revision,
        "company_source_sha256": pending.digest({"company": COMPANY["Company"], "fact": fact}),
        "store_binding_sha256": "3" * 64, "observation_generation": 1,
    }
    admission = {key: snapshot[key] for key in ("configured_url", "capability_id", "capability_digest",
                                                "mapping_digest", "configuration_digest")}
    admission.update(authority_url=fact["official_careers_url"], matrix_digest="4" * 64,
                     runtime_binding_sha256=pending.digest(runtime))
    payload = inventory_payload(Inventory("partial", ats="Rippling", reason="bounded"), COMPANY)
    state.close()
    with pending.open_verification_stores(state_path, jobs_path, inbox_path, "fixture-workbook") as stores:
        owner["store_binding_sha256"] = pending.store_binding(stores)
        yield stores, owner, admission, payload


def prepare(attempt, observation=OBSERVATION, failure=None):
    stores, owner, admission, payload = attempt
    state, inbox = stores.state, stores.inbox
    dispatched = pending.digest({"schema": pending.SCHEMA, "state": "ARMED", "owner": owner,
                                 "admission": admission})
    return pending.prepare_inventory(stores, CYCLE_ID, COMPANY_ID, payload,
                                     dispatch_digest=dispatched, observation=observation, failure=failure)


def test_same_attempt_transfers_payload_unchanged_and_exact_observation(attempt):
    stores, owner, admission, payload = attempt
    state, inbox = stores.state, stores.inbox
    preexisting = state.cycle(CYCLE_ID)
    assert pending.read_marker(preexisting, COMPANY_ID) is None
    armed = pending.arm(stores, owner, admission)
    assert armed == pending.arm(stores, owner, admission)
    assert pending.read_marker(armed, COMPANY_ID)["state"] == "ARMED"
    final = prepare(attempt)
    assert pending.verifier_payload(stores, CYCLE_ID, COMPANY_ID) == {
        "schema": pending.SCHEMA, "owner": owner, "admission": admission, "observation": OBSERVATION,
    }
    assert pending.read_prepared_inventory(stores, CYCLE_ID, COMPANY_ID) == (final, (payload, False))
    assert prepare(attempt) == final
    assert inbox.saved == 1
    assert set(inbox.get(CYCLE_ID, COMPANY_ID)[0]) == set(payload)


def test_typed_absence_cannot_become_verifier_input(attempt):
    stores, owner, admission, payload = attempt
    state, inbox = stores.state, stores.inbox
    pending.arm(stores, owner, admission)
    payload["inventory_status"] = "complete"
    final = prepare(attempt, observation=None)
    with pytest.raises(RepositoryError, match="no typed"):
        pending.verifier_payload(stores, CYCLE_ID, COMPANY_ID)
    assert pending.read_prepared_inventory(stores, CYCLE_ID, COMPANY_ID)[1] == (payload, False)


def test_cut_after_state_before_inventory_holds_without_second_write(attempt, monkeypatch):
    stores, owner, admission, _ = attempt
    state, inbox = stores.state, stores.inbox
    pending.arm(stores, owner, admission)

    def stop(*args):
        raise RuntimeError("cut after State commit")

    with monkeypatch.context() as patch:
        patch.setattr(inbox, "save", stop)
        with pytest.raises(RuntimeError, match="cut after State"):
            prepare(attempt)
    assert pending.read_marker(state.cycle(CYCLE_ID), COMPANY_ID)["state"] == "PREPARED"
    assert inbox.get(CYCLE_ID, COMPANY_ID) is None
    with pytest.raises(RepositoryError, match="does not match"):
        prepare(attempt)
    with pytest.raises(RepositoryError, match="does not match"):
        pending.verifier_payload(stores, CYCLE_ID, COMPANY_ID)
    assert inbox.saved == 0


def test_unbound_same_key_inbox_row_is_never_adopted(attempt):
    stores, owner, admission, payload = attempt
    state, inbox = stores.state, stores.inbox
    pending.arm(stores, owner, admission)
    inbox.save(CYCLE_ID, COMPANY_ID, payload)
    with pytest.raises(RepositoryError, match="Unbound inventory"):
        prepare(attempt)
    with pytest.raises(RepositoryError, match="no prepared"):
        pending.read_prepared_inventory(stores, CYCLE_ID, COMPANY_ID)


def test_insert_or_ignore_foreign_winner_is_detected(attempt, monkeypatch):
    stores, owner, admission, payload = attempt
    state, inbox = stores.state, stores.inbox
    pending.arm(stores, owner, admission)
    original_save = inbox.save
    foreign = {**payload, "reason": "another publisher won this key"}

    def competing_save(cycle_id, company_id, final_payload):
        original_save(cycle_id, company_id, foreign)
        original_save(cycle_id, company_id, final_payload)

    monkeypatch.setattr(inbox, "save", competing_save)
    with pytest.raises(RepositoryError, match="does not match"):
        prepare(attempt)
    assert inbox.get(CYCLE_ID, COMPANY_ID) == (foreign, False)


def test_cycle_update_race_preserves_the_new_checkpoint(attempt, monkeypatch):
    stores, owner, admission, _ = attempt
    state, inbox = stores.state, stores.inbox
    saved = state.cycle(CYCLE_ID)
    original_plan = inbox.plan

    def concurrent_checkpoint(*args):
        latest = deepcopy(saved)
        latest["unrelated_progress"] = 23
        other = State(state.path)
        try:
            other.save_cycle(latest)
        finally:
            other.close()
        return original_plan(*args)

    monkeypatch.setattr(inbox, "plan", concurrent_checkpoint)
    with pytest.raises(RepositoryError, match="owning cycle changed"):
        pending.arm(stores, owner, admission)
    assert state.cycle(CYCLE_ID)["unrelated_progress"] == 23
    assert pending.read_marker(state.cycle(CYCLE_ID), COMPANY_ID) is None


@pytest.mark.parametrize("route", ["company_event", "operator_request", "repair_retry", "recovery_pause"])
def test_other_routes_cannot_enroll(attempt, route):
    stores, owner, admission, _ = attempt
    state, inbox = stores.state, stores.inbox
    cycle = state.cycle(CYCLE_ID)
    cycle[route] = {}
    state.save_cycle(cycle)
    with pytest.raises(RepositoryError, match="one exact enrolled attempt"):
        pending.arm(stores, owner, admission)


def test_configuration_or_scope_drift_blocks_verifier_export(attempt):
    stores, owner, admission, _ = attempt
    state, inbox = stores.state, stores.inbox
    pending.arm(stores, owner, admission)
    final = prepare(attempt)
    final["runtime_binding"]["reviewed_runtime"] = "changed runtime"
    state.save_cycle(final)
    with pytest.raises(RepositoryError, match="frozen scope"):
        pending.verifier_payload(stores, CYCLE_ID, COMPANY_ID)


def test_incomplete_precedence_cannot_overrule_access(attempt):
    stores, owner, admission, _ = attempt
    state, inbox = stores.state, stores.inbox
    pending.arm(stores, owner, admission)
    failure = outcome_failure("access_denied", "public_access_denied")
    with pytest.raises(RepositoryError):
        prepare(attempt, failure=failure)
    assert pending.read_marker(state.cycle(CYCLE_ID), COMPANY_ID)["state"] == "ARMED"
    assert inbox.get(CYCLE_ID, COMPANY_ID) is None


def test_existing_transaction_stays_uncommitted_and_untouched(attempt):
    stores, owner, admission, _ = attempt
    state, inbox = stores.state, stores.inbox
    state.connection.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(RepositoryError, match="idle SQLite"):
            pending.arm(stores, owner, admission)
        assert state.connection.in_transaction
    finally:
        state.connection.rollback()
    assert pending.read_marker(state.cycle(CYCLE_ID), COMPANY_ID) is None


def test_stale_dispatch_or_changed_requested_url_never_saves(attempt):
    stores, owner, admission, payload = attempt
    cycle = pending.arm(stores, owner, admission)
    dispatch = pending.dispatch_sha256(cycle, COMPANY_ID)
    with pytest.raises(RepositoryError, match="frozen dispatch"):
        pending.prepare_inventory(stores, CYCLE_ID, COMPANY_ID, payload,
                                  dispatch_digest="0" * 64, observation=OBSERVATION, failure=None)
    with pytest.raises(RepositoryError, match="different requested source"):
        pending.prepare_inventory(stores, CYCLE_ID, COMPANY_ID,
                                  {**payload, "requested_url": "https://example.test/substituted"},
                                  dispatch_digest=dispatch, observation=OBSERVATION, failure=None)
    assert stores.inbox.saved == 0


def test_foreign_copy_of_exact_inbox_cannot_supply_verifier_input(attempt, tmp_path):
    from contextlib import ExitStack
    from dataclasses import replace

    stores, owner, admission, payload = attempt
    pending.arm(stores, owner, admission)
    prepare(attempt)
    path = tmp_path / "other-inbox.db"
    other = InventoryInbox(path, "fixture-workbook")
    other.save(CYCLE_ID, COMPANY_ID, payload)
    other.close()
    with ExitStack() as stack:
        opened = pending._open_store(stack, path,
                                    lambda db: InventoryInbox(db, "fixture-workbook"), "connection")
        with pytest.raises(RepositoryError, match="current stores differ"):
            pending.verifier_payload(replace(stores, inbox=opened), CYCLE_ID, COMPANY_ID)


def test_blocked_inbox_retained_but_cannot_export_verifier_input(attempt):
    stores, owner, admission, payload = attempt
    pending.arm(stores, owner, admission)
    prepare(attempt)
    stores.inbox.block(CYCLE_ID, COMPANY_ID)
    assert pending.read_prepared_inventory(stores, CYCLE_ID, COMPANY_ID)[1] == (payload, True)
    with pytest.raises(RepositoryError, match="Blocked ordinary inventory"):
        pending.verifier_payload(stores, CYCLE_ID, COMPANY_ID)


def test_authority_read_rejects_duplicate_json_keys(attempt):
    stores, owner, admission, _ = attempt
    pending.arm(stores, owner, admission)
    connection = stores.state.connection
    with connection:
        original = connection.execute("SELECT data FROM main.cycles WHERE id=?", (CYCLE_ID,)).fetchone()[0]
        duplicate = '{"id":"other earlier ID",' + original[1:]
        connection.execute("UPDATE main.cycles SET data=? WHERE id=?", (duplicate, CYCLE_ID))
    with pytest.raises(RepositoryError, match="cycle identity changed"):
        prepare(attempt)


def test_ordinary_rearm_cannot_skip_new_plan_check(attempt, monkeypatch):
    stores, owner, admission, _ = attempt
    pending.arm(stores, owner, admission)
    monkeypatch.setattr(stores.inbox, "plan", lambda *_: ({"other": "work"}, 0))
    with pytest.raises(RepositoryError, match="existing inventory or plan"):
        pending.arm(stores, owner, admission)


def test_verifier_export_refuses_active_inbox_statement(attempt):
    stores, owner, admission, payload = attempt
    pending.arm(stores, owner, admission)
    prepare(attempt)
    stores.inbox.save("other-cycle", COMPANY_ID, payload)
    cursor = stores.inbox.connection.execute("SELECT cycle FROM main.inventories")
    assert cursor.fetchone() is not None
    try:
        with pytest.raises(RepositoryError, match="idle SQLite statements"):
            pending.verifier_payload(stores, CYCLE_ID, COMPANY_ID)
    finally:
        cursor.close()
    assert pending.verifier_payload(stores, CYCLE_ID, COMPANY_ID)["observation"] == OBSERVATION


def test_prepared_replay_never_returns_different_valid_dispatch(attempt, monkeypatch):
    stores, owner, admission, _ = attempt
    pending.arm(stores, owner, admission)
    prepare(attempt)
    real_readback = pending.read_prepared_inventory

    def replace_prepared_dispatch(*args):
        current = stores.state.cycle(CYCLE_ID)
        marker = current["companies"][COMPANY_ID][pending.MARKER]
        marker["owner"]["observation_generation"] += 1
        marker["dispatch_sha256"] = pending._dispatch_sha256(marker)
        stores.state.save_cycle(current)
        return real_readback(*args)

    monkeypatch.setattr(pending, "read_prepared_inventory", replace_prepared_dispatch)
    with pytest.raises(RepositoryError, match="no longer matches the original dispatch"):
        prepare(attempt)
    assert stores.inbox.saved == 1
