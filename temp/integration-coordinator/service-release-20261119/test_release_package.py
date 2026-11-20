"""Isolated positive/negative checks for uninstalled release verifiers."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from offline_release_harness import LOGICAL, atomic, mapped, sha

root = Path(__file__).parent
with tempfile.TemporaryDirectory() as temporary:
    stage = Path(temporary) / "stage"; stage.mkdir()
    unit = root / "job-search-sync-watch-retained.conf.template"
    expiry = root / "expiry.conf.template"
    shutil.copy(unit, stage / "20-retained.conf")
    shutil.copy(expiry, stage / "expiry.conf")
    env = stage / "retained-watch.env"; env.write_text("COMPANY_RETAINED_KEY_ID=\nCOMPANY_RETAINED_ED25519_PUBLIC_KEY_BASE64=\nCOMPANY_RETAINED_SHEET_REQUEST_INTERVAL=1.1\n")
    os.chmod(env, 0o600)
    for name in ("20-retained.conf", "expiry.conf"):
        path = stage / name; path.write_text(path.read_text().replace("REPLACE_WITH_FUTURE_RFC3339", "2027-01-01T00:00:00Z"))
    receipt = Path(temporary) / "receipt.json"
    receipt.write_text(json.dumps({"env_mode": "0600", "managed_targets": [
        {"action": "create", "absolute_path": "/home/chris/.config/systemd/user/job-search-sync.service.d/20-retained.conf"},
        {"action": "replace", "absolute_path": "/home/chris/.config/systemd/user/job-search-sync.service.d/expiry.conf"},
        {"action": "create", "absolute_path": "/home/chris/.config/job-search-helper/retained-watch.env"},
    ]}))
    assert subprocess.run(["python3", str(root / "verify_generated_release.py"), str(stage), str(receipt)],
                          capture_output=True, text=True).returncode == 0
    (stage / "20-retained.conf").write_text("ExecStart=/bad\n")
    assert subprocess.run(["python3", str(root / "verify_generated_release.py"), str(stage), str(receipt)],
                          capture_output=True, text=True).returncode != 0
    (stage / "20-retained.conf").write_text((root / "job-search-sync-watch-retained.conf.template").read_text().replace("REPLACE_WITH_FUTURE_RFC3339", "2027-01-01T00:00:00Z"))
    (stage / "unmanaged.conf").write_text("unexpected")
    assert subprocess.run(["python3", str(root / "verify_generated_release.py"), str(stage), str(receipt)],
                          capture_output=True, text=True).returncode != 0
    (stage / "unmanaged.conf").unlink()
    sandbox = Path(temporary) / "sandbox"; sandbox.mkdir()
    capture = sandbox / "merged-unit"; atomic(capture, b"merged-unit", 0o600)
    expiry_path = mapped(sandbox, LOGICAL["expiry"]); atomic(expiry_path, b"old-expiry", 0o644)
    evidence = sandbox / "gates.json"
    good = {"service_id": "job-search-sync.service", "service_active": "inactive",
            "service_enabled": "disabled", "merged_unit_inspected": True,
            "fragment_path": "/home/chris/.config/systemd/user/job-search-sync.service",
            "expiry_dropin_path": "/home/chris/.config/systemd/user/job-search-sync.service.d/expiry.conf",
            "merged_unit_sha256": sha(b"merged-unit"), "merged_unit_capture": str(capture),
            "expiry_sha256": sha(b"old-expiry"), "expiry_uid": os.getuid(), "expiry_mode": 0o644,
            "not_after": "2027-01-01T00:00:00Z", "intake_status": {"enabled": False, "retained_enabled": False}}
    evidence.write_text(json.dumps(good))
    assert subprocess.run(["python3", str(root / "verify_preinstall_gates.py"), str(sandbox), str(evidence), "2026-11-19T00:00:00Z"],
                          capture_output=True, text=True).returncode == 0
    bad = dict(good); bad["service_active"] = "active"
    evidence.write_text(json.dumps(bad))
    assert subprocess.run(["python3", str(root / "verify_preinstall_gates.py"), str(sandbox), str(evidence), "2026-11-19T00:00:00Z"],
                          capture_output=True, text=True).returncode != 0
print("positive and negative release-package checks passed")
