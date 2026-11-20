"""Fail-closed, read-only Sprint 4 site attestation core."""
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
import subprocess

from alternate_writer_witness import CoverPin, verify_cover


WRAPPER_UNIT = "wrapper-development-host.service"
SYNC_UNIT = "job-search-sync.service"
STAGES = {
    "preflight", "host-fenced", "held", "pre-publish", "published",
    "admitted", "before-host-reopen", "restoring", "restored",
}
REQUEST_FIELDS = {
    "schema", "nonce", "checkpoint", "project", "package", "marker",
    "backend", "target", "maintenance_id", "locks", "pycache_prefixes", "source_manifest_sha256",
}
UNIT_FIELDS = ("Id", "LoadState", "ActiveState", "MainPID", "ControlPID",
               "UnitFileState", "FragmentPath", "NeedDaemonReload", "ControlGroup")


@dataclass(frozen=True)
class SourceFile:
    digest: str
    mode: int
    uid: int


@dataclass(frozen=True)
class SitePolicy:
    project: Path
    marker: Path
    lock_paths: tuple[Path, ...]
    cache_prefixes: tuple[Path, ...]
    maintenance_id: str
    manifest_sha256: str
    systemctl: Path
    launch_uid: int
    wrapper_active: bool
    wrapper_enabled: str
    wrapper_unit_file: Path
    sync_unit_file: Path
    wrapper_args: tuple[str, ...]
    wrapper_cwd: Path
    wrapper_exe: Path
    wrapper_port: int
    wrapper_cgroup: Path
    before_host: SourceFile
    after_host: SourceFile
    alternate_roots: tuple[Path, ...]
    covers: tuple[CoverPin, ...]


def require(value, message):
    if not value:
        raise ValueError(message)


def stage_of(request, policy):
    require(set(request) == REQUEST_FIELDS, "Site request fields differ")
    require(request["schema"] == "sprint-4-host-check-v1" and request["backend"] == "sqlite"
            and request["project"] == str(policy.project) and request["marker"] == str(policy.marker)
            and request["locks"] == list(map(str, policy.lock_paths))
            and request["pycache_prefixes"] == list(map(str, policy.cache_prefixes))
            and request["maintenance_id"] == policy.maintenance_id
            and request["source_manifest_sha256"] == policy.manifest_sha256
            and bool(re.fullmatch(r"[0-9a-f]{64}", policy.manifest_sha256))
            and request["target"] in {"INSTALLED", "ROLLED_BACK"}
            and bool(re.fullmatch(r"[0-9a-f]{32}", request["nonce"])),
            "Site request identity differs from the approved policy")
    stage, separator, remainder = request["checkpoint"].partition(":")
    require(stage in STAGES and ((stage == "held" and separator and 1 <= len(remainder) <= 300)
                                or (stage != "held" and not separator)), "Unknown site release checkpoint")
    canonical = policy.project / "src/job_search_helper"
    parked = policy.project / "src/.s4-maintenance-package"
    allowed = ((canonical, parked) if stage == "host-fenced" else
               (parked,) if stage in {"held", "pre-publish"} else (canonical,))
    require(Path(request["package"]) in allowed, "Unexpected package route at site checkpoint")
    return stage


def unit_status(executable, unit):
    output = subprocess.check_output(
        [str(executable), "--user", "show", *(f"--property={field}" for field in UNIT_FIELDS), unit],
        text=True, timeout=5,
    )
    items = [line.split("=", 1) for line in output.splitlines()]
    values = dict(items)
    require(len(items) == len(values) and set(values) == set(UNIT_FIELDS) and values["Id"] == unit,
            "Unexpected user service identity")
    require(values["LoadState"] == "loaded" and values["NeedDaemonReload"] == "no"
            and values["ControlPID"] == "0", "User service is not in a stable state")
    return values


