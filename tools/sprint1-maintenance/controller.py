#!/usr/bin/python3 -I
"""Resume an exact Sprint 1 maintenance window from a private durable bundle.

Place these four tools, candidate/, plan.json and a trusted executable
host-check together in a 0700 directory outside the checkout on its mount.
Run controller.py install or controller.py rollback. Repeat the same command
after interruptions. Rollback can also reverse an in-progress installation.
All files and locks named by the plan must have their normal production meaning.

plan.json fields: project (absolute checkout), hold_id, unit_directory
(absolute persistent user-unit directory), systemctl (absolute systemctl),
and pycache_prefixes (a list of absolute audited PYTHONPYCACHEPREFIX paths).
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
import stat
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
BUNDLE = Path(__file__).resolve().parent
sys.path.insert(0, str(BUNDLE))

import gate
import installer


UNITS = ("wrapper-development-host.service", "job-search-sync.service")
DROP_IN = "zzzz-job-search-foundation-maintenance.conf"
MARKER_NAME = "integration-release-journal.json"
STATE_NAME = "controller.json"
LOCK_EX = fcntl.LOCK_EX | fcntl.LOCK_NB
PHASES = {"CLOSING", "HELD", "PUBLISHING", "PUBLISHED", "ADMISSION_READY",
          "REHOLDING", "RELEASING", "RELEASED"}
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
        for line in Path(f"/proc/self/fdinfo/{fd}").read_text().splitlines():
            if line.startswith("mnt_id:"):
                return int(line.split()[1])
    raise ValueError(f"Cannot determine mount identity: {path}")


def ref(path):
    data, attrs = read(physical(path))
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
    fd, name = tempfile.mkstemp(prefix=".sprint-1-", dir=path.parent)
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


def scope(project, parked):
    with installer.source_tree(project, parked) as tree:
        return {path: installer.version(*installer.read_file(*installer.entry(tree, path)))
                for path in installer.SCOPE}


def unscoped(package, *, guarded=False):
    scoped = {Path(path).name for path in installer.SCOPE if "/" in path}
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


def purge_bytecode(project, package, prefixes):
    dirs = {}
    original, parked = gate.paths(project)
    for scoped_path in installer.SCOPE:
        source = Path(scoped_path)
        if source.suffix != ".py":
            continue
        stem = source.stem
        local = package if len(source.parts) > 1 else project
        dirs.setdefault(local / "__pycache__", set()).add(stem)
        legacy = local / (stem + ".pyc")
        if present(legacy):
            read(legacy)
            sync_unlink(legacy)
        for cache in prefixes:
            source_dirs = (original, parked) if len(source.parts) > 1 else (project,)
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
        for name, unit in self.status().items():
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
        self.check_status(prior, held=False)
        if present(self.sentinel):
            check_file(self.sentinel, b"", 0o600)
            sync_unlink(self.sentinel)
        if prior[UNITS[0]]["active"] == "active":
            self.command("start", UNITS[0], timeout=45)
        self.check_status(prior, held=False, restored=True)


class Controller:
    def __init__(self, bundle):
        self.bundle = bundle
        private_dir(bundle)
        plan_path = bundle / "plan.json"
        plan = read_object(plan_path)
        require(set(plan) == {"project", "hold_id", "unit_directory", "systemctl", "pycache_prefixes"},
                "Unexpected maintenance plan fields")
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
                                                      "installer.py", "host-check", "plan.json")]
        files = {str(p): ref(p) for p in [*self.tool_files, exe, *filter(present, config_files)]}
        require(os.access(self.checker, os.X_OK) and os.access(self.verifier, os.X_OK),
                "Verifier and host-check must be executable")
        source = self.project / "src"
        paths = [bundle, self.project, source, self.marker.parent, self.canonical]
        if present(self.parked):
            paths.append(self.parked)
        require(len({mount(path) for path in paths}) == 1, "Source and durable state mounts differ")
        self.binding = {"schema": "sprint-1-controller-v1",
                        "files": files, "project": str(self.project), "hold_id": self.hold_id,
                        "directories": {str(p): inode(p) for p in
                                        (bundle, self.project, source, self.marker.parent, unit_directory)},
                        "backend": self.backend, "marker": str(self.marker),
                        "locks": {str(path): inode(physical(path)) for path in self.locks}}

    def hook(self, checkpoint, *, package, target=None):
        request = {"schema": "sprint-1-host-check-v1", "nonce": secrets.token_hex(16),
                   "checkpoint": checkpoint, "project": str(self.project), "package": str(package),
                   "marker": str(self.marker), "backend": self.backend, "target": target,
                   "maintenance_id": self.hold_id, "locks": list(map(str, self.locks)),
                   "pycache_prefixes": list(map(str, self.prefixes))}
        environment = {**os.environ, "JSH_F3_HOST_PHASE": checkpoint.split(":", 1)[0]}
        reply = subprocess.run([str(self.checker)], cwd="/", input=installer.encode(request), env=environment,
                               stdout=subprocess.PIPE, check=True, timeout=5)
        value = json.loads(reply.stdout)
        require(value == {**request, "verified": True} and value.get("verified") is True,
                f"Host check did not confirm {checkpoint}")

    def load(self):
        record = read_object(self.journal)
        phase = record.get("phase")
        require(record.get("binding") == self.binding and phase in PHASES,
                "Controller journal does not match this host, bundle or source checkout")
        require(record.get("guard") is None or isinstance(record["guard"], list),
                "Invalid import guard identity")
        extension = record["admission_guard"]
        if extension is not None:
            require(isinstance(extension, dict) and set(extension) == {"file"},
                    "Invalid transient import guard record")
            identity = extension["file"]
            require(identity is None or (isinstance(identity, list) and len(identity) == 4
                    and all(type(value) is int and value >= 0 for value in identity)),
                    "Invalid transient import guard identity")
        if phase in {"PUBLISHED", "ADMISSION_READY", "RELEASING", "RELEASED"}:
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

    def new(self):
        require(not present(self.parked) and not present(self.marker)
                and not present(self.units.sentinel) and not present(self.bundle / STAGED_EXTENSION),
                "Existing maintenance path or runtime release journal")
        with installer.directory(self.canonical) as parent:
            require(not extension_present(parent), "Unexpected extension initializer")
        require(not any(self.state.iterdir()), "Existing installer transaction without controller journal")
        require(scope(self.project, False) == installer.BEFORE, "Base source identity differs")
        require(not self.candidate.is_symlink() and mount(self.candidate) == mount(self.bundle)
                and scope(self.candidate, False) == installer.AFTER, "Candidate must be durable and exact")
        for path in [*self.tool_files, *(self.candidate / name for name in installer.SCOPE)]:
            sync_file(path)
        with installer.source_tree(self.candidate) as tree:
            require(all(os.fstat(fd).st_dev == self.bundle.stat().st_dev for fd in tree),
                    "Candidate source mount differs")
            for fd in tree:
                os.fsync(fd)
        gate.syncdir(self.bundle)
        gate.syncdir(self.bundle.parent)
        self.hook("preflight", package=self.canonical, target="INSTALLED")
        record = {"binding": self.binding, "install_gate": inode(self.install_gate),
                  "controller_gate": inode(self.controller_gate), "state": inode(self.state),
                  "original": inode(self.canonical), "guard": None, "receipt": None,
                  "admission_guard": None,
                  "unscoped": unscoped(self.canonical), "prior": self.units.snapshot()}
        self.save(record, "CLOSING")
        return record

    def package(self, record):
        visible = inode(self.canonical) == record["original"]
        package, guard_path = (self.canonical, self.parked) if visible else (self.parked, self.canonical)
        require(inode(package) == record["original"], "Original package identity changed")
        if record["guard"] is not None:
            require(inode(guard_path) == record["guard"], "Import guard identity changed")
            gate.verify_marker(guard_path)
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

    def verify_tree(self, record, manifest, *, guarded=False):
        package, parked = self.package(record)
        with self.package_directory(record, package) as parent:
            self.check_extension(record, parent, guarded=guarded)
        require(scope(self.project, parked) == manifest, "Scoped source identity differs")
        require(unscoped(package, guarded=guarded) == record["unscoped"], "Non-scope package changed")
        return package

    def hold(self, record):
        ensure_file(self.marker, self.marker_data)
        gate.park(self.project, record["original"][1])
        identity = inode(self.canonical)
        require(record["guard"] is None or record["guard"] == identity, "Import guard identity changed")
        record["guard"] = identity
        require(unscoped(self.parked) == record["unscoped"], "Non-scope package changed")
        record["owner"] = proc_owner(os.getpid())
        self.verify_hold(record, "controller")
        self.save(record, "HELD")

    def verify_hold(self, record, checkpoint):
        package, parked = self.package(record)
        require(parked, "Canonical application package is visible during maintenance")
        with self.package_directory(record, package) as parent:
            self.check_extension(record, parent, guarded=False)
        check_file(self.marker, self.marker_data, 0o600)
        owner = record["owner"]
        require(proc_owner(owner[1]) == owner, "Controller owner changed")
        locked_by(owner[1], [self.controller_gate, *self.locks])
        self.units.verify(record["prior"])
        self.hook("held:" + checkpoint, package=package, target=record["target"])
        require(proc_owner(owner[1]) == owner, "Controller owner changed during verification")

    def installer_command(self, record, action, fds):
        args = ["--project", self.project, "--state", self.state, "--gate", self.install_gate,
                "--marker", self.marker, "--verifier", self.verifier, "--hold-id", self.hold_id,
                "--parked-package"]
        if not present(self.state / installer.JOURNAL):
            args.extend(("--candidate", self.candidate))
        reply = subprocess.run([sys.executable, "-I", "-B", str(self.bundle / "installer.py"),
                                action, *map(str, args)], cwd="/", pass_fds=tuple(fds),
                               stdout=subprocess.PIPE, check=True, timeout=300)
        receipt = json.loads(reply.stdout)
        self.verify_receipt(record, receipt)
        return receipt

    def verify_receipt(self, record, receipt):
        transaction = self.state / installer.JOURNAL
        if receipt is None:
            require(record["target"] == "ROLLED_BACK" and not present(transaction),
                    "Missing terminal installer receipt")
            return
        journal = read_object(transaction)
        owners = journal.pop("owners")
        package, _ = self.package(record)
        with installer.source_tree(self.project, package == self.parked) as tree:
            require(all(owners[path] == installer.ownership(installer.read_file(*installer.entry(tree, path))[1])
                        for path in installer.SCOPE), "Scoped source ownership changed")
        expected = {"schema": "sprint-1-transaction-v1", "project": str(self.project),
                    "source_directories": [inode(path) for path in (self.project, package,
                                           self.project / "src")] + [record["guard"]],
                    "parked_package": True, "state_directory": record["state"],
                    "maintenance_id": self.hold_id, "gate": str(self.install_gate),
                    "gate_inode": record["install_gate"], "marker": str(self.marker),
                    "marker_sha256": installer.digest(self.marker_data), "verifier": str(self.verifier),
                    "before_manifest_sha256": installer.manifest_digest(installer.BEFORE),
                    "after_manifest_sha256": installer.manifest_digest(installer.AFTER),
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
        self.verify_receipt(record, record["receipt"])
        return self.verify_tree(record, manifest, guarded=guarded)

    def publish(self, record, manifest):
        package, parked = self.package(record)
        if parked:
            self.units.verify(record["prior"])
            check_file(self.marker, self.marker_data, 0o600)
            self.verify_receipt(record, record["receipt"])
            if record["admission_guard"] is None:
                self.verify_tree(record, manifest)
                record["admission_guard"] = {"file": None}
                self.save(record, "PUBLISHING")
            self.prepare_extension(record)
            require(self.verify_tree(record, manifest, guarded=True) == self.parked,
                    "Package became visible before publication")
            purge_bytecode(self.project, package, self.prefixes)
            self.hook("pre-publish", package=package, target=record["target"])
            purge_bytecode(self.project, package, self.prefixes)
            require(self.held_terminal(record, manifest, guarded=True) == self.parked,
                    "Package became visible before publication")
        else:
            require(self.held_terminal(record, manifest, guarded=True) == self.canonical,
                    "Package publication identity changed")
        # If the exchange already happened, the same operation verifies both
        # directory names and fsyncs src without swapping again. The canonical
        # published probe still runs before any hold is removed.
        gate.publish(self.project, record["original"][1])
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
        self.save(record, "RELEASING")

    def release(self, record, manifest):
        if record["phase"] in {"PUBLISHED", "ADMISSION_READY"}:
            self.admit(record, manifest)
        require(record["phase"] == "RELEASING", "Missing verified admission checkpoint")
        require(self.verify_tree(record, manifest) == self.canonical, "Package not published")
        self.verify_receipt(record, record["receipt"])
        if present(self.marker):
            check_file(self.marker, self.marker_data, 0o600)
            sync_unlink(self.marker)
        else:
            gate.syncdir(self.marker.parent)
        self.units.restore(record["prior"])
        self.save(record, "RELEASED")

    def begin_rehold(self, record):
        """Bind the rollback decision while the terminal forward source is held."""
        package, parked = self.package(record)
        if parked:
            require(record["phase"] == "PUBLISHING", "Published package moved unexpectedly")
            if record["admission_guard"] is not None:
                self.units.verify(record["prior"])
                check_file(self.marker, self.marker_data, 0o600)
                self.verify_receipt(record, record["receipt"])
                self.prepare_extension(record)
        allow_canonical_without_guard = record["phase"] == "ADMISSION_READY"
        with self.package_directory(record, package) as parent:
            guarded = extension_present(parent)
        require(guarded or allow_canonical_without_guard
                or (parked and record["admission_guard"] is None), "Missing transient import guard")
        self.held_terminal(record, installer.AFTER, guarded=guarded)
        record["rollback_from_ready"] = allow_canonical_without_guard
        self.save(record, "REHOLDING")

    def rehold(self, record):
        package, parked = self.package(record)
        with self.package_directory(record, package) as parent:
            guarded = extension_present(parent)
        require(guarded or parked or record["rollback_from_ready"], "Missing transient import guard")
        self.held_terminal(record, installer.AFTER, guarded=guarded)
        gate.park(self.project, record["original"][1])
        self.remove_extension(record, self.parked, required=guarded)
        self.held_terminal(record, installer.AFTER, guarded=False)
        record.pop("rollback_from_ready")
        record["admission_guard"] = None
        record["target"] = "ROLLED_BACK"
        self.hold(record)

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
                    require(action == "install", "No Sprint 1 operation exists to roll back")
                    record = self.new()
                else:
                    record = self.load()
                phase = record["phase"]
                if phase == "RELEASED":
                    current = (installer.AFTER if record["target"] == "INSTALLED" else installer.BEFORE)
                    require(self.verify_tree(record, current) == self.canonical, "Package not published")
                    self.verify_receipt(record, record["receipt"])
                    require(not present(self.marker) and not present(self.units.sentinel),
                            "Unexpected maintenance or runtime release journal")
                    if record["target"] == target:
                        return self.result(record)
                    require(action == "rollback", "This maintenance transaction has rolled back")
                    self.hook("preflight", package=self.canonical, target=target)
                    record["prior"] = self.units.snapshot()
                    record["admission_guard"] = None
                    self.save(record, "CLOSING")
                elif phase == "REHOLDING":
                    require(action == "rollback", "Resume the recorded rollback")
                elif phase == "RELEASING":
                    require(record["target"] == target, "Finish the recorded release before switching direction")
                elif phase in {"PUBLISHING", "PUBLISHED", "ADMISSION_READY"}:
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
                    if phase in {"PUBLISHING", "PUBLISHED", "ADMISSION_READY"} and record["target"] != target:
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
                manifest = installer.AFTER if target == "INSTALLED" else installer.BEFORE
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
    fixed = {"schema": "sprint-1-hold-check-v1", "project": str(controller.project),
             "state": str(controller.state), "gate": str(controller.install_gate),
             "marker": str(controller.marker), "maintenance_id": controller.hold_id}
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
