"""Expiry recovery boundary fixture with SQLite and an offline Sheets model."""
from contextlib import closing
from pathlib import Path
import socket
from unittest.mock import Mock

import pytest

from job_search_helper.cli import PROJECT_ROOT, scraper_lock_name, writer_lock
from job_search_helper.exact_cycle_planner import _exact_plan_digest
from job_search_helper.exact_local_plan import commit_exact_local_plan, exact_local_plan
from job_search_helper.publication_receipts import record_fingerprints
from job_search_helper.repository import GoogleRepository, UncertainWriteError
from job_search_helper.retained_dirty_provenance import (
    REMOTE_PENDING, bind_remote_session, reserve_dirty_provenance, retained_publication,
)
from job_search_helper.retained_session_store import RetainedSessionStore
from job_search_helper import retained_work_publication as publication_module
from job_search_helper.retained_work_publication import (
    finish_confirmed_retained_publication, recover_claimed_retained_chunk,
)
from job_search_helper.retained_work_runner import (
    PreparedExceptionalStart, _StartJournal, _TOKEN, _read_existing_journal, _start_binding, digest,
)
from job_search_helper.sheet_profile import COMPACT_PROFILE, COMPACT_SCHEMAS
from job_search_helper.sheets_sync import SheetsSynchronizer
from job_search_helper.sqlite_repository import SQLiteRepository
from sheets_fixture import RangeSheets


RUNTIME = {
    "state": "NO_RELEASE", "source_manifest_sha256": digest("fixture source"),
    "config_sha256": digest("fixture config"),
    "dependency_manifest_sha256": digest("fixture dependencies"),
}
ADMISSION = {
    "request_id": "REQ-EXACT", "event_id": "CEV-EXACT", "exception_cycle_id": "CYC-HISTORICAL",
    "cycle_id": "CYC-SELECTED", "company_id": "COMP-SELECTED", "source_revision": "SOURCE-EXACT",
    "manifest_digest": digest("historical manifest"),
}
RESERVATION = digest({"signed": "original fixture reservation"})
INVENTORY = {"jobs": ["fixture-1", "fixture-2"]}
START = PreparedExceptionalStart(
    _TOKEN,
    {
        "request": {"request_id": ADMISSION["request_id"], "company_ids": [ADMISSION["company_id"]],
                    "company_event": {"event_id": ADMISSION["event_id"]}},
        "snapshot_digest": digest("frozen snapshot"),
    },
    {"Company ID": ADMISSION["company_id"]},
    {"id": ADMISSION["exception_cycle_id"]},
    INVENTORY,
    {"reservation_digest": RESERVATION, "manifest_digest": ADMISSION["manifest_digest"]},
    "2026-11-20T00:00:00+00:00",
)
ADMISSION["start_binding_digest"] = digest(_start_binding(START))


def fixture_plan():
    local, remote = [], []
    for index in range(2):
        key = {"Job Key": f"JOB-{index}"}
        fields = {**key, "Company": "Selected", "Job Title": f"Engineer {index}",
                  "Official Job URL": f"https://jobs.example.test/fixture/{index}",
                  "Job Status": "Open and verified", "Review Status": "Needs Review",
                  "Added to Opportunities?": "Pending"}
        operation = {
            "tab": "Job History", "identity": key, "append_if_missing": True,
            "on_insert": fields, "values": {}, "expected": {}, "append_notes": {},
        }
        source_hash = f"SOURCE-{index}"
        local.append(dict(operation, on_insert={**fields, "Source Hash": source_hash}))
        local.append({
            "tab": "Job Evidence", "identity": {**key, "Source Hash": source_hash},
            "append_if_missing": True, "on_insert": {
                **key, "Source Hash": source_hash, "Company": "Selected",
                "Job Title": fields["Job Title"], "Official Job URL": fields["Official Job URL"],
                "Job Description": "Fixture field engineering, integration and support evidence.",
            },
        })
        remote.append(operation)
    control = {
        "company_id": ADMISSION["company_id"], "requested_url": "https://jobs.example.test",
        "official_careers_url": "https://jobs.example.test", "company_status": "Active",
        "claimed_by": "", "claim_token": "",
    }
    schemas = {"Job History": sorted(remote[0]["on_insert"])}
    final = {"stage": "complete"}
    local_records, remote_records = record_fingerprints(local), record_fingerprints(remote)
    plan = {
        "exact_plan_version": 2, "cycle_id": ADMISSION["cycle_id"], "company_id": ADMISSION["company_id"],
        "inventory_payload_digest": digest(INVENTORY), "publication_profile": COMPACT_PROFILE,
        "requested_url": control["requested_url"], "control_evidence_version": 1, "control_evidence": control,
        "control_evidence_digest": digest(control), "publication_schema": schemas,
        "publication_schema_digest": digest(schemas), "retained_membership_only": True,
        "runtime_binding_sha256": digest(RUNTIME), "local_operations": local, "remote_projection": remote,
        "local_operations_digest": digest(local), "local_expected_records": local_records,
        "local_expected_records_digest": digest(local_records), "remote_projection_digest": digest(remote),
        "remote_records": remote_records, "remote_records_digest": digest(remote_records),
        "final": final, "final_projection": final,
        "local_finalization_digest": digest({"operations": local, "final": final}),
        "final_projection_digest": digest(final),
    }
    plan["plan_digest"] = _exact_plan_digest(plan)
    return plan


