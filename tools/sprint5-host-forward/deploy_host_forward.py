"""One-file, predecessor-preserving host-forward maintenance transaction.

This is deliberately a library-first tool.  The release owner supplies the
already-admitted Controller, exact idle/readback probes and only the existing
``wrapper-development-host.service`` command callbacks.  It never creates a
checkout exchange, touches application data, or opens an inference channel.
"""

from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
from typing import Callable, Mapping


HOST_RELATIVE = "dev/wrapper-coder/tools/host_server.py"
SERVICE_NAME = "wrapper-development-host.service"
BEFORE_SHA256 = "137563add244929e36f53dc0e4b87f2f9a9faaeb22a799102c89e9b939b79eae"
AFTER_SHA256 = "5abe835b6b550f3bb81a7c787e97382910ce1d882687521c60e3e8ec630a37ad"
TERMINAL_TASK_SHA256 = "95309e140a381be0b365a800fc76e2d4416705f8802691037ebf80f39c445db6"
TERMINAL_RECEIPT_SHA256 = "aeea900dc8bdcc5be0cd5e4e3781eca0706f8b2034ef98997d0028f439dcba7e"
REMAINING_SCOPE = frozenset({
    "job-search-scraper",
    "release_admission_bootstrap.py",
    "dev/wrapper-coder/tools/amphenol_recipe_choice_input.py",
    "src/job_search_helper/operator_selected_observation.py",
    "src/job_search_helper/operator_amphenol_fetch.py",
    "src/job_search_helper/operator_amphenol_settlement.py",
    "src/job_search_helper/ordinary_company_event_fetch.py",
    "src/job_search_helper/runner.py",
})


class HostForwardError(ValueError):
    pass


class HostForwardDurabilityUncertain(OSError):
    """The exact success receipt is visible, but its directory flush failed.

    Compensation here would leave an installed receipt describing an already
    restored runtime.  Preserve the verified candidate and require a later
    durable custody reconciliation instead.
    """


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _physical(path: Path) -> Path:
    if not path.is_absolute() or path.resolve(strict=True) != path:
        raise HostForwardError(f"Expected physical absolute path: {path}")
    return path


def _read(path: Path) -> tuple[bytes, os.stat_result]:
    _physical(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        status = os.fstat(fd)
        if not stat.S_ISREG(status.st_mode) or status.st_nlink != 1:
            raise HostForwardError(f"Unsafe file: {path}")
        chunks = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks), status
    finally:
        os.close(fd)


