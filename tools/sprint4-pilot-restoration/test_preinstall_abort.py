from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

import controller as joint
from host_exchange import Hold, encode
from preinstall_abort import (BOOT_ID, capture_refused_install, enroll_abort, observe_abort,
                              enrolled_capsule, observe_not_invoked, process_start, restore_abort,
                              restore_not_invoked, verify_protected)
from test_host_exchange import fixture, interrupt, states

APPROVED = Path("/tmp/jsh-s4-enrollment-release.EHxLVsCF")
WITNESS_FIXTURE = Path("/tmp/jsh-s4-ancillary-process-site.nhmkZYVm")
sys.path[:0] = [str(APPROVED / "site-source"), str(WITNESS_FIXTURE)]
from site_bundle import BUNDLE_ENTRIES, build_host_checker
import test_protected_state as protected_fixture
del sys.path[:2]


def digest(raw):
    return sha256(raw).hexdigest()


def write(path, data, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    path.chmod(mode)


@pytest.fixture(name="original")
def original_fixture(fixture, tmp_path, monkeypatch):
    monkeypatch.delenv("JOB_STORAGE_BACKEND", raising=False)
    monkeypatch.delenv("STATE_DB_FILE", raising=False)
    monkeypatch.delenv("PYTHONPYCACHEPREFIX", raising=False)
    exchange, _ = fixture
    exchange.prepare()
    closure = exchange.close()
    protected = protected_fixture.ProtectedWitnessTests("test_success_and_no_source_changes")
    protected.setUp()
    try:
        project = protected.root
        bundle = tmp_path / "capsule"
        bundle.mkdir(mode=0o700)
        paths = {name: {} for name in sorted(joint.installer.WRAPPER_PATHS)}
        for label, root in (("before", project), ("after", bundle / "candidate")):
            (root / "src/job_search_helper").mkdir(parents=True)
            for name, endpoints in paths.items():
                raw = f"# {label} approved wrapper payload\n".encode()
                write(root / name, raw)
                endpoints[label] = {"mode": "0600", "sha256": digest(raw)}
                endpoints["owner"] = [os.geteuid(), os.getegid()]
        write(project / ".storage-backend", b"sqlite\n")
        locks = [project / ".integration-install.lock",
                 *(project / ".state" / name for name in ("scraper.lock", "writer.lock", "review-writeback.lock"))]
        for path in (*locks, bundle / "controller.lock", bundle / "installer.lock"):
            write(path, b"")
        units = tmp_path / "units"
        units.mkdir()
        fake_systemctl = tmp_path / "physical-systemctl"
        write(fake_systemctl, b"#!/bin/sh\nexit 1\n", mode=0o700)
        manifest = joint.installer.encode({"schema": "sprint-4-source-manifest-v1", "paths": paths})
        write(bundle / "manifest.json", manifest)
        write(bundle / "plan.json", encode({"project": str(project), "hold_id": "fixture-hold",
                                          "unit_directory": str(units), "systemctl": str(fake_systemctl),
                                          "pycache_prefixes": [], "manifest_sha256": digest(manifest)}))
        for name in ("controller.py", "installer.py", "gate.py", "verify_hold"):
            shutil.copy2(APPROVED / name, bundle / name)
        fence = {"policy_file": str(exchange.policy_path), "policy_sha256": exchange.approved_sha256,
                 "generation": closure.generation, "intent_sha256": closure.intent_sha256,
                 "launch_uid": os.geteuid(),
                 "pairs": [[str(pair.canonical), str(pair.parked)] for pair in closure.pairs]}
        policy = {
            "schema": "sprint-4-site-policy-v1", "protected_pin_file": str(protected.pin),
            "protected_pin_sha256": protected.digest,
            "site": {"maintenance_bundle": str(bundle), "project": str(project), "maintenance_id": "fixture-hold",
                     "manifest_sha256": digest(manifest), "marker": str(project / ".state" / joint.MARKER_NAME),
                     "lock_paths": list(map(str, locks)), "cache_prefixes": [], "source_paths": list(paths),
                     "launch_uid": os.geteuid(), "exchange_fence": fence, "covers": [],
                     "alternate_roots": [pair[0] for pair in fence["pairs"]]},
        }
        entries = {
            name: (APPROVED / "site-source" / name).read_bytes()
            for name in BUNDLE_ENTRIES - {"__main__.py", "approved_site_policy.json"}
        }
        entries["__main__.py"] = (APPROVED / "site-source" / "host_check_main.py").read_bytes()
        entries["approved_site_policy.json"] = encode(policy)
        checker_sha = build_host_checker(bundle / "host-check", entries)
        attempt_directory = tmp_path / "attempt"
        attempt_directory.mkdir(mode=0o700)
        write(attempt_directory / "attempt.lock", b"")
        enrollment = enroll_abort(bundle, attempt_directory=attempt_directory, approved_checker_sha256=checker_sha,
                                  approved_protected_pin_sha256=protected.digest)
        yield bundle, exchange, protected, enrollment
    finally:
        protected.doCleanups()


def attempt_for(original):
    _, _, _, enrollment = original
    return capture_refused_install(enrollment, approved_enrollment_sha256=digest(enrollment))


def pins_for(enrollment, attempt):
    return {"approved_enrollment_sha256": digest(enrollment), "approved_attempt_sha256": digest(attempt)}


def approval_for(enrollment, attempt):
    values = pins_for(enrollment, attempt)
    approval = encode(observe_abort(enrollment, attempt, **values))
    return approval, {**values, "approved_sha256": digest(approval)}


def test_actual_controller_refuses_and_original_archive_verifies_before_restore_and_replay(original):
    bundle, exchange, _, enrollment = original
    attempt = attempt_for(original)
    record = json.loads(attempt)
    assert record["returncode"] == 1 and record["stdout"] == ""
    assert b"Host checker refused preflight" in bytes.fromhex(record["stderr"])
    assert (bundle / "transaction").is_dir()
    assert not (bundle / "controller.json").exists()
    approval, pins = approval_for(enrollment, attempt)
    restored = restore_abort(enrollment, attempt, approval, **pins)
    assert states(exchange) == [True, True, True]
    assert restored.terminal_proof_sha256 == digest(approval)
    assert restore_abort(enrollment, attempt, approval, **pins) == restored


def test_no_invocation_fabricated_attempt_or_running_process_refuses(original):
    _, exchange, _, enrollment = original
    with pytest.raises(Hold, match="independently held pin"):
        observe_abort(enrollment, b"", **pins_for(enrollment, b""))
    attempt = attempt_for(original)
    forged = json.loads(attempt)
    forged["process"] = [BOOT_ID.read_text().strip(), os.getpid(), process_start(os.getpid())]
    forged = encode(forged)
    with pytest.raises(Hold, match="independently held pin"):
        observe_abort(enrollment, forged, **pins_for(enrollment, attempt))
    with pytest.raises(Hold, match="process has not exited"):
        observe_abort(enrollment, forged, **pins_for(enrollment, forged))
    assert states(exchange) == [False, False, False]


@pytest.mark.parametrize("change", ["checker", "pin", "capsule-copy", "candidate", "controller-gate", "installer-gate", "application-lease",
                                    "journal", "marker", "sentinel", "dropin", "pending-guard", "guard",
                                    "before-seal", "after-seal", "scoped-source", "unscoped-source", "state-gone",
                                    "state-dangling", "state-replaced", "state-occupied", "state-mode", "logical"])
def test_original_route_or_evidence_drift_refuses_after_approval(original, change):
    bundle, exchange, protected, enrollment = original
    attempt = attempt_for(original)
    approval, pins = approval_for(enrollment, attempt)
    controller = joint.Controller(bundle)
    paths = {
        "checker": controller.checker, "pin": protected.pin,
        "controller-gate": controller.controller_gate, "installer-gate": controller.install_gate,
        "application-lease": controller.locks[-1], "journal": controller.journal, "marker": controller.marker,
        "sentinel": controller.units.sentinel, "dropin": controller.units.path(joint.UNITS[0]),
        "pending-guard": bundle / joint.STAGED_EXTENSION, "guard": controller.canonical / "__init__.abi3.so",
        "before-seal": bundle / joint.installer.host_image_name("before"),
        "after-seal": bundle / joint.installer.host_image_name("after"),
        "scoped-source": controller.project / joint.installer.WRAPPER_HOST,
        "candidate": controller.candidate / joint.installer.WRAPPER_HOST,
        "unscoped-source": controller.canonical / "introduced.py",
        "state-occupied": controller.state / "unexpected",
    }
    if change == "capsule-copy":
        previous = bundle.with_name("old-original-capsule")
        bundle.rename(previous)
        shutil.copytree(previous, bundle)
    elif change in {"controller-gate", "installer-gate", "application-lease"}:
        path = paths[change]
        path.rename(path.with_suffix(".old"))
        write(path, b"")
    elif change in paths:
        write(paths[change], b"modified")
    elif change == "logical":
        protected.sql("inbox", "UPDATE sync_plans SET cursor=68")
    elif change == "state-mode":
        controller.state.chmod(0o755)
    else:
        controller.state.rename(controller.state.with_name("original-transaction"))
        if change == "state-dangling":
            controller.state.symlink_to(bundle / "missing")
        if change == "state-replaced":
            controller.state.mkdir(mode=0o700)
    with pytest.raises((Hold, ValueError, OSError)) as error:
        restore_abort(enrollment, attempt, approval, **pins)
    if change == "logical":
        assert "Original protected application baseline could not be verified" in str(error.value)
    assert states(exchange) == [False, False, False]


def test_abort_uses_same_approval_after_interrupted_exchange_and_rechecks_baseline(original, monkeypatch):
    _, exchange, protected, enrollment = original
    attempt = attempt_for(original)
    approval, pins = approval_for(enrollment, attempt)
    interrupt(monkeypatch, lambda: restore_abort(enrollment, attempt, approval, **pins), "_exchange")
    assert states(exchange) == [True, False, False]
    protected.sql("inbox", "UPDATE sync_plans SET cursor=68")
    with pytest.raises(Hold, match="protected application baseline"):
        restore_abort(enrollment, attempt, approval, **pins)
    assert states(exchange) == [True, False, False]
    protected.sql("inbox", "UPDATE sync_plans SET cursor=67")
    restored = restore_abort(enrollment, attempt, approval, **pins)
    assert restored == exchange.witness("restored")
    assert states(exchange) == [True, True, True]


def test_original_lease_is_held_until_after_protected_check(original):
    bundle, exchange, _, enrollment = original
    attempt = attempt_for(original)
    approval, pins = approval_for(enrollment, attempt)
    controller = joint.Controller(bundle)
    with joint.lock(controller.install_gate), pytest.raises((Hold, OSError)):
        restore_abort(enrollment, attempt, approval, **pins)
    assert states(exchange) == [False, False, False]


def test_original_protected_verifier_requires_real_scraper_lease(original):
    _, _, _, enrollment = original
    controller, archive, enrolled = enrolled_capsule(enrollment, digest(enrollment))
    with pytest.raises(Hold, match="protected application baseline"):
        verify_protected(controller, archive, enrolled["protected_pin"])


def test_explicit_not_invoked_restores_without_creating_transaction(original):
    bundle, exchange, _, enrollment = original
    pin = {"approved_enrollment_sha256": digest(enrollment)}
    approval = encode(observe_not_invoked(enrollment, **pin))
    kwargs = {**pin, "approved_sha256": digest(approval)}
    with pytest.raises(Hold, match="Malformed abort evidence"):
        restore_abort(enrollment, b"", approval, approved_attempt_sha256=digest(b""), **kwargs)
    restored = restore_not_invoked(enrollment, approval, **kwargs)
    assert restore_not_invoked(enrollment, approval, **kwargs) == restored
    assert states(exchange) == [True, True, True]
    assert not (bundle / "transaction").exists()


def test_not_invoked_approval_refuses_later_attempt_and_wrong_floor(original):
    _, exchange, _, enrollment = original
    pin = {"approved_enrollment_sha256": digest(enrollment)}
    approval = encode(observe_not_invoked(enrollment, **pin))
    attempt = attempt_for(original)
    with pytest.raises(Hold, match="already contains launch evidence"):
        restore_not_invoked(enrollment, approval, approved_sha256=digest(approval), **pin)
    refused_approval, _ = approval_for(enrollment, attempt)
    with pytest.raises(Hold, match="Malformed abort evidence"):
        restore_not_invoked(enrollment, refused_approval, approved_sha256=digest(refused_approval), **pin)
    assert states(exchange) == [False, False, False]


@pytest.mark.parametrize("status", [0, 7])
def test_non_abort_launch_keeps_wait_status_and_output(original, monkeypatch, status):
    _, exchange, _, enrollment = original
    actual_popen = subprocess.Popen

    def fixture_process(*_, **kwargs):
        script = f"import sys; print('success-body'); print('stderr-body', file=sys.stderr); sys.exit({status})"
        return actual_popen([sys.executable, "-I", "-c", script], **kwargs)

    monkeypatch.setattr(subprocess, "Popen", fixture_process)
    pins = {"approved_enrollment_sha256": digest(enrollment)}
    with pytest.raises(Hold, match="non-abort outcome"):
        capture_refused_install(enrollment, **pins)
    attempt_dir = Path(json.loads(enrollment)["attempt"]["path"])
    assert (attempt_dir / "stdout").read_text() == "success-body\n"
    assert (attempt_dir / "stderr").read_text() == "stderr-body\n"
    assert json.loads((attempt_dir / "exit.json").read_bytes())["returncode"] == status
    assert not (attempt_dir / "refusal.json").exists()
    with pytest.raises(Hold, match="already contains launch evidence"):
        observe_not_invoked(enrollment, **pins)
    assert states(exchange) == [False, False, False]


def test_uncertain_spawn_preserves_intent_and_refuses_not_invoked(original, monkeypatch):
    _, exchange, _, enrollment = original

    def lost_spawn(*args, **kwargs):
        raise OSError("simulated lost launch")

    monkeypatch.setattr(subprocess, "Popen", lost_spawn)
    pins = {"approved_enrollment_sha256": digest(enrollment)}
    with pytest.raises(OSError, match="lost launch"):
        capture_refused_install(enrollment, **pins)
    attempt_dir = Path(json.loads(enrollment)["attempt"]["path"])
    assert (attempt_dir / "launch.json").is_file()
    assert not (attempt_dir / "exit.json").exists()
    with pytest.raises(Hold, match="already contains launch evidence"):
        observe_not_invoked(enrollment, **pins)
    with pytest.raises(Hold, match="already contains launch evidence"):
        capture_refused_install(enrollment, **pins)
    assert states(exchange) == [False, False, False]
