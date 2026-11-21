from copy import deepcopy
import os

import controller as joint
import gate
import pytest


@pytest.fixture
def capsule(tmp_path):
    project = tmp_path / "project"
    src = project / "src" / "job_search_helper"
    src.mkdir(parents=True)
    (project / ".state").mkdir()
    (project / "dev" / "wrapper-coder" / "tools").mkdir(parents=True)
    (project / ".storage-backend").write_text("sqlite\n")
    units = tmp_path / "units"
    units.mkdir()
    systemctl = tmp_path / "systemctl-not-executed"
    systemctl.write_bytes(b"fixture")
    (project / ".integration-install.lock").write_bytes(b"")
    for name in ("review-writeback.lock", "scraper.lock", "writer.lock"):
        (project / ".state" / name).write_bytes(b"")
    bundle = tmp_path / "bundle"
    bundle.mkdir(mode=0o700)
    for name in (
        "controller.py", "gate.py", "installer.py", "verify_hold", "host-check",
        "controller.lock", "installer.lock",
    ):
        path = bundle / name
        path.write_bytes(b"fixture")
        path.chmod(0o700)
    (bundle / "transaction").mkdir(mode=0o700)
    manifest = {
        "schema": "sprint-4-source-manifest-v1",
        "paths": {
            name: {
                "before": {"mode": "0600", "sha256": "1" * 64},
                "after": {"mode": "0600", "sha256": "2" * 64},
                "owner": [os.geteuid(), os.getegid()],
            } for name in joint.installer.WRAPPER_PATHS
        },
    }
    raw = joint.installer.encode(manifest)
    (bundle / "manifest.json").write_bytes(raw)
    guard = project / "src" / gate.PARKED
    gate.create_marker(guard)
    handoff = bundle / "predecessor-guard.json"
    handoff_raw = joint.installer.encode({
        "schema": "s4-predecessor-guard-handoff-v1",
        "observed": {"guard": gate.guard_identity(guard)},
        "successor": {},
    })
    handoff.write_bytes(handoff_raw)
    handoff.chmod(0o600)
    (bundle / "plan.json").write_bytes(joint.installer.encode({
        "project": str(project),
        "hold_id": "scope-bound",
        "unit_directory": str(units),
        "systemctl": str(systemctl),
        "pycache_prefixes": [],
        "manifest_sha256": joint.installer.digest(raw),
        "predecessor_guard_sha256": joint.installer.digest(handoff_raw),
    }))
    return bundle, handoff, handoff_raw, guard


def test_same_inode_marker_content_change_during_validation_holds(capsule, monkeypatch):
    _, _, _, guard = capsule
    expected = gate.guard_identity(guard)
    fdopen = os.fdopen
    marker = guard / "__init__.py"
    changed = False

    class RewritingMarker:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            self.stream.__enter__()
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def fileno(self):
            return self.stream.fileno()

        def read(self, size):
            nonlocal changed
            result = self.stream.read(size)
            assert result == gate.MESSAGE
            marker.chmod(0o644)
            marker.write_bytes(b"substituted marker")
            marker.chmod(0o444)
            changed = True
            return result

    monkeypatch.setattr(gate.os, "fdopen", lambda *args, **kwargs: RewritingMarker(fdopen(*args, **kwargs)))
    with pytest.raises(ValueError, match="marker file changed while being read"):
        gate.verify_guard_identity(guard, expected)
    assert changed


def test_controller_cannot_pin_different_handoff_after_authenticating_it(capsule, monkeypatch):
    bundle, handoff, approved, _ = capsule
    read = joint.read
    swapped = False

    def changed_after_initial_read(path):
        nonlocal swapped
        value = read(path)
        if path == handoff and not swapped:
            foreign = bundle / "replacement"
            foreign.write_bytes(b"unapproved authorization")
            foreign.chmod(0o600)
            foreign.replace(handoff)
            swapped = True
        return value

    monkeypatch.setattr(joint, "read", changed_after_initial_read)
    try:
        controller = joint.Controller(bundle)
    except ValueError:
        pass
    else:
        assert controller.binding["files"][str(handoff)][-1] == joint.installer.digest(approved)
        with pytest.raises(ValueError):
            controller.verify_preinstall_parked()
    assert swapped


def test_inherited_closing_record_cannot_resume_without_approved_guard(capsule):
    bundle, _, _, guard = capsule
    candidate = joint.Controller(bundle)
    expected = gate.guard_identity(guard)["directory"][:2]
    record = {
        "binding": deepcopy(candidate.binding),
        "phase": "CLOSING",
        "host_exposed_before_hold": "before",
        "guard": expected,
        "admission_guard": None,
        "install_gate": joint.inode(candidate.install_gate),
        "controller_gate": joint.inode(candidate.controller_gate),
        "state": joint.inode(candidate.state),
    }
    candidate.journal.write_bytes(joint.installer.encode(record))
    assert candidate.load(canonical=True)["guard"] == expected
    record["guard"] = None
    candidate.journal.write_bytes(joint.installer.encode(record))
    with pytest.raises(ValueError):
        candidate.load(canonical=True)


class Interrupted(RuntimeError):
    pass


@pytest.mark.parametrize("operation", ["park", "publish"])
def test_real_exchange_interruption_replays_without_a_second_swap(capsule, monkeypatch, operation):
    _, _, _, guard = capsule
    project = guard.parent.parent
    canonical = guard.parent / 'job_search_helper'
    original_inode = canonical.stat().st_ino
    expected = gate.guard_identity(guard)
    if operation == "publish":
        gate.park(project, original_inode, approved_guard=expected)
    rename = gate.rename
    swaps = []

    def interrupted(left, right, flags):
        rename(left, right, flags)
        swaps.append((left, right, flags))
        raise Interrupted

    monkeypatch.setattr(gate, "rename", interrupted)
    action = getattr(gate, operation)
    with pytest.raises(Interrupted):
        action(project, original_inode, approved_guard=expected)
    action(project, original_inode, approved_guard=expected)
    intended_source, intended_guard = (guard, canonical) if operation == "park" else (canonical, guard)
    assert intended_source.stat().st_ino == original_inode
    assert gate.guard_identity(intended_guard) == expected
    assert len(swaps) == 1
