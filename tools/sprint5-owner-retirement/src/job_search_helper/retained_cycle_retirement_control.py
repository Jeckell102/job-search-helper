"""Record an explicit owner retirement without mutating saved or published work."""
from __future__ import annotations

from contextlib import ExitStack, closing
import json
from pathlib import Path
import sqlite3

from .retained_cycle_retirement import (
    VERSION, _STORES, _digest, _original_rows, _read_scoped, verify_retirement_archive,
)


_TABLE = "retained_cycle_retirements"


def _has_table(conn):
    return isinstance(conn, sqlite3.Connection) and bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (_TABLE,),
    ).fetchone())


def _read(conn, cycle_id):
    if not _has_table(conn):
        return None
    row = conn.execute(f"SELECT record,sha256 FROM {_TABLE} WHERE cycle=?", (cycle_id,)).fetchone()
    if row is None:
        return None
    record = json.loads(row[0])
    if (not isinstance(record, dict) or record.get("version") != VERSION
            or record.get("cycle_id") != cycle_id or record.get("state") != "RETIRED_UNPUBLISHED"
            or _digest(record) != row[1]):
        raise ValueError("Retirement control is corrupt. Keep the older run held.")
    return record



def assert_cycle_not_retired(state, cycle_id):
    """Refuse ownership even if an already recorded archive becomes unavailable."""
    _require_not_retired(getattr(state, "connection", None), cycle_id)


def _require_not_retired(conn, cycle_id):
    if _read(conn, cycle_id) is not None:
        raise ValueError("This saved scrape was retired. Start a fresh request to scrape again.")



def assert_cycle_path_not_retired(state_path, cycle_id):
    """Check the file-backed authority before opening a mutation factory."""
    path = Path(state_path).resolve()
    if path.exists():
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
            _require_not_retired(conn, cycle_id)


def verified_retired_cycle_ids(state):
    """Exclude only owner-retired cycles with intact archive and original controls."""
    conn = getattr(state, "connection", None)
    if not _has_table(conn):
        return set()
    live = Path(state.path).resolve(strict=True)
    if live.name != "state.db":
        raise ValueError("Retirement control is bound to the original State database.")
    retired = set()
    for (cycle_id,) in conn.execute(f"SELECT cycle FROM {_TABLE} ORDER BY cycle"):
        record = _read(conn, cycle_id)
        original = conn.execute("SELECT data FROM cycles WHERE id=?", (cycle_id,)).fetchone()
        if (original is None or _digest(original[0]) != record["original_state_sha256"]
                or record.get("published") is not False):
            raise ValueError("Retired cycle differs from its preserved original State.")
        archive = Path(record["archive_root"]).resolve(strict=True)
        if any((archive / name).samefile(live.parent / name) for name in _STORES):
            raise ValueError("Retirement archive and live State must remain separate.")
        archived = _read_scoped(archive, cycle_id)
        if (_digest(archived) != record["archive_scope_sha256"]
                or _digest(archived["mirror"]) != record["original_mirror_sha256"]):
            raise ValueError("Retirement archive no longer matches the approved scope.")
        with ExitStack() as stack:
            jobs, inbox = [
                stack.enter_context(closing(sqlite3.connect(
                    (live.parent / name).as_uri() + "?mode=ro", uri=True,
                ))) for name in _STORES[1:]
            ]
            for db in (jobs, inbox):
                db.execute("PRAGMA query_only=ON")
                db.execute("BEGIN")
            current = _original_rows(conn, jobs, inbox, cycle_id, require_clean=False)
        if current != archived:
            raise ValueError("Retired saved work differs from its approved archive.")
        retired.add(cycle_id)
    return retired


def _record_retirement(state_path, proof, archive_root, *, reason, timestamp):
    cycle_id = proof["cycle_id"]
    path = Path(state_path).resolve(strict=True)
    record = {**proof, "retired": True, "state": "RETIRED_UNPUBLISHED",
              "reason": reason, "recorded_at": timestamp, "archive_root": str(archive_root)}
    with closing(sqlite3.connect(path.as_uri() + "?mode=rw", uri=True)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        original = conn.execute("SELECT data FROM cycles WHERE id=?", (cycle_id,)).fetchone()
        if original is None or _digest(original[0]) != proof["original_state_sha256"]:
            raise ValueError("Original saved cycle changed before recording retirement.")
        retained = _read(conn, cycle_id)
        if retained is not None:
            original_approval = {k: v for k, v in retained.items() if k != "recorded_at"}
            replay = {k: v for k, v in record.items() if k != "recorded_at"}
            if original_approval != replay:
                raise ValueError("Archived retirement authority changed.")
            return retained
        conn.execute(f"""CREATE TABLE IF NOT EXISTS {_TABLE} (
            cycle TEXT PRIMARY KEY, record TEXT NOT NULL, sha256 TEXT NOT NULL
        )""")
        conn.execute(
            f"INSERT INTO {_TABLE} VALUES (?,?,?)",
            (cycle_id, json.dumps(record, ensure_ascii=False, sort_keys=True), _digest(record)),
        )
    return record


def retire_saved_cycle(live_root, archive_root, cycle_id, *, archive_scope_sha256, reason):
    """Write only a retirement record, under normal exclusion, after exact archive proof.

    The runtime must support this distinct disposition everywhere it can own or
    publish a cycle before this command is enabled on a live installation.
    """
    if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 256:
        raise ValueError("Provide a short reason for this exact retirement.")
    from .cli import review_lock_name, scraper_lock_name, storage_backend, writer_lock
    from .integration_release import assert_release_settled
    from .retained_work_runner import assert_normal_lifecycle_not_held
    from .sqlite_repository import timestamp

    if storage_backend() != "sqlite":
        raise ValueError("Retirement requires the installed single-writer SQLite backend.")
    root, backup = (Path(p).resolve(strict=True) for p in (live_root, archive_root))
    with (writer_lock(root / scraper_lock_name()), writer_lock(root / "writer.lock"),
          writer_lock(root / review_lock_name())):
        assert_release_settled(root)
        assert_normal_lifecycle_not_held(root, root / "jobs.sqlite3")
        proof = verify_retirement_archive(root, backup, cycle_id)
        if proof["archive_scope_sha256"] != archive_scope_sha256:
            raise ValueError("The verified archive differs from the reviewed retirement scope.")
        return _record_retirement(root / "state.db", proof, backup,
                                  reason=reason.strip(), timestamp=timestamp())
