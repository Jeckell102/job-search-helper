from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

import host_exchange
import pilot_restore_command as entry
from test_host_exchange import fixture as known_exchange_fixture, states


class FixtureRepository:
    def __init__(self, path, workbook, *, readonly):
        assert readonly
        self.path = path
        self.spreadsheet_id = workbook

    def close(self):
        pass


@pytest.fixture
def selected(tmp_path, monkeypatch):
    bundle = tmp_path / "capsule"
    bundle.mkdir(mode=0o700)
    project = tmp_path / "checkout"
    project.mkdir()
    state = project / ".state"
    state.mkdir()
    for name in entry.TOOLS:
        (bundle / name).write_text(name)
    for name in ("pilot_restoration.py", "host_exchange.py", "installer.py", "gate.py"):
        (bundle / name).write_bytes(Path(entry.__file__).with_name(name).read_bytes())
    (bundle / "controller.py").write_text(
        "from contextlib import contextmanager\n"
        "from pathlib import Path\n"
        "class Controller:\n"
        "    def __init__(self, bundle):\n"
        "        self.project = bundle.parent / 'checkout'\n"
        "        self.backend = 'sqlite'\n"
        "        self.marker = self.project / '.state/integration-release-journal.json'\n"
        "    @contextmanager\n"
        "    def restoration_terminal(self):\n"
        "        yield {'source': 'INSTALLED', 'maintenance_id': 'fixture'}\n"
    )
    (bundle / "retained_pilot_receiver.py").write_text(
        "def verify_pilot_delivery(proof, receiver):\n"
        "    return {'application': proof, 'receiver': receiver}\n"
    )
    (bundle / "retained_pilot_terminal.py").write_text(
        "def verify_retained_pilot_terminal(local, *, runtime_binding, **selection):\n"
        "    return {'runtime': runtime_binding, 'pilot': selection, 'path': str(local.path)}\n",
    )
    bootstrap = project / "release_admission_bootstrap.py"
    bootstrap.write_text(
        "from pathlib import Path\n"
        "def _load_environment(path):\n"
        "    pass\n"
        "def _validate_runtime(project, state_root):\n"
        "    return {'state': 'NO_RELEASE'}\n"
        "def _retained_operator_sqlite_layout(project, state, backend):\n"
        "    return {'jobs': {'path': str(state.with_name('jobs.sqlite3'))}}\n",
        encoding="utf-8",
    )
    with bootstrap.open("a", encoding="utf-8") as stream:
        stream.write("def _project_path(project, value):\n    return project / Path(value)\n")
    monkeypatch.setitem(sys.modules, "controller", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "job_search_helper.sqlite_repository",
                        SimpleNamespace(SQLiteRepository=FixtureRepository))
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setattr(sys, "prefix", str(project / ".venv"))
    monkeypatch.setattr(sys, "executable", str(project / ".venv/bin/python"))
    monkeypatch.delenv("STATE_DB_FILE", raising=False)
    monkeypatch.setenv("SPREADSHEET_ID", "fixture-sheet")
    monkeypatch.setattr(host_exchange, "FIXTURE_BASE", bundle / "fixtures")
    with contextmanager(known_exchange_fixture.__wrapped__)() as (exchange, _):
        exchange.prepare()
        exchange.close()
        selection = {
            "schema": entry.SCHEMA, "tools": {name: sha256((bundle / name).read_bytes()).hexdigest()
                                            for name in entry.TOOLS},
            "project": str(project), "interpreter": sys.executable,
            "bootstrap_sha256": sha256(bootstrap.read_bytes()).hexdigest(),
            "exchange_policy": str(exchange.policy_path), "exchange_policy_sha256": exchange.approved_sha256,
            "receiver_database": str(tmp_path / "receiver/tasks.sqlite3"),
            "workbook_id_sha256": sha256(b"fixture-sheet").hexdigest(),
            "pilot": {"request_sha256": "a" * 64, "reservation_digest": "b" * 64, "source_revision": "c" * 64,
                      "company_event_id": "CEV-" + "c" * 32, "company_id": "COMP-0001",
                      "blocking_cycle_id": "CYC-ABCDEF123456"},
        }
        yield selection, bundle, exchange


def test_exact_observation_and_explicit_approval_restore(selected):
    selection, bundle, exchange = selected
    observation = entry.approved_command(selection, bundle)
    assert observation["pilot"]["selection_sha256"] == sha256(entry.canonical(selection)).hexdigest()
    assert observation["pilot"]["application"]["pilot"] == selection["pilot"]
    assert observation["pilot"]["application"]["runtime"] == {"state": "NO_RELEASE"}
    assert Path(observation["pilot"]["application"]["path"]).name == "jobs.sqlite3"
    assert states(exchange) == [False, False, False]
    approval = entry.canonical(observation)
    result = entry.approved_command(selection, bundle, approval, sha256(approval).hexdigest())
    assert result["phase"] == "restored"
    assert result["terminal_proof_sha256"] == sha256(approval).hexdigest()
    assert states(exchange) == [True, True, True]


def test_modified_approval_and_bundled_tool_are_held_before_restore(selected):
    selection, bundle, exchange = selected
    observation = entry.approved_command(selection, bundle)
    approval = entry.canonical(observation)
    with pytest.raises(ValueError, match="approved digest"):
        entry.approved_command(selection, bundle, approval + b" ", sha256(approval).hexdigest())
    (bundle / "controller.py").write_text("different bytes")
    with pytest.raises(ValueError, match="maintenance tool changed"):
        entry.approved_command(selection, bundle, approval, sha256(approval).hexdigest())
    assert states(exchange) == [False, False, False]


def test_selection_requires_canonical_bytes_and_private_mode(selected, tmp_path):
    selection, _, _ = selected
    path = tmp_path / "selection.json"
    data = entry.canonical(selection)
    path.write_bytes(data)
    path.chmod(0o600)
    assert entry.read_selection(path, sha256(data).hexdigest()) == selection
    path.write_bytes(data + b" ")
    with pytest.raises(ValueError, match="encoding"):
        entry.read_selection(path, sha256(data + b" ").hexdigest())
    path.chmod(0o644)
    with pytest.raises(ValueError, match="mode is unsafe"):
        entry.read_selection(path, sha256(data + b" ").hexdigest())