class ReadOnlyTransport:
    def __init__(self, remote):
        self.spreadsheet_id = remote.spreadsheet_id
        self.read_columns = Mock(wraps=remote.read_columns)
        self.read_row = Mock(wraps=remote.read_row)


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    assert PROJECT_ROOT == Path(__file__).resolve().parents[1]

    def reject_network(*args, **kwargs):
        pytest.fail("fixture attempted network access")

    monkeypatch.setattr(socket.socket, "connect", reject_network)
    monkeypatch.setattr(socket.socket, "connect_ex", reject_network)
    path = tmp_path / "jobs.sqlite3"
    stores = tmp_path / "retained-sessions.sqlite3"
    with closing(SQLiteRepository(path, "fixture", initialize=True)) as local, RetainedSessionStore(stores) as store:
        with local.transaction():
            local.set_meta("ready", "yes")
            local.set_meta("sheets_profile", COMPACT_PROFILE)
            local.db.execute("""CREATE TABLE retained_intake_holds (
                reservation_digest TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE,
                event_id TEXT NOT NULL UNIQUE, company_id TEXT NOT NULL,
                manifest_digest TEXT NOT NULL, start_binding_digest TEXT NOT NULL,
                state TEXT NOT NULL CHECK(state='FROZEN'))""")
            local.db.execute("INSERT INTO retained_intake_holds VALUES (?,?,?,?,?,?,?)",
                (RESERVATION, ADMISSION["request_id"], ADMISSION["event_id"], ADMISSION["company_id"],
                 ADMISSION["manifest_digest"], ADMISSION["start_binding_digest"], "FROZEN"))
        with closing(_StartJournal(tmp_path / "retained-work-starts.sqlite3")) as start:
            start.reserve(START)
        plan = fixture_plan()
        reserve_dirty_provenance(local, reservation_digest=RESERVATION, plan=plan, **ADMISSION)
        commit_exact_local_plan(
            local, ADMISSION["cycle_id"], ADMISSION["company_id"], plan, reservation_digest=RESERVATION,
        )
        applied = exact_local_plan(local, ADMISSION["cycle_id"], ADMISSION["company_id"])
        store.freeze(RESERVATION, admission=ADMISSION, inventory=INVENTORY, plan=plan)
        sheet = RangeSheets({}, schemas=COMPACT_SCHEMAS)
        remote = GoogleRepository(sheet, "fixture", schemas=COMPACT_SCHEMAS, min_request_interval=0)
        exact = SheetsSynchronizer(local, remote).plan_exact_scope(applied["row_scope"], plan["remote_projection"])
        store.freeze_remote_intent(RESERVATION, exact_scope=exact)
        bind_remote_session(local, RESERVATION, plan, session_store=store)
        with closing(SQLiteRepository(path, "fixture", readonly=True)) as reader:
            yield tmp_path, reader, store, remote, sheet


def recover(root, reader, store, factory, claim_id, *, runtime=RUNTIME, reservation=RESERVATION):
    with writer_lock(root / scraper_lock_name()), writer_lock(root / "writer.lock"):
        return recover_claimed_retained_chunk(
            reservation, store, reader, factory, claim_id=claim_id, runtime_binding=runtime,
        )


