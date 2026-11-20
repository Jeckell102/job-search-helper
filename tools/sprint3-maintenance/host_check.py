#!/usr/bin/python3 -I
"""Read-only MuleLab attestation for Sprint 3's pre-pilot source transaction."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import subprocess
import sys


PROJECT = Path("/home/chris/job-search-helper_old")
WRAPPER = str(PROJECT / "dev/wrapper-coder/tools/host_server.py")
BRIDGE = "/home/chris/AI/assistant-tools-bridge/bridge.py"
LOCAL_WORKER = "/home/chris/AI/local-ai/worker.py"
HOLD_ID = "s3-samtec-operator-20261120"
MANIFEST_SHA256 = None
PACKAGE_SHA256 = {"INSTALLED": None, "ROLLED_BACK": None}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def service(name):
    response = subprocess.check_output(
        ["systemctl", "--user", "show", name, "-p", "ActiveState", "-p", "MainPID",
         "-p", "UnitFileState"], text=True, timeout=5)
    return dict(line.split("=", 1) for line in response.splitlines())


def request_digest(value):
    return hashlib.sha256(json.dumps(value, separators=(",", ":"), sort_keys=True).encode()).hexdigest()


def read_request_control(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                and info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o600,
                f"Unsafe operator control file: {path.name}")
        return json.load(stream)


def read_controls():
    state = PROJECT / ".state"
    request = read_request_control(state / "next-scan.json")
    request_identity = {
        "schema": "operator-company-scan-request-v1", "request_id": "operator-samtec-m1-20261119",
        "company_id": "COMP-0739", "source_revision": request["source_revision"],
    }
    require(request["company_ids"] == ["COMP-0739"]
            and request["request_id"] == request_identity["request_id"] and request["mode"] == "company-only"
            and request.get("operator_request") == request_identity,
            "Held Samtec control changed")
    receipt_path = state / "operator-company-requests/receipts" / (
        request_digest({"request_id": request_identity["request_id"]}) + ".json")
    receipt = read_request_control(receipt_path)
    require(all(receipt.get(key) == value for key, value in request_identity.items())
            and receipt.get("state") in {"REQUEST_WRITTEN", "REQUEST_ALREADY_DURABLE"}
            and receipt.get("request_sha256") == request_digest(request),
            "Held Samtec request receipt changed")
    for name in ("company-intake-dispatch.sqlite3", "retained-operator-admission.json",
                 "retained-work-starts.sqlite3", "retained-sessions.sqlite3"):
        require(not os.path.lexists(state / name), f"Unexpected pre-pilot lifecycle file: {name}")
    db = PROJECT / "dev/wrapper-coder/tasks/tasks.sqlite3"
    with closing(sqlite3.connect(db.as_uri() + "?mode=ro", uri=True, timeout=1)) as conn:
        conn.execute("PRAGMA query_only=ON")
        flags = dict(conn.execute("SELECT key,value FROM settings WHERE key IN "
                                  "('autopilot_enabled','queue_enabled','campaign_enabled')"))
        require(len(flags) == 3 and all(v == "false" for v in flags.values()),
                "Coordinator queue, campaign or autopilot changed")
        active, = conn.execute("SELECT count(*) FROM tasks WHERE json_extract(state,'$.status') "
                               "IN ('QUEUED','RUNNING','PAUSING')").fetchone()
        require(active == 0, "Coordinator owns active work")
        unsettled, = conn.execute("SELECT count(*) FROM inference_receipts WHERE status "
                                  "IN ('DISPATCHING','UNCERTAIN')").fetchone()
        require(unsettled == 0, "A service restart would reconcile outstanding inference")
    with closing(sqlite3.connect((state / "jobs.sqlite3").as_uri() + "?mode=ro", uri=True,
                                 timeout=1)) as conn:
        conn.execute("PRAGMA query_only=ON")
        pending = conn.execute("SELECT 1 FROM scrape_outcomes o LEFT JOIN scrape_outcome_deliveries d "
                               "ON d.outcome_id=o.outcome_id AND d.consumer='wrapper-coordinator' "
                               "WHERE d.outcome_id IS NULL LIMIT 1").fetchone()
        require(pending is None, "A service restart would deliver pending scraper outcomes")
        for table, terminal in (("retained_publications", "FIRST_PASS_RELEASED"), ("retained_intake_holds", None)):
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                pending = conn.execute(f"SELECT 1 FROM {table} WHERE state IS NOT ? LIMIT 1", (terminal,)).fetchone()
                require(pending is None, f"Unsettled retained work exists in {table}")


def census(allowed):
    require(Path("/proc/1/comm").read_text().strip() == "systemd",
            "The full host process table is required")
    ancestors = set()
    pid = os.getpid()
    while pid > 1:
        ancestors.add(pid)
        stat = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        pid = int(stat[1])
    for proc in Path("/proc").iterdir():
        if not proc.name.isdecimal() or int(proc.name) in ancestors:
            continue
        try:
            if proc.stat().st_uid != os.getuid():
                continue
            command = (proc / "comm").read_text().strip()
            args = (proc / "cmdline").read_bytes().decode(errors="replace").split("\0")
        except (FileNotFoundError, ProcessLookupError):
            continue
        if not args[0]:
            continue
        if (command.startswith(("python", "pypy", "pytest", "job-search"))
                or any(Path(s).name in {"job-search-helper", "job-search-scraper",
                                        "release_admission_bootstrap.py"} for s in args)):
            require(any(script in args and (pid is None or pid == int(proc.name))
                        for script, pid in allowed.items()),
                    f"Inspect active process {proc.name} ({command}) before continuing")


def check(phase):
    require(phase in ("preflight", "held", "pre-publish", "published", "admitted"),
            "Unknown host check phase")
    wrapper = service("wrapper-development-host.service")
    sync = service("job-search-sync.service")
    bridge = service("jetson-assistant-bridge.service")
    require(sync["ActiveState"] == "inactive" and sync["UnitFileState"] == "disabled"
            and sync["MainPID"] == "0", "Sync service state changed")
    require(wrapper["UnitFileState"] == "enabled", "Wrapper enablement changed")
    require(bridge["ActiveState"] == "active" and int(bridge["MainPID"]) > 0,
            "Read-only assistant bridge state changed")
    allowed = {BRIDGE: int(bridge["MainPID"]), LOCAL_WORKER: None}
    if phase != "preflight":
        require(wrapper["ActiveState"] == "inactive" and wrapper["MainPID"] == "0",
                "Wrapper host has not drained")
    else:
        require(wrapper["ActiveState"] == "active" and int(wrapper["MainPID"]) > 0,
                "Wrapper host changed before maintenance")
        allowed[WRAPPER] = int(wrapper["MainPID"])
    census(allowed)
    read_controls()


def launcher_probe(package):
    # Load exactly the parked or newly published package; help exits before
    # application state is opened. Deny SQLite and network access in the probe.
    probe = """
