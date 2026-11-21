#!/usr/bin/python3 -I
"""Resume an exact Sprint 4 maintenance window from a private durable bundle.

Place these four tools, candidate/, plan.json, manifest.json and a trusted executable
host-check together in a 0700 directory outside the checkout on its mount.
Run controller.py install or controller.py rollback. Repeat the same command
after interruptions. Rollback can also reverse an in-progress installation.
All files and locks named by the plan must have their normal production meaning.

plan.json fields: project (absolute checkout), hold_id, unit_directory
(absolute persistent user-unit directory), systemctl (absolute systemctl),
pycache_prefixes (a list of absolute audited PYTHONPYCACHEPREFIX paths), and
manifest_sha256 (the independently approved SHA-256 of manifest.json).
Under every effective launch environment resolve the same runtime state and
storage backend and enumerate every cache prefix. The default resolution is
independently derived from the project's .env and .storage-backend.

host-check receives a JSON request and returns that exact object plus
"verified":true. It is a trusted external host-specific check, never a dummy
acknowledgment. The request includes checkpoint, nonce, project, package,
marker, backend, lock paths, cache prefixes and target. Required checkpoints:

* preflight: inventory launch/writer routes and effective environments,
  exclude alternate checkouts and external writers, check accepted base
  prerequisites, and establish ongoing exclusion of source editors.
* held:<installer checkpoint> and held:controller: verify continuing
  exclusion and census of consumers/source writers. Controller checks the
  loaded user-unit conditions, drained cgroups, and lock ownership itself.
* pre-publish: verify parked target launcher and resolution behavior with
  credential-free checks while the real runtime remains held.
* published: verify canonical fresh-import refusal and use an explicit,
  isolated source loader for positive read-only checks while held.
* admitted: verify ordinary canonical launches using read-only probes after
  the extension guard is removed and while the service and journal holds remain.

The host check must complete promptly (five seconds per invocation), and its
policy and side inputs must persist across process restart and reboot.
The hidden import-guard package remains parked after release to preserve
the journal-bound guard inode for a subsequent rollback.
"""
from contextlib import ExitStack, contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import signal
import stat
import subprocess
import sys
import tempfile
from io import BytesIO
from zipfile import ZipFile

sys.dont_write_bytecode = True
BUNDLE = Path(__file__).resolve().parent
sys.path.insert(0, str(BUNDLE))

import gate
import installer


UNITS = ("wrapper-development-host.service", "job-search-sync.service")
DROP_IN = "zzzz-job-search-sprint4-maintenance.conf"
MARKER_NAME = "integration-release-journal.json"
STATE_NAME = "controller.json"
LOCK_EX = fcntl.LOCK_EX | fcntl.LOCK_NB
PHASES = {"CLOSING", "HELD", "PUBLISHING", "PUBLISHED", "ADMISSION_READY",
          "HOST_REOPEN", "REHOLDING", "RELEASING", "RELEASE_REFUSED", "RELEASED"}
EXTENSION = "__init__.so"
EXTENSION_MODE = 0o444
STAGED_EXTENSION = "admission-guard.pending"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def present(path):
    return os.path.lexists(path)


def physical(path, *, optional=False):
    require(path.is_absolute() and path.resolve(strict=not optional) == path,
            f"Expected canonical absolute path: {path}")
    return path


def read(path):
    with installer.directory(path.parent) as parent:
        return installer.read_file(parent, path.name)


def inode(path):
    return installer.identity(path.lstat())


def mount(path):
    with installer.directory(path) as fd:
        return installer.mount_id(fd)


def ref(path):
    data, attrs = read(physical(path))
    return file_reference(data, attrs)


def file_reference(data, attrs):
    return [*installer.identity(attrs), stat.S_IMODE(attrs.st_mode),
            *installer.ownership(attrs), installer.digest(data)]


def sync_file(path):
    fd = os.open(path, installer.READ)
    try:
        st = os.fstat(fd)
        require(stat.S_ISREG(st.st_mode) and st.st_nlink == 1, f"Unsafe durable input: {path}")
        os.fsync(fd)
    finally:
        os.close(fd)


def sync_unlink(path):
    path.unlink()
    gate.syncdir(path.parent)


def private_dir(path):
    physical(path)
    st = path.lstat()
    require(stat.S_ISDIR(st.st_mode) and stat.S_IMODE(st.st_mode) == 0o700
            and st.st_uid == os.geteuid(), f"Expected a private directory: {path}")