@pytest.mark.parametrize(("count", "state"), [(1, "HELD_UNCLAIMED_SUFFIX"), (2, "READY_FOR_FULL_READBACK")])
def test_lost_response_confirms_only_existing_claim(prepared, monkeypatch, count, state):
    root, reader, store, remote, sheet = prepared
    claim = store.claim_chunk(RESERVATION, operation_count=count)
    sheet.lose_response = True
    with pytest.raises(UncertainWriteError):
        remote.commit(claim["exact_scope"]["operations"])
    before = tuple(reader.db.iterdump())
    batches = list(sheet.batches)
    request = root / "next-scan.json"
    assert not request.exists()
    transport = ReadOnlyTransport(remote)
    factory = Mock(return_value=transport)
    forbidden_claim = Mock(side_effect=AssertionError("recovery claimed a new chunk"))
    monkeypatch.setattr(store, "claim_chunk", forbidden_claim)
    result = recover(root, reader, store, factory, claim["claim_id"])
    assert result["state"] == state
    assert result["reservation_digest"] == RESERVATION
    assert result["claim_id"] == claim["claim_id"]
    assert result["operation_count"] == result["remote_cursor"] == count
    assert result["unclaimed_operations"] == 2 - count
    assert result["session_state"] == "SYNC_PENDING"
    session = store.load(RESERVATION)
    confirmed, = session["chunks"]
    assert confirmed["state"] == "CONFIRMED"
    assert confirmed["readback_digest"] == result["readback_digest"]
    assert session["receipt_id"] == result["receipt_id"]
    assert session["intent_id"] == result["intent_id"]
    assert session["acknowledgement_id"] is None
    assert retained_publication(reader, RESERVATION)["state"] == REMOTE_PENDING
    assert transport.read_row.call_count == count
    assert sheet.batches == batches
    assert tuple(reader.db.iterdump()) == before
    assert not request.exists()
    assert not (root / "retained-first-pass").exists()
    assert recover(root, reader, store, factory, claim["claim_id"]) == result
    factory.assert_called_once()
    forbidden_claim.assert_not_called()


def test_unapplied_claim_stays_claimed_without_dispatch(prepared):
    root, reader, store, remote, sheet = prepared
    claim = store.claim_chunk(RESERVATION, operation_count=1)
    before = store.load(RESERVATION)
    factory = Mock(return_value=ReadOnlyTransport(remote))
    with pytest.raises(ValueError, match="identity is missing or ambiguous"):
        recover(root, reader, store, factory, claim["claim_id"])
    assert store.load(RESERVATION) == before
    assert sheet.batches == []
    factory.assert_called_once()


def test_missing_claim_or_mismatched_runtime_does_not_open_remote(prepared):
    root, reader, store, remote, sheet = prepared
    factory = Mock(return_value=ReadOnlyTransport(remote))
    with pytest.raises(ValueError, match="retained_claim_readback_exact_claim_missing"):
        recover(root, reader, store, factory, digest("unclaimed"))
    claim = store.claim_chunk(RESERVATION, operation_count=1)
    with pytest.raises(ValueError, match="retained_operator_saved_plan_runtime_changed"):
        recover(root, reader, store, factory, claim["claim_id"],
                runtime=dict(RUNTIME, config_sha256=digest("different")))
    with pytest.raises(ValueError, match="retained_session_missing"):
        recover(root, reader, store, factory, claim["claim_id"], reservation=digest("re-signed"))
    factory.assert_not_called()
    assert sheet.batches == []
    assert store.load(RESERVATION)["chunks"][0]["state"] == "CLAIMED"


def test_corrupt_operation_digest_fails_before_remote_factory(prepared):
    root, reader, store, remote, sheet = prepared
    claim = store.claim_chunk(RESERVATION, operation_count=1)
    with store.connection:
        store.connection.execute(
            "UPDATE retained_remote_chunks SET operation_digest=? WHERE claim_id=?",
            (digest("changed frozen operations"), claim["claim_id"]),
        )
    factory = Mock(return_value=ReadOnlyTransport(remote))
    with pytest.raises(ValueError, match="retained_claim_readback_claim_binding_changed"):
        recover(root, reader, store, factory, claim["claim_id"])
    factory.assert_not_called()
    assert sheet.batches == []


