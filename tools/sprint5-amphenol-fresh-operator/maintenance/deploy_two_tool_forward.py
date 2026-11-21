"""Two-tool, predecessor-preserving host-forward maintenance transaction.

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
STORE_RELATIVE = "dev/wrapper-coder/tools/coordinator_store.py"
FORWARD_PATHS = (STORE_RELATIVE, HOST_RELATIVE)
SERVICE_NAME = "wrapper-development-host.service"
BEFORE_SHA256 = "137563add244929e36f53dc0e4b87f2f9a9faaeb22a799102c89e9b939b79eae"
AFTER_SHA256 = "5abe835b6b550f3bb81a7c787e97382910ce1d882687521c60e3e8ec630a37ad"
PREDECESSOR_RECEIPT_SHA256 = "e07eab1cf86378f6b6fe0055763a83bb212b52626774fb6d0fe0366f311b7dc3"
HISTORICAL_PREDECESSOR_RECEIPT_SHA256 = "eecbb742a212acdfb30a7be7687daf90dd8cb348a4076b7041680ad2d1243058"
TWO_TOOL_BEFORE = {
    STORE_RELATIVE: "9f0a84a626fcf910f24233759ff940ff68db81c97b9b0e7096a3d4b0580ea835",
    HOST_RELATIVE: "5abe835b6b550f3bb81a7c787e97382910ce1d882687521c60e3e8ec630a37ad",
}
TWO_TOOL_AFTER = {
    STORE_RELATIVE: "16c442d8019d5173f188348890fd89fe224d2c4315fde67528ed26e25478134d",
    HOST_RELATIVE: "a1cafe60d2025116bcaa43dd8dd1b4099a9c2845c35353f3f25dec98a8df5567",
}
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


def _verify_idle(idle: Mapping[str, object], expected_loaded: Mapping[str, str]) -> None:
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
    if idle.get('loaded_hashes') != dict(expected_loaded):
        raise HostForwardError('Restart readback did not attest the exact loaded two-tool hashes')


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


def _exact_pins(value: Mapping[str, str], *, name: str) -> dict[str, str]:
    if (not isinstance(value, Mapping) or set(value) != set(FORWARD_PATHS)
            or any(not isinstance(pin, str) or not __import__('re').fullmatch(r'[0-9a-f]{64}', pin)
                   for pin in value.values())):
        raise HostForwardError(f'{name} must pin exactly the Store and host paths')
    return dict(value)


def apply_two_tool_forward(*, project: Path, successor_guard, candidates: Mapping[str, bytes],
                           before_sha256: Mapping[str, str], after_sha256: Mapping[str, str],
                       predecessor_receipt_sha256: str, remaining_scope: Mapping[str, str],
                       idle_probe: Callable[[], Mapping[str, object]],
                       exchange_probe: Callable[[Mapping[str, object]], Mapping[str, object]],
                       stop_service: Callable[[str], None], start_service: Callable[[str], None],
                       stopped_probe: Callable[[], bool],
                       restart_probe: Callable[[], Mapping[str, object]], receipt_directory: Path) -> dict:
    """Install the accepted two tool bytes or restore both exact prior bytes.

    ``successor_guard.terminal()`` is deliberately held across the transition.
    It is a fresh -04 successor guard supplied by native wiring; this updater
    does not reuse the historical -03 controller, whose terminal predicate
    still pins the pre--04 host image.
    """
    project = _physical(project)
    receipt_directory = _physical(receipt_directory)
    directory_status = receipt_directory.stat()
    if not stat.S_ISDIR(directory_status.st_mode) or stat.S_IMODE(directory_status.st_mode) != 0o700:
        raise HostForwardError("Receipt directory must be private mode 0700")
    before_sha256 = _exact_pins(before_sha256, name='Before pins')
    after_sha256 = _exact_pins(after_sha256, name='After pins')
    if before_sha256 != TWO_TOOL_BEFORE or after_sha256 != TWO_TOOL_AFTER:
        raise HostForwardError('Two-tool pins do not match the accepted -04 successor images')
    if not isinstance(candidates, Mapping) or set(candidates) != set(FORWARD_PATHS):
        raise HostForwardError('Candidates must contain exactly the Store and host paths')
    if any(not isinstance(candidates[path], bytes) or _digest(candidates[path]) != after_sha256[path]
           for path in FORWARD_PATHS):
        raise HostForwardError('Candidate does not match its independently accepted after-image')
    if predecessor_receipt_sha256 != PREDECESSOR_RECEIPT_SHA256:
        raise HostForwardError("Missing exact -04 predecessor receipt pin")
    paths = {relative: _physical(project / relative) for relative in FORWARD_PATHS}
    receipt_path = receipt_directory / "two-tool-forward-receipt.json"
    backup_paths = {relative: receipt_directory / (Path(relative).name + ".before") for relative in FORWARD_PATHS}
    with _deployment_lock(project), successor_guard.terminal() as terminal:
        if (not isinstance(terminal, Mapping) or terminal.get("source") != "INSTALLED"
                or terminal.get("predecessor_receipt_sha256") != predecessor_receipt_sha256
                or terminal.get("historical_predecessor_receipt_sha256") != HISTORICAL_PREDECESSOR_RECEIPT_SHA256
                or not isinstance(terminal.get("source_manifest_sha256"), str)
                or not isinstance(terminal.get("controller_journal_sha256"), str)):
                raise HostForwardError("Successor guard did not prove the installed -04 terminal")
        exchange = exchange_probe(terminal)
        if (not isinstance(exchange, Mapping) or exchange.get("restored_exchange") is not True
                or exchange.get("predecessor_receipt_sha256") != predecessor_receipt_sha256
                or exchange.get("historical_predecessor_receipt_sha256") != HISTORICAL_PREDECESSOR_RECEIPT_SHA256):
            raise HostForwardError("Exact restored exchange was not proven for the -03 predecessor")
        _verify_idle(idle_probe(), before_sha256)
        other_before = _verify_scope(project, remaining_scope)
        before = {}
        modes = {}
        for relative, path in paths.items():
            data, status = _read(path)
            if _digest(data) != before_sha256[relative]:
                raise HostForwardError(f'Installed {relative} does not match its before-image')
            if backup_paths[relative].exists():
                raise HostForwardError('Private before-image already exists')
            before[relative], modes[relative] = data, stat.S_IMODE(status.st_mode)
            _write_new_private(backup_paths[relative], data)
        installed = False
        initial_stop_attempted = False
        forward_start_attempted = False
        try:
            initial_stop_attempted = True
            stop_service(SERVICE_NAME)
            if stopped_probe() is not True:
                raise HostForwardError("Host service did not stop before replacement")
            for relative in FORWARD_PATHS:  # Store is committed before host, before restart.
                _write_atomic(paths[relative], candidates[relative], modes[relative])
                installed_data, installed_status = _read(paths[relative])
                if (_digest(installed_data) != after_sha256[relative]
                        or stat.S_IMODE(installed_status.st_mode) != modes[relative]):
                    raise HostForwardError(f'Atomic {relative} replacement readback differs')
            if _verify_scope(project, remaining_scope) != other_before:
                raise HostForwardError("Unrelated -03 scope changed during host forward")
            # The service callback may start the unit and then fail while
            # reporting status, so this is intentionally before the callback.
            forward_start_attempted = True
            start_service(SERVICE_NAME)
            _verify_idle(restart_probe(), after_sha256)
            receipt = {
                "schema": "amphenol-two-tool-forward-receipt-v1",
                "status": "TWO_TOOL_FORWARD_INSTALLED",
                "predecessor": {"receipt_sha256": predecessor_receipt_sha256, "terminal_source": "INSTALLED"},
                "historical_predecessor_receipt_sha256": HISTORICAL_PREDECESSOR_RECEIPT_SHA256,
                "paths": {path: {"before_sha256": before_sha256[path], "after_sha256": after_sha256[path],
                                  "mode": f"{modes[path]:04o}"} for path in FORWARD_PATHS},
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
            if not installed and initial_stop_attempted:
                rollback_stop_error = None
                if forward_start_attempted:
                    try:
                        stop_service(SERVICE_NAME)
                    except Exception as error:
                        # A callback failure may follow a real stop.  The
                        # measured probe below, not its transport result,
                        # decides whether reverse replacement is safe.
                        rollback_stop_error = error
                if stopped_probe() is not True:
                    raise HostForwardError("Host service state is uncertain after stop attempt; refusing source replacement") from rollback_stop_error
                for relative in reversed(FORWARD_PATHS):
                    current, current_status = _read(paths[relative])
                    candidate_present = (current == candidates[relative]
                                         and stat.S_IMODE(current_status.st_mode) == modes[relative])
                    original_present = (current == before[relative]
                                        and stat.S_IMODE(current_status.st_mode) == modes[relative])
                    if candidate_present:
                        _write_atomic(paths[relative], before[relative], modes[relative])
                    elif not original_present:
                        raise HostForwardError(f'{relative} drifted after forward replacement; refusing overwrite')
                    restored, restored_status = _read(paths[relative])
                    if restored != before[relative] or stat.S_IMODE(restored_status.st_mode) != modes[relative]:
                        raise HostForwardError(f'Rollback did not restore exact {relative} contents')
                start_service(SERVICE_NAME)
                _verify_idle(restart_probe(), before_sha256)
                rollback = {
                    "schema": "amphenol-two-tool-forward-receipt-v1",
                    "status": "TWO_TOOL_FORWARD_ROLLED_BACK",
                    "predecessor": {"receipt_sha256": predecessor_receipt_sha256, "terminal_source": "INSTALLED"},
                    "historical_predecessor_receipt_sha256": HISTORICAL_PREDECESSOR_RECEIPT_SHA256,
                    "paths": {path: {"before_sha256": before_sha256[path], "attempted_after_sha256": after_sha256[path]}
                              for path in FORWARD_PATHS},
                }
                if not receipt_path.exists():
                    _write_new_private(receipt_path, _canonical_json(rollback))

