import json, os, subprocess, sys, tempfile
from datetime import datetime, timezone
from pathlib import Path
from offline_release_harness import *
import offline_release_harness as harness

NOW = datetime(2026, 11, 19, tzinfo=timezone.utc)
def fixture():
    temporary = tempfile.TemporaryDirectory(); root = Path(temporary.name); stage = root / "stage"; stage.mkdir()
    expiry = mapped(root, LOGICAL["expiry"]); atomic(expiry, b"old-expiry", 0o640)
    for name, data in (("20-retained.conf", b"unit"), ("retained-watch.env", b"COMPANY_RETAINED_KEY_ID=\n"), ("expiry.conf", b"new-expiry")): atomic(stage / name, data, 0o600)
    capture = root / "merged-unit"; atomic(capture, b"merged", 0o600)
    preflight = {"service_id":"job-search-sync.service", "service_active":"inactive", "service_enabled":"disabled", "intake_status":{"enabled":False,"retained_enabled":False}, "fragment_path":"/home/chris/.config/systemd/user/job-search-sync.service", "expiry_dropin_path":"/home/chris/.config/systemd/user/job-search-sync.service.d/expiry.conf", "merged_unit_capture":str(capture), "merged_unit_sha256":sha(b"merged"), "expiry_sha256":sha(b"old-expiry"), "expiry_uid":os.getuid(), "expiry_mode":0o640, "not_after":"2027-01-01T00:00:00Z"}
    preflight_path = root / "preflight.json"; preflight_path.write_text(json.dumps(preflight))
    return temporary, root, stage, preflight_path, root / "receipt.json", expiry

faults = ["receipt-before", "receipt-after", "receipt-permission"]
for target in ("unit", "env", "expiry"):
    faults += [f"{target}-before", f"{target}-written", f"{target}-after",
               f"{target}-committed-before", f"{target}-committed-after",
               f"receipt-{target}-before", f"receipt-{target}-committed-before",
               f"receipt-{target}-committed-after", f"receipt-{target}-before-permission",
               f"receipt-{target}-committed-before-permission", f"receipt-{target}-committed-after-permission"]
for fault in faults:
    temporary, root, stage, preflight, receipt, expiry = fixture()
    try:
        try: install_or_recover(root, stage, preflight, receipt, now=NOW, fail_at=fault)
        except (OSError, PermissionError): pass
        else: raise AssertionError(f"fault did not fire: {fault}")
        assert expiry.read_bytes() == b"old-expiry" and (expiry.stat().st_mode & 0o777) == 0o640
        assert not mapped(root, LOGICAL["unit"]).exists() and not mapped(root, LOGICAL["env"]).exists()
    finally: temporary.cleanup()

temporary, root, stage, preflight, receipt, expiry = fixture()
try:
    try: install(root, stage, preflight, receipt, now=NOW, fail_at="unit-written")
    except OSError: pass
    atomic(mapped(root, LOGICAL["unit"]), b"foreign", 0o644)
    try: rollback(root, receipt)
    except ValueError as error: assert str(error) == "rollback_target_drift"
    else: raise AssertionError("drift was deleted")
finally: temporary.cleanup()

# A captured preimage owned by somebody else is refused before a receipt or
# target mutation; this harness intentionally does not attempt fchown.
temporary, root, stage, preflight, receipt, expiry = fixture()
try:
    data = json.loads(preflight.read_text()); data["expiry_uid"] = os.getuid() + 1; preflight.write_text(json.dumps(data))
    try: install(root, stage, preflight, receipt, now=NOW)
    except ValueError as error: assert str(error) == "expiry_owner_not_installer"
    else: raise AssertionError("foreign owner was accepted")
    assert not receipt.exists() and expiry.read_bytes() == b"old-expiry"
    assert not mapped(root, LOGICAL["unit"]).exists() and not mapped(root, LOGICAL["env"]).exists()
finally: temporary.cleanup()

# Retain the final UID check after restoration: a simulated owner change makes
# recovery fail closed even after the old bytes have been written back.
temporary, root, stage, preflight, receipt, expiry = fixture()
try:
    try: install(root, stage, preflight, receipt, now=NOW, fail_at="expiry-written")
    except OSError: pass
    original_metadata = harness._metadata
    def owner_drift(path):
        result = original_metadata(path)
        if Path(path) == expiry and Path(path).read_bytes() == b"old-expiry":
            return {**result, "uid": result["uid"] + 1}
        return result
    harness._metadata = owner_drift
    try:
        rollback(root, receipt)
    except ValueError as error: assert str(error) == "rollback_restore_failed"
    else: raise AssertionError("restored owner drift was accepted")
    finally: harness._metadata = original_metadata
finally: temporary.cleanup()

temporary, root, stage, preflight, receipt, expiry = fixture()
try:
    command = [sys.executable, "verify_preinstall_gates.py", str(root), str(preflight), "2026-11-19T00:00:00Z"]
    completed = subprocess.run(command, cwd=Path(__file__).parent, check=False, capture_output=True, text=True); assert completed.returncode == 0, completed.stderr
    data = json.loads(preflight.read_text()); data["intake_status"]["extra"] = "actual-status-field"; preflight.write_text(json.dumps(data))
    completed = subprocess.run(command, cwd=Path(__file__).parent, check=False, capture_output=True, text=True); assert completed.returncode == 0, completed.stderr
    atomic(expiry, b"changed", 0o640); completed = subprocess.run(command, cwd=Path(__file__).parent, check=False, capture_output=True, text=True); assert completed.returncode != 0
finally: temporary.cleanup()
print("offline receipt ownership, recovery, drift refusal, and shared preflight checks passed")
