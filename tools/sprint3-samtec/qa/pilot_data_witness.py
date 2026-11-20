"""Read-only fingerprints to check the Samtec pilot's local record boundary."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import sys


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def snapshot(root):
    path = root / "jobs.sqlite3"
    counts = {}
    outside = {}
    selected = {}
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as jobs:
        jobs.execute("PRAGMA query_only=ON")
        jobs.execute("BEGIN")
        for tab, number, data, policies in jobs.execute(
                "SELECT tab,row_id,data,policies FROM records ORDER BY tab,row_id"):
            if tab in {"Job History", "Job Evidence"}:
                row = json.loads(data)
                if str(row.get("Company", "")).strip().casefold() == "samtec":
                    selected.setdefault(tab, {})[number] = {
                        "identity": digest([row.get("Job Key"), row.get("Source Hash")]),
                        "row": digest([data, policies]),
                        "closed": row.get("Job Status") == "Closed",
                        "salary": digest(row.get("Salary / Range", "")),
                        "manual_choice": digest(row.get("Added to Opportunities?", "")),
                    }
                    continue
            counts[tab] = counts.get(tab, 0) + 1
            outside.setdefault(tab, hashlib.sha256()).update(encoded([number, data, policies]) + b"\n")
        dirty = jobs.execute("SELECT count(*) FROM dirty").fetchone()[0]
    return {"outside": {tab: {"count": counts[tab], "sha256": checksum.hexdigest()}
                        for tab, checksum in outside.items()},
            "selected": selected, "dirty_count": dirty}


if __name__ == "__main__":
    print(json.dumps(snapshot(Path(sys.argv[1]).resolve()), indent=2, sort_keys=True))
