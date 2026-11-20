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
    maintenance_bundle: Path
    maintenance_exe: Path
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
    network_namespace: tuple[int, int]
    before_host: SourceFile
    after_host: SourceFile
    alternate_roots: tuple[Path, ...]
    covers: tuple[CoverPin, ...]
    source_paths: frozenset[str]


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
    held_checkpoints = {"controller", "entry", "before-journal", "before-INSTALLED",
                        "before-ROLLED_BACK", "verified-INSTALLED", "verified-ROLLED_BACK"}
    operation, _, source = remainder.partition(":")
    known_held = remainder in held_checkpoints or (
        operation in {"INSTALLING", "ROLLING_BACK"} and source in policy.source_paths)
    require(stage in STAGES and (known_held if stage == "held" else not separator),
            "Unknown site release checkpoint")
    canonical = policy.project / "src/job_search_helper"
    parked = policy.project / "src/.s4-maintenance-package"
    allowed = ((canonical, parked) if stage == "host-fenced" else
               (parked,) if stage in {"held", "pre-publish"} else (canonical,))
    require(request["package"] in {str(path) for path in allowed}, "Unexpected package route at site checkpoint")
    return stage


def unit_status(executable, unit):
    output = subprocess.check_output(
        [str(executable), "--user", "show", "--all", *(f"--property={field}" for field in UNIT_FIELDS), unit],
        text=True, stderr=subprocess.PIPE, timeout=5,
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


def proc_args(process):
    return tuple(os.fsdecode(arg) for arg in (process / "cmdline").read_bytes().rstrip(b"\0").split(b"\0"))


def namespace_pin(path):
    info = path.stat()
    return info.st_dev, info.st_ino


def verify_wrapper_process(policy, pid, proc_root):
    process = proc_root / str(pid)
    first = process_start(process)
    args = proc_args(process)
    require(process.stat().st_uid == policy.launch_uid and args == policy.wrapper_args
            and Path(os.readlink(process / "cwd")) == policy.wrapper_cwd
            and Path(os.readlink(process / "exe")) == policy.wrapper_exe
            and process_start(process) == first,
            "Running wrapper is not the approved launcher, interpreter and checkout")
    require(f"0::{policy.wrapper_cgroup}" in (process / "cgroup").read_text().splitlines(),
            "Wrapper process is outside its approved cgroup")
    require(namespace_pin(process / "ns/net") == policy.network_namespace,
            "Wrapper process is outside the approved network namespace")
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
    require(namespace_pin(proc_root / "self/ns/net") == policy.network_namespace,
            "Checker is outside the approved network namespace")
    listening = listening_inodes(proc_root, policy.wrapper_port)
    if pid:
        require(bool(listening) and listening <= socket_inodes(proc_root / str(pid)),
                "Wrapper listener is missing or is owned by another process")
        for process in proc_root.iterdir():
            if not process.name.isdecimal() or int(process.name) == pid:
                continue
            try:
                if process.stat().st_uid == policy.launch_uid:
                    require(not (socket_inodes(process) & listening),
                            "Wrapper listener is shared with another launch-account process")
            except (FileNotFoundError, ProcessLookupError):
                continue
    else:
        require(not listening, "Wrapper listener survived the hold")
    return listening


def in_route(text, checkout_roots):
    candidate = Path(text.removesuffix(" (deleted)"))
    return candidate.is_absolute() and any(candidate.is_relative_to(root) for root in checkout_roots)


def maintenance_process(policy, proc_root, pid, role):
    process = proc_root / str(pid)
    state = (process / "stat").read_text().rsplit(")", 1)[1].split()
    require(state[0] not in {"X", "Z"} and process.stat().st_uid == policy.launch_uid
            and Path(os.readlink(process / "exe")) == policy.maintenance_exe,
            "Unrecognized maintenance process identity")
    args = proc_args(process)
    script = str(policy.maintenance_bundle / role)
    require(args.count(script) == 1, "Unrecognized maintenance script")
    before = args[1:args.index(script)]
    require("-I" in before and set(before) <= {"-I", "-B"}, "Maintenance interpreter is not isolated")
    options = args[args.index(script) + 1:]
    if role == "controller.py":
        require(options in {("install",), ("rollback",)}, "Unrecognized controller operation")
    elif role == "verify_hold":
        require(not options, "Unrecognized verifier operation")
    else:
        require(options[:1] in {("install",), ("rollback",), ("verify",)}
                and "--parked-package" in options and "--fenced-host" in options,
                "Unrecognized installer operation")
        pinned = {"--project": str(policy.project), "--marker": str(policy.marker),
                  "--gate": str(policy.maintenance_bundle / "installer.lock"),
                  "--state": str(policy.maintenance_bundle / "transaction"),
                  "--verifier": str(policy.maintenance_bundle / "verify_hold"),
                  "--manifest": str(policy.maintenance_bundle / "manifest.json"),
                  "--manifest-sha256": policy.manifest_sha256, "--hold-id": policy.maintenance_id}
        for flag, argument in pinned.items():
            require(options.count(flag) == 1 and options[options.index(flag) + 1:options.index(flag) + 2] == (argument,),
                    "Installer argument differs from the approved transaction")
    require(process_start(process) == state[19], "Maintenance process changed during attestation")
    return int(state[1]), state[19]


def verify_flocks(proc_root, pid, paths):
    owners = set()
    for line in (proc_root / "locks").read_text().splitlines():
        fields = line.split()
        if len(fields) >= 8 and fields[1:4] == ["FLOCK", "ADVISORY", "WRITE"]:
            major, minor, inode = fields[5].split(":")
            owners.add((int(fields[4]), int(major, 16), int(minor, 16), int(inode)))
    for path in paths:
        info = path.lstat()
        require((pid, os.major(info.st_dev), os.minor(info.st_dev), info.st_ino) in owners,
                "Maintenance process does not own its expected lock")


def authenticated_maintenance(policy, request, stage, proc_root, caller_pid):
    require(policy.lock_paths, "Maintenance lock policy is empty")
    pids = {}
    if stage == "held" and request["checkpoint"] != "held:controller":
        installer_pid, verifier_start = maintenance_process(policy, proc_root, caller_pid, "verify_hold")
        controller_pid, installer_start = maintenance_process(policy, proc_root, installer_pid, "installer.py")
        pids[caller_pid] = (verifier_start, "verify_hold")
        pids[installer_pid] = (installer_start, "installer.py")
        verify_flocks(proc_root, installer_pid, (policy.maintenance_bundle / "installer.lock",))
    else:
        controller_pid = caller_pid
    _, controller_start = maintenance_process(policy, proc_root, controller_pid, "controller.py")
    pids[controller_pid] = (controller_start, "controller.py")
    verify_flocks(proc_root, controller_pid, (*policy.lock_paths, policy.maintenance_bundle / "controller.lock"))
    return pids


def maintenance_descriptor(policy, descriptor, destination, role):
    path = Path(destination)
    if destination in set(map(str, policy.lock_paths)):
        expected_kind = stat.S_ISREG
    else:
        directories = {
            "installer.py": (".", "src", "src/job_search_helper", "src/.s4-maintenance-package",
                             "dev", "dev/wrapper-coder", "dev/wrapper-coder/tools"),
            "controller.py": (".", "dev", "dev/wrapper-coder", "dev/wrapper-coder/tools"),
        }
        if destination not in {str(policy.project / part) for part in directories.get(role, ())}:
            return False
        expected_kind = stat.S_ISDIR
    attrs = descriptor.stat()
    try:
        named = path.lstat()
    except FileNotFoundError:
        raise ValueError("Authenticated maintenance descriptor has lost its named endpoint") from None
    return expected_kind(attrs.st_mode) and os.path.samestat(attrs, named)


def verify_route_drain(policy, current_wrapper_pid, proc_root, maintenance=None):
    require((proc_root / "1/comm").read_text().strip() == "systemd", "Full MuleLab process view is required")
    roots = (policy.project, *policy.alternate_roots)
    maintenance = {} if maintenance is None else maintenance
    for proc in proc_root.iterdir():
        if not proc.name.isdecimal() or int(proc.name) in {os.getpid(), current_wrapper_pid}:
            continue
        try:
            if proc.stat().st_uid != policy.launch_uid:
                continue
            args = proc_args(proc)
            if not args[0]:
                continue
            authorized = maintenance.get(int(proc.name))
            role = None
            if authorized is not None:
                start, role = authorized
                require(process_start(proc) == start, "Maintenance process changed before drain check")
            permitted_args = {str(policy.project), str(policy.marker)} if role == "installer.py" else set()
            cwd = os.readlink(proc / "cwd")
            require(not in_route(cwd, roots)
                    and not any(in_route(arg, roots) and arg not in permitted_args for arg in args if arg),
                    f"Checkout process remains live (PID {proc.name})")
            for fd in (proc / "fd").iterdir():
                try:
                    destination = os.readlink(fd)
                    require(not in_route(destination, roots)
                            or (role is not None and maintenance_descriptor(policy, fd, destination, role)),
                            f"Checkout descriptor remains open (PID {proc.name})")
                except FileNotFoundError:
                    continue
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


def attest(request, policy, verify_protected_state, *, verify_launcher=None, proc_root=Path("/proc")):
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
    if stage == "restoring" and pid:
        require(not os.path.lexists(policy.marker), "A restored wrapper is running behind a maintenance marker")
    started = verify_wrapper_process(policy, pid, proc_root) if pid else None
    caller = os.getppid()
    maintenance = authenticated_maintenance(policy, request, stage, proc_root, caller)
    listening = verify_listener(policy, pid, proc_root)
    verify_route_drain(policy, pid, proc_root, maintenance)
    verify_protected_state(stage, request["target"])
    if verify_launcher is not None:
        verify_launcher(stage, request["target"])
    require(wrapper == unit_status(policy.systemctl, WRAPPER_UNIT)
            and sync == unit_status(policy.systemctl, SYNC_UNIT)
            and (not pid or verify_wrapper_process(policy, pid, proc_root) == started),
            "Launch runtime changed during site attestation")
    for pin in policy.covers:
        verify_cover(pin)
    verify_host_path(policy, stage, request["target"])
    verify_marker(policy, stage)
    if stage == "restoring" and pid:
        require(not os.path.lexists(policy.marker), "A restored wrapper is running behind a maintenance marker")
    require(authenticated_maintenance(policy, request, stage, proc_root, caller) == maintenance,
            "Maintenance process ownership changed during site attestation")
    require(verify_listener(policy, pid, proc_root) == listening, "Wrapper listener changed during site attestation")
    verify_route_drain(policy, pid, proc_root, maintenance)
    return {**request, "verified": True}
