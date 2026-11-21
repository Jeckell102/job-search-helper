"""Sprint 4 exact-source transaction. Requires an independent maintenance controller.

Use a dedicated private, durable state directory outside the runtime tree but
on its source filesystem. The controller must provide a stable, private, empty
gate file outside that tree and transaction state. It must take an exclusive
flock on that same inode for *all* hold transitions, and keep the route closures
durable after releasing the lock or dying. Before invoking this tool it must
drain existing consumers/source writers and publish the backend-resolved release
journal with schema integration-release-journal-v1, state FOUNDATION_MAINTENANCE
and maintenance_id equal to --hold-id. Never substitute for an existing release
journal without separately reconciling it.

A trusted external verifier receives an identity/checkpoint object on stdin
and must return the exact object plus "verified": true, with exit status zero.
It must independently check the durable journal location, persistent closure of
all launch/writer routes, consumer quiescence, and ownership of this transaction.
It runs while the installer owns the gate, so it must not acquire that gate.
The verifier and installer run outside the runtime source they are replacing.

The controller must keep the hold on crash, error, missing receipt, or mixed
source. Release requires separate verification of a terminal receipt, full
pinned source identity, and expected launcher behavior, under the same gate.
The installer never establishes or removes a hold. Paths must be canonical.
"""

import argparse
from contextlib import ExitStack, contextmanager
import ctypes
from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess


SOURCE_PATH = re.compile(
    r"(?:job-search-(?:helper|scraper)|release_admission_bootstrap\.py|"
    r"src/job_search_helper/(?!__init__\.py$)[A-Za-z_][A-Za-z_0-9]*\.py)"
)
PACKAGE_PREFIX = "src/job_search_helper/"
WRAPPER_PARENT = Path("dev/wrapper-coder/tools")
WRAPPER_HOST = (WRAPPER_PARENT / "host_server.py").as_posix()
WRAPPER_PATHS = frozenset((WRAPPER_PARENT / name).as_posix() for name in (
    "host_server.py", "coordinator_receipt_host_bridge.py", "coordinator_store.py",
))
CONSOLIDATED_SCHEMA = "sprint-6-consolidated-source-manifest-v1"
RETIREMENT_SCHEMA = "sprint-6-consolidated-retirement-source-manifest-v1"
CONSOLIDATED_WRAPPER_PATHS = frozenset((WRAPPER_PARENT / (name + ".py")).as_posix() for name in (
    "acquiretm_membership_recipe", "amphenol_candidate_release", "amphenol_installed_verification",
    "amphenol_recipe_candidate", "amphenol_recipe_choice_input", "amphenol_retry_completion",
    "coordinator", "coordinator_inference", "coordinator_store", "coordinator_supervision", "host_server",
))
CONSOLIDATED_PATHS = CONSOLIDATED_WRAPPER_PATHS | {"job-search-scraper"} | frozenset(
    PACKAGE_PREFIX + name + ".py" for name in (
        "acquiretm", "ats", "company_events", "company_intake_dispatcher", "company_sources", "engine",
        "exact_cycle_planner", "exact_cycle_receipt", "exact_cycle_recovery", "exact_cycle_sync", "inbox",
        "integration_release", "ordinary_company_event_command", "ordinary_company_event_publication",
        "ordinary_event_settlement", "private_file_custody", "qualified_release_owner", "release_controller",
        "release_qualification", "repair_retry", "repair_retry_status", "runner", "scan_request",
        "scrape_outcome_producer", "sqlite_repository", "sync_cli",
    )
)
RETIREMENT_PATHS = CONSOLIDATED_PATHS | frozenset(
    PACKAGE_PREFIX + name + ".py" for name in (
        "control_before_prefix_runner", "exact_legacy_migration_runner",
        "exact_recovery_pause_executor", "retained_cycle_retirement",
        "retained_cycle_retirement_control", "selected_recovery_runner",
    )
)
HEX_SHA256 = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class SourceManifest:
    sha256: str
    before: dict
    after: dict
    owners: dict
    schema: str

    @property
    def paths(self):
        return tuple(self.before)