import importlib.util, pathlib, sys
def audit(event, args):
    if event in ('sqlite3.connect', 'socket.connect', 'subprocess.Popen'):
        raise RuntimeError('Unexpected external effect during help')
sys.addaudithook(audit)
package = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location('job_search_helper', package / '__init__.py',
                                             submodule_search_locations=[str(package)])
module = importlib.util.module_from_spec(spec)
sys.modules[module.__name__] = module
spec.loader.exec_module(module)
from job_search_helper import runner
assert pathlib.Path(runner.__file__).parent == package
raise SystemExit(runner.main(['--help']))
"""
    for launcher in ("job-search-helper", "job-search-scraper"):
        subprocess.run(["/bin/bash", "-n", str(PROJECT / launcher)], check=True, timeout=1)
    subprocess.run([str(PROJECT / ".venv/bin/python"), "-I", "-B", "-X",
                    "pycache_prefix=/dev/null", "-c", probe, str(package)],
                   cwd="/", check=True, stdout=subprocess.DEVNULL, timeout=4)


def public_help(parked, *, extension_held=False):
    environment = {"PATH": "/usr/bin:/bin", "HOME": os.environ["HOME"],
                   "LANG": "C", "PYTHONDONTWRITEBYTECODE": "1"}
    entries = [PROJECT / name for name in ("job-search-helper", "job-search-scraper",
                                            ".venv/bin/job-search-helper")]
    if PROJECT == Path("/home/chris/job-search-helper_old"):
        entries.append(PROJECT.parent / "job-search-helper_old_copy/.venv/bin/job-search-helper")
    for entry in entries:
        result = subprocess.run([str(entry), "--help"], cwd="/", env=environment,
                                capture_output=True, timeout=3)
        if parked:
            require(result.returncode != 0 and b"Job Search Helper is held for source maintenance" in result.stderr,
                    f"Expected maintenance refusal from {entry}")
        elif extension_held:
            require(result.returncode != 0 and b"file too short" in result.stderr
                    and os.fsencode(PROJECT / "src/job_search_helper/__init__.so") in result.stderr,
                    f"Expected held canonical package from {entry}")
        else:
            require(result.returncode == 0 and b"start" in result.stdout.lower(),
                    f"Unexpected help response from {entry}")


def verify_environment():
    raw = subprocess.check_output(["systemctl", "--user", "show-environment"], text=True, timeout=2)
    overrides = {"STATE_DB_FILE", "JOB_DB_FILE", "JOB_STORAGE_BACKEND", "PYTHONPYCACHEPREFIX",
                 "PYTHONPATH", "PYTHONOPTIMIZE"}
    require(not overrides.intersection(line.partition("=")[0] for line in raw.splitlines()),
            "Effective user service environment drifted")
    copy = PROJECT.parent / "job-search-helper_old_copy"
    code = ("import importlib.util; print(importlib.util.find_spec('job_search_helper').origin)")
    for checkout, explicit_src, expected in ((PROJECT, False, PROJECT),
                                             (copy, False, PROJECT), (copy, True, copy)):
        env = {"PATH": "/usr/bin:/bin", "HOME": os.environ["HOME"], "PYTHONDONTWRITEBYTECODE": "1"}
        if explicit_src:
            env["PYTHONPATH"] = str(checkout / "src")
        found = subprocess.check_output([str(checkout / ".venv/bin/python"), "-B", "-c", code],
                                        env=env, cwd="/", text=True, timeout=1)
        require(Path(found.strip()).parent == expected / "src/job_search_helper",
                f"Unexpected Python package resolution for {checkout.name}")


def verify_package(package, version):
    require(PACKAGE_SHA256[version] is not None, "The reviewed package pins have not been installed")
    entries = {}
    for file in package.rglob("*"):
        relative = file.relative_to(package)
        if "__pycache__" in relative.parts or file.suffix not in (".py", ".json"):
            continue
        info = file.lstat()
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "Unsafe package source")
        data = file.read_bytes()
        entries[relative.as_posix()] = {"sha256": hashlib.sha256(data).hexdigest(),
                                        "size": len(data), "mode": stat.S_IMODE(info.st_mode)}
    encoded = json.dumps(entries, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    require(hashlib.sha256(encoded).hexdigest() == PACKAGE_SHA256[version], "Full package pin changed")


def attest(request):
    phase = os.environ["JSH_F3_HOST_PHASE"]
    require(MANIFEST_SHA256 is not None and request["source_manifest_sha256"] == MANIFEST_SHA256
            and request["schema"] == "sprint-3-host-check-v1" and request["project"] == str(PROJECT)
            and request["maintenance_id"] == HOLD_ID
            and re.fullmatch(r"[0-9a-f]{32}", request["nonce"])
            and request["target"] in PACKAGE_SHA256
            and request["checkpoint"].split(":", 1)[0] == phase
            and request["backend"] == "sqlite" and request["pycache_prefixes"] == []
            and request["marker"] == str(PROJECT / ".state/integration-release-journal.json"),
            "Unexpected host check identity")
    expected_locks = [PROJECT / ".integration-install.lock",
                      *(PROJECT / ".state" / n for n in ("scraper.lock", "writer.lock", "review-writeback.lock"))]
    require(request["locks"] == list(map(str, expected_locks)), "Unexpected application lock paths")
    canonical = PROJECT / "src/job_search_helper"
    parked = PROJECT / "src/.s3-maintenance-package"
    package = Path(request["package"])
    require(package == (parked if phase in ("held", "pre-publish") else canonical),
            "Unexpected source location")
    check(phase)
    if phase == "preflight":
        verify_environment()
        verify_package(package, "ROLLED_BACK" if request["target"] == "INSTALLED" else "INSTALLED")
    if phase in ("pre-publish", "published", "admitted"):
        verify_package(package, request["target"])
        launcher_probe(package)
        public_help(phase == "pre-publish", extension_held=phase == "published")
    return {**request, "verified": True}


if __name__ == "__main__":
    try:
        if sys.argv[1:] == ["--preflight-only"]:
            check("preflight")
        else:
            print(json.dumps(attest(json.load(sys.stdin))))
    except (KeyError, OSError, RuntimeError, ValueError, sqlite3.Error,
            subprocess.SubprocessError) as error:
        sys.exit(str(error))
