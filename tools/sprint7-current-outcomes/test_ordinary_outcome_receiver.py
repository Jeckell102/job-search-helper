from contextlib import closing
import fcntl
import json
import os
from pathlib import Path
import sys
from unittest.mock import Mock

import pytest

import release_admission_bootstrap as bootstrap
from job_search_helper import ats, cli, runner
from job_search_helper.engine import State
from job_search_helper.inbox import InventoryInbox
from job_search_helper.scrape_outcome_delivery import OutcomeDelivery
from job_search_helper.sqlite_repository import SQLiteRepository
from coordinator import Coordinator
from test_two_sided_outcome_delivery import ReceiverSink
from test_ordinary_company_event_command import queued
from test_ordinary_company_event_fetch import BOARD, OBSERVED

def no_network(event, args):
    if event in {"socket.connect", "socket.bind", "socket.getaddrinfo"}:
        raise AssertionError("attempted network")
sys.addaudithook(no_network)

def invoke(queued, action, monkeypatch, capsys, *, cycle=None, digest=None, inherited=True):
    paths, _, expected, *_ = queued
    args = ["ordinary-company-event", action, "--request-sha256", digest or expected]
    if cycle is not None:
        args += ["--cycle-id", cycle]
    with monkeypatch.context() as env:
        if inherited:
            path = paths[0].parent / "scraper.lock"
            descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            layout = bootstrap._retained_operator_sqlite_layout(runner.PROJECT_ROOT, paths[0], "sqlite")
            runtime = bootstrap._validate_runtime(runner.PROJECT_ROOT, paths[0].parent)
            env.setenv("JSH_SCRAPER_ADMISSION_FD", str(descriptor))
            env.setenv("JSH_SCRAPER_ADMISSION_PATH", str(path))
            env.setenv("JSH_SCRAPER_RUNTIME_BINDING", json.dumps(runtime))
            env.setenv(bootstrap.RETAINED_OPERATOR_LAYOUT_ENV, json.dumps(layout))
        try:
            code = runner.main(args)
        finally:
            if inherited:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
    capture = capsys.readouterr()
    lines = [line for line in capture.out.splitlines() if line.startswith("Ordinary Company event: ")]
    return code, json.loads(lines[-1].removeprefix("Ordinary Company event: ")) if lines else None, capture.err

def provider_result(kind):
    if kind == "zero":
        return ats.Inventory("complete", source_url="https://boards-api.greenhouse.io/v1/boards/fixture/jobs",
                             ats="Greenhouse", verified_zero="greenhouse_explicit_total_zero")
    if kind == "ambiguous":
        return ats.Inventory("complete", source_url=OBSERVED, ats="Lever")
    if kind == "temporary":
        return ats.Inventory("failed", source_url=OBSERVED, ats="Lever",
                             outcome_failure=ats.outcome_failure("temporary_transport", "retryable_http_status"))
    return ats.Inventory("blocked", source_url=OBSERVED, ats="Lever",
                         outcome_failure=ats.outcome_failure("access_denied", "public_access_denied"))

@pytest.mark.parametrize(("queued", "kind", "expected"), [
    ("greenhouse", "zero", "VERIFIED_ZERO"), ("lever", "temporary", "FETCH_TEMPORARY"),
    ("lever", "denied", "FETCH_BLOCKED"),
], indirect=["queued"])
def test_actual_guarded_runner_settles_and_replays_local_only(queued, kind, expected, monkeypatch, capsys):
    paths, _, _, provider, factory, remote, _ = queued
    provider.return_value = provider_result(kind)
    from job_search_helper import scrape_first_pass
    broad = Mock(side_effect=AssertionError("broad startup entered"))
    monkeypatch.setattr(scrape_first_pass, "main", broad)
    assert runner.main(["start"]) == 1
    capsys.readouterr()
    code, admitted, _ = invoke(queued, "admit-fetch", monkeypatch, capsys)
    assert code == 0 and admitted["state"] == "INVENTORY_FROZEN"
    cycle_id = admitted["cycle_id"]
    assert runner.main(["--admitted-workflow", "run"]) == 1
    capsys.readouterr()
    assert invoke(queued, "admit-fetch", monkeypatch, capsys, cycle=cycle_id)[1] == {**admitted, "recovered": True}
    original_save = State.save_cycle
    def cut(state, cycle):
        if cycle.get("ordinary_event_settlement_sha256"):
            raise RuntimeError("cut before terminal State")
        return original_save(state, cycle)
    with monkeypatch.context() as stop:
        stop.setattr(State, "save_cycle", cut)
        code, _, err = invoke(queued, "publish", monkeypatch, capsys, cycle=cycle_id)
        assert code == 1 and "cut before terminal State" in err
    coordinator = Coordinator(base=paths[0].parent / 'receiver')
    coordinator.store.set_queue_enabled(False)
    sink = ReceiverSink(coordinator)
    with closing(SQLiteRepository(paths[1], "sheet")) as local:
        record, = local.scrape_outcomes()
        assert OutcomeDelivery(local, sink).drain(outcome_id=record["outcome_id"]) == [
            {"outcome_id": record["outcome_id"], "disposition": "HELD_ORDINARY_EVENT_SETTLEMENT"}]
    code, terminal, _ = invoke(queued, "publish", monkeypatch, capsys, cycle=cycle_id)
    assert code == 0 and terminal["state"] == expected
    assert invoke(queued, "publish", monkeypatch, capsys, cycle=cycle_id)[:2] == (0, terminal)
    with closing(SQLiteRepository(paths[1], "sheet")) as local:
        delivery = OutcomeDelivery(local, sink)
        assert delivery.drain(outcome_id=record["outcome_id"]) == [
            {"outcome_id": record["outcome_id"], "disposition": "ACCEPTED"}]
        assert delivery.drain(outcome_id=record["outcome_id"]) == []
    assert sink.calls == 1
    assert coordinator.store.all() == []
    assert coordinator.store.held_repair_intake() == []
    assert not coordinator.store.queue_enabled()
    with (closing(SQLiteRepository(paths[1], 'sheet', readonly=True)) as local,
          coordinator.store.connect() as receiver):
        source_receipt, = local.db.execute(
            "SELECT receipt FROM scrape_outcome_delivery_receipts WHERE outcome_id=?",
            (record["outcome_id"],)).fetchone()
        sink_receipt, = receiver.execute(
            "SELECT receipt FROM scrape_outcome_delivery_receipts WHERE outcome_id=?",
            (record["outcome_id"],)).fetchone()
        assert source_receipt == sink_receipt
        assert json.loads(sink_receipt)["sink_status"] == "RECORDED_NO_REPAIR"
    expected_outcome = {"zero": "COMPLETE", "temporary": "TEMPORARY", "denied": "BLOCKED"}[kind]
    assert record["outcome"] == expected_outcome
    with closing(State(str(paths[0]), readonly=True)) as state:
        measured = state.cycle(cycle_id)["runtime_binding"]
    assert measured["source_manifest_sha256"] == "2c9aecf5382fc6d17b749f978ae0950baf2259ffc9c088bcbf6b664305d8f588"

    assert [call.kwargs["write"] for call in factory.call_args_list] == [False, False]
    assert not remote.service.batches
    provider.assert_called_once()
    broad.assert_not_called()

