"""Local SQLite connections, checked migrations, transactions and backups."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
from importlib.resources import files
import os
from pathlib import Path
import sqlite3
import tempfile
from typing import Iterator

from .models import new_id, utc_now


APPLICATION_ID = 0x4A534831
MIGRATIONS = ("001_foundation.sql", "002_scan_ingestion.sql", "003_local_screening.sql")
SCHEMA_VERSION = len(MIGRATIONS)


class DatabaseError(ValueError):
    """An incompatible or unrecognized database must remain untouched."""


def _migration(number: int) -> tuple[str, str]:
    sql = files("job_search_helper.migrations").joinpath(MIGRATIONS[number - 1]).read_text(encoding="utf-8")
    return sql, hashlib.sha256(sql.encode("utf-8")).hexdigest()


def _connect(path: Path, *, readonly: bool = False) -> sqlite3.Connection:
    connection = sqlite3.connect(path.as_uri() + ("?mode=ro" if readonly else "?mode=rw"),
                                 uri=True, timeout=5, isolation_level=None)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
            raise DatabaseError("This SQLite runtime cannot enforce foreign keys")
        if readonly:
            connection.execute("PRAGMA query_only = ON")
    except BaseException:
        connection.close()
        raise
    return connection


@contextmanager
def transaction(connection: sqlite3.Connection, *, immediate: bool = True) -> Iterator[None]:
    """Nest writes with savepoints; immediate=False also supports read snapshots."""
    nested = connection.in_transaction
    savepoint = "sp_" + new_id().replace("-", "")
    connection.execute(f"SAVEPOINT {savepoint}" if nested else "BEGIN IMMEDIATE" if immediate else "BEGIN")
    try:
        yield
        connection.execute(f"RELEASE {savepoint}" if nested else "COMMIT")
    except BaseException:
        if connection.in_transaction:
            if nested:
                connection.execute(f"ROLLBACK TO {savepoint}")
                connection.execute(f"RELEASE {savepoint}")
            else:
                connection.rollback()
        raise


def _verify_schema(connection: sqlite3.Connection, *, allow_older: bool = False) -> int:
    if connection.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID:
        raise DatabaseError("Not a Job Search Helper catalog; use a separate database for the local workflow")
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version > SCHEMA_VERSION:
        raise DatabaseError(f"Database schema {version} is newer than supported schema {SCHEMA_VERSION}")
    rows = connection.execute("SELECT version, name, checksum FROM schema_migrations ORDER BY version").fetchall()
    if [row["version"] for row in rows] != list(range(1, version + 1)):
        raise DatabaseError("Database migration history is inconsistent")
    for row in rows:
        _, checksum = _migration(row["version"])
        if row["name"] != MIGRATIONS[row["version"] - 1] or row["checksum"] != checksum:
            raise DatabaseError(f"Migration {row['version']} checksum does not match this installation")
    if not allow_older and version != SCHEMA_VERSION:
        raise DatabaseError("Database needs an upgrade; run job-search-helper db migrate")
    return version


def _configure_writer(connection: sqlite3.Connection) -> None:
    # Use rollback journaling and one writer, including on older runtimes.
    if connection.execute("PRAGMA journal_mode").fetchone()[0] != "delete":
        raise DatabaseError("Local catalog requires DELETE journal mode in this release")
    connection.execute("PRAGMA synchronous = FULL")


def _execute_migration(connection: sqlite3.Connection, sql: str) -> None:
    # executescript commits any open transaction. Parse complete SQL statements
    # instead so schema, migration ledger and version advance atomically.
    statement = ""
    for line in sql.splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            connection.execute(statement)
            statement = ""
    if statement.strip():
        raise DatabaseError("Migration contains an incomplete SQL statement")


class Database:
    def __init__(self, path: str | Path, *, readonly: bool = False):
        self.path = Path(path).expanduser().resolve()
        self.connection = _connect(self.path, readonly=readonly)
        try:
            _verify_schema(self.connection)
            if not readonly:
                _configure_writer(self.connection)
        except BaseException:
            self.connection.close()
            raise

    @classmethod
    def initialize(cls, path: str | Path) -> Database:
        """Create a private catalog, or validate an already initialized catalog."""
        target = Path(path).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            return cls(target)
        else:
            os.close(descriptor)
        connection = None
        try:
            connection = _connect(target)
            _configure_writer(connection)
            with transaction(connection):
                connection.execute(f"PRAGMA application_id = {APPLICATION_ID}")
                connection.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, "
                                   "name TEXT NOT NULL, checksum TEXT NOT NULL, applied_at TEXT NOT NULL)")
                _apply_migrations(connection, 0)
                connection.execute("INSERT INTO app_metadata VALUES ('database_id', ?)", (new_id(),))
        except BaseException:
            if connection is not None:
                connection.close()
            target.unlink(missing_ok=True)
            raise
        else:
            connection.close()
        return cls(target)

    @classmethod
    def migrate(cls, path: str | Path) -> Database:
        """Upgrade a recognized database; never adopt an old recovery database."""
        target = Path(path).expanduser().resolve()
        connection = _connect(target)
        try:
            _configure_writer(connection)
            with transaction(connection):
                version = _verify_schema(connection, allow_older=True)
                _apply_migrations(connection, version)
        finally:
            connection.close()
        return cls(target)

    def transaction(self, *, immediate: bool = True):
        return transaction(self.connection, immediate=immediate)

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> Database:
        return self

    def __exit__(self, *_args) -> None:
        self.close()

    @property
    def database_id(self) -> str:
        row = self.connection.execute("SELECT value FROM app_metadata WHERE key = 'database_id'").fetchone()
        if row is None or not row[0]:
            raise DatabaseError("Catalog has no database instance ID")
        return row[0]

    def check(self) -> dict:
        _verify_schema(self.connection)
        integrity = [row[0] for row in self.connection.execute("PRAGMA integrity_check")]
        foreign_keys = list(self.connection.execute("PRAGMA foreign_key_check"))
        if integrity != ["ok"] or foreign_keys:
            raise DatabaseError("Database integrity check failed; preserve this file and inspect a backup")
        counts = {table: self.connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                  for table in ("companies", "jobs", "applications", "scan_cycles")}
        recovery = {state: self.connection.execute(
            "SELECT count(*) FROM inventory_batches WHERE apply_state=?", (state,)).fetchone()[0]
                    for state in ("pending", "quarantined")}
        recovery["unfinished_cycles"] = self.connection.execute(
            "SELECT count(*) FROM scan_cycles WHERE status IN ('running', 'interrupted')").fetchone()[0]
        return {"ok": True, "database": str(self.path), "database_id": self.database_id,
                "schema_version": SCHEMA_VERSION, "sqlite_version": sqlite3.sqlite_version,
                "journal_mode": self.connection.execute("PRAGMA journal_mode").fetchone()[0],
                "counts": counts, "scan_recovery": recovery}

    def backup(self, destination: str | Path) -> Path:
        """Publish a verified SQLite backup without replacing an existing file."""
        if self.connection.in_transaction:
            raise DatabaseError("Finish the current transaction before making a backup")
        target = Path(destination).expanduser().absolute()
        if target.exists() or target.is_symlink():
            raise FileExistsError(f"Backup destination already exists: {target}")
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor, name = tempfile.mkstemp(prefix=".jsh-backup-", suffix=".sqlite3", dir=target.parent)
        temporary = Path(name)
        os.close(descriptor)
        try:
            output = sqlite3.connect(temporary)
            try:
                self.connection.backup(output)
            finally:
                output.close()
            with Database(temporary, readonly=True) as copy:
                copy.check()
                if copy.database_id != self.database_id:
                    raise DatabaseError("Backup database identity does not match")
            with temporary.open("rb") as handle:
                os.fsync(handle.fileno())
            # Both files are in the same directory. link is atomic and refuses
            # an existing destination even if another process creates it now.
            os.link(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        return target


def _apply_migrations(connection: sqlite3.Connection, current: int) -> None:
    for version in range(current + 1, SCHEMA_VERSION + 1):
        sql, checksum = _migration(version)
        _execute_migration(connection, sql)
        connection.execute("INSERT INTO schema_migrations VALUES (?, ?, ?, ?)",
                           (version, MIGRATIONS[version - 1], checksum, utc_now()))
        connection.execute(f"PRAGMA user_version = {version}")
