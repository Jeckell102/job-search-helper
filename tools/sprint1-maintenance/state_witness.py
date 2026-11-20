"""Read-only Sprint 1 witness for protected production data and control files."""
import hashlib
import json
from pathlib import Path
import sys


def fingerprint(path):
    try:
        with path.open("rb") as stream:
            start = path.stat()
            checksum = hashlib.file_digest(stream, "sha256").hexdigest()
            end = path.stat()
    except FileNotFoundError:
        if path.exists():
            raise
        return None
    if (start.st_ino, start.st_size, start.st_mtime_ns) != (
        end.st_ino, end.st_size, end.st_mtime_ns
    ):
        raise RuntimeError(f"Concurrent change while reading {path.name}")
    return {"size": end.st_size, "sha256": checksum}


def witness(project):
    state = project / ".state"
    database_names = ("state.db", "jobs.sqlite3", "inventories.sqlite3")
    paths = [state / name for name in database_names]
    paths += [state / (name + "-wal") for name in database_names]
    paths += [state / name for name in ("next-scan.json", "integration-release-journal.json",
                                        "company-intake-dispatch.sqlite3", "scrape-first-pass/latest.json")]
    paths += sorted((state / "operator-company-requests").rglob("*.json"))
    return {str(p.relative_to(state)): fingerprint(p) for p in paths}


if __name__ == "__main__":
    print(json.dumps(witness(Path(sys.argv[1])), sort_keys=True, indent=2))