def _write_atomic(path: Path, data: bytes, mode: int) -> None:
    """Replace only one regular file from a same-directory private temp file."""
    parent = _physical(path.parent)
    fd, temporary_name = tempfile.mkstemp(prefix=".host-forward-", dir=parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fchmod(handle.fileno(), mode)
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary.exists():
            temporary.unlink()


def _canonical_json(value: dict) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _write_new_private(path: Path, data: bytes) -> None:
    """Publish a new receipt/backup atomically without replacing prior custody."""
    parent = _physical(path.parent)
    fd, temporary_name = tempfile.mkstemp(prefix=".host-forward-publish-", dir=parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fchmod(handle.fileno(), 0o600)
            os.fsync(handle.fileno())
        os.link(temporary, path, follow_symlinks=False)
        directory = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary.exists():
            temporary.unlink()


def _visible_exact(path: Path, expected: bytes) -> bool:
    try:
        observed, _ = _read(path)
    except FileNotFoundError:
        return False
    return observed == expected


@contextmanager
def _deployment_lock(project: Path):
    lock = _physical(project / "dev/wrapper-coder/repairs/deployment.lock")
    fd = os.open(lock, os.O_RDWR | os.O_NOFOLLOW)
    try:
        status = os.fstat(fd)
        if not stat.S_ISREG(status.st_mode) or status.st_nlink != 1:
            raise HostForwardError("Unsafe retained deployment lock")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def _verify_idle(idle: Mapping[str, object]) -> None:
    if idle.get("task_sha256") != TERMINAL_TASK_SHA256 or idle.get("receipt_sha256") != TERMINAL_RECEIPT_SHA256:
        raise HostForwardError("Closed pilot does not match retained terminal evidence")
    if idle.get("open_inference") != 0:
        raise HostForwardError("Inference is open")
    if idle.get("service") != SERVICE_NAME:
        raise HostForwardError("Only the existing wrapper host service may be maintained")
    controls = idle.get("controls")
    if not isinstance(controls, Mapping) or any(controls.get(name) is not False for name in
                                                ("queue", "campaign", "autopilot", "unqualified_release")):
        raise HostForwardError("Default disabled controls were not proven")


def _verify_scope(project: Path, scope: Mapping[str, str]) -> dict[str, str]:
    if set(scope) != REMAINING_SCOPE or any(not isinstance(value, str) or len(value) != 64 for value in scope.values()):
        raise HostForwardError("Expected exact hashes for the eight remaining -03 scope files")
    observed = {}
    for relative, expected in sorted(scope.items()):
        data, _ = _read(project / relative)
        actual = _digest(data)
        if actual != expected:
            raise HostForwardError(f"-03 scope changed outside host_server.py: {relative}")
        observed[relative] = actual
    return observed


def apply_host_forward(*, project: Path, controller, candidate: bytes,
                       predecessor_receipt_sha256: str, remaining_scope: Mapping[str, str],
                       idle_probe: Callable[[], Mapping[str, object]],
                       exchange_probe: Callable[[Mapping[str, object]], Mapping[str, object]],
                       stop_service: Callable[[str], None], start_service: Callable[[str], None],
                       stopped_probe: Callable[[], bool],
                       restart_probe: Callable[[], Mapping[str, object]], receipt_directory: Path) -> dict:
    """Install the accepted host bytes or restore the exact prior bytes on failure.

    ``controller.restoration_terminal()`` is deliberately held across the host
    transition: it is the existing native admission/readback authority.  No
    caller-provided local state can substitute for it.
    """
    project = _physical(project)
    receipt_directory = _physical(receipt_directory)
    directory_status = receipt_directory.stat()
    if not stat.S_ISDIR(directory_status.st_mode) or stat.S_IMODE(directory_status.st_mode) != 0o700:
        raise HostForwardError("Receipt directory must be private mode 0700")
    if _digest(candidate) != AFTER_SHA256:
        raise HostForwardError("Candidate does not match independently accepted host after-image")
    if len(predecessor_receipt_sha256) != 64:
        raise HostForwardError("Missing -03 predecessor receipt pin")
    host = _physical(project / HOST_RELATIVE)
    receipt_path = receipt_directory / "host-forward-receipt.json"
    backup_path = receipt_directory / "host_server.py.before"
    with _deployment_lock(project), controller.restoration_terminal() as terminal:
        if (not isinstance(terminal, Mapping) or terminal.get("source") != "INSTALLED"
                or terminal.get("installer_receipt_sha256") != predecessor_receipt_sha256
                or not isinstance(terminal.get("source_manifest_sha256"), str)
                or not isinstance(terminal.get("controller_journal_sha256"), str)):
            raise HostForwardError("-03 Controller did not prove an installed restoration terminal")
        exchange = exchange_probe(terminal)
        if (not isinstance(exchange, Mapping) or exchange.get("restored_exchange") is not True
                or exchange.get("predecessor_receipt_sha256") != predecessor_receipt_sha256):
            raise HostForwardError("Exact restored exchange was not proven for the -03 predecessor")
        _verify_idle(idle_probe())
        other_before = _verify_scope(project, remaining_scope)
        before, status = _read(host)
        if _digest(before) != BEFORE_SHA256:
            raise HostForwardError("Installed host_server.py does not match -03 before-image")
        if backup_path.exists():
            raise HostForwardError("Private backup already exists")
        _write_new_private(backup_path, before)
        installed = False
        initial_stop_completed = False
        forward_start_attempted = False
        try:
            stop_service(SERVICE_NAME)
            initial_stop_completed = True
            if stopped_probe() is not True:
                raise HostForwardError("Host service did not stop before replacement")
            _write_atomic(host, candidate, stat.S_IMODE(status.st_mode))
            installed_data, installed_status = _read(host)
            if _digest(installed_data) != AFTER_SHA256 or stat.S_IMODE(installed_status.st_mode) != stat.S_IMODE(status.st_mode):
                raise HostForwardError("Atomic host replacement readback differs")
            if _verify_scope(project, remaining_scope) != other_before:
                raise HostForwardError("Unrelated -03 scope changed during host forward")
            # The service callback may start the unit and then fail while
            # reporting status, so this is intentionally before the callback.
            forward_start_attempted = True
            start_service(SERVICE_NAME)
            _verify_idle(restart_probe())
            receipt = {
                "schema": "amphenol-host-forward-receipt-v1",
                "status": "HOST_FORWARD_INSTALLED",
                "predecessor": {"receipt_sha256": predecessor_receipt_sha256, "terminal_source": "INSTALLED"},
                "path": HOST_RELATIVE,
                "before_sha256": BEFORE_SHA256,
                "after_sha256": AFTER_SHA256,
                "mode": f"{stat.S_IMODE(status.st_mode):04o}",
                "remaining_scope": other_before,
                "controller_terminal": dict(terminal),
                "restored_exchange": dict(exchange),
            }
            receipt_bytes = _canonical_json(receipt)
            try:
                _write_new_private(receipt_path, receipt_bytes)
            except OSError as error:
                if _visible_exact(receipt_path, receipt_bytes):
                    # The transaction is live and its exact receipt is named.
                    # Do not compensate a directory-sync uncertainty by
                    # restoring old source beneath that success evidence.
                    installed = True
                    raise HostForwardDurabilityUncertain(
                        "Host forward receipt is visible but directory durability is uncertain: "
                        f"{error}"
                    ) from error
                raise
            installed = True
            return receipt
        finally:
            if not installed and initial_stop_completed:
                current, current_status = _read(host)
                candidate_present = (current == candidate
                                     and stat.S_IMODE(current_status.st_mode) == stat.S_IMODE(status.st_mode))
                original_present = (current == before
                                    and stat.S_IMODE(current_status.st_mode) == stat.S_IMODE(status.st_mode))
                if forward_start_attempted:
                    stop_service(SERVICE_NAME)
                if stopped_probe() is not True:
                    raise HostForwardError("Host service could not be proven stopped before rollback")
                if candidate_present:
                    _write_atomic(host, before, stat.S_IMODE(status.st_mode))
                elif not original_present:
                    raise HostForwardError("Host source drifted after forward replacement; refusing overwrite")
                restored, restored_status = _read(host)
                if restored != before or stat.S_IMODE(restored_status.st_mode) != stat.S_IMODE(status.st_mode):
                    raise HostForwardError("Rollback did not restore exact host contents")
                start_service(SERVICE_NAME)
                _verify_idle(restart_probe())
                rollback = {
                    "schema": "amphenol-host-forward-receipt-v1",
                    "status": "HOST_FORWARD_ROLLED_BACK",
                    "predecessor": {"receipt_sha256": predecessor_receipt_sha256, "terminal_source": "INSTALLED"},
                    "path": HOST_RELATIVE,
                    "before_sha256": BEFORE_SHA256,
                    "attempted_after_sha256": AFTER_SHA256,
                }
                if not receipt_path.exists():
                    _write_new_private(receipt_path, _canonical_json(rollback))