PHASES = {"INSTALLING", "INSTALLED", "ROLLING_BACK", "ROLLED_BACK"}
DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
READ = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
JOURNAL = "transaction.json"
PARKED_PACKAGE = ".s4-maintenance-package"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def manifest_digest(manifest):
    lines = []
    for path, endpoint in sorted(manifest.items()):
        fields = "ABSENT" if endpoint is None else f"{endpoint[0]:04o} {endpoint[1]}"
        lines.append(f"{fields} {path}\n")
    return digest("".join(lines).encode())


def endpoint(value, *, allow_absent=False):
    if value is None and allow_absent:
        return None
    if (not isinstance(value, dict) or set(value) != {"mode", "sha256"}
            or not isinstance(value["mode"], str) or not re.fullmatch(r"0[0-7]{3}", value["mode"])
            or not isinstance(value["sha256"], str) or not HEX_SHA256.fullmatch(value["sha256"])):
        raise ValueError("Invalid source manifest endpoint")
    return int(value["mode"], 8), value["sha256"]


def load_manifest(path, expected_sha256):
    canonical(path)
    with directory(path.parent) as parent:
        raw, _ = read_file(parent, path.name)
    if digest(raw) != expected_sha256:
        raise ValueError("Source manifest hash differs from the approved pin")
    value = json.loads(raw)
    if (not isinstance(value, dict) or set(value) != {"schema", "paths"}
            or value["schema"] not in ("sprint-4-source-manifest-v1", CONSOLIDATED_SCHEMA, RETIREMENT_SCHEMA)
            or not isinstance(value["paths"], dict) or not value["paths"]
            or raw != encode(value)):
        raise ValueError("Expected canonical maintenance source manifest JSON")
    expected_paths = {CONSOLIDATED_SCHEMA: CONSOLIDATED_PATHS,
                      RETIREMENT_SCHEMA: RETIREMENT_PATHS}.get(value["schema"])
    consolidated = expected_paths is not None
    if consolidated and set(value["paths"]) != expected_paths:
        raise ValueError("The consolidated manifest must list the exact reviewed source paths")
    wrapper_paths = CONSOLIDATED_WRAPPER_PATHS if consolidated else WRAPPER_PATHS
    before, after, owners = {}, {}, {}
    for name, row in sorted(value["paths"].items()):
        if ((not SOURCE_PATH.fullmatch(name) and name not in wrapper_paths) or not isinstance(row, dict)
                or set(row) != {"before", "after", "owner"}):
            raise ValueError(f"Source path is outside the allowed scope: {name}")
        old, new = endpoint(row["before"], allow_absent=True), endpoint(row["after"])
        owner = row["owner"]
        if (old == new or not isinstance(owner, list) or len(owner) != 2
                or any(type(part) is not int or not 0 <= part < 2**32 - 1 for part in owner)):
            raise ValueError(f"Invalid or unchanged source manifest entry: {name}")
        before[name], after[name], owners[name] = old, new, owner
    if consolidated:
        existing = (WRAPPER_HOST, (WRAPPER_PARENT / "coordinator_store.py").as_posix())
        if any(before[path] is None for path in existing):
            raise ValueError("The consolidated release requires the existing wrapper host and store")
    elif any(before.get(path) is None for path in WRAPPER_PATHS):
        raise ValueError("The combined release requires the three existing wrapper endpoints")
    return SourceManifest(expected_sha256, before, after, owners, value["schema"])


def identity(info):
    return [info.st_dev, info.st_ino]


def mount_id(fd):
    for line in Path(f"/proc/self/fdinfo/{fd}").read_text().splitlines():
        if line.startswith("mnt_id:"):
            return int(line.split()[1])
    raise ValueError("Cannot determine source or transaction mount identity")


