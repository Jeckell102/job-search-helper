#!/usr/bin/python3
"""Observe or restore one approved Sprint 4 retained pilot from a private bundle."""
import argparse
from contextlib import closing
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import re
import stat
import sys
from types import ModuleType
from zipfile import ZipFile


SCHEMA = "sprint-4-pilot-selection-v1"
ROLLBACK_SELECTION_SCHEMA = "sprint-4-pre-pilot-rollback-selection-v1"
TOOLS = frozenset({
    "pilot_restore_command.py", "host_exchange.py", "pilot_restoration.py",
    "retained_pilot_receiver.py", "retained_pilot_terminal.py", "controller.py",
    "installer.py", "gate.py", "verify_hold", "host-check", "plan.json", "manifest.json",
})
PILOT_FIELDS = frozenset({
    "request_sha256", "reservation_digest", "company_event_id",
    "company_id", "source_revision", "blocking_cycle_id",
})


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def read_file(path, *, private=False, limit=16 * 1024 * 1024):
    require(path.is_absolute() and path.resolve(strict=True) == path, "Evidence path is not canonical")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        initial = os.fstat(stream.fileno())
        require(stat.S_ISREG(initial.st_mode) and initial.st_nlink == 1
                and initial.st_uid == os.geteuid()
                and (not private or stat.S_IMODE(initial.st_mode) == 0o600),
                "Evidence file ownership, links, or mode is unsafe")
        data = stream.read(limit + 1)
        after = path.lstat()
        require(len(data) <= limit and os.path.samestat(initial, after)
                and initial.st_ctime_ns == after.st_ctime_ns, "Evidence file changed or is too large")
        return data


def read_selection(path, approved_sha256):
    data = read_file(path, private=True, limit=256 * 1024)
    require(sha256(data).hexdigest() == approved_sha256, "Selection differs from its approved digest")
    selection = json.loads(data)
    require(isinstance(selection, dict) and set(selection) == {
        "schema", "tools", "project", "interpreter", "bootstrap_sha256", "exchange_policy", "exchange_policy_sha256",
        "receiver_database", "workbook_id_sha256", "pilot",
    } and selection["schema"] in (SCHEMA, ROLLBACK_SELECTION_SCHEMA) and data == canonical(selection),
            "Selection fields or encoding differ from the approved contract")
    pilot = selection["pilot"]
    require(isinstance(selection["tools"], dict) and set(selection["tools"]) == TOOLS,
            "Selection does not bind all maintenance tools")
    digests = [selection[key] for key in ("bootstrap_sha256", "exchange_policy_sha256", "workbook_id_sha256")]
    digests.extend(selection["tools"].values())
    if selection["schema"] == SCHEMA:
        require(isinstance(pilot, dict) and set(pilot) == PILOT_FIELDS, "Selection does not bind the pilot scope")
        digests.extend(pilot[key] for key in ("request_sha256", "reservation_digest", "source_revision"))
    else:
        require(pilot is None, "Pre-pilot rollback selection cannot name an admitted pilot")
    require(all(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) for value in digests),
            "Selection contains an invalid digest")
    return selection


def load_source(name, path, source):
    """Execute already verified source bytes without consulting Python bytecode."""
    module = ModuleType(name)
    module.__file__ = str(path)
    module.__package__ = name.rpartition(".")[0]
    sys.modules[name] = module
    try:
        exec(compile(source, str(path), "exec"), module.__dict__)
    except BaseException:
        del sys.modules[name]
        raise
    return module