def finish(root, reader, store, remote_factory, writer_factory, claim_id):
    with writer_lock(root / scraper_lock_name()), writer_lock(root / "writer.lock"):
        return finish_confirmed_retained_publication(
            RESERVATION, store, reader, remote_factory, writer_factory,
            claim_id=claim_id, runtime_binding=RUNTIME,
        )


def confirm_fixture_claim(prepared, count):
    root, reader, store, remote, sheet = prepared
    claim = store.claim_chunk(RESERVATION, operation_count=count)
    sheet.lose_response = True
    with pytest.raises(UncertainWriteError):
        remote.commit(claim["exact_scope"]["operations"])
    result = recover(root, reader, store, lambda: ReadOnlyTransport(remote), claim["claim_id"])
    return result["claim_id"]


@pytest.mark.parametrize("interruption", ["before_local_ack", "after_local_ack"])
def test_terminal_only_restarts_with_original_proof(prepared, monkeypatch, interruption):
    root, reader, store, remote, sheet = prepared
    claim_id = confirm_fixture_claim(prepared, 2)
    batches = list(sheet.batches)
    pending = store.load(RESERVATION)
    assert pending["state"] == "SYNC_PENDING"
    assert _read_existing_journal(root / "retained-work-starts.sqlite3")["state"] == "FROZEN"
    transport = ReadOnlyTransport(remote)
    reader_factory = Mock(return_value=transport)

    def writer():
        assert store.load(RESERVATION)["state"] == "SYNC_CONFIRMED"
        assert transport.read_row.call_count >= 2
        return SQLiteRepository(reader.path, reader.spreadsheet_id, initialize=False)

    def fail(*_args, **_kwargs):
        raise RuntimeError("injected terminal interruption")

    with monkeypatch.context() as interrupted:
        interrupted.setattr(store, "claim_chunk", Mock(side_effect=AssertionError("claimed suffix")))
        interrupted.setattr(store, "freeze_remote_intent", Mock(side_effect=AssertionError("froze intent")))
        interrupted.setattr(SheetsSynchronizer, "plan_exact_scope", Mock(side_effect=AssertionError("replanned scope")))
        writer_factory = Mock(side_effect=writer)
        if interruption == "before_local_ack":
            writer_factory.side_effect = fail
        else:
            interrupted.setattr(publication_module, "confirm_remote_from_session", fail)
        with pytest.raises(RuntimeError, match="injected terminal interruption"):
            finish(root, reader, store, reader_factory, writer_factory, claim_id)
    stored = store.load(RESERVATION)
    assert stored["state"] == "SYNC_CONFIRMED"
    assert stored["chunks"] == pending["chunks"]
    assert stored["receipt_id"] == pending["receipt_id"]
    assert stored["intent_id"] == pending["intent_id"]
    assert stored["acknowledgement_id"]
    assert retained_publication(reader, RESERVATION)["state"] == REMOTE_PENDING
    assert _read_existing_journal(root / "retained-work-starts.sqlite3")["state"] == "FROZEN"
    assert not (root / "retained-first-pass").exists()
    assert not (root / "next-scan.json").exists()
    if interruption == "before_local_ack":
        assert reader.db.execute("SELECT count(*) FROM dirty").fetchone()[0] > 0
        assert reader.db.execute("SELECT count(*) FROM exact_local_acknowledgements").fetchone() == (0,)
    else:
        assert reader.db.execute("SELECT count(*) FROM dirty").fetchone() == (0,)
        assert reader.db.execute("SELECT acknowledgement_id FROM exact_local_acknowledgements").fetchall() == [
            (stored["acknowledgement_id"],),
        ]

    writers = Mock(side_effect=writer)
    monkeypatch.setattr(store, "claim_chunk", Mock(side_effect=AssertionError("claimed suffix")))
    monkeypatch.setattr(store, "freeze_remote_intent", Mock(side_effect=AssertionError("froze intent")))
    monkeypatch.setattr(SheetsSynchronizer, "plan_exact_scope", Mock(side_effect=AssertionError("replanned scope")))
    result = finish(root, reader, store, reader_factory, writers, claim_id)
    assert result["state"] == "FIRST_PASS_RELEASED"
    assert result["settlement"]["settled"] is True
    writers.assert_called_once()
    assert result["acknowledgement_id"] == stored["acknowledgement_id"]
    assert _read_existing_journal(root / "retained-work-starts.sqlite3") is None
    assert [row["job_key"] for row in result["first_pass"]["selected_jobs"]] == ["JOB-0", "JOB-1"]
    assert Path(result["first_pass"]["output_dir"], "first-pass.jsonl").is_file()
    assert reader.db.execute("SELECT count(*) FROM dirty").fetchone() == (0,)
    assert reader.db.execute("SELECT count(*) FROM exact_local_acknowledgements").fetchone() == (1,)
    assert store.load(RESERVATION) == stored
    assert sheet.batches == batches
    assert not (root / "next-scan.json").exists()
    replay = finish(root, reader, store, reader_factory, writers, claim_id)
    assert replay["first_pass"] == result["first_pass"]
    assert replay["acknowledgement_id"] == result["acknowledgement_id"]
    writers.assert_called_once()
    assert sheet.batches == batches