def ownership(info):
    return [info.st_uid, info.st_gid]


def version(data, info):
    return stat.S_IMODE(info.st_mode), digest(data)


@contextmanager
def directory(name, parent=None):
    if parent is None:
        path = Path(name)
        if not path.is_absolute() or path.anchor != "/" or ".." in path.parts:
            raise ValueError("Expected a physical absolute directory path")
        with ExitStack() as ancestry:
            fd = os.open("/", DIRECTORY)
            ancestry.callback(os.close, fd)
            for part in path.parts[1:]:
                fd = ancestry.enter_context(directory(part, fd))
            yield fd
        return
    fd = os.open(name, DIRECTORY, dir_fd=parent)
    try:
        yield fd
    finally:
        os.close(fd)


@contextmanager
def source_tree(path, parked=False):
    package_name = PARKED_PACKAGE if parked else "job_search_helper"
    with ExitStack() as stack:
        root = stack.enter_context(directory(path))
        src = stack.enter_context(directory("src", root))
        package = stack.enter_context(directory(package_name, src))
        dev = stack.enter_context(directory("dev", root))
        wrapper = stack.enter_context(directory("wrapper-coder", dev))
        tools = stack.enter_context(directory("tools", wrapper))
        tree = {"root": root, "src": src, "package": package,
                "dev": dev, "wrapper": wrapper, "tools": tools}
        if parked:
            guard = stack.enter_context(directory("job_search_helper", src))
            if os.path.samestat(os.fstat(package), os.fstat(guard)):
                raise ValueError("The parked package and canonical guard must be distinct")
            tree["guard"] = guard
        witness = source_directories(tree)
        if (len({row["mount"] for row in witness.values()}) != 1
                or len({tuple(row["identity"]) for row in witness.values()}) != len(tree)):
            raise ValueError("Source directories must be distinct and share one mount")
        yield tree


def source_directories(tree):
    return {key: {"identity": identity(os.fstat(fd)), "mount": mount_id(fd)}
            for key, fd in tree.items()}


def source_location(path):
    if path in WRAPPER_PATHS or path in CONSOLIDATED_WRAPPER_PATHS:
        return "tools"
    if not SOURCE_PATH.fullmatch(path):
        raise ValueError(f"Unknown source destination: {path}")
    return "package" if path.startswith(PACKAGE_PREFIX) else "root"


def entry(tree, path):
    return tree[source_location(path)], path.rsplit("/", 1)[-1]


def read_file(parent, name):
    fd = os.open(name, READ, dir_fd=parent)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or mount_id(fd) != mount_id(parent)):
            raise ValueError(f"Expected a regular same-mount file with one link: {name}")
        data = stream.read()
        after = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if (identity(info), info.st_ctime_ns) != (identity(after), after.st_ctime_ns):
            raise ValueError(f"File changed during read: {name}")
    return data, info


def read_optional(parent, name):
    try:
        os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return None
    # Disappearance during this read is drift, not an acceptable ABSENT read.
    return read_file(parent, name)


def optional_version(snapshot):
    return None if snapshot is None else version(*snapshot)


def create_exclusive(state, scratch, parent, name):
    rename = ctypes.CDLL(None, use_errno=True).renameat2
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(state, os.fsencode(scratch), parent, os.fsencode(name), 1) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), name)


def write_atomic(state, parent, name, data, mode, owner=None, before_replace=None, *, create=False):
    # Scratch stays in the private transaction directory even after a crash.
    scratch = ".pending"
    try:
        os.unlink(scratch, dir_fd=state)
    except FileNotFoundError:
        pass
    fd = os.open(scratch, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600,
                 dir_fd=state)
    with os.fdopen(fd, "wb") as stream:
        if owner is not None and ownership(os.fstat(fd)) != owner:
            os.fchown(fd, *owner)
        stream.write(data)
        stream.flush()
        os.fchmod(fd, mode)
        os.fsync(fd)
    if before_replace is not None:
        before_replace()
    if create:
        create_exclusive(state, scratch, parent, name)
    else:
        os.replace(scratch, name, src_dir_fd=state, dst_dir_fd=parent)
    os.fsync(parent)
    if parent != state:
        os.fsync(state)


