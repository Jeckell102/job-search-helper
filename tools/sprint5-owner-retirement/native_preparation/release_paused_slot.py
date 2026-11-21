"""Release one known paused pilot slot through the installed coordinator CLI."""
import argparse
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import subprocess
import sys


ROOT = Path("/home/chris/job-search-helper_old/dev/wrapper-coder")
DATABASE = ROOT / "tasks/tasks.sqlite3"
CLI = ROOT / "tools/wrapper_task.py"
TASK = "WRAP-9b6f2e2274"
FLAGS = ("autopilot_enabled", "campaign_enabled", "queue_enabled")
EXPECTED_TASK_SHA = "534608748805c862c691c1c7d613ba21fadf5e63433cb5f4da3200634c401fa8"


def snapshot():
    paths = DATABASE, DATABASE.with_name(DATABASE.name + "-wal"), DATABASE.with_name(DATABASE.name + "-journal")

    def identities():
        result = []
        for index, path in enumerate(paths):
            try:
                st = path.stat()
                if index and st.st_size:
                    raise RuntimeError("Coordinator has SQLite changes in flight")
                result.append((st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns))
            except FileNotFoundError:
                if not index:
                    raise
                result.append(None)
        return result

    before = identities()
    with closing(sqlite3.connect(DATABASE.as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
        db.execute("PRAGMA query_only=ON")
        control = dict(db.execute("SELECT key,value FROM settings"))
        saved, = db.execute("SELECT state FROM tasks WHERE id=?", (TASK,)).fetchone()
        receipts = db.execute(
            "SELECT request_id,status,data FROM inference_receipts WHERE task=? ORDER BY request_id", (TASK,),
        ).fetchall()
        inflight = db.execute(
            "SELECT count(*) FROM inference_receipts WHERE status NOT IN ('COMPLETED','RESPONSE_DROPPED','FAILED','CANCELLED')"
        ).fetchone()[0]
        running = db.execute(
            "SELECT count(*) FROM tasks WHERE json_extract(state,'$.status') IN ('QUEUED','RUNNING','PAUSING') "
            "OR json_extract(state,'$.inference_session_open')=1"
        ).fetchone()[0]
    if identities() != before:
        raise RuntimeError("Coordinator changed while reading the snapshot")
    if (any(control.get(flag) != "false" for flag in FLAGS) or inflight or running
            or json.loads(saved).get("status") != "PAUSED_BLOCKED" or not receipts
            or sha256(saved.encode()).hexdigest() != EXPECTED_TASK_SHA):
        raise RuntimeError("The paused task or closed coordinator controls no longer match")
    return {"pilot": json.loads(control.get("pilot_task", "null")), "task_sha256": EXPECTED_TASK_SHA,
            "receipt_count": len(receipts),
            "receipts_sha256": sha256(json.dumps(receipts, separators=(",", ":")).encode()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    before = snapshot()
    if before["pilot"] != TASK:
        raise RuntimeError("The known paused task no longer owns the pilot slot")
    if not args.apply:
        print(json.dumps({"status": "READY", **before}, sort_keys=True))
        return
    ret = subprocess.run([sys.executable, "-B", str(CLI), "pilot-stop"],
                         cwd="/tmp", capture_output=True, timeout=22)
    after = snapshot()
    if after != dict(before, pilot=None):
        raise RuntimeError("Coordinator readback did not settle the exact pilot; preserve evidence and do not replay")
    print(json.dumps({"status": "SLOT_RELEASED", "cli_acknowledged": ret.returncode == 0,
                      "before": before, "after": after, "other_automation_off": True}, sort_keys=True))


if __name__ == "__main__":
    main()
