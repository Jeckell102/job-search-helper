"""Workspace-relative settings for the local database workflow."""
from __future__ import annotations

from dataclasses import dataclass
import math
import os
from pathlib import Path
from typing import Mapping
import tomllib


@dataclass(frozen=True)
class Settings:
    workspace: Path
    database: Path
    workers: int = 1
    timeout_seconds: float = 25.0
    host_interval_seconds: float = 0.4
    retry_attempts: int = 3
    missing_threshold: int = 2
    browser_enabled: bool = False


def workspace_path(workspace: Path, value: str | Path) -> Path:
    path = Path(value).expanduser()
    return (path if path.is_absolute() else workspace / path).resolve()


def load_settings(*, workspace: str | Path | None = None,
                  database: str | Path | None = None,
                  settings_file: str | Path | None = None,
                  environ: Mapping[str, str] | None = None) -> Settings:
    """Resolve CLI > JSH_* environment > TOML > defaults, without writing files."""
    env = os.environ if environ is None else environ
    root = Path(workspace or env.get("JSH_WORKSPACE") or Path.cwd()).expanduser().resolve()
    explicit = settings_file if settings_file is not None else env.get("JSH_SETTINGS")
    path = workspace_path(root, explicit if explicit is not None else "config/settings.toml")
    data = {}
    if explicit is not None or path.exists():
        try:
            with path.open("rb") as handle:
                data = tomllib.load(handle)
        except (OSError, ValueError) as exc:
            raise ValueError(f"Cannot read settings {path}: {exc}") from exc
    _keys(data, {"storage", "scan"}, "settings")
    storage, scan = data.get("storage", {}), data.get("scan", {})
    _keys(storage, {"database"}, "storage")
    _keys(scan, {"workers", "timeout_seconds", "host_interval_seconds", "retry_attempts",
                 "missing_threshold", "browser_enabled"}, "scan")
    stored_database = storage.get("database", "data/job-search-helper.sqlite3")
    if not isinstance(stored_database, str) or not stored_database.strip():
        raise ValueError("storage.database must be a nonempty path")
    db = database if database is not None else env.get("JSH_DATABASE", stored_database)
    if not str(db).strip():
        raise ValueError("Database path must not be empty")
    defaults = Settings(root, workspace_path(root, db))
    values = {key: scan.get(key, getattr(defaults, key)) for key in (
        "workers", "timeout_seconds", "host_interval_seconds", "retry_attempts",
        "missing_threshold", "browser_enabled",
    )}
    for key, minimum, maximum in (
        ("workers", 1, 5), ("retry_attempts", 1, 5), ("missing_threshold", 1, 100),
    ):
        if type(values[key]) is not int or not minimum <= values[key] <= maximum:
            raise ValueError(f"scan.{key} must be an integer from {minimum} to {maximum}")
    for key, minimum, maximum in (
        ("timeout_seconds", 1, 300), ("host_interval_seconds", 0, 60),
    ):
        value = values[key]
        if type(value) not in (int, float) or not math.isfinite(value) or not minimum <= value <= maximum:
            raise ValueError(f"scan.{key} must be a number from {minimum} to {maximum}")
    if type(values["browser_enabled"]) is not bool:
        raise ValueError("scan.browser_enabled must be true or false")
    return Settings(root, defaults.database, **values)


def _keys(value: object, allowed: set[str], section: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{section} must be a TOML table")
    unknown = value.keys() - allowed
    if unknown:
        raise ValueError(f"Unknown {section} setting: {', '.join(sorted(unknown))}")