def attest_host_endpoint(parent, expected, owner, *, absent_ok=False):
    """Verify the host path and return its exact bytes or authorized absence."""
    name = Path(WRAPPER_HOST).name
    found = read_optional(parent, name)
    if found is None and absent_ok:
        return None
    if found is None or version(*found) != expected or ownership(found[1]) != owner:
        raise ValueError("Canonical wrapper host does not match its recorded endpoint")
    return found


def seal_host_image(state, label, data, expected):
    """Use a durable private name that the wrapper interpreter never launches."""
    name = host_image_name(label)
    if digest(data) != expected[1]:
        raise ValueError("Wrapper host payload differs from the approved digest")
    saved = read_optional(state, name)
    if saved is None:
        write_atomic(state, state, name, data, 0o600, create=True)
    load_host_image(state, label, expected)
    os.fsync(state)


def load_host_image(state, label, expected):
    data, info = read_file(state, host_image_name(label))
    if (info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600
            or digest(data) != expected[1]):
        raise ValueError("Sealed wrapper host payload identity changed")
    return data


def host_image_name(label):
    if label not in {"before", "after"}:
        raise ValueError("Unknown wrapper host payload direction")
    return f"wrapper-host-{label}.sealed"


def close_host_path(parent, expected, owner, prove_parent):
    """Apply an already journaled close intent and durably verify absence."""
    found = attest_host_endpoint(parent, expected, owner, absent_ok=True)
    if found is not None:
        prove_parent()
        current = attest_host_endpoint(parent, expected, owner)
        if (identity(current[1]), current[1].st_ctime_ns) != (identity(found[1]), found[1].st_ctime_ns):
            raise ValueError("Canonical wrapper host changed before closure")
        os.unlink(Path(WRAPPER_HOST).name, dir_fd=parent)
    os.fsync(parent)
    prove_parent()
    if read_optional(parent, Path(WRAPPER_HOST).name) is not None:
        raise ValueError("Canonical wrapper host reappeared during closure")


def open_host_path(state, parent, label, expected, owner, prove_parent):
    """Apply an already journaled reopen intent without replacing any path."""
    name = Path(WRAPPER_HOST).name
    data = load_host_image(state, label, expected)
    present = attest_host_endpoint(parent, expected, owner, absent_ok=True)
    if present is None:
        write_atomic(state, parent, name, data, expected[0], owner, before_replace=prove_parent, create=True)
    prove_parent()
    attest_host_endpoint(parent, expected, owner)
    os.fsync(parent)
    os.fsync(state)


