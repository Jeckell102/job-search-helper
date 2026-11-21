from hashlib import sha256
from pathlib import Path
import sqlite3

import pytest

import run_native_two_tool_forward as launch


def test_live_source_check_rejects_a_shadowed_store(tmp_path, monkeypatch):
    tools = tmp_path / 'tools'
    tools.mkdir()
    monkeypatch.setattr(launch, 'PROJECT', tmp_path)
    monkeypatch.setattr(launch, 'TOOLS', tools)
    coordinator = tools / 'coordinator.py'
    coordinator.write_text('from coordinator_store import Store\n')
    monkeypatch.setattr(launch, 'COORDINATOR', sha256(coordinator.read_bytes()).hexdigest())
    store = tools / 'coordinator_store.py'
    store.write_text('class Store: pass\n')
    store.chmod(0o644)
    assert launch.verify_source_selection({'tools/coordinator_store.py': 0o644}) == {
        'tools/coordinator_store.py': sha256(store.read_bytes()).hexdigest(),
    }
    competing = tools / 'coordinator_store'
    competing.mkdir()
    (competing / '__init__.py').write_text('class Store: pass\n')
    with pytest.raises(ValueError, match='Unexpected import source'):
        launch.verify_source_selection({'tools/coordinator_store.py': 0o644})


def test_readback_preserves_wal_sidecars_and_rejects_unsettled_snapshot(tmp_path, monkeypatch):
    database = tmp_path / 'tasks.sqlite3'
    monkeypatch.setattr(launch, 'DATABASE', database)
    with sqlite3.connect(database) as db:
        db.executescript('''PRAGMA journal_mode=wal;
        CREATE TABLE settings (key, value);
        INSERT INTO settings VALUES ('pilot_task', 'null'), ('queue_enabled', 'false'),
                                    ('campaign_enabled', 'false'), ('autopilot_enabled', 'false');
        CREATE TABLE tasks (id, state);
        CREATE TABLE inference_receipts (request_id, status, data, task);
        ''')
        db.execute('INSERT INTO tasks VALUES (?,?)', (launch.TASK, '{"status":"PAUSED_ERROR"}'))
        db.execute('INSERT INTO inference_receipts VALUES (?,?,?,?)',
                   (launch.INFERENCE, 'COMPLETED', '{}', launch.TASK))
    db.close()
    assert launch.retained_task()[-1] == 0
    assert sorted(path.name for path in tmp_path.iterdir()) == [database.name]
    pending = Path(str(database) + '-wal')
    pending.write_bytes(b'not a settled snapshot')
    with pytest.raises(ValueError, match='unsettled WAL'):
        launch.retained_task()
