"""Retirement blocks old ownership but never blocks an unrelated fresh start."""
import pytest

from job_search_helper.engine import Engine
from job_search_helper.exact_cycle_sync import publish_exact_cycle
from job_search_helper.engine import State
from job_search_helper.runner import (_readonly_named_exact_preflight, active_inbox_cycles,
                                      resolve_cycle, validate_exact_sync_cycle)
from job_search_helper import runner
import job_search_helper.retained_cycle_retirement_control as control


RETIRED = "CYC-retired"


def test_direct_resume_and_exact_publish_stop_before_any_owner_work(monkeypatch):
    def stop(_state, cycle_id):
        assert cycle_id == RETIRED
        raise ValueError("This saved scrape was retired. Start a fresh request to scrape again.")

    monkeypatch.setattr(control, "assert_cycle_not_retired", stop)
    engine = Engine.__new__(Engine)
    engine.state = object()
    with pytest.raises(ValueError, match="saved scrape was retired"):
        Engine.resume(engine, RETIRED, retry_blocked=True)
    with pytest.raises(ValueError, match="saved scrape was retired"):
        Engine.resume_parallel(engine, RETIRED, retry_blocked=True)
    with pytest.raises(ValueError, match="saved scrape was retired"):
        publish_exact_cycle(None, RETIRED, None, company_ids=["COMP-1"], state=object(),
                            company_guard=lambda *_: None)


def test_fresh_start_ignores_verified_retired_cycle_when_checking_active_work(monkeypatch):
    class State:
        def cycles(self):
            return [{"id": RETIRED, "status": "In Progress"}]

    class Repo:
        def validate_schema(self):
            pass
        def read_columns(self, *_args):
            return []

    monkeypatch.setattr(control, "verified_retired_cycle_ids", lambda state: {RETIRED})
    engine = Engine.__new__(Engine)
    engine.state, engine.repo, engine.runtime_binding = State(), Repo(), None
    engine._company_rows = lambda: []
    with pytest.raises(ValueError, match="No active companies selected"):
        Engine.start_cycle(engine)


def test_named_exact_preflight_stops_before_inventory_or_google_setup(tmp_path, monkeypatch):
    state_path = tmp_path / "state.db"
    State(state_path).close()
    monkeypatch.setattr(control, "assert_cycle_not_retired",
                        lambda _state, _cycle: (_ for _ in ()).throw(ValueError("retired")))
    with pytest.raises(ValueError, match="retired"):
        _readonly_named_exact_preflight(state_path, tmp_path / "missing-inbox.sqlite3",
                                       RETIRED, ["COMP-1"])


def test_active_and_resume_selection_exclude_verified_retirement(monkeypatch):
    class State:
        def cycles(self):
            return [{"id": RETIRED, "status": "In Progress", "started_at": "z"},
                    {"id": "CYC-live", "status": "In Progress", "started_at": "a"}]

    class Inbox:
        def cycles(self, **_kwargs):
            return [RETIRED, "CYC-live"]

    class Repo:
        def read(self, _tab):
            return []

    monkeypatch.setattr(control, "verified_retired_cycle_ids", lambda _state: {RETIRED})
    state = State()
    assert active_inbox_cycles(Inbox(), state) == ["CYC-live"]
    engine = type("Engine", (), {"runtime_binding": None})()
    assert resolve_cycle(engine, state, Repo())[0] == "CYC-live"


def test_validate_exact_sync_rejects_retired_before_inbox_open(tmp_path, monkeypatch):
    state_path = tmp_path / "state.db"
    state = State(state_path); state.save_cycle({"id": RETIRED, "status": "In Progress", "companies": {}}); state.close()
    monkeypatch.setattr(control, "assert_cycle_not_retired",
                        lambda _state, _cycle: (_ for _ in ()).throw(ValueError("retired")))
    with pytest.raises(ValueError, match="retired"):
        validate_exact_sync_cycle(state_path, RETIRED)


def test_retirement_cli_requires_apply_and_never_prints_private_archive(monkeypatch, tmp_path, capsys):
    args = ["retire-interrupted-cycle", "--cycle-id", RETIRED, "--archive-root", str(tmp_path),
            "--archive-scope-sha256", "a" * 64, "--reason", "owner retired saved work"]
    assert runner.scrape_main(args) == 1
    assert "apply-only" in capsys.readouterr().err
    state_path = tmp_path / "state.db"
    state_path.touch(); (tmp_path / "jobs.sqlite3").touch()
    monkeypatch.setattr(runner, "_load_environment", lambda: None)
    monkeypatch.setattr(runner, "state_path", lambda: state_path)
    monkeypatch.setattr(runner.helper_cli, "job_database_path", lambda: tmp_path / "jobs.sqlite3")
    monkeypatch.setattr(control, "retire_saved_cycle", lambda *_a, **_kw: {
        "cycle_id": RETIRED, "state": "RETIRED_UNPUBLISHED", "published": False,
        "retired": True, "archive_scope_sha256": "a" * 64, "recorded_at": "now",
        "archive_root": "/private/path", "saved_plan": {"private": "payload"},
    })
    assert runner.scrape_main([*args, "--apply"]) == 0
    text = capsys.readouterr().out
    assert "/private/path" not in text and "private" not in text
