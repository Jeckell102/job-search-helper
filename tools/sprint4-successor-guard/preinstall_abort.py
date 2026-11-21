"""Restore an approved alternate closure after a witnessed controller preflight refusal."""
from contextlib import ExitStack, contextmanager
from dataclasses import asdict
import fcntl
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import re
import stat
import subprocess
from zipfile import ZipFile

import controller as joint
from host_exchange import HostExchange, encode, pin, require, unique_fields


ENROLLMENT = "sprint-4-preinstall-abort-enrollment-v2"
ATTEMPT = "sprint-4-preinstall-abort-refusal-v2"
SCHEMA = "sprint-4-preinstall-abort-v2"
NOT_INVOKED = "sprint-4-preinstall-not-invoked-v2"
ATTEMPT_LOCK = "attempt.lock"
REFUSAL = b"Maintenance stopped. Preserve the bundle for recovery. Host checker refused preflight\n"
BOOT_ID = Path("/proc/sys/kernel/random/boot_id")
HEX = re.compile(r"[0-9a-f]{64}")

# Import only the original sealed archive in an isolated interpreter. The site
# checkpoint's controller authentication intentionally cannot authenticate this
# abort process. Reuse its read-only logical verifier with a real lease check.
PROTECTED_CHECK = """
import json
import os
import sys

sys.path.insert(0, '/proc/self/fd/' + sys.argv[1])
from protected_state import verify_protected_state, verify_release_lease

project, pin, digest, owner = json.load(sys.stdin)
if os.getppid() != owner:
    sys.exit(1)
verified = verify_protected_state(project, pin, digest, maintenance_id=None,
                                  verify_release_hold=lambda: verify_release_lease(project, owner))
if verified is not True or os.getppid() != owner or verify_release_lease(project, owner) is not True:
    sys.exit(1)
"""


def approved_object(raw, digest, schema, keys):
    require(type(raw) is bytes and raw and isinstance(digest, str) and HEX.fullmatch(digest)
            and sha256(raw).hexdigest() == digest, "Abort evidence differs from its independently held pin")
    record = json.loads(raw, object_pairs_hook=unique_fields)
    require(type(record) is dict and set(record) == {"schema", *keys}
            and record["schema"] == schema and encode(record) == raw, "Malformed abort evidence")
    return record


def directory_identity(path, *, empty=False):
    joint.private_dir(path)
    with joint.installer.directory(path) as descriptor:
        info = os.fstat(descriptor)
        require(os.path.samestat(info, path.lstat()), "Original private directory was replaced")
        identity = asdict(pin(descriptor))
        if empty:
            require(not os.listdir(descriptor), "Installer has an existing transaction")
            require(info.st_ctime_ns == path.lstat().st_ctime_ns, "Installer directory changed during inspection")
            identity["ctime_ns"] = info.st_ctime_ns
        return identity


def leases(controller):
    # Match normal controller order. The package install lock precedes the
    # installer gate, followed by the three application writer locks.
    return [controller.controller_gate, controller.locks[0], controller.install_gate, *controller.locks[1:]]


def lock_identity(path, descriptor=None):
    if descriptor is None:
        fd = os.open(joint.physical(path), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            return lock_identity(path, fd)
        finally:
            os.close(fd)
    info = os.fstat(descriptor)
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == os.geteuid()
            and os.path.samestat(info, path.lstat()), "Original lease path was replaced")
    return {**asdict(pin(descriptor)), "ctime_ns": info.st_ctime_ns}