def encode(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode() + b"\n"


def payload_name(side, index):
    return f"{side}-{index:02d}"


class Hold:
    def __init__(self, args, gate):
        self.args = args
        self.gate = gate
        self.marker_digest = None

    def check_marker(self):
        args = self.args
        path_stat = args.gate.lstat()
        if identity(path_stat) != identity(os.fstat(self.gate)) or path_stat.st_nlink != 1:
            raise ValueError("Maintenance gate was replaced")
        with directory(args.marker.parent) as parent:
            raw, _ = read_file(parent, args.marker.name)
        marker = json.loads(raw)
        if (not isinstance(marker, dict)
                or marker.get("schema") != "integration-release-journal-v1"
                or marker.get("state") != "FOUNDATION_MAINTENANCE"
                or marker.get("maintenance_id") != args.hold_id):
            raise ValueError("Expected the persistent maintenance marker for this hold")
        if self.marker_digest is not None and digest(raw) != self.marker_digest:
            raise ValueError("Maintenance marker changed during the operation")
        self.marker_digest = digest(raw)

    def verify(self, checkpoint):
        self.check_marker()
        args = self.args
        request = {
            "schema": "sprint-4-hold-check-v1",
            "project": str(args.project),
            "state": str(args.state),
            "gate": str(args.gate),
            "marker": str(args.marker),
            "maintenance_id": args.hold_id,
            "source_manifest_sha256": args.manifest_sha256,
            "checkpoint": checkpoint,
            "nonce": secrets.token_hex(16),
        }
        reply = subprocess.run([str(args.verifier)], cwd="/", input=encode(request),
                               stdout=subprocess.PIPE, timeout=15, check=True)
        attestation = json.loads(reply.stdout)
        if (not isinstance(attestation, dict) or attestation.get("verified") is not True
                or attestation != {**request, "verified": True}):
            raise ValueError("Maintenance verifier did not confirm this checkpoint")
        self.check_marker()


class Transaction:
    def __init__(self, args, tree, state, hold, manifest):
        self.args = args
        self.tree = tree
        self.state = state
        self.hold = hold
        self.manifest = manifest
        self.fenced_host = getattr(args, "fenced_host", False)
        self.binding = {
            "schema": "sprint-4-transaction-v1",
            "project": str(args.project),
            "source_directories": source_directories(tree),
            "parked_package": bool(args.parked_package),
            "state_directory": identity(os.fstat(state)),
            "maintenance_id": args.hold_id,
            "gate": str(args.gate),
            "gate_inode": identity(os.fstat(hold.gate)),
            "marker": str(args.marker),
            "marker_sha256": hold.marker_digest,
            "verifier": str(args.verifier),
            "source_manifest_sha256": manifest.sha256,
            "before_manifest_sha256": manifest_digest(manifest.before),
            "after_manifest_sha256": manifest_digest(manifest.after),
        }
        if self.fenced_host:
            self.binding["wrapper_host_fenced"] = True

    def staged_endpoints(self, endpoints):
        if self.fenced_host:
            return {**endpoints, WRAPPER_HOST: None}
        return endpoints

    def read_phase(self):
        try:
            raw, _ = read_file(self.state, JOURNAL)
        except FileNotFoundError:
            return None
        record = json.loads(raw)
        if not isinstance(record, dict):
            raise ValueError("Invalid transaction journal")
        self.phase = record.pop("phase", None)
        self.owners = record.pop("owners", None)
        if (record != self.binding or not isinstance(self.phase, str) or self.phase not in PHASES
                or self.owners != self.manifest.owners):
            raise ValueError("Transaction journal does not bind this installation")
        # A previous process may have died after publishing this journal name
        # but before syncing its directory. Make this phase durable before
        # acting on it or returning a terminal receipt.
        os.fsync(self.state)
        return self.phase

    def record(self, phase):
        write_atomic(self.state, self.state, JOURNAL,
                     encode({**self.binding, "owners": self.owners, "phase": phase}), 0o600)
        self.phase = phase

    def prepare(self):
        if self.args.candidate is None:
            raise ValueError("Initial installation requires --candidate")
        manifest = self.manifest
        self.owners = manifest.owners
        before_pins = self.staged_endpoints(manifest.before)
        after_pins = self.staged_endpoints(manifest.after)
        before = {path: read_optional(*entry(self.tree, path)) for path in manifest.paths}
        self.check_source((before_pins,))
        with source_tree(self.args.candidate) as candidate:
            if mount_id(candidate["root"]) != mount_id(self.state):
                raise ValueError("Candidate and transaction directories must share a mount")
            after = {path: read_file(*entry(candidate, path)) for path in manifest.paths}
        for path in manifest.paths:
            if optional_version(before[path]) != before_pins[path]:
                raise ValueError(f"Base presence, digest or mode drift: {path}")
            if version(*after[path]) != manifest.after[path] or ownership(after[path][1]) != self.owners[path]:
                raise ValueError(f"Candidate digest, mode or owner drift: {path}")
        for side, files, endpoints in (("before", before, before_pins), ("after", after, after_pins)):
            for index, path in enumerate(manifest.paths):
                if endpoints[path] is not None:
                    write_atomic(self.state, self.state, payload_name(side, index),
                                 files[path][0], endpoints[path][0])
        self.load_payload("before", before_pins)
        self.load_payload("after", after_pins)
        self.hold.verify("before-journal")
        self.check_source((before_pins,))
        self.record("INSTALLING")

    def load_payload(self, side, manifest):
        data = {}
        for index, path in enumerate(self.manifest.paths):
            raw = read_optional(self.state, payload_name(side, index))
            if optional_version(raw) != manifest[path]:
                raise ValueError(f"Durable {side} payload presence, digest or mode drift: {path}")
            data[path] = None if raw is None else raw[0]
        return data

    def check_file(self, path, allowable):
        found = read_optional(*entry(self.tree, path))
        measured = optional_version(found)
        if ((found is not None and ownership(found[1]) != self.owners[path])
                or measured not in {m[path] for m in allowable}):
            raise ValueError(f"Unexpected source presence, digest, mode, or owner: {path}")
        return found

    def check_directories(self):
        with source_tree(self.args.project, self.args.parked_package) as current:
            if source_directories(current) != self.binding["source_directories"]:
                raise ValueError("Source directory was replaced")
        if identity(self.args.state.lstat()) != self.binding["state_directory"]:
            raise ValueError("Transaction directory was replaced")

    def check_source(self, allowable):
        self.check_directories()
        for path in self.manifest.paths:
            self.check_file(path, allowable)

    def converge(self, side, manifest, active, terminal):
        # Rollback requires only the original payload, not the candidate.
        before, after = (self.staged_endpoints(self.manifest.before), self.staged_endpoints(self.manifest.after))
        manifest = self.staged_endpoints(manifest)
        if side == "after":
            self.load_payload("before", before)
        payload = self.load_payload(side, manifest)
        if self.phase == terminal:
            self.check_source((manifest,))
            return
        expected = (after,) if self.phase == "INSTALLED" else (before, after)
        self.check_source(expected)
        if self.phase != active:
            self.record(active)
        for path in self.manifest.paths:
            self.hold.verify(f"{active}:{path}")
            self.replace_file(path, payload[path], manifest[path])
        # Replay can see a prior rename or unlink whose directory sync did not run.
        for fd in {self.state, *(entry(self.tree, path)[0] for path in self.manifest.paths)}:
            os.fsync(fd)
        self.hold.verify(f"before-{terminal}")
        self.check_source((manifest,))
        self.record(terminal)

    def replace_file(self, path, data, target):
        allowed = (self.staged_endpoints(self.manifest.before), self.staged_endpoints(self.manifest.after))
        found = self.check_file(path, allowed)
        measured = optional_version(found)
        if measured == target:
            return

        def verify_original():
            self.check_directories()
            current = self.check_file(path, allowed)
            if (optional_version(current) != measured
                    or (found is not None and (identity(found[1]), found[1].st_ctime_ns)
                        != (identity(current[1]), current[1].st_ctime_ns))):
                raise ValueError(f"Source changed while replacement was staged: {path}")

        parent, name = entry(self.tree, path)
        if target is None:
            verify_original()
            os.unlink(name, dir_fd=parent)
            os.fsync(parent)
        else:
            write_atomic(self.state, parent, name, data, target[0], self.owners[path],
                         before_replace=verify_original, create=found is None)

    def run(self):
        phase = self.read_phase()
        action = self.args.action
        if action == "install":
            if phase is None:
                self.prepare()
            elif phase in {"ROLLING_BACK", "ROLLED_BACK"}:
                raise ValueError("Rollback selected; use rollback to finish or verify it")
            self.converge("after", self.manifest.after, "INSTALLING", "INSTALLED")
        elif action == "rollback":
            if phase is None:
                raise ValueError("No durable installation journal to roll back")
            self.converge("before", self.manifest.before, "ROLLING_BACK", "ROLLED_BACK")
        elif phase in {"INSTALLED", "ROLLED_BACK"}:
            self.load_payload("before", self.staged_endpoints(self.manifest.before))
            if phase == "INSTALLED":
                self.load_payload("after", self.staged_endpoints(self.manifest.after))
            manifest = self.manifest.after if phase == "INSTALLED" else self.manifest.before
            self.check_source((self.staged_endpoints(manifest),))
        else:
            raise ValueError("No terminal transaction to verify")
        self.hold.verify(f"verified-{self.phase}")
        return {**self.binding, "phase": self.phase}


def canonical(path):
    if not path.is_absolute() or path.resolve(strict=True) != path:
        raise ValueError(f"Use a canonical absolute path: {path}")


def independent(left, right):
    if left.is_relative_to(right) or right.is_relative_to(left):
        raise ValueError(f"Paths must be separate: {left} and {right}")


def run(args):
    manifest = load_manifest(args.manifest, args.manifest_sha256)
    for path in (args.project, args.state, args.gate, args.marker, args.verifier, args.manifest):
        canonical(path)
    for path in (args.gate, args.marker, args.verifier, args.manifest):
        independent(path, args.state)
    for path in (args.gate, args.state, args.verifier, args.manifest):
        independent(path, args.project)
    if args.marker.name != "integration-release-journal.json":
        raise ValueError("Expected the runtime integration release journal")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", args.hold_id):
        raise ValueError("Invalid maintenance hold ID")
    if args.candidate is not None:
        canonical(args.candidate)
        independent(args.project, args.candidate)
        independent(args.state, args.candidate)
    with ExitStack() as stack:
        tree = stack.enter_context(source_tree(args.project, args.parked_package))
        state = stack.enter_context(directory(args.state))
        state_info = os.fstat(state)
        if state_info.st_uid != os.geteuid() or stat.S_IMODE(state_info.st_mode) != 0o700:
            raise ValueError("The transaction directory must be owned by this user and mode 0700")
        if mount_id(tree["root"]) != mount_id(state):
            raise ValueError("Transaction and source directories must share a mount")
        gate = os.open(args.gate, READ)
        stack.callback(os.close, gate)
        info = os.fstat(gate)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size != 0
                or stat.S_IMODE(info.st_mode) != 0o600):
            raise ValueError("Gate must be an empty, single-link regular file with mode 0600")
        fcntl.flock(gate, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(state, fcntl.LOCK_EX | fcntl.LOCK_NB)
        hold = Hold(args, gate)
        hold.verify("entry")
        expected = {JOURNAL, ".pending"}
        expected.update(payload_name(side, index)
                        for side, endpoints in (("before", manifest.before), ("after", manifest.after))
                        for index, path in enumerate(manifest.paths) if endpoints[path] is not None)
        if set(os.listdir(state)) - expected:
            raise ValueError("Transaction directory contains files outside the transaction")
        with directory(args.state.parent) as parent:
            os.fsync(parent)
        return Transaction(args, tree, state, hold, manifest).run()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=("install", "rollback", "verify"))
    for name in ("project", "state", "gate", "marker", "verifier", "manifest"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    parser.add_argument("--hold-id", required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--parked-package", action="store_true",
                        help=f"target src/{PARKED_PACKAGE} under the controller's import guard")
    parser.add_argument("--fenced-host", action="store_true",
                        help="require the canonical host to remain absent throughout installer convergence")
    args = parser.parse_args()
    try:
        receipt = run(args)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Maintenance transaction stopped. Keep the hold in place. {error}\n")
    print(encode(receipt).decode(), end="")


if __name__ == "__main__":
    main()
