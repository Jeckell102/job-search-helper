"""Sandbox-only transactional installer and rollback model; never targets a host."""
import hashlib
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

LOGICAL = {"unit": "/home/chris/.config/systemd/user/job-search-sync.service.d/20-retained.conf", "expiry": "/home/chris/.config/systemd/user/job-search-sync.service.d/expiry.conf", "env": "/home/chris/.config/job-search-helper/retained-watch.env"}
STEPS = (("unit", "20-retained.conf", 0o644), ("env", "retained-watch.env", 0o600), ("expiry", "expiry.conf", 0o644))

def sha(data): return hashlib.sha256(data).hexdigest()
def _inside(root, path):
    root, path = Path(root).resolve(), Path(path).resolve()
    try: path.relative_to(root)
    except ValueError as exc: raise ValueError("sandbox_escape") from exc
    return path
def mapped(root, logical): return _inside(root, Path(root).resolve() / logical.lstrip("/"))
def _receipt_path(root, path): return _inside(root, path)
def atomic(path, data, mode):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True); fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "wb", closefd=True) as output: output.write(data); output.flush(); os.fsync(output.fileno())
        os.chmod(temporary, mode); os.replace(temporary, path)
    except BaseException: Path(temporary).unlink(missing_ok=True); raise
def _metadata(path):
    stat = path.stat(); return {"sha256": sha(path.read_bytes()), "uid": stat.st_uid, "mode": stat.st_mode & 0o777}
def _matches(path, expected): return path.is_file() and _metadata(path) == expected
def deadline(value, now):
    try: parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc: raise ValueError("expiry_invalid") from exc
    if parsed.tzinfo is None or parsed <= now: raise ValueError("expiry_not_future")
def verify_preflight(root, preflight, now):
    root = Path(root).resolve()
    if preflight["service_active"] != "inactive" or preflight["service_enabled"] != "disabled": raise ValueError("service_not_stopped_disabled")
    controls = preflight["intake_status"]
    if not isinstance(controls, dict) or controls.get("enabled") is not False or controls.get("retained_enabled") is not False: raise ValueError("intake_not_default_off")
    capture = _inside(root, preflight["merged_unit_capture"])
    if sha(capture.read_bytes()) != preflight["merged_unit_sha256"]: raise ValueError("merged_unit_changed")
    expected = {"sha256": preflight["expiry_sha256"], "uid": preflight["expiry_uid"], "mode": preflight["expiry_mode"]}
    # This user-level harness has no safe fchown path.  Do not create a
    # receipt, much less replace expiry, unless it can restore this owner.
    if expected["uid"] != os.getuid(): raise ValueError("expiry_owner_not_installer")
    if not _matches(mapped(root, LOGICAL["expiry"]), expected): raise ValueError("expiry_preimage_changed")
    deadline(preflight["not_after"], now)
def _write_receipt(path, receipt, fail_at, point):
    if fail_at in ("receipt-permission", f"receipt-{point}-permission", f"receipt-{point}-before-permission", f"receipt-{point}-after-permission"): raise PermissionError("injected_receipt_permission")
    if fail_at in (point, f"receipt-{point}", f"receipt-{point}-before"): raise OSError(f"injected_receipt_{point}")
    atomic(path, json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode(), 0o600)
    if fail_at in (f"{point}-after", f"receipt-{point}-after"): raise OSError(f"injected_receipt_{point}_after")
def _read_receipt(root, receipt_path):
    path = _receipt_path(root, receipt_path); receipt = json.loads(path.read_text()); root = Path(root).resolve()
    if receipt.get("sandbox_root") != str(root): raise ValueError("receipt_sandbox_changed")
    if receipt.get("targets") != LOGICAL: raise ValueError("receipt_targets_invalid")
    return path, receipt