def read_protected_rollback(controller, checker_path, checker_source, selection, selection_sha256):
    """Verify the same pre-install protected-state pin used by the controller."""
    require(checker_path == controller.checker
            and sha256(checker_source).hexdigest() == controller.binding["files"][str(controller.checker)][-1],
            "Rollback checker differs from the original controller binding")
    with ZipFile(io.BytesIO(checker_source)) as archive:
        policy = json.loads(archive.read("approved_site_policy.json"))
        protected_source = archive.read("protected_state.py")
    site = policy["site"]
    fence = site["exchange_fence"]
    require(policy["schema"] == "sprint-4-site-policy-v1"
            and site["project"] == str(controller.project) and site["maintenance_id"] == controller.hold_id
            and fence["policy_file"] == selection["exchange_policy"]
            and fence["policy_sha256"] == selection["exchange_policy_sha256"],
            "Rollback does not match the release's approved site and exchange")
    protected = load_source("protected_state", checker_path / "protected_state.py", protected_source)
    require(getattr(protected, "RETAINED_FIRST_PASS", None) == "retained-first-pass",
            "Original protected baseline has no retained FIRST PASS coverage")
    require(controller.marker.parent == controller.project / ".state"
            and selection["receiver_database"] == str(controller.project / protected.DATABASES["coordinator"]),
            "Rollback cannot verify protection for these storage paths")
    pin_digest = policy["protected_pin_sha256"]
    require(protected.verify_protected_state(
        controller.project, policy["protected_pin_file"], pin_digest,
        verify_release_hold=lambda: protected.verify_release_lease(controller.project, os.getpid()),
    ) is True, "Original protected state could not be confirmed after rollback")
    return {"selection_sha256": selection_sha256, "protected_pin_sha256": pin_digest}


