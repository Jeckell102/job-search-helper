"""Freeze the idle wrapper's periodic SQLite snapshots during private enrollment."""
import argparse
from hashlib import sha256
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, '/tmp/jsh-retirement-pilot-control')
from release_paused_slot import snapshot


WRAPPER = "wrapper-development-host.service"
SYSTEMCTL = "/usr/bin/systemctl"
PREPARE = Path("/tmp/jsh-retirement-launch-recovery/retry-preparation/prepare_native.py")
PIN = Path("/tmp/jsh-retirement-pilot-control/current-protected-pin.json")
PREPARE_SHA = "d917ccb537f09c29216d1be97b3178f8b9ee5cc1ff068a29e464eb47a40ca2b8"
PIN_SHA = "d6fa29b0ad2e6af3568e38ccdb1f1606909e30d94f3d7e335b9444b5d5acd294"


def command(*args):
    return subprocess.check_output([SYSTEMCTL, "--user", *args], text=True, timeout=20).strip()


def state():
    values = command("show", WRAPPER, "-p", "ActiveState", "-p", "FreezerState", "-p", "MainPID")
    return dict(line.split("=", 1) for line in values.splitlines())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    flags = parser.parse_args()
    if snapshot()["pilot"] is not None:
        raise RuntimeError("The wrapper's old pilot is no longer released")
    if sha256(PIN.read_bytes()).hexdigest() != PIN_SHA:
        raise RuntimeError("The approved protected-state fingerprint changed")
    if sha256(PREPARE.read_bytes()).hexdigest() != PREPARE_SHA:
        raise RuntimeError("The reviewed native preparation source changed")
    before = state()
    if before["ActiveState"] != "active" or before["FreezerState"] != "running":
        raise RuntimeError("The wrapper service is not on the expected active baseline")
    if not flags.apply:
        print("Idle wrapper baseline and exact private fingerprint verified.")
        return
    try:
        command("freeze", WRAPPER)
        frozen = state()
        if frozen != {**before, "FreezerState": "frozen"}:
            raise RuntimeError("The same wrapper did not enter the systemd frozen state")
        result = subprocess.run(
            [sys.executable, "-I", "-S", "-B", str(PREPARE), "--current-pin", str(PIN),
             "--current-pin-sha256", PIN_SHA, "--enable-native-preparation"],
            cwd="/tmp", timeout=240,
        )
    finally:
        command("thaw", WRAPPER)
        if state() != before:
            raise RuntimeError("Verify wrapper service recovery before continuing")
        print("The same wrapper service is active and running again.", flush=True)
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
