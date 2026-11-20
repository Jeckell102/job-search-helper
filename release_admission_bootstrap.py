#!/usr/bin/env python3
"""Stable pre-import admission for normal scraper start/sync commands.

This file deliberately lives outside the integration-replaceable package and
uses only the Python standard library.  It owns the normal scraper lock before
the interpreter imports any Job Search Helper module, validates the terminal
release journal against the installed source/config/dependency trees, then
inherits that exact lock into the real runner process.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys


JOURNAL_SCHEMA = "integration-release-journal-v1"
TERMINAL_STATES = frozenset({"COMPLETE", "ROLLED_BACK"})


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def _digest(value):
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _metadata(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1:
        raise RuntimeError("Admission trees must contain ordinary single-link files")
    raw = path.read_bytes()
    return {"sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw),
            "mode": stat.S_IMODE(path.stat().st_mode)}


def _tree_digest(root, *, suffix=None):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise RuntimeError(f"Admission tree is missing or unsafe: {root}")
    values = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if "__pycache__" in relative.parts or path.suffix == ".pyc":
            continue
        if path.is_symlink():
            raise RuntimeError("Admission tree must not contain symlinks")
        if path.is_file() and (suffix is None or path.name.endswith(suffix)):
            values[relative.as_posix()] = _metadata(path)
    return _digest(values)


def source_tree_digest(project):
    return _tree_digest(Path(project) / "src/job_search_helper", suffix=(".py", ".json"))


def config_tree_digest(project):
    project = Path(project)
    root = Path(project) / ".state/integration-configs"
    if root.is_symlink():
        raise RuntimeError(f"Admission tree is missing or unsafe: {root}")
    values = {
        "integration-configs": _digest({}) if not root.exists() else _tree_digest(root),
    }
    for name in (".env", ".storage-backend", "title-blacklist.txt",
                 "title-review-list.txt"):
        path = project / name
        values[name] = _metadata(path) if path.exists() else None
    selected_environment = {
        name: os.environ.get(name)
        for name in (
            "JOB_STORAGE_BACKEND", "STATE_DB_FILE", "JOB_DB_FILE",
            "SPREADSHEET_ID", "EVIDENCE_ARCHIVES_FILE",
            "JOB_SCRAPER_CHROMIUM_EXECUTABLE",
            "COMPANY_RETAINED_KEY_ID",
            "COMPANY_RETAINED_ED25519_PUBLIC_KEY_BASE64",
        )
    }
    for name, default in (
        ("GOOGLE_CREDENTIALS_FILE", "credentials.json"),
        ("GOOGLE_TOKEN_READ_FILE", ".secrets/token-readonly.json"),
        ("GOOGLE_TOKEN_WRITE_FILE", ".secrets/token-write.json"),
    ):
        path = _project_path(project, os.environ.get(name, default))
        selected_environment[name] = str(path.relative_to(project) if path.is_relative_to(project) else path)
    values["effective-environment-sha256"] = _digest(selected_environment)
    return _digest(values)


def dependency_manifest_digest(project):
    """Measure actual installed bytes plus the project's dependency policy."""
    project = Path(project)
    values = {}
    for name in ("pyproject.toml", "requirements.txt", "requirements.lock",
                 "uv.lock", "poetry.lock", ".venv/pyvenv.cfg"):
        path = project / name
        if path.exists():
            values[name] = _metadata(path)
    for site in sorted((project / ".venv/lib").glob("python*/site-packages")):
        values[site.relative_to(project).as_posix() + "/<tree>"] = _tree_digest(site)
        for distribution in sorted(site.glob("*.dist-info")):
            for name in ("METADATA", "RECORD", "direct_url.json"):
                path = distribution / name
                if path.exists():
                    values[path.relative_to(project).as_posix()] = _metadata(path)
    if not values:
        raise RuntimeError("No measurable dependency manifest is installed")
    return _digest(values)


def _load_environment(path):
    if not path.exists():
        return
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise RuntimeError(f"Invalid .env entry on line {number}")
        name, value = (part.strip() for part in line.split("=", 1))
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise RuntimeError(f"Invalid .env variable on line {number}")
        if value.startswith(("'", '"')):
            if len(value) < 2 or value[-1] != value[0]:
                raise RuntimeError(f"Unclosed .env quotation on line {number}")
            value = value[1:-1]
        os.environ.setdefault(name, value)


def _read_object(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Cannot safely read release evidence: {path}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"Release evidence must be an object: {path}")
    return value