def checker_policy(controller, checker_sha256, protected_pin_sha256):
    archive, attrs = joint.read(joint.physical(controller.checker))
    require(sha256(archive).hexdigest() == checker_sha256
            and os.path.samestat(attrs, controller.checker.lstat()), "Approved host checker differs")
    with ZipFile(BytesIO(archive)) as checker:
        require(checker.namelist().count("approved_site_policy.json") == 1
                and checker.namelist().count("protected_state.py") == 1, "Host checker lacks its approved modules")
        policy = json.loads(checker.read("approved_site_policy.json"), object_pairs_hook=unique_fields)
    site = policy["site"]
    require(policy["schema"] == "sprint-4-site-policy-v1"
            and site["maintenance_bundle"] == str(controller.bundle)
            and site["project"] == str(controller.project)
            and site["maintenance_id"] == controller.hold_id
            and site["manifest_sha256"] == controller.manifest.sha256
            and site["marker"] == str(controller.marker)
            and site["lock_paths"] == list(map(str, controller.locks))
            and site["cache_prefixes"] == list(map(str, controller.prefixes))
            and site["source_paths"] and set(site["source_paths"]) == set(controller.manifest.paths)
            and site["launch_uid"] == os.geteuid()
            and controller.backend == "sqlite"
            and controller.project / ".state/scraper.lock" in controller.locks,
            "Host checker belongs to another controller or policy")
    protected_path = joint.physical(Path(policy["protected_pin_file"]))
    protected_ref = joint.ref(protected_path)
    require(policy["protected_pin_sha256"] == protected_pin_sha256
            and protected_ref[2] == 0o600 and protected_ref[3] == os.geteuid()
            and protected_ref[-1] == protected_pin_sha256, "Approved protected-state pin differs")
    fence = site["exchange_fence"]
    require(type(fence) is dict and fence["launch_uid"] == os.geteuid()
            and not site["covers"] and sorted(site["alternate_roots"]) == sorted(pair[0] for pair in fence["pairs"]),
            "Host checker lacks the approved exchange fence")
    return archive, {"path": str(protected_path), "ref": protected_ref}, fence


def block_installation_routes(controller):
    private_paths = (
        controller.journal, controller.marker, controller.units.sentinel,
        controller.bundle / joint.STAGED_EXTENSION,
        *(controller.bundle / joint.installer.host_image_name(side) for side in ("before", "after")),
        *(controller.units.path(name) for name in joint.UNITS),
    )
    require(not any(joint.present(path) for path in private_paths),
            "Joint installation has started or still owns a protected route")
    controller.verify_preinstall_parked()
    with joint.installer.directory(controller.canonical) as package:
        require(not joint.extension_present(package), "Canonical extension guard is present")


def source_before(controller):
    require(joint.scope(controller.project, False, controller.manifest.paths, controller.manifest.owners)
            == controller.manifest.before, "Original source differs from the enrolled before image")


def checked_capsule(bundle, checker_sha256, protected_pin_sha256):
    controller = joint.Controller(bundle)
    archive, protected, fence = checker_policy(controller, checker_sha256, protected_pin_sha256)
    require(joint.physical(controller.candidate) == controller.candidate
            and joint.mount(controller.candidate) == joint.mount(bundle)
            and joint.scope(controller.candidate, False, controller.manifest.paths, controller.manifest.owners)
            == controller.manifest.after, "Original capsule candidate differs")
    identity = {"bundle": str(bundle), "capsule": directory_identity(bundle),
                "controller": controller.binding, "checker_sha256": checker_sha256,
                "protected_pin": protected, "fence": fence,
                "canonical": joint.inode(controller.canonical), "candidate": joint.inode(controller.candidate),
                "unscoped": joint.unscoped(controller.canonical, controller.package_names),
                "unscoped_wrapper": joint.unscoped(controller.wrapper_tools, controller.wrapper_names)}
    return controller, archive, identity


def closed_identity(witness, fence):
    identity = {
        "generation": witness.generation, "policy_sha256": witness.policy_sha256,
        "intent_sha256": witness.intent_sha256, "control": str(witness.control),
        "mount_namespace": witness.mount_namespace,
        "paths": [[str(pair.canonical), str(pair.parked)] for pair in witness.pairs],
    }
    require(witness.phase == "closed" and witness.terminal_proof_sha256 is None
            and witness.policy_sha256 == fence["policy_sha256"]
            and witness.generation == fence["generation"] and witness.intent_sha256 == fence["intent_sha256"]
            and witness.control == Path(fence["policy_file"]).parent and identity["paths"] == fence["pairs"],
            "Exchange differs from the original approved closed generation")
    return identity