def test_terminal_only_does_not_open_either_factory_with_an_unclaimed_suffix(prepared):
    root, reader, store, remote, sheet = prepared
    claim_id = confirm_fixture_claim(prepared, 1)
    remote_factory, writer_factory = Mock(), Mock()
    with pytest.raises(ValueError, match="retained_terminal_readback_claims_incomplete"):
        finish(root, reader, store, remote_factory, writer_factory, claim_id)
    remote_factory.assert_not_called()
    writer_factory.assert_not_called()
    assert store.load(RESERVATION)["remote_cursor"] == 1
    assert len(sheet.batches) == 1


def test_terminal_only_holds_changed_remote_values_before_jobs_writer(prepared):
    root, reader, store, remote, sheet = prepared
    claim_id = confirm_fixture_claim(prepared, 2)
    remote.commit([{"tab": "Job History", "identity": {"Job Key": "JOB-1"}, "values": {"Job Title": "Changed"}}])
    before = store.load(RESERVATION)
    batches = list(sheet.batches)
    writer_factory = Mock()
    with pytest.raises(ValueError, match="differs from the frozen projection"):
        finish(root, reader, store, lambda: ReadOnlyTransport(remote), writer_factory, claim_id)
    writer_factory.assert_not_called()
    assert store.load(RESERVATION) == before
    assert sheet.batches == batches
    assert not (root / "retained-first-pass").exists()


def test_terminal_only_binds_full_readback_to_previously_confirmed_claim_bytes(prepared):
    root, reader, store, remote, sheet = prepared
    claim_id = confirm_fixture_claim(prepared, 2)
    with store.connection:
        store.connection.execute(
            "UPDATE retained_remote_chunks SET readback_digest=? WHERE claim_id=?",
            (digest("different claim readback"), claim_id),
        )
    writer_factory = Mock()
    with pytest.raises(ValueError, match="retained_terminal_readback_claim_evidence_changed"):
        finish(root, reader, store, lambda: ReadOnlyTransport(remote), writer_factory, claim_id)
    writer_factory.assert_not_called()
    assert store.load(RESERVATION)["state"] == "SYNC_PENDING"
    assert len(sheet.batches) == 1


def test_terminal_only_replays_a_complete_multi_claim_prefix(prepared, monkeypatch):
    root, reader, store, remote, sheet = prepared
    first = confirm_fixture_claim(prepared, 1)
    second = confirm_fixture_claim(prepared, 1)
    pending = store.load(RESERVATION)
    assert [(claim["claim_id"], claim["start_cursor"], claim["state"]) for claim in pending["chunks"]] == [
        (first, 0, "CONFIRMED"), (second, 1, "CONFIRMED"),
    ]
    transport = ReadOnlyTransport(remote)
    factory = Mock(return_value=transport)
    writer = Mock(side_effect=lambda: SQLiteRepository(reader.path, reader.spreadsheet_id))
    monkeypatch.setattr(store, "claim_chunk", Mock(side_effect=AssertionError("claimed suffix")))
    with pytest.raises(ValueError, match="retained_claim_readback_exact_claim_missing"):
        finish(root, reader, store, factory, writer, first)
    factory.assert_not_called()
    writer.assert_not_called()
    result = finish(root, reader, store, factory, writer, second)
    assert result["state"] == "FIRST_PASS_RELEASED"
    assert store.load(RESERVATION)["chunks"] == pending["chunks"]
    assert transport.read_row.call_count == 2
    assert len(sheet.batches) == 2
    writer.assert_called_once()