def write(path, data, mode=0o600, *, replace=False):
    # A temp file can survive SIGKILL but cannot be mistaken for any journal.
    fd, name = tempfile.mkstemp(prefix=".sprint-4-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fchmod(handle.fileno(), mode)
            os.fsync(handle.fileno())
        if replace:
            os.replace(temporary, path)
            gate.syncdir(path.parent)
        else:
            gate.rename(temporary, path, 1)  # RENAME_NOREPLACE
    finally:
        if present(temporary):
            sync_unlink(temporary)


def read_object(path):
    raw, _ = read(path)
    result = json.loads(raw)
    require(isinstance(result, dict), f"Expected a JSON object: {path}")
    return result


def ensure_file(path, data, mode=0o600):
    if not present(path):
        write(path, data, mode)
    check_file(path, data, mode)
    gate.syncdir(path.parent)


def check_file(path, data, mode):
    actual, st = read(physical(path))
    require(actual == data and stat.S_IMODE(st.st_mode) == mode
            and st.st_uid == os.geteuid(), f"Conflicting file: {path}")


@contextmanager
def lock(path):
    fd = os.open(physical(path), os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        st = os.fstat(fd)
        require(stat.S_ISREG(st.st_mode) and st.st_nlink == 1
                and st.st_uid == os.geteuid(), f"Unsafe lock: {path}")
        fcntl.flock(fd, LOCK_EX)
        require(inode(path) == installer.identity(st), f"Lock was replaced: {path}")
        yield fd
    finally:
        os.close(fd)


def proc_stat(pid):
    stat_fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    require(stat_fields[0] not in {"Z", "X"}, "Maintenance controller exited")
    return stat_fields


def proc_owner(pid):
    stat_fields = proc_stat(pid)
    boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    return [boot, pid, int(stat_fields[19])]


def locked_by(pid, paths):
    have = set()
    for line in Path("/proc/locks").read_text().splitlines():
        fields = line.split()
        if len(fields) >= 8 and fields[1:4] == ["FLOCK", "ADVISORY", "WRITE"]:
            major, minor, number = fields[5].split(":")
            have.add((int(fields[4]), int(major, 16), int(minor, 16), int(number)))
    for path in paths:
        device, number = inode(path)
        require((pid, os.major(device), os.minor(device), number) in have,
                f"Controller no longer owns lock: {path}")


def backend(project):
    # Match both standard-library bootstraps without importing runtime source.
    env = {}
    dotenv = project / ".env"
    if present(dotenv):
        for raw in read(dotenv)[0].decode().splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            require("=" in line, "Malformed runtime environment")
            name, value = (part.strip() for part in line.split("=", 1))
            require(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name), "Malformed environment key")
            if value.startswith(("'", '"')):
                require(len(value) >= 2 and value[0] == value[-1], "Malformed environment value")
                value = value[1:-1]
            env.setdefault(name, value)
    default = project / ".storage-backend"
    default_backend = read(default)[0].decode().strip() if present(default) else "sheets"
    store = os.environ.get("JOB_STORAGE_BACKEND", env.get("JOB_STORAGE_BACKEND", default_backend)).strip().lower()
    require(store in {"sqlite", "sheets"}, "Unknown storage backend")
    state = Path(os.environ.get("STATE_DB_FILE", env.get("STATE_DB_FILE", ".state/state.db"))).expanduser()
    path = physical(project / state, optional=True)
    root = physical(path.parent)
    names = ("scraper.lock", "writer.lock", "review-writeback.lock") if store == "sqlite" else ("writer.lock",)
    return store, root / MARKER_NAME, [root / name for name in names]


def scope(project, parked, paths, owners=None):
    with installer.source_tree(project, parked) as tree:
        result = {}
        for path in paths:
            snapshot = installer.read_optional(*installer.entry(tree, path))
            if owners is not None and snapshot is not None:
                require(installer.ownership(snapshot[1]) == owners[path], f"Scoped source owner differs: {path}")
            result[path] = installer.optional_version(snapshot)
        return result


def unscoped(package, scoped, *, guarded=False):
    result = {}
    for parent, dirs, files in os.walk(package, followlinks=False):
        dirs[:] = sorted(name for name in dirs if name != "__pycache__")
        for name in sorted(dirs + files):
            path = Path(parent) / name
            relative = path.relative_to(package).as_posix()
            if relative in scoped or relative.endswith(".pyc") or (guarded and relative == EXTENSION):
                continue
            st = path.lstat()
            result[relative] = (["directory", *installer.identity(st), stat.S_IMODE(st.st_mode),
                                 *installer.ownership(st)] if stat.S_ISDIR(st.st_mode)
                                else [*ref(path), st.st_mtime_ns])
    return installer.digest(installer.encode(result))


def extension_present(parent):
    # Include the generic and all ABI-tagged Linux loader suffixes, not
    # just those of the Python interpreter running the controller.
    initializers = {name for name in os.listdir(parent)
                    if name.startswith("__init__.") and name.endswith(".so")}
    require(initializers <= {EXTENSION}, "Unexpected extension initializer")
    return EXTENSION in initializers


def extension_identity(parent, name, links):
    fd = os.open(name, installer.READ, dir_fd=parent)
    try:
        st = os.fstat(fd)
        require(stat.S_ISREG(st.st_mode) and st.st_size == 0 and st.st_nlink == links
                and stat.S_IMODE(st.st_mode) == EXTENSION_MODE and st.st_uid == os.geteuid(),
                "Unsafe transient import guard")
        after = os.stat(name, dir_fd=parent, follow_symlinks=False)
        require(os.path.samestat(st, after) and st.st_ctime_ns == after.st_ctime_ns,
                "Transient import guard changed during verification")
        return [*installer.identity(st), *installer.ownership(st)]
    finally:
        os.close(fd)


def purge_bytecode(project, package, prefixes, paths):
    dirs = {}
    original, parked = gate.paths(project)
    for scoped_path in paths:
        source = Path(scoped_path)
        if source.suffix != ".py":
            continue
        stem = source.stem
        location = installer.source_location(scoped_path)
        if location == "package":
            local, source_dirs = package, (original, parked)
        elif location == "tools":
            local = project / installer.WRAPPER_PARENT
            source_dirs = (local,)
        else:
            local, source_dirs = project, (project,)
        dirs.setdefault(local / "__pycache__", set()).add(stem)
        legacy = local / (stem + ".pyc")
        if present(legacy):
            read(legacy)
            sync_unlink(legacy)
        for cache in prefixes:
            for parent in source_dirs:
                dirs.setdefault(cache / parent.relative_to("/"), set()).add(stem)
    for path, stems in dirs.items():
        if not present(path):
            continue
        physical(path)
        for item in path.iterdir():
            if item.suffix == ".pyc" and item.name.split(".", 1)[0] in stems:
                read(item)
                sync_unlink(item)
        gate.syncdir(path)


class Systemd:
    PROPERTIES = ("Id", "LoadState", "ActiveState", "SubState", "UnitFileState", "MainPID",
                  "ControlPID", "ControlGroup", "FragmentPath", "DropInPaths", "NeedDaemonReload")

    def __init__(self, exe, directory, sentinel):
        self.exe, self.directory, self.sentinel = exe, directory, sentinel
        require(re.fullmatch(r"/[A-Za-z0-9_./-]+", str(sentinel)),
                "Bundle path is unsafe for a systemd condition")
        self.data = f"[Unit]\nConditionPathExists=!{sentinel}\n".encode()

    def command(self, *args, timeout=5):
        return subprocess.run([str(self.exe), "--user", *args], check=True, capture_output=True,
                              text=True, timeout=timeout).stdout

    def status(self):
        raw = self.command("show", "--all", *(f"--property={name}" for name in self.PROPERTIES), *UNITS)
        units = {}
        for block in raw.strip().split("\n\n"):
            values = dict(line.split("=", 1) for line in block.splitlines())
            require(set(values) == set(self.PROPERTIES), "Incomplete user-unit status")
            require(values["LoadState"] == "loaded" and values["NeedDaemonReload"] == "no",
                    f"Unexpected configuration state for {values['Id']}")
            units[values["Id"]] = values
        require(set(units) == set(UNITS), "Unexpected user units returned")
        return units

    def path(self, unit):
        return self.directory / f"{unit}.d" / DROP_IN

    def snapshot(self):
        units = self.status()
        prior = {}
        for name, unit in units.items():
            require(not present(self.path(name)), f"Conflicting service hold: {name}")
            active = unit["ActiveState"]
            require(active in {"active", "inactive"}, f"Unsettled service: {name}")
            if name == UNITS[1]:
                require(active == "inactive" and unit["UnitFileState"] == "disabled",
                        "Sync must be inactive and disabled at entry")
            elif active == "active":
                require(unit["ControlGroup"], "Active wrapper has no auditable cgroup")
            prior[name] = {"active": active, "enabled": unit["UnitFileState"],
                           "cgroup": unit["ControlGroup"], "files": self.files(unit),
                           "had_dropin_directory": present(self.path(name).parent)}
        return prior

    def files(self, unit):
        paths = [unit["FragmentPath"], *unit["DropInPaths"].split()]
        return {value: ref(Path(value)) for value in paths if value != str(self.path(unit["Id"]))}

    def check_status(self, prior, *, held, restored=False):
        units = self.status()
        for name, unit in units.items():
            expected = prior[name]
            loaded = unit["DropInPaths"].split()
            hold_path = self.path(name)
            require((str(hold_path) in loaded) == held
                    and self.files(unit) == expected["files"]
                    and unit["UnitFileState"] == expected["enabled"],
                    f"Effective unit configuration changed: {name}")
            if held:
                require(loaded[-1] == str(hold_path), f"Maintenance condition may be overridden: {name}")
                check_file(hold_path, self.data, 0o644)
            if held or restored:
                wanted = "inactive" if held else expected["active"]
                require(unit["ActiveState"] == wanted, f"Unexpected service activity: {name}")
                if wanted == "inactive":
                    require(unit["MainPID"] == unit["ControlPID"] == "0",
                            f"Service process still present: {name}")
                    for group in {expected["cgroup"], unit["ControlGroup"]} - {""}:
                        self.check_cgroup(group)
        return units

    @staticmethod
    def check_cgroup(group):
        path = Path(group)
        require(path.is_absolute() and ".." not in path.parts and path != Path("/"),
                "Invalid systemd cgroup path")
        require(Path("/sys/fs/cgroup/cgroup.controllers").is_file(), "cgroup v2 cannot be inspected")
        members = Path("/sys/fs/cgroup") / path.relative_to("/") / "cgroup.events"
        try:
            data = members.read_text().splitlines()
        except FileNotFoundError:
            return
        require("populated 0" in data, f"User service cgroup is not drained: {group}")

    def close(self, prior):
        ensure_file(self.sentinel, b"")
        for unit in UNITS:
            path = self.path(unit)
            path.parent.mkdir(exist_ok=True, mode=0o755)
            physical(path.parent)
            gate.syncdir(path.parent.parent)
            ensure_file(path, self.data, 0o644)
        self.command("daemon-reload", timeout=30)
        self.command("stop", *UNITS, timeout=85)
        self.check_status(prior, held=True)

    def verify(self, prior):
        check_file(self.sentinel, b"", 0o600)
        self.check_status(prior, held=True)

    def restore(self, prior):
        for unit in UNITS:
            path = self.path(unit)
            if present(path):
                check_file(path, self.data, 0o644)
                sync_unlink(path)
            if not prior[unit]["had_dropin_directory"] and present(path.parent):
                physical(path.parent)
                path.parent.rmdir()
                gate.syncdir(path.parent.parent)
        self.command("daemon-reload", timeout=30)
        units = self.check_status(prior, held=False)
        if present(self.sentinel):
            check_file(self.sentinel, b"", 0o600)
            sync_unlink(self.sentinel)
        if prior[UNITS[0]]["active"] == "active" and units[UNITS[0]]["ActiveState"] != "active":
            self.command("start", UNITS[0], timeout=45)
        self.check_status(prior, held=False, restored=True)


class Controller:
    def __init__(self, bundle):
        self.bundle = bundle
        private_dir(bundle)
        plan_path = bundle / "plan.json"
        plan_data, plan_info = read(plan_path)
        plan = json.loads(plan_data)
        require(type(plan) is dict, "Unexpected maintenance plan")
        approved_plan = file_reference(plan_data, plan_info)
        plan_fields = {"project", "hold_id", "unit_directory", "systemctl", "pycache_prefixes", "manifest_sha256"}
        require(set(plan) in (plan_fields, plan_fields | {"predecessor_guard_sha256"}),
                "Unexpected maintenance plan fields")
        self.manifest_path = bundle / "manifest.json"
        self.manifest = installer.load_manifest(self.manifest_path, plan["manifest_sha256"])
        self.project = physical(Path(plan["project"]))
        self.hold_id = plan["hold_id"]
        require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", self.hold_id),
                "Invalid hold ID")
        self.prefixes = [physical(Path(path), optional=True) for path in plan["pycache_prefixes"]]
        current_prefix = os.environ.get("PYTHONPYCACHEPREFIX")
        require(not current_prefix or Path(current_prefix) in self.prefixes, "Unlisted cache prefix")
        self.backend, self.marker, app_locks = backend(self.project)
        installer.independent(self.project, bundle)
        installer.independent(self.marker.parent, bundle)
        self.canonical, self.parked = gate.paths(self.project)
        self.wrapper_tools = self.project / installer.WRAPPER_PARENT
        self.package_names = {Path(path).name for path in self.manifest.paths
                              if installer.source_location(path) == "package"}
        self.wrapper_names = {Path(path).name for path in installer.WRAPPER_PATHS}
        self.install_gate = bundle / "installer.lock"
        self.controller_gate = bundle / "controller.lock"
        self.journal = bundle / STATE_NAME
        self.state = bundle / "transaction"
        self.candidate = bundle / "candidate"
        self.verifier = bundle / "verify_hold"
        self.checker = bundle / "host-check"
        self.marker_data = installer.encode({"schema": "integration-release-journal-v1",
                                             "state": "FOUNDATION_MAINTENANCE",
                                             "maintenance_id": self.hold_id})
        unit_directory = physical(Path(plan["unit_directory"]))
        exe = physical(Path(plan["systemctl"]))
        self.units = Systemd(exe, unit_directory, bundle / "service-hold")
        self.locks = [self.project / ".integration-install.lock", *app_locks]
        config_files = [self.project / name for name in (".env", ".storage-backend")]
        self.tool_files = [bundle / name for name in ("controller.py", "verify_hold", "gate.py",
                                                      "installer.py", "host-check", "plan.json", "manifest.json")]
        self.predecessor = None
        approved_handoff = None
        if "predecessor_guard_sha256" in plan:
            handoff = bundle / "predecessor-guard.json"
            raw, attrs = read(handoff)
            require(stat.S_IMODE(attrs.st_mode) == 0o600 and attrs.st_uid == os.geteuid()
                    and attrs.st_nlink == 1 and installer.digest(raw) == plan["predecessor_guard_sha256"],
                    "Predecessor guard approval differs")
            predecessor = json.loads(raw)
            require(type(predecessor) is dict and set(predecessor) == {"schema", "observed", "successor"}
                    and predecessor["schema"] == "s4-predecessor-guard-handoff-v1"
                    and installer.encode(predecessor) == raw, "Malformed predecessor guard approval")
            self.predecessor = predecessor
            approved_handoff = file_reference(raw, attrs)
            self.tool_files.append(handoff)
        files = {str(p): ref(p) for p in [*self.tool_files, exe, *filter(present, config_files)]}
        require(files[str(plan_path)] == approved_plan, "Maintenance plan changed during enrollment")
        if approved_handoff is not None:
            require(files[str(handoff)] == approved_handoff, "Predecessor guard approval changed during enrollment")
        require(os.access(self.checker, os.X_OK) and os.access(self.verifier, os.X_OK),
                "Verifier and host-check must be executable")
        source = self.project / "src"
        fixed_directories = (bundle, self.project, source, self.marker.parent,
                             self.project / "dev", self.wrapper_tools.parent, self.wrapper_tools)
        paths = [*fixed_directories, self.canonical]
        if present(self.parked):
            paths.append(self.parked)
        require(len({mount(path) for path in paths}) == 1, "Source and durable state mounts differ")
        self.binding = {"schema": "sprint-4-controller-v1",
                        "files": files, "project": str(self.project), "hold_id": self.hold_id,
                        "directories": {str(p): inode(p) for p in
                                        (*fixed_directories, unit_directory)},
                        "backend": self.backend, "marker": str(self.marker),
                        "locks": {str(path): inode(physical(path)) for path in self.locks}}

    def inherited_guard(self):
        if self.predecessor is None:
            return None
        guard = self.predecessor["observed"]["guard"]
        return {"directory": guard["directory"], "marker": guard["marker"]}

    @staticmethod
    def checker_policy(data):
        with ZipFile(BytesIO(data)) as source:
            return json.loads(source.read("approved_site_policy.json"))

    def inherited_guard_options(self):
        guard = self.inherited_guard()
        return {} if guard is None else {"approved_guard": guard}

    def checked_tool(self, path):
        data, attributes = read(physical(path))
        require(file_reference(data, attributes) == self.binding["files"][str(path)],
                "Approved maintenance tool changed")
        return data

    def verify_preinstall_parked(self):
        if self.predecessor is None:
            require(not present(self.parked), "Unexpected preinstall parked package")
            return None
        approval = self.predecessor
        observed = approval["observed"]
        successor = approval["successor"]
        require(observed["schema"] == "s4-observed-terminal-guard-v1"
                and observed["view"] == "PREDECESSOR_ONLY" and observed["guard_path"] == str(self.parked),
                "Predecessor guard is for another source")
        policy = self.checker_policy(self.checked_tool(self.checker))
        site = policy["site"]
        handoff = self.bundle / "predecessor-guard.json"
        require(ref(handoff) == self.binding["files"][str(handoff)]
                and ref(self.checker) == self.binding["files"][str(self.checker)],
                "Handoff file or current checker changed")
        fence = site["exchange_fence"]
        expected = {"bundle": str(self.bundle), "bundle_identity": inode(self.bundle),
                    "hold_id": self.hold_id, "checker_sha256": self.binding["files"][str(self.checker)][-1],
                    "manifest_sha256": self.manifest.sha256, "exchange": fence}
        require(successor == expected and site["maintenance_bundle"] == str(self.bundle)
                and site["maintenance_id"] == self.hold_id and site["project"] == str(self.project)
                and site["manifest_sha256"] == self.manifest.sha256, "Handoff belongs to another successor")

        old_path = physical(Path(observed["predecessor"]))
        require(old_path != self.bundle, "Cannot reuse the previous controller")
        old = Controller(old_path)
        terminal = old.load(canonical=True)
        require(old.project == self.project and old.hold_id != self.hold_id and terminal["target"] == "ROLLED_BACK"
                and isinstance(terminal["receipt"], dict) and terminal["receipt"].get("phase") == "ROLLED_BACK",
                "Predecessor did not complete an independent rollback")
        old.verify_released_source(terminal)
        prior = {"maintenance_id": old.hold_id, "project": str(old.project), "source": terminal["target"],
                 "source_manifest_sha256": old.manifest.sha256,
                 "controller_journal_sha256": installer.digest(installer.encode(terminal)),
                 "installer_receipt_sha256": installer.digest(installer.encode(terminal["receipt"]))}
        require(prior == observed["terminal_release"] and terminal["original"] == observed["source_identity"],
                "Predecessor receipt or original source identity changed")
        old_policy = self.checker_policy(old.checked_tool(old.checker))
        old_fence = old_policy["site"]["exchange_fence"]
        pinned = observed["protected_pin"]
        for archived in (old_policy, policy):
            require({"path": archived["protected_pin_file"], "sha256": archived["protected_pin_sha256"]} == pinned,
                    "Successor must retain the exact original protected baseline")
        require(ref(Path(pinned["path"]))[-1] == pinned["sha256"]
                and installer.digest(read(old.state / installer.JOURNAL)[0]) == observed["installer_journal_sha256"],
                "Predecessor protected or installer journal bytes changed")
        historical = observed["restored_exchange"]
        prior_policy = physical(Path(old_fence["policy_file"]))
        fresh_policy = physical(Path(fence["policy_file"]))
        require(prior_policy.parent != fresh_policy.parent
                and installer.digest(read(prior_policy)[0]) == old_fence["policy_sha256"]
                and installer.digest(read(fresh_policy)[0]) == fence["policy_sha256"],
                "Predecessor exchange policy changed or was reused")
        raw = read(prior_policy.with_name("exchange.json"))[0]
        exchange = json.loads(raw)
        require(installer.digest(raw) == historical["journal_sha256"] and exchange["phase"] == "restored"
                and exchange["completed"] == len(fence["pairs"]) == len(old_fence["pairs"])
                and exchange["terminal_proof_sha256"] == historical["terminal_sha256"]
                and exchange["intent_sha256"] == historical["intent_sha256"] == old_fence["intent_sha256"]
                and historical["policy_sha256"] == old_fence["policy_sha256"] != fence["policy_sha256"]
                and historical["generation"] == old_fence["generation"] != fence["generation"]
                and old_fence["pairs"] == fence["pairs"], "Predecessor restored alternate evidence changed")
        guard = self.inherited_guard()
        gate.verify_guard_identity(self.parked, guard)
        require(inode(self.canonical) == observed["source_identity"] and terminal["guard"] == guard["directory"][:2]
                and mount(self.parked) == observed["guard"]["mount"] == mount(self.canonical)
                and inode(self.parked.parent) == observed["guard"]["parent"]
                and installer.digest(read(self.parked / "__init__.py")[0]) == observed["guard"]["marker_sha256"],
                "Inherited guard or original package changed")
        return guard["directory"][:2]

    def hook(self, checkpoint, *, package, target=None):
        request = {"schema": "sprint-4-host-check-v1", "nonce": secrets.token_hex(16),
                   "checkpoint": checkpoint, "project": str(self.project), "package": str(package),
                   "marker": str(self.marker), "backend": self.backend, "target": target,
                   "maintenance_id": self.hold_id, "locks": list(map(str, self.locks)),
                   "pycache_prefixes": list(map(str, self.prefixes)),
                   "source_manifest_sha256": self.manifest.sha256}
        environment = {**os.environ, "JSH_F3_HOST_PHASE": checkpoint.split(":", 1)[0]}
        short_checkpoint = checkpoint.startswith("held:") and checkpoint != "held:controller"
        timeout = 5 if short_checkpoint else 180
        require(ref(self.checker) == self.binding["files"][str(self.checker)],
                "Pinned host checker changed")
        with subprocess.Popen([str(self.checker)], cwd="/", env=environment, start_new_session=True,
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE) as child:
            try:
                output, _ = child.communicate(installer.encode(request), timeout=timeout)
            except subprocess.TimeoutExpired as error:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.communicate()
                raise ValueError("Host checker exceeded its checkpoint deadline") from error
            require(child.returncode == 0, f"Host checker refused {checkpoint}")
        value = json.loads(output)
        require(value == {**request, "verified": True} and value.get("verified") is True,
                f"Host check did not confirm {checkpoint}")

    def load(self, *, canonical=False):
        raw, _ = read(self.journal)
        record = json.loads(raw)
        require(isinstance(record, dict), "Expected a controller journal object")
        if canonical:
            require(installer.encode(record) == raw, "Controller journal bytes are not canonical")
        phase = record.get("phase")
        require(record.get("binding") == self.binding and phase in PHASES,
                "Controller journal does not match this host, bundle or source checkout")
        require(record.get("host_exposed_before_hold") in {"before", "after"},
                "Controller journal is missing the wrapper host closure pin")
        require(record.get("guard") is None or isinstance(record["guard"], list),
                "Invalid import guard identity")
        inherited = self.inherited_guard()
        require(inherited is None or record["guard"] == inherited["directory"][:2],
                "Journal disagrees with the approved predecessor guard")
        extension = record["admission_guard"]
        if extension is not None:
            require(isinstance(extension, dict) and set(extension) == {"file"},
                    "Invalid transient import guard record")
            identity = extension["file"]
            require(identity is None or (isinstance(identity, list) and len(identity) == 4
                    and all(type(value) is int and value >= 0 for value in identity)),
                    "Invalid transient import guard identity")
        if phase in {"PUBLISHED", "ADMISSION_READY", "HOST_REOPEN", "RELEASING", "RELEASE_REFUSED", "RELEASED"}:
            require(extension is not None and extension["file"] is not None,
                    "Missing journaled transient import guard identity")
        require(inode(self.install_gate) == record["install_gate"] and
                inode(self.controller_gate) == record["controller_gate"] and
                inode(self.state) == record["state"], "Maintenance lock or journal directory replaced")
        gate.syncdir(self.bundle)
        return record

    def save(self, record, phase):
        record["phase"] = phase
        write(self.journal, installer.encode(record), replace=present(self.journal))

    def probe_preflight(self, target):
        with ExitStack() as stack:
            for path in self.locks[1:]:
                stack.enter_context(lock(path))
            require({str(path): inode(path) for path in self.locks} == self.binding["locks"],
                    "Application lock identity changed before preflight")
            self.hook("preflight", package=self.canonical, target=target)

    def new(self):
        inherited = self.verify_preinstall_parked()
        require(not present(self.marker)
                and not present(self.units.sentinel) and not present(self.bundle / STAGED_EXTENSION),
                "Existing maintenance path or runtime release journal")
        with installer.directory(self.canonical) as parent:
            require(not extension_present(parent), "Unexpected extension initializer")
        require(not any(self.state.iterdir()), "Existing installer transaction without controller journal")
        require(scope(self.project, False, self.manifest.paths, self.manifest.owners) == self.manifest.before,
                "Base source identity differs")
        require(not self.candidate.is_symlink() and mount(self.candidate) == mount(self.bundle)
                and scope(self.candidate, False, self.manifest.paths, self.manifest.owners) == self.manifest.after,
                "Candidate must be durable and exact")
        for path in [*self.tool_files, *(self.candidate / name for name in self.manifest.paths)]:
            sync_file(path)
        with installer.source_tree(self.candidate) as tree:
            require(installer.mount_id(tree["root"]) == mount(self.bundle),
                    "Candidate source mount differs")
            for fd in tree.values():
                os.fsync(fd)
        gate.syncdir(self.bundle)
        gate.syncdir(self.bundle.parent)
        self.probe_preflight("INSTALLED")
        require(self.verify_preinstall_parked() == inherited, "Preinstall guard changed during preflight")
        self.seal_wrapper_images()
        record = {"binding": self.binding, "install_gate": inode(self.install_gate),
                  "controller_gate": inode(self.controller_gate), "state": inode(self.state),
                  "original": inode(self.canonical), "guard": inherited, "receipt": None,
                  "admission_guard": None,
                  "host_exposed_before_hold": "before",
                  "unscoped": unscoped(self.canonical, self.package_names),
                  "unscoped_wrapper": unscoped(self.wrapper_tools, self.wrapper_names),
                  "prior": self.units.snapshot()}
        self.save(record, "CLOSING")
        return record

    def seal_wrapper_images(self):
        path = installer.WRAPPER_HOST
        owner = self.manifest.owners[path]
        with installer.directory(self.bundle) as private:
            for side, root, endpoints in (("before", self.project, self.manifest.before),
                                          ("after", self.candidate, self.manifest.after)):
                with installer.source_tree(root) as tree:
                    data, _ = installer.attest_host_endpoint(tree["tools"], endpoints[path], owner)
                    installer.seal_host_image(private, side, data, endpoints[path])

    def prove_wrapper_parent(self, parent):
        with installer.directory(self.wrapper_tools) as current:
            require(installer.identity(os.fstat(current)) == self.binding["directories"][str(self.wrapper_tools)]
                    and installer.identity(os.fstat(parent)) == installer.identity(os.fstat(current))
                    and installer.mount_id(parent) == installer.mount_id(current),
                    "Wrapper tools directory changed")

    def require_fenced_host(self):
        with installer.directory(self.wrapper_tools) as parent:
            self.prove_wrapper_parent(parent)
            require(installer.read_optional(parent, Path(installer.WRAPPER_HOST).name) is None,
                    "Canonical wrapper host must remain absent")

    def close_wrapper(self, side):
        path = installer.WRAPPER_HOST
        expected = (self.manifest.before if side == "before" else self.manifest.after)[path]
        with installer.directory(self.bundle) as private, installer.directory(self.wrapper_tools) as parent:
            installer.load_host_image(private, side, expected)
            self.prove_wrapper_parent(parent)
            installer.close_host_path(parent, expected, self.manifest.owners[path],
                                      lambda: self.prove_wrapper_parent(parent))

    def attest_fenced_wrapper(self, record):
        package, _ = self.package(record)
        self.require_fenced_host()
        self.hook("host-fenced", package=package, target=record["target"])
        self.require_fenced_host()

    def package(self, record):
        visible = inode(self.canonical) == record["original"]
        package, guard_path = (self.canonical, self.parked) if visible else (self.parked, self.canonical)
        require(inode(package) == record["original"], "Original package identity changed")
        if record["guard"] is not None:
            require(inode(guard_path) == record["guard"], "Import guard identity changed")
            inherited = self.inherited_guard()
            if inherited is None:
                gate.verify_marker(guard_path)
            else:
                gate.verify_guard_identity(guard_path, inherited)
        return package, not visible

    @contextmanager
    def package_directory(self, record, package):
        with installer.directory(package) as parent:
            require(installer.identity(os.fstat(parent)) == record["original"],
                    "Original package identity changed")
            yield parent

    def check_extension(self, record, parent, *, guarded):
        require(not present(self.bundle / STAGED_EXTENSION), "Import guard staging is incomplete")
        if guarded:
            require(extension_present(parent), "Missing transient import guard")
            expected = (record["admission_guard"] or {}).get("file")
            require(extension_identity(parent, EXTENSION, 1) == expected,
                    "Transient import guard identity changed")
        else:
            require(not extension_present(parent), "Unexpected extension initializer")

    def verify_tree(self, record, manifest, *, guarded=False, host_absent=False):
        package, parked = self.package(record)
        with self.package_directory(record, package) as parent:
            self.check_extension(record, parent, guarded=guarded)
        expected = {**manifest, installer.WRAPPER_HOST: None} if host_absent else manifest
        require(scope(self.project, parked, self.manifest.paths, self.manifest.owners) == expected,
                "Scoped source identity differs")
        require(unscoped(package, self.package_names, guarded=guarded) == record["unscoped"],
                "Non-scope package changed")
        self.verify_wrapper_siblings(record)
        return package

    def verify_wrapper_siblings(self, record):
        require(unscoped(self.wrapper_tools, self.wrapper_names) == record["unscoped_wrapper"],
                "Non-scope wrapper source changed")

    def hold(self, record):
        ensure_file(self.marker, self.marker_data)
        if record["phase"] == "CLOSING":
            self.units.verify(record["prior"])
            self.close_wrapper(record["host_exposed_before_hold"])
            self.attest_fenced_wrapper(record)
        self.require_fenced_host()
        gate.park(self.project, record["original"][1], **self.inherited_guard_options())
        identity = inode(self.canonical)
        require(record["guard"] is None or record["guard"] == identity, "Import guard identity changed")
        record["guard"] = identity
        require(unscoped(self.parked, self.package_names) == record["unscoped"], "Non-scope package changed")
        record["owner"] = proc_owner(os.getpid())
        self.verify_hold(record, "controller")
        self.save(record, "HELD")

    def verify_hold(self, record, checkpoint):
        package, parked = self.package(record)
        require(parked, "Canonical application package is visible during maintenance")
        self.require_fenced_host()
        with self.package_directory(record, package) as parent:
            self.check_extension(record, parent, guarded=False)
        check_file(self.marker, self.marker_data, 0o600)
        owner = record["owner"]
        require(proc_owner(owner[1]) == owner, "Controller owner changed")
        locked_by(owner[1], [self.controller_gate, *self.locks])
        self.verify_wrapper_siblings(record)
        self.units.verify(record["prior"])
        self.hook("held:" + checkpoint, package=package, target=record["target"])
        require(proc_owner(owner[1]) == owner, "Controller owner changed during verification")

    def installer_command(self, record, action, fds):
        args = ["--project", self.project, "--state", self.state, "--gate", self.install_gate,
                "--marker", self.marker, "--verifier", self.verifier, "--hold-id", self.hold_id,
                "--manifest", self.manifest_path, "--manifest-sha256", self.manifest.sha256,
                "--parked-package", "--fenced-host"]
        if not present(self.state / installer.JOURNAL):
            args.extend(("--candidate", self.candidate))
        reply = subprocess.run([sys.executable, "-I", "-B", str(self.bundle / "installer.py"),
                                action, *map(str, args)], cwd="/", pass_fds=tuple(fds),
                               stdout=subprocess.PIPE, check=True, timeout=300)
        receipt = json.loads(reply.stdout)
        self.verify_receipt(record, receipt, host_absent=True)
        return receipt

    def verify_receipt(self, record, receipt, *, host_absent=False):
        transaction = self.state / installer.JOURNAL
        if receipt is None:
            require(record["target"] == "ROLLED_BACK" and not present(transaction),
                    "Missing terminal installer receipt")
            return
        journal = read_object(transaction)
        owners = journal.pop("owners")
        require(owners == self.manifest.owners, "Scoped source owner pin changed")
        target = self.manifest.after if record["target"] == "INSTALLED" else self.manifest.before
        staged_target = {**target, installer.WRAPPER_HOST: None} if host_absent else target
        package, _ = self.package(record)
        with installer.source_tree(self.project, package == self.parked) as tree:
            directories = installer.source_directories(tree)
            if package == self.canonical:
                # The same guard inode moved to the parked name at publication.
                with installer.directory(gate.PARKED, tree["src"]) as guard:
                    directories.update(installer.source_directories({"guard": guard}))
            require(directories["guard"]["identity"] == record["guard"], "Import guard identity changed")
            for path in self.manifest.paths:
                snapshot = installer.read_optional(*installer.entry(tree, path))
                require(installer.optional_version(snapshot) == staged_target[path]
                        and (snapshot is None or installer.ownership(snapshot[1]) == owners[path]),
                        f"Scoped source presence, version or ownership changed: {path}")
        expected = {"schema": "sprint-4-transaction-v1", "project": str(self.project),
                    "source_directories": directories,
                    "parked_package": True, "wrapper_host_fenced": True, "state_directory": record["state"],
                    "maintenance_id": self.hold_id, "gate": str(self.install_gate),
                    "gate_inode": record["install_gate"], "marker": str(self.marker),
                    "marker_sha256": installer.digest(self.marker_data), "verifier": str(self.verifier),
                    "source_manifest_sha256": self.manifest.sha256,
                    "before_manifest_sha256": installer.manifest_digest(self.manifest.before),
                    "after_manifest_sha256": installer.manifest_digest(self.manifest.after),
                    "phase": record["target"]}
        require(receipt == journal == expected, "Terminal installer receipt does not match the source and hold")

    def prepare_extension(self, record):
        """Place only the inode authorized by the journal at the parked path."""
        stage = self.bundle / STAGED_EXTENSION
        intent = record["admission_guard"]
        with self.package_directory(record, self.parked) as parent, installer.directory(self.bundle) as private:
            placed = extension_present(parent)
            staged = present(stage)
            if intent["file"] is None:
                require(not placed, "Unexpected transient import guard")
                if not staged:
                    write(stage, b"", EXTENSION_MODE)
                intent["file"] = extension_identity(private, STAGED_EXTENSION, 1)
                self.save(record, "PUBLISHING")
                staged = True
            if staged:
                links = 2 if placed else 1
                require(extension_identity(private, STAGED_EXTENSION, links) == intent["file"],
                        "Staged import guard identity changed")
                if not placed:
                    # link() does not overwrite the destination and both names
                    # are anchored to the verified open directories.
                    os.link(STAGED_EXTENSION, EXTENSION, src_dir_fd=private,
                            dst_dir_fd=parent, follow_symlinks=False)
                require(extension_identity(parent, EXTENSION, 2) == intent["file"],
                        "Transient import guard identity changed")
                os.fsync(parent)
                os.unlink(STAGED_EXTENSION, dir_fd=private)
                os.fsync(private)
            self.check_extension(record, parent, guarded=True)
            os.fsync(parent)

    def held_terminal(self, record, manifest, *, guarded):
        self.units.verify(record["prior"])
        check_file(self.marker, self.marker_data, 0o600)
        self.verify_receipt(record, record["receipt"], host_absent=True)
        return self.verify_tree(record, manifest, guarded=guarded, host_absent=True)

    def publish(self, record, manifest):
        package, parked = self.package(record)
        if parked:
            self.units.verify(record["prior"])
            check_file(self.marker, self.marker_data, 0o600)
            self.verify_receipt(record, record["receipt"], host_absent=True)
            if record["admission_guard"] is None:
                self.verify_tree(record, manifest, host_absent=True)
                record["admission_guard"] = {"file": None}
                self.save(record, "PUBLISHING")
            self.prepare_extension(record)
            require(self.verify_tree(record, manifest, guarded=True, host_absent=True) == self.parked,
                    "Package became visible before publication")
            purge_bytecode(self.project, package, self.prefixes, self.manifest.paths)
            self.hook("pre-publish", package=package, target=record["target"])
            purge_bytecode(self.project, package, self.prefixes, self.manifest.paths)
            require(self.held_terminal(record, manifest, guarded=True) == self.parked,
                    "Package became visible before publication")
        else:
            require(self.held_terminal(record, manifest, guarded=True) == self.canonical,
                    "Package publication identity changed")
        # If the exchange already happened, the same operation verifies both
        # directory names and fsyncs src without swapping again. The canonical
        # published probe still runs before any hold is removed.
        gate.publish(self.project, record["original"][1], **self.inherited_guard_options())
        self.save(record, "PUBLISHED")

    def canonical_probe(self, record, manifest, checkpoint, *, guarded):
        require(self.held_terminal(record, manifest, guarded=guarded) == self.canonical,
                "Package not published")
        self.hook(checkpoint, package=self.canonical, target=record["target"])
        require(self.held_terminal(record, manifest, guarded=guarded) == self.canonical,
                "Package publication identity changed during probe")

    def remove_extension(self, record, package, *, required):
        with self.package_directory(record, package) as parent:
            guarded = extension_present(parent)
            require(guarded or not required, "Missing transient import guard")
            self.check_extension(record, parent, guarded=guarded)
            if guarded:
                os.unlink(EXTENSION, dir_fd=parent)
            os.fsync(parent)

    def admit(self, record, manifest):
        newly_ready = record["phase"] == "PUBLISHED"
        if newly_ready:
            self.canonical_probe(record, manifest, "published", guarded=True)
            self.save(record, "ADMISSION_READY")
        with self.package_directory(record, self.canonical) as parent:
            still_guarded = extension_present(parent)
        require(still_guarded or not newly_ready, "Missing transient import guard")
        if still_guarded and not newly_ready:
            # A crash before a durable unlink can leave the authenticated
            # extension in place despite a durable admission-ready phase.
            self.canonical_probe(record, manifest, "published", guarded=True)
        require(self.held_terminal(record, manifest, guarded=still_guarded) == self.canonical,
                "Package not published")
        self.remove_extension(record, self.canonical, required=still_guarded)
        self.canonical_probe(record, manifest, "admitted", guarded=False)
        self.canonical_probe(record, manifest, "before-host-reopen", guarded=False)
        self.save(record, "HOST_REOPEN")

    def reopen_wrapper(self, record, manifest):
        self.units.verify(record["prior"])
        check_file(self.marker, self.marker_data, 0o600)
        path = installer.WRAPPER_HOST
        side = "after" if record["target"] == "INSTALLED" else "before"
        with installer.directory(self.bundle) as private, installer.directory(self.wrapper_tools) as parent:
            self.prove_wrapper_parent(parent)
            remaining_absent = installer.attest_host_endpoint(
                parent, manifest[path], self.manifest.owners[path], absent_ok=True,
            ) is None
            require(self.verify_tree(record, manifest, host_absent=remaining_absent) == self.canonical,
                    "Package not published")
            self.verify_receipt(record, record["receipt"], host_absent=remaining_absent)
            if remaining_absent:
                self.canonical_probe(record, manifest, "before-host-reopen", guarded=False)
            installer.open_host_path(private, parent, side, manifest[path], self.manifest.owners[path],
                                     lambda: self.prove_wrapper_parent(parent))
        require(self.verify_tree(record, manifest) == self.canonical, "Package not published")
        self.verify_receipt(record, record["receipt"])
        self.save(record, "RELEASING")

    def reestablish_release_hold(self, record):
        outcomes = []
        closure_failed = False
        closures = (
            ("refusal journal", lambda: self.save(record, "RELEASE_REFUSED")),
            ("direct wrapper hold", lambda: self.close_wrapper(
                "after" if record["target"] == "INSTALLED" else "before")),
            ("runtime marker", lambda: ensure_file(self.marker, self.marker_data)),
            ("service hold", lambda: self.units.close(record["prior"])),
            ("direct wrapper drain", lambda: self.attest_fenced_wrapper(record)),
        )
        for name, close in closures:
            try:
                close()
            except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as refusal:
                closure_failed = True
                outcomes.append(f"{name} failed ({refusal})")
            else:
                outcomes.append(f"{name} verified")
        if closure_failed:
            raise ValueError(". ".join(outcomes))

    def release(self, record, manifest):
        if record["phase"] == "RELEASE_REFUSED":
            self.reestablish_release_hold(record)
            self.save(record, "HOST_REOPEN")
        if record["phase"] in {"PUBLISHED", "ADMISSION_READY"}:
            self.admit(record, manifest)
        try:
            if record["phase"] == "HOST_REOPEN":
                self.reopen_wrapper(record, manifest)
            require(record["phase"] == "RELEASING", "Missing verified admission checkpoint")
            require(self.verify_tree(record, manifest) == self.canonical, "Package not published")
            self.verify_receipt(record, record["receipt"])
            self.hook("restoring", package=self.canonical, target=record["target"])
            require(self.verify_tree(record, manifest) == self.canonical,
                    "Source changed before host restoration")
            self.verify_receipt(record, record["receipt"])
            if present(self.marker):
                check_file(self.marker, self.marker_data, 0o600)
                sync_unlink(self.marker)
            else:
                gate.syncdir(self.marker.parent)
            self.units.restore(record["prior"])
            self.hook("restored", package=self.canonical, target=record["target"])
            require(self.verify_tree(record, manifest) == self.canonical,
                    "Source changed during host restoration")
            self.verify_receipt(record, record["receipt"])
            self.units.check_status(record["prior"], held=False, restored=True)
            require(not present(self.marker) and not present(self.units.sentinel), "Release hold remains")
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
            try:
                self.reestablish_release_hold(record)
            except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as refusal:
                raise ValueError(f"Release verification failed ({error}). Hold recovery: {refusal}") from error
            raise
        self.save(record, "RELEASED")

    def begin_rehold(self, record):
        """Bind the rollback decision while the terminal forward source is held."""
        package, parked = self.package(record)
        if parked:
            require(record["phase"] == "PUBLISHING", "Published package moved unexpectedly")
            if record["admission_guard"] is not None:
                self.units.verify(record["prior"])
                check_file(self.marker, self.marker_data, 0o600)
                self.verify_receipt(record, record["receipt"], host_absent=True)
                self.prepare_extension(record)
        allow_canonical_without_guard = record["phase"] in {"ADMISSION_READY", "HOST_REOPEN", "RELEASE_REFUSED"}
        with self.package_directory(record, package) as parent:
            guarded = extension_present(parent)
        require(guarded or allow_canonical_without_guard
                or (parked and record["admission_guard"] is None), "Missing transient import guard")
        self.held_terminal(record, self.manifest.after, guarded=guarded)
        record["rollback_from_ready"] = allow_canonical_without_guard
        self.save(record, "REHOLDING")

    def rehold(self, record):
        package, parked = self.package(record)
        with self.package_directory(record, package) as parent:
            guarded = extension_present(parent)
        require(guarded or parked or record["rollback_from_ready"], "Missing transient import guard")
        self.held_terminal(record, self.manifest.after, guarded=guarded)
        gate.park(self.project, record["original"][1], **self.inherited_guard_options())
        self.remove_extension(record, self.parked, required=guarded)
        self.held_terminal(record, self.manifest.after, guarded=False)
        record.pop("rollback_from_ready")
        record["admission_guard"] = None
        record["target"] = "ROLLED_BACK"
        self.hold(record)

    def verify_released_source(self, record):
        require(record["phase"] == "RELEASED" and record["target"] in {"INSTALLED", "ROLLED_BACK"},
                "Maintenance controller has no terminal release")
        manifest = self.manifest.after if record["target"] == "INSTALLED" else self.manifest.before
        require(self.verify_tree(record, manifest) == self.canonical, "Package not published")
        self.verify_receipt(record, record["receipt"])
        require(not present(self.marker) and not present(self.units.sentinel),
                "Unexpected maintenance or runtime release journal")

    @contextmanager
    def restoration_terminal(self):
        """Hold maintenance and writer leases while a caller verifies reopening."""
        with ExitStack() as stack:
            for path in (self.controller_gate, *self.locks, self.install_gate):
                stack.enter_context(lock(path))
            require({str(path): inode(path) for path in self.locks} == self.binding["locks"],
                    "Existing application lock identity changed")
            record = self.load(canonical=True)
            self.verify_released_source(record)
            self.units.check_status(record["prior"], held=False, restored=True)
            yield {
                "maintenance_id": self.hold_id,
                "project": str(self.project),
                "source": record["target"],
                "source_manifest_sha256": self.manifest.sha256,
                "controller_journal_sha256": installer.digest(installer.encode(record)),
                "installer_receipt_sha256": installer.digest(installer.encode(record["receipt"])),
            }

    def run(self, action):
        target = {"install": "INSTALLED", "rollback": "ROLLED_BACK"}[action]
        ensure_file(self.controller_gate, b"")
        with lock(self.controller_gate) as controller_fd, lock(self.locks[0]) as install_fd:
            ensure_file(self.install_gate, b"")
            self.state.mkdir(exist_ok=True, mode=0o700)
            private_dir(self.state)
            require(mount(self.state) == mount(self.bundle), "Installer state is on another mount")
            gate.syncdir(self.bundle)
            with lock(self.install_gate):
                if not present(self.journal):
                    require(action == "install", "No Sprint 4 operation exists to roll back")
                    record = self.new()
                else:
                    record = self.load()
                phase = record["phase"]
                if phase == "RELEASED":
                    self.verify_released_source(record)
                    if record["target"] == target:
                        return self.result(record)
                    require(action == "rollback", "This maintenance transaction has rolled back")
                    self.probe_preflight(target)
                    record["prior"] = self.units.snapshot()
                    record["admission_guard"] = None
                    record["host_exposed_before_hold"] = "after"
                    self.save(record, "CLOSING")
                elif phase == "REHOLDING":
                    require(action == "rollback", "Resume the recorded rollback")
                elif phase == "RELEASING":
                    require(record["target"] == target, "Finish the recorded release before switching direction")
                elif phase in {"PUBLISHING", "PUBLISHED", "ADMISSION_READY", "HOST_REOPEN", "RELEASE_REFUSED"}:
                    require(record["target"] == target or action == "rollback",
                            "Rollback is already selected")
                if record["phase"] == "CLOSING":
                    # Closing services before waiting for application locks permits
                    # an in-flight wrapper request to finish as the unit stops.
                    if present(self.marker):
                        check_file(self.marker, self.marker_data, 0o600)
                    self.units.close(record["prior"])

            with ExitStack() as stack:
                fds = [controller_fd, install_fd]
                fds.extend(stack.enter_context(lock(path)) for path in self.locks[1:])
                require({str(path): inode(path) for path in self.locks} == self.binding["locks"],
                        "Existing application lock identity changed")
                with lock(self.install_gate):
                    phase = record["phase"]
                    if phase in {"HOST_REOPEN", "RELEASE_REFUSED"} and record["target"] != target:
                        self.reestablish_release_hold(record)
                        self.begin_rehold(record)
                    elif phase in {"PUBLISHING", "PUBLISHED", "ADMISSION_READY"} and record["target"] != target:
                        self.begin_rehold(record)
                    if record["phase"] == "REHOLDING":
                        self.rehold(record)
                        needs_transaction = True
                    elif phase in {"CLOSING", "HELD"}:
                        if record.get("target") == "ROLLED_BACK":
                            require(target == "ROLLED_BACK", "Rollback is already selected")
                        elif record["phase"] == "CLOSING" and "target" in record:
                            require(target == "ROLLED_BACK", "Resume the reopened rollback hold")
                        record["target"] = target
                        self.hold(record)
                        needs_transaction = action == "install" or present(self.state / installer.JOURNAL)
                    else:
                        needs_transaction = False
                if record["phase"] == "HELD":
                    if needs_transaction:
                        record["receipt"] = self.installer_command(record, action, fds)
                    with lock(self.install_gate):
                        self.verify_hold(record, "controller")
                        self.save(record, "PUBLISHING")
                manifest = self.manifest.after if target == "INSTALLED" else self.manifest.before
                with lock(self.install_gate):
                    if record["phase"] == "PUBLISHING":
                        self.publish(record, manifest)
                    self.release(record, manifest)
        return self.result(record)

    @staticmethod
    def result(record):
        return {"phase": record["phase"], "source": record["target"],
                "receipt": record["receipt"], "maintenance_id": record["binding"]["hold_id"]}