def active_wrapper_pid(policy, stage, wrapper, sync):
    require(sync["FragmentPath"] == str(policy.sync_unit_file) and sync["UnitFileState"] == "disabled"
            and sync["ActiveState"] == "inactive" and sync["MainPID"] == "0",
            "Synchronization service is not held")
    require(wrapper["FragmentPath"] == str(policy.wrapper_unit_file)
            and wrapper["UnitFileState"] == policy.wrapper_enabled, "Wrapper service routing changed")
    states = {"inactive"}
    if policy.wrapper_active and stage in {"preflight", "restored", "restoring"}:
        states = {"inactive", "active"} if stage == "restoring" else {"active"}
    require(wrapper["ActiveState"] in states, "Wrapper service activity differs from checkpoint")
    pid = int(wrapper["MainPID"])
    require((pid > 0) == (wrapper["ActiveState"] == "active"), "Wrapper service PID differs from its state")
    require(wrapper["ControlGroup"] in {"", str(policy.wrapper_cgroup)}
            and (not pid or wrapper["ControlGroup"] == str(policy.wrapper_cgroup)),
            "Wrapper service cgroup differs")
    return pid


def process_start(proc):
    return (proc / "stat").read_text().rsplit(")", 1)[1].split()[19]


def verify_wrapper_process(policy, pid, proc_root):
    process = proc_root / str(pid)
    first = process_start(process)
    args = tuple(os.fsdecode(arg) for arg in (process / "cmdline").read_bytes().rstrip(b"\0").split(b"\0"))
    require(process.stat().st_uid == policy.launch_uid and args == policy.wrapper_args
            and Path(os.readlink(process / "cwd")) == policy.wrapper_cwd
            and Path(os.readlink(process / "exe")) == policy.wrapper_exe
            and process_start(process) == first,
            "Running wrapper is not the approved launcher, interpreter and checkout")
    require(f"0::{policy.wrapper_cgroup}" in (process / "cgroup").read_text().splitlines(),
            "Wrapper process is outside its approved cgroup")
    return first


def socket_inodes(process):
    result = set()
    for descriptor in (process / "fd").iterdir():
        try:
            name = os.readlink(descriptor)
        except FileNotFoundError:
            continue
        match = re.fullmatch(r"socket:\[(\d+)]", name)
        if match:
            result.add(match[1])
    return result


def listening_inodes(proc_root, port):
    inodes = set()
    for protocol in ("tcp", "tcp6"):
        for line in (proc_root / "net" / protocol).read_text().splitlines()[1:]:
            fields = line.split()
            if fields[3] == "0A" and int(fields[1].rsplit(":", 1)[1], 16) == port:
                inodes.add(fields[9])
                require(protocol == "tcp" and fields[1].split(":")[0] == "0100007F",
                        "Wrapper listener is not confined to IPv4 loopback")
    return inodes


def verify_listener(policy, pid, proc_root):
    listening = listening_inodes(proc_root, policy.wrapper_port)
    if pid:
        require(bool(listening) and listening <= socket_inodes(proc_root / str(pid)),
                "Wrapper listener is missing or is owned by another process")
    else:
        require(not listening, "Wrapper listener survived the hold")


def in_route(text, checkout_roots):
    candidate = Path(text.removesuffix(" (deleted)"))
    return candidate.is_absolute() and any(candidate.is_relative_to(root) for root in checkout_roots)


def verify_route_drain(policy, current_wrapper_pid, proc_root):
    require((proc_root / "1/comm").read_text().strip() == "systemd", "Full MuleLab process view is required")
    roots = (policy.project, *policy.alternate_roots)
    for proc in proc_root.iterdir():
        if not proc.name.isdecimal() or int(proc.name) in {os.getpid(), current_wrapper_pid}:
            continue
        try:
            if proc.stat().st_uid != policy.launch_uid:
                continue
            args = (proc / "cmdline").read_bytes().split(b"\0")
            if not args[0]:
                continue
            cwd = os.readlink(proc / "cwd")
            require(not in_route(cwd, roots)
                    and not any(in_route(os.fsdecode(arg), roots) for arg in args if arg),
                    f"Checkout process remains live (PID {proc.name})")
            for fd in (proc / "fd").iterdir():
                try:
                    destination = os.readlink(fd)
                except FileNotFoundError:
                    continue
                require(not in_route(destination, roots),
                        f"Checkout descriptor remains open (PID {proc.name})")
        except (FileNotFoundError, ProcessLookupError):
            continue