def install(root, stage, preflight_path, receipt_path, *, now, fail_at=None):
    root = Path(root).resolve(); stage = _inside(root, stage); preflight_path = _inside(root, preflight_path); receipt_path = _receipt_path(root, receipt_path)
    verify_preflight(root, json.loads(preflight_path.read_text()), now); targets = {name: mapped(root, logical) for name, logical in LOGICAL.items()}
    if targets["unit"].exists() or targets["env"].exists(): raise ValueError("create_target_exists")
    old = _metadata(targets["expiry"])
    receipt = {"version": 2, "state": "PREPARED", "sandbox_root": str(root), "targets": LOGICAL, "managed": {}, "expiry_preimage": {**old, "bytes_hex": targets["expiry"].read_bytes().hex()}}
    for name, source, mode in STEPS:
        source_path = _inside(root, stage / source); receipt["managed"][name] = {"sha256": sha(source_path.read_bytes()), "uid": os.getuid(), "mode": mode, "state": "PREPARED"}
    _write_receipt(receipt_path, receipt, fail_at, "before"); _write_receipt(receipt_path, receipt, fail_at, "after")
    for name, source, mode in STEPS:
        receipt["managed"][name]["state"] = "WRITING"; _write_receipt(receipt_path, receipt, fail_at, f"{name}-before")
        if fail_at == f"{name}-before": raise OSError(f"injected_{name}_before")
        atomic(targets[name], (stage / source).read_bytes(), mode)
        # This is the crash window that matters: the file is durable but the
        # receipt still says WRITING, so rollback must recognize it as owned.
        if fail_at in (f"{name}-written", f"{name}-after"):
            raise OSError(f"injected_{name}_written")
        receipt["managed"][name]["state"] = "COMMITTED"
        if fail_at == f"{name}-committed-before": raise OSError(f"injected_{name}_committed_before")
        _write_receipt(receipt_path, receipt, fail_at, f"{name}-committed")
        if fail_at == f"{name}-committed-after": raise OSError(f"injected_{name}_committed_after")
    receipt["state"] = "INSTALLED"; _write_receipt(receipt_path, receipt, fail_at, "complete"); return receipt
def rollback(root, receipt_path):
    root = Path(root).resolve(); receipt_path, receipt = _read_receipt(root, receipt_path); targets = {name: mapped(root, logical) for name, logical in receipt["targets"].items()}
    old = receipt.get("expiry_preimage", {})
    try: old_bytes = bytes.fromhex(old["bytes_hex"]); old_meta = {key: old[key] for key in ("sha256", "uid", "mode")}
    except (KeyError, TypeError, ValueError) as exc: raise ValueError("receipt_corrupt") from exc
    if sha(old_bytes) != old_meta["sha256"]: raise ValueError("receipt_corrupt")
    for name in ("unit", "env"):
        owned = receipt.get("managed", {}).get(name)
        if not owned or owned.get("state") not in {"PREPARED", "WRITING", "COMMITTED"}: raise ValueError("receipt_target_state_invalid")
        path = targets[name]
        if path.exists():
            wanted = {key: owned[key] for key in ("sha256", "uid", "mode")}
            if not _matches(path, wanted): raise ValueError("rollback_target_drift")
            path.unlink()
    owned = receipt.get("managed", {}).get("expiry")
    if not owned or owned.get("state") not in {"PREPARED", "WRITING", "COMMITTED"}: raise ValueError("receipt_target_state_invalid")
    new_meta = {key: owned[key] for key in ("sha256", "uid", "mode")}; expiry = targets["expiry"]
    if not _matches(expiry, old_meta):
        if not _matches(expiry, new_meta): raise ValueError("rollback_target_drift")
        atomic(expiry, old_bytes, old_meta["mode"])
    if not _matches(expiry, old_meta): raise ValueError("rollback_restore_failed")
    receipt["state"] = "ROLLED_BACK"; _write_receipt(receipt_path, receipt, None, "rollback"); return receipt
def install_or_recover(root, stage, preflight_path, receipt_path, *, now, fail_at=None):
    try: return install(root, stage, preflight_path, receipt_path, now=now, fail_at=fail_at)
    except BaseException:
        path = _receipt_path(root, receipt_path)
        if path.exists(): rollback(root, path)
        raise