def approved_command(selection, bundle, approval=None, approved_sha256=None):
    require((approval is None and approved_sha256 is None)
            or (type(approval) is bytes and sha256(approval).hexdigest() == approved_sha256),
            "Restoration evidence differs from its approved digest")
    require(stat.S_IMODE(bundle.stat().st_mode) == 0o700 and bundle.stat().st_uid == os.geteuid(),
            "The approved maintenance bundle must be private")
    paths = {name: bundle / name for name in TOOLS}
    sources = {}
    for name, path in paths.items():
        source = read_file(path)
        require(sha256(source).hexdigest() == selection["tools"][name], "Approved maintenance tool changed")
        sources[name] = source
    project = Path(selection["project"])
    venv = project / ".venv"
    require(project.is_absolute() and project.resolve(strict=True) == project
            and Path(sys.executable) == Path(selection["interpreter"]) == venv / "bin/python"
            and Path(sys.prefix) == venv, "Wrong release project or interpreter")
    bootstrap_path = project / "release_admission_bootstrap.py"
    bootstrap_source = read_file(bootstrap_path)
    require(sha256(bootstrap_source).hexdigest() == selection["bootstrap_sha256"],
            "Approved runtime measurement tool changed")
    bootstrap = load_source("_pilot_runtime_measurement", bootstrap_path, bootstrap_source)
    bootstrap._load_environment(project / ".env")

    for name in ("gate", "installer", "host_exchange", "pilot_restoration", "controller"):
        load_source(name, paths[name + ".py"], sources[name + ".py"])
    sys.path[:0] = [str(project / "src"), str(project / "dev/wrapper-coder/tools")]
    restore = sys.modules["pilot_restoration"]
    controller = sys.modules["controller"].Controller(bundle)
    require(controller.project == project and controller.backend == "sqlite",
            "Selected release scope does not match installed controller")
    exchange = sys.modules["host_exchange"].HostExchange(
        selection["exchange_policy"], selection["exchange_policy_sha256"], enable_host_writes=approval is not None,
    )
    state_root = controller.marker.parent
    selection_sha256 = sha256(canonical(selection)).hexdigest()
    workbook = os.environ.get("SPREADSHEET_ID", "").strip()
    require(bool(workbook) and sha256(workbook.encode()).hexdigest() == selection["workbook_id_sha256"],
            "The observed workbook differs from the selected destination")
    effective_state = bootstrap._project_path(project, os.environ.get("STATE_DB_FILE", ".state/state.db"))
    require(effective_state.parent == state_root, "The runtime state root differs from the release")

    def read_settled_pilot():
        runtime = bootstrap._validate_runtime(project, state_root)
        layout = bootstrap._retained_operator_sqlite_layout(project, effective_state, controller.backend)
        observed_path = Path(layout["jobs"]["path"])
        from job_search_helper.sqlite_repository import SQLiteRepository

        verifier_name = "retained_pilot_terminal.py"
        verifier = load_source("job_search_helper.retained_pilot_terminal", paths[verifier_name],
                               sources[verifier_name])
        receiver_name = "retained_pilot_receiver.py"
        receiver = load_source("retained_pilot_receiver", paths[receiver_name], sources[receiver_name])
        with closing(SQLiteRepository(observed_path, workbook, readonly=True)) as local:
            application = verifier.verify_retained_pilot_terminal(local, runtime_binding=runtime, **selection["pilot"])
        require(layout == bootstrap._retained_operator_sqlite_layout(project, effective_state, controller.backend),
                "Pilot database identities changed during verification")
        return {"selection_sha256": selection_sha256,
                **receiver.verify_pilot_delivery(application, selection["receiver_database"])}

    def observe(source, schema, proof_key, read_proof):
        with controller.restoration_terminal() as release:
            require(release["source"] == source, "The approved release has a different terminal state")
            closed = exchange.witness("closed")
            return {"schema": schema, "release": release, "exchange": restore.exchange_identity(closed),
                    proof_key: read_proof()}

    if selection["schema"] == ROLLBACK_SELECTION_SCHEMA:
        def read_rollback():
            layout = bootstrap._retained_operator_sqlite_layout(project, effective_state, controller.backend)
            proof = read_protected_rollback(controller, paths["host-check"], sources["host-check"],
                                            selection, selection_sha256)
            require(layout == bootstrap._retained_operator_sqlite_layout(project, effective_state, controller.backend),
                    "Rollback database identities changed during verification")
            return proof

        if approval is None:
            return observe("ROLLED_BACK", restore.ROLLBACK_SCHEMA, "rollback", read_rollback)
        restored = restore.restore_after_rollback(
            controller, exchange, approval, approved_sha256=approved_sha256, read_protected_rollback=read_rollback,
        )
    else:
        if approval is None:
            return observe("INSTALLED", restore.SCHEMA, "pilot", read_settled_pilot)
        restored = restore.restore_after_pilot(
            controller, exchange, approval, approved_sha256=approved_sha256, read_settled_pilot=read_settled_pilot,
        )
    return {"phase": restored.phase, "generation": restored.generation,
            "terminal_proof_sha256": restored.terminal_proof_sha256}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("observe", "restore"))
    parser.add_argument("--selection", required=True, type=Path)
    parser.add_argument("--selection-sha256", required=True)
    parser.add_argument("--approval", type=Path)
    parser.add_argument("--approval-sha256")
    args = parser.parse_args()
    if (args.mode == "restore" and not (args.approval and args.approval_sha256)
            or args.mode == "observe" and (args.approval or args.approval_sha256)):
        parser.error("Restore requires independently approved evidence. Observe accepts only the selection.")
    if not (sys.flags.isolated and sys.dont_write_bytecode and sys.pycache_prefix == "/dev/null"):
        parser.error("Use the approved launcher with -I -B -X pycache_prefix=/dev/null")
    try:
        bundle = Path(__file__).absolute().parent
        selection = read_selection(args.selection, args.selection_sha256)
        approval = None if args.approval is None else read_file(args.approval, private=True, limit=256 * 1024)
        result = approved_command(selection, bundle, approval, args.approval_sha256)
        sys.stdout.buffer.write(canonical(result))
    except Exception as error:
        parser.exit(1, f"Pilot restoration is held ({type(error).__name__}). Preserve the bundle and evidence.\n")


if __name__ == "__main__":
    main()