def read_regular(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        attrs = os.fstat(stream.fileno())
        require(stat.S_ISREG(attrs.st_mode) and attrs.st_nlink == 1, "Site witness is not an ordinary file")
        data = stream.read()
        after = path.lstat()
        require(os.path.samestat(attrs, after) and attrs.st_ctime_ns == after.st_ctime_ns,
                "Site witness changed during the read")
    return data, attrs


def verify_host_path(policy, stage, target):
    host = policy.wrapper_cwd / "host_server.py"
    if stage in {"host-fenced", "held", "pre-publish", "published", "admitted", "before-host-reopen"}:
        require(not os.path.lexists(host), "Canonical wrapper entry must be absent")
    else:
        expect_after = (target == "INSTALLED") != (stage == "preflight")
        endpoint = policy.after_host if expect_after else policy.before_host
        data, attrs = read_regular(host)
        require(attrs.st_uid == endpoint.uid and stat.S_IMODE(attrs.st_mode) == endpoint.mode
                and sha256(data).hexdigest() == endpoint.digest,
                "Canonical wrapper source differs from the approved endpoint")


def verify_marker(policy, stage):
    exists = os.path.lexists(policy.marker)
    if stage in {"preflight", "restored"}:
        require(not exists, "Release marker exists outside its held window")
        return
    if stage == "restoring" and not exists:
        return
    data, attrs = read_regular(policy.marker)
    require(stat.S_IMODE(attrs.st_mode) == 0o600 and attrs.st_uid == policy.launch_uid
            and json.loads(data) == {"schema": "integration-release-journal-v1",
                                     "state": "FOUNDATION_MAINTENANCE",
                                     "maintenance_id": policy.maintenance_id},
            "Maintenance marker does not prove this release hold")


def attest(request, policy, verify_protected_state, *, proc_root=Path("/proc")):
    """Reply only after real, read-only observations and protected-state checks."""
    stage = stage_of(request, policy)
    require(policy.alternate_roots and len(set(policy.alternate_roots)) == len(policy.alternate_roots)
            and {pin.path for pin in policy.covers} == set(policy.alternate_roots)
            and len(policy.covers) == len(policy.alternate_roots),
            "An approved alternate writer route lacks a separate cover")
    for pin in policy.covers:
        require(not (policy.project.is_relative_to(pin.path) or pin.path.is_relative_to(policy.project)),
                "An alternate writer cover overlaps production")
        verify_cover(pin)
    verify_host_path(policy, stage, request["target"])
    verify_marker(policy, stage)
    wrapper = unit_status(policy.systemctl, WRAPPER_UNIT)
    sync = unit_status(policy.systemctl, SYNC_UNIT)
    pid = active_wrapper_pid(policy, stage, wrapper, sync)
    started = verify_wrapper_process(policy, pid, proc_root) if pid else None
    verify_listener(policy, pid, proc_root)
    verify_route_drain(policy, pid, proc_root)
    verify_protected_state(stage, request["target"])
    require(wrapper == unit_status(policy.systemctl, WRAPPER_UNIT)
            and sync == unit_status(policy.systemctl, SYNC_UNIT)
            and (not pid or verify_wrapper_process(policy, pid, proc_root) == started),
            "Launch runtime changed during site attestation")
    for pin in policy.covers:
        verify_cover(pin)
    verify_host_path(policy, stage, request["target"])
    verify_marker(policy, stage)
    return {**request, "verified": True}
