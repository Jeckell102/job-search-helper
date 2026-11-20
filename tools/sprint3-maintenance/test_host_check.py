import json
import sqlite3

import pytest

import host_check


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(host_check, "PROJECT", tmp_path)
    state = tmp_path / ".state"
    directory = state / "operator-company-requests/receipts"
    directory.mkdir(parents=True)
    identity = {"schema": "operator-company-scan-request-v1", "request_id": "operator-samtec-m1-20261119",
                "company_id": "COMP-0739", "source_revision": "fixture"}
    request = {"company_ids": ["COMP-0739"], "request_id": identity["request_id"], "mode": "company-only",
               "source_revision": identity["source_revision"], "operator_request": identity}
    path = state / "next-scan.json"
    path.write_text(json.dumps(request), encoding="utf-8")
    path.chmod(0o600)
    receipt_path = directory / (host_check.request_digest({"request_id": identity["request_id"]}) + ".json")
    receipt_path.write_text(json.dumps({**identity, "state": "REQUEST_WRITTEN",
                                        "request_sha256": host_check.request_digest(request)}), encoding="utf-8")
    receipt_path.chmod(0o600)
    tasks = tmp_path / "dev/wrapper-coder/tasks"
    tasks.mkdir(parents=True)
    with sqlite3.connect(tasks / "tasks.sqlite3") as db:
        db.executescript("""
        CREATE TABLE settings(key, value);
        INSERT INTO settings VALUES ('autopilot_enabled','false'),('queue_enabled','false'),
                                    ('campaign_enabled','false');
        CREATE TABLE tasks(state);
        CREATE TABLE inference_receipts(status);
        """)
    with sqlite3.connect(state / "jobs.sqlite3") as db:
        db.executescript("""
        CREATE TABLE scrape_outcomes(outcome_id);
        CREATE TABLE scrape_outcome_deliveries(outcome_id, consumer);
        CREATE TABLE retained_intake_holds(state);
        CREATE TABLE retained_publications(state);
        INSERT INTO retained_publications VALUES ('FIRST_PASS_RELEASED');
        """)
    return state, receipt_path


def test_preflight_requires_exact_safe_request_and_receipt(sandbox):
    state, receipt = sandbox
    host_check.read_controls()
    request_path = state / "next-scan.json"
    before = request_path.read_bytes()
    changed = json.loads(before)
    changed["enqueued_at"] = "tampered"
    request_path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(RuntimeError, match="request receipt changed"):
        host_check.read_controls()
    request_path.write_bytes(before)
    receipt.rename(receipt.with_suffix(".real"))
    receipt.symlink_to(receipt.with_suffix(".real"))
    with pytest.raises(OSError):
        host_check.read_controls()


def test_file_and_database_holds_each_block_source_only_rollback(sandbox):
    state, _receipt = sandbox
    marker = state / "retained-operator-admission.json"
    marker.touch()
    with pytest.raises(RuntimeError, match="Unexpected pre-pilot lifecycle file"):
        host_check.read_controls()
    marker.unlink()
    with sqlite3.connect(state / "jobs.sqlite3") as db:
        db.execute("INSERT INTO retained_intake_holds VALUES ('FROZEN')")
    with pytest.raises(RuntimeError, match="Unsettled retained work"):
        host_check.read_controls()


def test_attestation_stays_held_until_separate_manifest_and_package_pins(sandbox, monkeypatch):
    project = host_check.PROJECT
    monkeypatch.setenv("JSH_F3_HOST_PHASE", "preflight")
    monkeypatch.setattr(host_check, "check", lambda phase: None)
    monkeypatch.setattr(host_check, "verify_environment", lambda: None)
    request = {
        "schema": "sprint-3-host-check-v1", "project": str(project), "package": str(project / "src/job_search_helper"),
        "nonce": "9" * 32,
        "checkpoint": "preflight:controller", "backend": "sqlite", "maintenance_id": host_check.HOLD_ID,
        "marker": str(project / ".state/integration-release-journal.json"),
        "pycache_prefixes": [], "source_manifest_sha256": "fixture-manifest", "target": "INSTALLED",
        "locks": list(map(str, (project / ".integration-install.lock",
                                *(project / ".state" / name for name in
                                  ("scraper.lock", "writer.lock", "review-writeback.lock"))))),
    }
    with pytest.raises(RuntimeError, match="Unexpected host check identity"):
        host_check.attest(request)
    monkeypatch.setattr(host_check, "MANIFEST_SHA256", "fixture-manifest")
    with pytest.raises(RuntimeError, match="pins have not been installed"):
        host_check.attest(request)
