"""Offline guard for the uninstalled retained-watch release templates."""
from pathlib import Path

root = Path(__file__).parent
unit = (root / "job-search-sync-watch-retained.conf.template").read_text()
env = (root / "retained-watch.env.template").read_text()
expiry = (root / "30-release-expiry.conf.template").read_text()

assert unit.count("ExecStart=") == 2  # reset plus exactly one watcher command
assert "job-search-sync.service.d" in unit and "sync_cli watch --interval 60 --max-batches 20" in unit
assert "PRIVATE" not in unit and "KEY=" not in unit
assert "COMPANY_RETAINED_KEY_ID=" in env
assert "COMPANY_RETAINED_ED25519_PUBLIC_KEY_BASE64=" in env
assert "COMPANY_RETAINED_INTAKE_ENABLED" not in env  # durable gate, not env activation
assert "sync_expiry_guard.py REPLACE_WITH_FUTURE_RFC3339" in expiry
assert "ExecCondition=\nExecCondition=" in expiry
print("release templates are offline, single-watcher, and default-off")