def attempt_identity(path):
    return {"path": str(path), "directory": directory_identity(path), "lock": lock_identity(path / ATTEMPT_LOCK)}


def require_unused_attempt(path):
    require(set(os.listdir(path)) == {ATTEMPT_LOCK}, "Original attempt directory already contains launch evidence")


def enroll_abort(bundle, *, attempt_directory, approved_checker_sha256, approved_protected_pin_sha256):
    """Observe the exact pre-attempt empty boundary without changing the host."""
    controller, _, identity = checked_capsule(bundle, approved_checker_sha256, approved_protected_pin_sha256)
    block_installation_routes(controller)
    require(not joint.present(controller.state), "Original transaction directory already exists")
    for path in (controller.controller_gate, controller.install_gate):
        joint.check_file(path, b"", 0o600)
    roots = [controller.project, controller.bundle, Path(identity["fence"]["policy_file"]).parent,
             *(Path(route) for pair in identity["fence"]["pairs"] for route in pair)]
    require(not any(attempt_directory.is_relative_to(root) or root.is_relative_to(attempt_directory)
                    for root in roots), "Original attempt directory overlaps a protected route")
    joint.check_file(attempt_directory / ATTEMPT_LOCK, b"", 0o600)
    require_unused_attempt(attempt_directory)
    source_before(controller)
    return encode({"schema": ENROLLMENT, **identity,
                   "leases": {str(path): lock_identity(path) for path in leases(controller)},
                   "attempt": attempt_identity(attempt_directory)})


def enrolled_capsule(enrollment, approved_enrollment_sha256):
    original = approved_object(enrollment, approved_enrollment_sha256, ENROLLMENT,
                               {"bundle", "capsule", "controller", "checker_sha256", "protected_pin",
                                "fence", "leases", "canonical", "candidate", "unscoped", "unscoped_wrapper", "attempt"})
    controller, archive, identity = checked_capsule(Path(original["bundle"]), original["checker_sha256"],
                                                    original["protected_pin"]["ref"][-1])
    require(all(original[key] == value for key, value in identity.items()), "Original capsule identity changed")
    require({str(path): lock_identity(path) for path in leases(controller)} == original["leases"],
            "Original lease identity changed")
    return controller, archive, original


@contextmanager
def attempt_custody(original):
    directory = Path(original["attempt"]["path"])
    path = directory / ATTEMPT_LOCK
    with joint.lock(path) as fd:
        require(attempt_identity(directory) == original["attempt"]
                and lock_identity(path, fd) == original["attempt"]["lock"], "Original attempt custody changed")
        yield directory


def exchange_for(original, *, write=False):
    fence = original["fence"]
    return HostExchange(fence["policy_file"], fence["policy_sha256"], enable_host_writes=write)


def state_identity(controller):
    identity = directory_identity(controller.state, empty=True)
    require(identity["mount_id"] == joint.mount(controller.bundle), "Installer state is on another mount")
    return identity


def process_start(pid):
    return int(Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19])


def require_exited(process):
    boot, pid, started = process
    require(boot == BOOT_ID.read_text().strip() and type(pid) is int and pid > 0
            and type(started) is int and started > 0, "Original process identity is unavailable")
    try:
        current = process_start(pid)
    except FileNotFoundError:
        return
    require(current != started, "Original controller process has not exited")


def open_private_output(path):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_DSYNC
    return os.fdopen(os.open(path, flags, 0o600), "wb")


