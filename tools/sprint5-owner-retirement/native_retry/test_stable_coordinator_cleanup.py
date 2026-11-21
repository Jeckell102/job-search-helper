"""Disposable simulation of the exact freeze wrapper, without calling systemctl."""
import hashlib
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

PATH=Path(os.environ.get("QA_WRAPPER_PATH", "/tmp/jsh-retirement-launch-recovery/run_retry_with_stable_coordinator.py"))


@pytest.fixture
def local_wrapper(tmp_path, monkeypatch):
    spec=importlib.util.spec_from_file_location("reviewed_freeze_wrapper", PATH)
    wrapper=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wrapper)
    bundle=tmp_path/"bundle"
    bundle.mkdir()
    attempt=bundle.with_name("bundle-attempt")
    attempt.mkdir()
    (attempt/"attempt.lock").touch()
    control=tmp_path/"control"
    control.mkdir()
    runner=tmp_path/"runner.py"
    enrollment=bundle/"preinstall-enrollment.json"
    for attr, label, path in [
        ("RUNNER", "RUNNER_SHA", runner),
        ("ENROLLMENT", "ENROLLMENT_SHA", enrollment),
        (None, "PIN_SHA", control/"current-protected-pin.json"),
    ]:
        raw=path.name.encode()
        path.write_bytes(raw)
        if attr:
            monkeypatch.setattr(wrapper, attr, path)
        monkeypatch.setattr(wrapper, label, hashlib.sha256(raw).hexdigest())
    monkeypatch.setattr(wrapper, "CONTROL", control)
    monkeypatch.setattr(wrapper, "BUNDLE", bundle)
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setitem(sys.modules, "release_paused_slot", SimpleNamespace(snapshot=lambda: {"pilot": None}))
    return wrapper


def simulate(wrapper, monkeypatch, scenario):
    state={"ActiveState":"active","FreezerState":"running","MainPID":"42"}
    commands=[]
    after_child=False
    failed_status=False

    def status():
        nonlocal failed_status
        if scenario=="cleanup-show-fails" and after_child and not failed_status:
            failed_status=True
            raise subprocess.TimeoutExpired("fixture systemctl show",20)
        return state.copy()

    def command(action, unit):
        assert unit==wrapper.WRAPPER
        assert action in ("freeze","thaw")
        commands.append(action)
        if action=="thaw":
            if state["ActiveState"]=="inactive":
                raise subprocess.CalledProcessError(1, "fixture thaw inactive")
            state["FreezerState"]="running"
        elif scenario=="freeze-in-progress":
            state["FreezerState"]="freezing"
        else:
            state["FreezerState"]="frozen"

    def run(args, **kwargs):
        nonlocal after_child
        assert kwargs=={"cwd":wrapper.BUNDLE,"check":False}
        assert args==[sys.executable,"-I","-S","-B",str(wrapper.RUNNER),wrapper.ENROLLMENT_SHA,str(wrapper.ENROLLMENT)]
        after_child=True
        if scenario=="intentional-inactive":
            state.update(ActiveState="inactive", FreezerState="running", MainPID="0")
            return SimpleNamespace(returncode=3)
        raise OSError("disposable child launch failure")

    monkeypatch.setattr(wrapper,"unit",status)
    monkeypatch.setattr(wrapper,"command",command)
    monkeypatch.setattr(wrapper,"subprocess",SimpleNamespace(run=run, SubprocessError=subprocess.SubprocessError))
    return commands,state


@pytest.mark.parametrize("scenario", ["cleanup-show-fails","freeze-in-progress","child-fails"])
def test_exceptions_leave_no_frozen_wrapper(local_wrapper, monkeypatch, scenario):
    commands,state=simulate(local_wrapper,monkeypatch,scenario)
    with pytest.raises((OSError,RuntimeError,subprocess.SubprocessError)):
        local_wrapper.main()
    assert commands==["freeze","thaw"]
    assert state["FreezerState"]=="running"


def test_intentionally_inactive_service_is_left_alone(local_wrapper, monkeypatch):
    commands,state=simulate(local_wrapper,monkeypatch,"intentional-inactive")
    assert local_wrapper.main()==3
    assert commands==["freeze","thaw"]
    assert state=={"ActiveState":"inactive","FreezerState":"running","MainPID":"0"}
