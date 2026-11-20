"""Sprint 1 exact-source transaction. Requires an independent maintenance controller.

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
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess


# Canonical aggregate: SHA-256 of lines "MODE SHA256 RELATIVE_PATH\n", sorted
# by path, with four octal digits. Both tables bind all 13 installed modes.
SCOPE = (
    "job-search-helper",
    "job-search-scraper",
    "release_admission_bootstrap.py",
    "src/job_search_helper/cli.py",
    "src/job_search_helper/engine.py",
    "src/job_search_helper/exact_cycle_recovery.py",
    "src/job_search_helper/inbox.py",
    "src/job_search_helper/integration_release.py",
    "src/job_search_helper/launcher.py",
    "src/job_search_helper/local_pipeline.py",
    "src/job_search_helper/runner.py",
    "src/job_search_helper/scrape_first_pass.py",
    "src/job_search_helper/sync_cli.py",
)
ROWS = (
    (0o775, "3be128e037f9fc4d18d8add3ac7f1c09ba9e8aee11ea9dfaabf4604559a11c71", "f692b6b6dbe57961402972190b61d8fc4d575f944f9be163c9ef9b2a6ed7c5bf"),
    (0o755, "d57553bc170006d5faeec39bad0abd47538216080972174b53af83b39f19da0a", "cb8469304e44372e375baa6e33700be7326c2f237ce8e1b3e6980784c51435bf"),
    (0o664, "8e1fd9441bf23c82d1c6e6385813497641fd8b826c7fb9de4ed25f32d17b876b", "758509aad23c415e16d075f81776fa0348722e171655b51d9d281f3f8d148437"),
    (0o644, "84a0d37bf852b9e36eb060bd56be0711bf1179de124a56895d9e3792a51b557e", "a2ceca8ea944d81f7385ad3771924671c2f6024cfd6c700c56fde4ff53e63e7f"),
    (0o644, "093a6d3a8568a46f82991d67976aaddf0dde0d18eaa6e48389b7d9c89a3ccd74", "faf5d9493dce9f1c6fdb569cffdf3481c2ea35a2e9c6091a04958b955be0e1b5"),
    (0o664, "7758cb3f291f8c9394b47e3eda3aa70daca02ac4cef3e0e7877b5fcf13b88219", "033a4bc48035cac0e28cb129029e88da12e7102e782679e7af3098fb9432b7a1"),
    (0o664, "e56a7d30857f0cf29b169a00ad762f0feeda800ddf9c0031ade025ab238d1f44", "e100003bd7f04d1dc7109c1f07b44cf19d502ab25a3316f04bec9f8cb2d346ec"),
    (0o664, "394d15185d881f07a7742f319a462b391ff30e4ceaf5aae8311a2c8683edf2c1", "9ddd1e9c6908670415f6e4c7b61dbf5e16d0297e2f32213afeedbd37d77217ff"),
    (0o664, "e046ef9181de3e033435493f49dfc82ae013975f9e11bd379222bb9af78f6653", "b0b58f207e6291c07d98e225f58f248708f9f4e2b695f3eede2ea935ab88eda3"),
    (0o644, "3a4160e712cbfa374b0d8bc61e8c93135cc742ae910282b08c9cfdd6a466167a", "1b5029b85d4d54bb9239881b7ec7ce4c19b1c50ffb350ef2b0d197a0e2f16862"),
    (0o664, "2ac017c5de16135db7d9ba833df75fc9ddb4e3178ade28c9ef4fc51cb713c3be", "fed4267cb4c9afb55433f4d59a4f5691d4e49a45ed3011f55e7aad57faced7b3"),
    (0o664, "9cc3942bc83fd9b05aac27d5b3404b9ac69e038e15b4a1c6b2d63486222e847f", "0f9faa554199a52d1b3279df51dc0f89af3a0f03f84a4b1429554903f100ea26"),
    (0o664, "da5529a95c765239c1fee3b8abec9811cf55b979e5d1411666e0b4fc08075cd5", "336f688967d463fda07f69ba5625cf7170749edbe55555dcd11b429b08fc5662"),
)
BEFORE = {path: (mode, before) for path, (mode, before, _) in zip(SCOPE, ROWS, strict=True)}
AFTER = {path: (mode, after) for path, (mode, _, after) in zip(SCOPE, ROWS, strict=True)}
PHASES = {"INSTALLING", "INSTALLED", "ROLLING_BACK", "ROLLED_BACK"}
DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
READ = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
JOURNAL = "transaction.json"
PARKED_PACKAGE = ".f3-maintenance-package"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def manifest_digest(manifest):
    return digest("".join(f"{mode:04o} {sha} {path}\n"
                          for path, (mode, sha) in sorted(manifest.items())).encode())


def identity(info):
    return [info.st_dev, info.st_ino]


def ownership(info):
    return [info.st_uid, info.st_gid]


def version(data, info):
    return stat.S_IMODE(info.st_mode), digest(data)


@contextmanager
def directory(name, parent=None):
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
        if parked:
            guard = stack.enter_context(directory("job_search_helper", src))
            if os.path.samestat(os.fstat(package), os.fstat(guard)):
                raise ValueError("The parked package and canonical guard must be distinct")
            yield root, package, src, guard
        else:
            yield root, package, src


def entry(tree, path):
    return tree[1 if "/" in path else 0], path.rsplit("/", 1)[-1]


def read_file(parent, name):
    fd = os.open(name, READ, dir_fd=parent)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError(f"Expected a regular file with one link: {name}")
        data = stream.read()
        after = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if (identity(info), info.st_ctime_ns) != (identity(after), after.st_ctime_ns):
            raise ValueError(f"File changed during read: {name}")
    return data, info


def write_atomic(state, parent, name, data, mode, owner=None, before_replace=None):
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
    os.replace(scratch, name, src_dir_fd=state, dst_dir_fd=parent)
    os.fsync(parent)
    if parent != state:
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
            "schema": "sprint-1-hold-check-v1",
            "project": str(args.project),
            "state": str(args.state),
            "gate": str(args.gate),
            "marker": str(args.marker),
            "maintenance_id": args.hold_id,
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
    def __init__(self, args, tree, state, hold):
        self.args = args
        self.tree = tree
        self.state = state
        self.hold = hold
        self.binding = {
            "schema": "sprint-1-transaction-v1",
            "project": str(args.project),
            "source_directories": [identity(os.fstat(fd)) for fd in tree],
            "parked_package": bool(args.parked_package),
            "state_directory": identity(os.fstat(state)),
            "maintenance_id": args.hold_id,
            "gate": str(args.gate),
            "gate_inode": identity(os.fstat(hold.gate)),
            "marker": str(args.marker),
            "marker_sha256": hold.marker_digest,
            "verifier": str(args.verifier),
            "before_manifest_sha256": manifest_digest(BEFORE),
            "after_manifest_sha256": manifest_digest(AFTER),
        }

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
                or not isinstance(self.owners, dict) or set(self.owners) != set(SCOPE)
                or any(not isinstance(owner, list) or len(owner) != 2
                       or any(type(part) is not int or part < 0 for part in owner)
                       for owner in self.owners.values())):
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
        with source_tree(self.args.candidate) as candidate:
            before = {path: read_file(*entry(self.tree, path)) for path in SCOPE}
            after = {path: read_file(*entry(candidate, path)) for path in SCOPE}
        for path in SCOPE:
            if version(*before[path]) != BEFORE[path]:
                raise ValueError(f"Base digest or mode drift: {path}")
            if version(*after[path]) != AFTER[path]:
                raise ValueError(f"Candidate digest or mode drift: {path}")
        self.owners = {path: ownership(info) for path, (_, info) in before.items()}
        for side, files, manifest in (("before", before, BEFORE), ("after", after, AFTER)):
            for index, path in enumerate(SCOPE):
                write_atomic(self.state, self.state, payload_name(side, index),
                             files[path][0], manifest[path][0])
        self.load_payload("before", BEFORE)
        self.load_payload("after", AFTER)
        self.hold.verify("before-journal")
        self.check_source((BEFORE,))
        self.record("INSTALLING")

    def load_payload(self, side, manifest):
        data = {}
        for index, path in enumerate(SCOPE):
            value, info = read_file(self.state, payload_name(side, index))
            if version(value, info) != manifest[path]:
                raise ValueError(f"Durable {side} payload digest or mode drift: {path}")
            data[path] = value
        return data

    def check_file(self, path, allowable):
        value, info = read_file(*entry(self.tree, path))
        measured = version(value, info)
        if ownership(info) != self.owners[path] or measured not in {m[path] for m in allowable}:
            raise ValueError(f"Unexpected source digest, mode, or owner: {path}")
        return measured

    def check_source(self, allowable):
        with source_tree(self.args.project, self.args.parked_package) as current:
            if [identity(os.fstat(fd)) for fd in current] != self.binding["source_directories"]:
                raise ValueError("Source directory was replaced")
        if identity(self.args.state.lstat()) != self.binding["state_directory"]:
            raise ValueError("Transaction directory was replaced")
        for path in SCOPE:
            self.check_file(path, allowable)

    def converge(self, side, manifest, active, terminal):
        # Check both payloads before installation, so rollback remains available.
        # Rollback needs only the durable original, even if the candidate is lost.
        if side == "after":
            self.load_payload("before", BEFORE)
        payload = self.load_payload(side, manifest)
        if self.phase == terminal:
            self.check_source((manifest,))
            return
        expected = (AFTER,) if self.phase == "INSTALLED" else (BEFORE, AFTER)
        self.check_source(expected)
        if self.phase != active:
            self.record(active)
        for path in SCOPE:
            self.hold.verify(f"{active}:{path}")
            self.replace_file(path, payload[path], manifest)
        # Reflush both destination directories even where replay skipped a
        # rename that was visible after process death before its directory fsync.
        for fd in (*self.tree[:2], self.state):
            os.fsync(fd)
        self.hold.verify(f"before-{terminal}")
        self.check_source((manifest,))
        self.record(terminal)

    def replace_file(self, path, data, manifest):
        measured = self.check_file(path, (BEFORE, AFTER))
        if measured == manifest[path]:
            return

        def verify_original():
            if self.check_file(path, (BEFORE, AFTER)) != measured:
                raise ValueError(f"Source changed while replacement was staged: {path}")

        parent, name = entry(self.tree, path)
        write_atomic(self.state, parent, name, data, manifest[path][0], self.owners[path],
                     before_replace=verify_original)

    def run(self):
        phase = self.read_phase()
        action = self.args.action
        if action == "install":
            if phase is None:
                self.prepare()
            elif phase in {"ROLLING_BACK", "ROLLED_BACK"}:
                raise ValueError("Rollback selected; use rollback to finish or verify it")
            self.converge("after", AFTER, "INSTALLING", "INSTALLED")
        elif action == "rollback":
            if phase is None:
                raise ValueError("No durable installation journal to roll back")
            self.converge("before", BEFORE, "ROLLING_BACK", "ROLLED_BACK")
        elif phase in {"INSTALLED", "ROLLED_BACK"}:
            self.load_payload("before", BEFORE)
            if phase == "INSTALLED":
                self.load_payload("after", AFTER)
            manifest = AFTER if phase == "INSTALLED" else BEFORE
            self.check_source((manifest,))
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
    for path in (args.project, args.state, args.gate, args.marker, args.verifier):
        canonical(path)
    for path in (args.gate, args.marker, args.verifier):
        independent(path, args.state)
    for path in (args.gate, args.state, args.verifier):
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
        if any(os.fstat(fd).st_dev != state_info.st_dev for fd in tree):
            raise ValueError("Transaction and source directories must share a filesystem")
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
                        for side in ("before", "after") for index in range(len(SCOPE)))
        if set(os.listdir(state)) - expected:
            raise ValueError("Transaction directory contains files outside the transaction")
        with directory(args.state.parent) as parent:
            os.fsync(parent)
        return Transaction(args, tree, state, hold).run()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=("install", "rollback", "verify"))
    for name in ("project", "state", "gate", "marker", "verifier"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    parser.add_argument("--hold-id", required=True)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--parked-package", action="store_true",
                        help=f"target src/{PARKED_PACKAGE} under the controller's import guard")
    args = parser.parse_args()
    try:
        receipt = run(args)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Maintenance transaction stopped. Keep the hold in place. {error}\n")
    print(encode(receipt).decode(), end="")


if __name__ == "__main__":
    main()
