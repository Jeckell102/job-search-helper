"""Route exclusion for the exact two-tool update with the read-only bridge running."""

import os

from host_checkpoint import checkout_routes, in_route, proc_args, process_start, require
from ancillary_process_witness import verify_ancillary_process


BRIDGE_ARGS = (
    "/home/chris/job-search-helper_old/.venv/bin/python",
    "-B",
    "/home/chris/AI/assistant-tools-bridge/bridge.py",
)
BRIDGE_CWD = "/home/chris/AI/assistant-tools-bridge"
BRIDGE_EXE = "/usr/bin/python3.11"
BRIDGE_CGROUP = "/user.slice/user-1000.slice/user@1000.service/app.slice/jetson-assistant-bridge.service"


def _require_bridge_identity(process, uid, expected_start):
    require(process_start(process) == expected_start
            and process.stat().st_uid == uid
            and proc_args(process) == BRIDGE_ARGS
            and os.readlink(process / "cwd") == BRIDGE_CWD
            and os.readlink(process / "exe") == BRIDGE_EXE
            and f"0::{BRIDGE_CGROUP}" in (process / "cgroup").read_text().splitlines()
            and process_start(process) == expected_start,
            "Read-only bridge identity changed during the two-tool update")


def verify_two_tool_route_drain(policy, current_wrapper_pid, proc_root, bridge):
    require((proc_root / "1/comm").read_text().strip() == "systemd", "Full MuleLab process view is required")
    roots = checkout_routes(policy)
    bridge_pid, bridge_start = bridge
    bridge_proc = proc_root / str(bridge_pid)
    _require_bridge_identity(bridge_proc, policy.launch_uid, bridge_start)
    for proc in proc_root.iterdir():
        if not proc.name.isdecimal() or int(proc.name) in {os.getpid(), current_wrapper_pid}:
            continue
        try:
            if proc.stat().st_uid != policy.launch_uid:
                continue
            permission_gap = False

            def inspect(reader):
                nonlocal permission_gap
                try:
                    return reader()
                except PermissionError:
                    permission_gap = True
                    return None

            args = inspect(lambda: proc_args(proc))
            if args is not None and not args[0]:
                continue
            arguments = args or ()
            if int(proc.name) == bridge_pid:
                require(arguments == BRIDGE_ARGS, "Bridge arguments changed during route inspection")
                arguments = arguments[1:]
            require(not any(in_route(arg, roots) for arg in arguments if arg),
                    f"Checkout process remains live (PID {proc.name})")
            cwd = inspect(lambda: os.readlink(proc / "cwd"))
            require(cwd is None or not in_route(cwd, roots),
                    f"Checkout process remains live (PID {proc.name})")
            for fd in inspect(lambda: list((proc / "fd").iterdir())) or ():
                try:
                    destination = inspect(lambda: os.readlink(fd))
                    require(destination is None or not in_route(destination, roots),
                            f"Checkout descriptor remains open (PID {proc.name})")
                except FileNotFoundError:
                    continue
            if permission_gap:
                for item in ("root", "exe"):
                    destination = inspect(lambda: os.readlink(proc / item))
                    require(destination is None or not in_route(destination, roots),
                            f"Checkout process remains live (PID {proc.name})")
                require(policy.ancillary_process_evidence is not None
                        and verify_ancillary_process(policy.ancillary_process_evidence, proc, policy.launch_uid,
                                                     policy.maintenance_id, roots) is True,
                        f"Checkout process metadata is unavailable (PID {proc.name})")
        except (FileNotFoundError, ProcessLookupError):
            require(not proc.exists(), f"Checkout process metadata is incomplete (PID {proc.name})")
            continue
    _require_bridge_identity(bridge_proc, policy.launch_uid, bridge_start)