def capture_refused_install(enrollment, *, approved_enrollment_sha256):
    """Run the authorized install once and retain its complete outcome in the enrolled directory."""
    controller, _, original = enrolled_capsule(enrollment, approved_enrollment_sha256)
    with attempt_custody(original) as log:
        enrolled_capsule(enrollment, approved_enrollment_sha256)
        require_unused_attempt(log)
        block_installation_routes(controller)
        require(not joint.present(controller.state), "Original attempt is missing its pre-invocation boundary")
        source_before(controller)
        exchange = exchange_for(original)
        closure = closed_identity(exchange.witness("closed"), original["fence"])
        argv = [str(controller.bundle / "controller.py"), "install"]
        launch = {"enrollment_sha256": approved_enrollment_sha256, "argv": argv, "exchange": closure}
        joint.write(log / "launch.json", encode(launch))
        with open_private_output(log / "stdout") as output, open_private_output(log / "stderr") as errors:
            joint.gate.syncdir(log)
            with subprocess.Popen(argv, cwd="/", stdin=subprocess.DEVNULL, stdout=output, stderr=errors) as process:
                identity = [BOOT_ID.read_text().strip(), process.pid, process_start(process.pid)]
                joint.write(log / "process.json", encode(identity))
                returncode = process.wait()
            os.fsync(output.fileno())
            os.fsync(errors.fileno())
        joint.write(log / "exit.json", encode({"process": identity, "returncode": returncode}))
        require(returncode == 1 and (log / "stdout").stat().st_size == 0
                and (log / "stderr").stat().st_size <= 16384,
                "Original install produced a non-abort outcome. Read the enrolled attempt directory.")
        stderr, _ = joint.read(log / "stderr")
        require(stderr.endswith(REFUSAL), "Original install did not exit with the controller's preflight refusal")
        require_exited(identity)
        enrolled_capsule(enrollment, approved_enrollment_sha256)
        block_installation_routes(controller)
        transaction = state_identity(controller)
        require(closed_identity(exchange.witness("closed"), original["fence"]) == closure,
                "Original exchange changed during the attempted install")
        receipt = encode({"schema": ATTEMPT, **launch, "process": identity, "returncode": returncode,
                          "stdout": "", "stderr": stderr.hex(), "transaction": transaction})
        joint.write(log / "refusal.json", receipt)
        return receipt