def _validate_runtime(project, state_root):
    journal_path = state_root / "integration-release-journal.json"
    measured = {
        "source_manifest_sha256": source_tree_digest(project),
        "config_sha256": config_tree_digest(project),
        "dependency_manifest_sha256": dependency_manifest_digest(project),
    }
    if not journal_path.exists():
        return {"state": "NO_RELEASE", **measured}
    journal = _read_object(journal_path)
    if journal.get("schema") != JOURNAL_SCHEMA or journal.get("state") not in TERMINAL_STATES:
        raise RuntimeError("Interrupted integration release blocks pre-import scraper admission")
    state = journal["state"]
    if state == "COMPLETE":
        binding = journal.get("release")
        if (not isinstance(binding, dict)
                or set(binding) != {"schema", "release_id", *measured}
                or binding.get("schema") != "integration-release-binding-v1"
                or binding.get("release_id") != journal.get("release_id")):
            raise RuntimeError("Completed release has no runtime binding")
        expected = {name: binding.get(name) for name in measured}
        record = Path(str(journal.get("record") or ""))
        receipt = _read_object(record / "receipt.json")
        if (receipt.get("state") != "COMPLETE"
                or receipt.get("release_id") != journal.get("release_id")
                or receipt.get("manifest_sha256") != journal.get("manifest_sha256")
                or receipt.get("release") != binding):
            raise RuntimeError("Completed release receipt does not match its journal")
    else:
        record = Path(str(journal.get("record") or ""))
        manifest = _read_object(record / "manifest.json")
        if _digest(manifest) != journal.get("manifest_sha256"):
            raise RuntimeError("Rollback manifest does not match its journal")
        rollback = _read_object(record / "rollback.json")
        expected_rollback = {
            "state": "ROLLED_BACK",
            "release_id": journal.get("release_id"),
            "manifest_sha256": journal.get("manifest_sha256"),
        }
        if rollback != expected_rollback:
            raise RuntimeError("Rollback receipt does not match its journal")
        expected = {
            "source_manifest_sha256": manifest.get("before_source_manifest_sha256"),
            "config_sha256": manifest.get("before_config_sha256"),
            "dependency_manifest_sha256": manifest.get("dependency_manifest_sha256"),
        }
    if measured != expected:
        raise RuntimeError("Installed runtime does not match the terminal release journal")
    return {"state": state, "release_id": journal.get("release_id"), **measured}


def _project_path(project, value):
    candidate = Path(value).expanduser()
    return candidate if candidate.is_absolute() else project / candidate


def admit_and_exec(project, arguments):
    project = Path(project).resolve()
    _load_environment(project / ".env")
    state = _project_path(project, os.environ.get("STATE_DB_FILE", ".state/state.db"))
    marker = project / ".storage-backend"
    default_backend = marker.read_text(encoding="utf-8").strip() if marker.exists() else "sheets"
    backend = os.environ.get("JOB_STORAGE_BACKEND", default_backend).strip().lower()
    if backend not in {"sqlite", "sheets"}:
        raise RuntimeError("JOB_STORAGE_BACKEND must be sqlite or sheets")
    lock_path = state.parent / ("scraper.lock" if backend == "sqlite" else "writer.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(f"Another scraper or release owns admission: {lock_path}") from exc
        runtime = _validate_runtime(project, state.parent)
        os.set_inheritable(descriptor, True)
        os.environ["JSH_SCRAPER_ADMISSION_FD"] = str(descriptor)
        os.environ["JSH_SCRAPER_ADMISSION_PATH"] = str(lock_path.resolve())
        os.environ["JSH_SCRAPER_RUNTIME_BINDING"] = _canonical(runtime)
        os.environ["PYTHONPATH"] = os.pathsep.join((str(project / "src"), str(project)))
        os.environ["PYTHONNOUSERSITE"] = "1"
        python = project / ".venv/bin/python"
        executable = str(python if python.is_file() and os.access(python, os.X_OK) else Path(sys.executable))
        module = "job_search_helper.runner"
        if arguments and arguments[0] == "--scan-worker":
            module, arguments = "job_search_helper.scrape_worker", arguments[1:]
        elif arguments and arguments[0] == "--pipeline":
            module, arguments = "job_search_helper.scrape_first_pass", arguments[1:]
        # Release source identity excludes interpreter caches. Bypass existing
        # cache entries even when a replacement preserves size and mtime.
        os.execve(executable, [executable, "-P", "-B", "-X", "pycache_prefix=/dev/null",
                               "-m", module, *arguments], os.environ)
    finally:
        os.close(descriptor)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    project = Path(__file__).resolve().parent
    try:
        admit_and_exec(project, argv)
    except Exception as exc:
        print(f"Startup admission failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