def verify_request(request, bundle=BUNDLE):
    controller = Controller(bundle)
    record = controller.load()
    fixed = {"schema": "sprint-4-hold-check-v1", "project": str(controller.project),
             "state": str(controller.state), "gate": str(controller.install_gate),
             "marker": str(controller.marker), "maintenance_id": controller.hold_id,
             "source_manifest_sha256": controller.manifest.sha256}
    require(set(request) == {*fixed, "checkpoint", "nonce"}
            and all(request[key] == expected for key, expected in fixed.items())
            and isinstance(request["checkpoint"], str) and isinstance(request["nonce"], str),
            "Installer request does not match its maintenance controller")
    require(record["phase"] == "HELD", "Controller has no active installer window")
    installer_pid = os.getppid()
    require(int(proc_stat(installer_pid)[1]) == record["owner"][1],
            "Installer was not launched by this maintenance controller")
    locked_by(installer_pid, [controller.install_gate])
    controller.verify_hold(record, request["checkpoint"])
    return {**request, "verified": True}


def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=("install", "rollback"))
    args = parser.parse_args()
    try:
        print(installer.encode(Controller(BUNDLE).run(args.action)).decode(), end="")
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Maintenance stopped. Preserve the bundle for recovery. {error}\n")


if __name__ == "__main__":
    main()
