"""Offline verifier for a substituted, staged release directory.

Usage: verify_generated_release.py STAGED_DIR RECEIPT_JSON
It reads only the supplied directory; it never calls systemctl or writes files.
"""
import json
import os
from pathlib import Path
import re
import sys
import base64
from datetime import datetime, timezone

stage, receipt_path = map(Path, sys.argv[1:3])
assert {path.name for path in stage.iterdir()} == {"20-retained.conf", "expiry.conf", "retained-watch.env"}
unit = (stage / "20-retained.conf").read_text()
expiry = (stage / "expiry.conf").read_text()
env = stage / "retained-watch.env"
receipt = json.loads(receipt_path.read_text())
joined = "\n".join((unit, expiry, env.read_text(), json.dumps(receipt, sort_keys=True)))
assert "REPLACE" not in joined and "<" not in joined
starts = [line for line in unit.splitlines() if line.startswith("ExecStart=")]
assert len(starts) == 2 and starts[0] == "ExecStart="
assert starts[1] == "ExecStart=/home/chris/job-search-helper_old/.venv/bin/python -m job_search_helper.sync_cli watch --interval 60 --max-batches 20"
conditions = [line for line in expiry.splitlines() if line.startswith("ExecCondition=")]
assert len(conditions) == 2 and conditions[0] == "ExecCondition=" and conditions[1].startswith("ExecCondition=/usr/bin/python3 /home/chris/job-search-helper_old/scripts/sync_expiry_guard.py ")
expiry_at = conditions[1].rsplit(" ", 1)[1]
parsed = datetime.fromisoformat(expiry_at.replace("Z", "+00:00"))
assert parsed.tzinfo is not None and parsed > datetime.now(timezone.utc)
assert os.stat(env).st_mode & 0o777 == 0o600
assert os.stat(env).st_uid == os.getuid()
for line in env.read_text().splitlines():
    if line.startswith("COMPANY_RETAINED_ED25519_PUBLIC_KEY_BASE64="):
        value=line.partition("=")[2]
        assert not value or len(base64.b64decode(value, validate=True)) == 32
assert receipt["env_mode"] == "0600"
expected_targets = [
    {"action": "create", "absolute_path": "/home/chris/.config/systemd/user/job-search-sync.service.d/20-retained.conf"},
    {"action": "replace", "absolute_path": "/home/chris/.config/systemd/user/job-search-sync.service.d/expiry.conf"},
    {"action": "create", "absolute_path": "/home/chris/.config/job-search-helper/retained-watch.env"},
]
assert receipt["managed_targets"] == expected_targets
active_material = "\n".join(
    line for line in joined.splitlines() if line.strip() and not line.lstrip().startswith("#")
)
for forbidden in (
    "PRIVATE KEY", "BEGIN PRIVATE", "BEGIN OPENSSH", "approval_file",
    "approval-envelope", "approval_envelope", "claim_token", "owner_token",
    "secret=", "password=",
):
    assert forbidden.casefold() not in active_material.casefold()
allowed_env = {
    "COMPANY_RETAINED_KEY_ID",
    "COMPANY_RETAINED_ED25519_PUBLIC_KEY_BASE64",
    "COMPANY_RETAINED_SHEET_REQUEST_INTERVAL",
}
env_lines = [line for line in env.read_text().splitlines()
             if line.strip() and not line.lstrip().startswith("#")]
assert all("=" in line and line.split("=", 1)[0] in allowed_env for line in env_lines)
print("generated release artifacts are bounded and secret-free")
