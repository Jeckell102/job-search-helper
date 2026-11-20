"""Validate captured preinstall evidence with the exact harness byte-binding."""
import json, sys
from datetime import datetime
from pathlib import Path
from offline_release_harness import verify_preflight

if len(sys.argv) != 4: raise SystemExit("usage: verify_preinstall_gates.py SANDBOX_ROOT PREFLIGHT_JSON NOW_RFC3339")
root = Path(sys.argv[1]).resolve(); evidence = json.loads(Path(sys.argv[2]).read_text())
if evidence.get("service_id") != "job-search-sync.service": raise ValueError("wrong_service")
if evidence.get("fragment_path") != "/home/chris/.config/systemd/user/job-search-sync.service": raise ValueError("wrong_fragment")
if evidence.get("expiry_dropin_path") != "/home/chris/.config/systemd/user/job-search-sync.service.d/expiry.conf": raise ValueError("wrong_expiry_path")
verify_preflight(root, evidence, datetime.fromisoformat(sys.argv[3].replace("Z", "+00:00")))
print("preinstall byte-binding proves stopped, disabled, and durable default-off")