def verify_protected(controller, archive, protected):
    descriptor = os.memfd_create("approved-s4-host-check", flags=os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
    with os.fdopen(descriptor, "wb") as sealed:
        sealed.write(archive)
        sealed.flush()
        fcntl.fcntl(descriptor, fcntl.F_ADD_SEALS,
                    fcntl.F_SEAL_WRITE | fcntl.F_SEAL_GROW | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_SEAL)
        proc = subprocess.run(["/usr/bin/python3", "-I", "-B", "-c", PROTECTED_CHECK, str(descriptor)],
                              cwd="/", env={}, input=encode([str(controller.project), protected["path"],
                                                            protected["ref"][-1], os.getpid()]),
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              pass_fds=(descriptor,), timeout=180, check=False)
    require(proc.returncode == 0, "Original protected application baseline could not be verified")


def require_original_refusal(log, attempt, result):
    require_exited(result["process"])
    launch = {key: result[key] for key in ("enrollment_sha256", "argv", "exchange")}
    expected = {
        "launch.json": encode(launch), "process.json": encode(result["process"]),
        "exit.json": encode({key: result[key] for key in ("process", "returncode")}),
        "refusal.json": attempt, "stdout": b"", "stderr": bytes.fromhex(result["stderr"]),
    }
    for name, content in expected.items():
        joint.check_file(log / name, content, 0o600)


@contextmanager
def original_source(enrollment, approved_enrollment_sha256, *, refusal=None):
    controller, archive, original = enrolled_capsule(enrollment, approved_enrollment_sha256)
    with ExitStack() as held:
        log = held.enter_context(attempt_custody(original))
        if refusal is not None:
            attempt, approved_attempt_sha256 = refusal
            result = approved_object(attempt, approved_attempt_sha256, ATTEMPT,
                                     {"enrollment_sha256", "argv", "process", "returncode", "stdout", "stderr",
                                      "transaction", "exchange"})
            require(result["enrollment_sha256"] == approved_enrollment_sha256
                    and result["argv"] == [str(controller.bundle / "controller.py"), "install"]
                    and type(result["returncode"]) is int and result["returncode"] == 1 and result["stdout"] == ""
                    and bytes.fromhex(result["stderr"]).endswith(REFUSAL), "Original preflight refusal proof differs")
        descriptors = {path: held.enter_context(joint.lock(path)) for path in leases(controller)}

        def verify_boundary():
            joint.locked_by(os.getpid(), [*descriptors, log / ATTEMPT_LOCK])
            require({str(path): lock_identity(path, fd) for path, fd in descriptors.items()} == original["leases"],
                    "Original held lease identity changed")
            require(attempt_identity(log) == original["attempt"], "Original attempt custody changed")
            enrolled_capsule(enrollment, approved_enrollment_sha256)
            if refusal is None:
                require_unused_attempt(log)
                require(not joint.present(controller.state), "Original transaction directory is present")
            else:
                require_original_refusal(log, attempt, result)
                require(state_identity(controller) == result["transaction"], "Original installer directory changed")
            block_installation_routes(controller)
            source_before(controller)

        def verify_original(witness):
            closure = closed_identity(witness, original["fence"])
            verify_boundary()
            verify_protected(controller, archive, original["protected_pin"])
            verify_boundary()
            plan = {"schema": NOT_INVOKED, "enrollment_sha256": approved_enrollment_sha256, "exchange": closure}
            if refusal is not None:
                require(closure == result["exchange"], "Exchange no longer matches the original refusal")
                plan.update(schema=SCHEMA, attempt_sha256=approved_attempt_sha256)
            return plan

        yield original, verify_original


def observe(enrollment, approved_enrollment_sha256, *, refusal=None):
    with original_source(enrollment, approved_enrollment_sha256, refusal=refusal) as (original, verify_original):
        exchange = exchange_for(original)
        witness = exchange.witness("closed")
        result = verify_original(witness)
        require(exchange.witness("closed") == witness, "Exchange changed during abort observation")
        return result


def restore(enrollment, approved_enrollment_sha256, approval, approved_sha256, enable_host_writes, *, refusal=None):
    schema, keys = NOT_INVOKED, {"enrollment_sha256", "exchange"}
    if refusal is not None:
        schema, keys = SCHEMA, {*keys, "attempt_sha256"}
    plan = approved_object(approval, approved_sha256, schema, keys)
    with original_source(enrollment, approved_enrollment_sha256, refusal=refusal) as (original, verify_original):
        def verify_terminal(witness, evidence):
            return evidence == approval and verify_original(witness) == plan

        return exchange_for(original, write=enable_host_writes).restore(approval, verify_terminal=verify_terminal)


def observe_abort(enrollment, attempt, *, approved_enrollment_sha256, approved_attempt_sha256):
    return observe(enrollment, approved_enrollment_sha256, refusal=(attempt, approved_attempt_sha256))


def restore_abort(enrollment, attempt, approval, *, approved_enrollment_sha256, approved_attempt_sha256,
                  approved_sha256, enable_host_writes=False):
    return restore(enrollment, approved_enrollment_sha256, approval, approved_sha256, enable_host_writes,
                   refusal=(attempt, approved_attempt_sha256))


def observe_not_invoked(enrollment, *, approved_enrollment_sha256):
    return observe(enrollment, approved_enrollment_sha256)


def restore_not_invoked(enrollment, approval, *, approved_enrollment_sha256, approved_sha256,
                        enable_host_writes=False):
    return restore(enrollment, approved_enrollment_sha256, approval, approved_sha256, enable_host_writes)
