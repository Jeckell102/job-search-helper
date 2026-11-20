"""Read-only maintenance probes for pinned launcher routing and Python imports."""
from dataclasses import dataclass
from hashlib import sha256
import os
from pathlib import Path
import subprocess

from host_checkpoint import read_regular, require


PROBE_STAGES = {"preflight", "pre-publish", "published", "admitted", "before-host-reopen", "restored"}
LAUNCH_FILES = {"job-search-helper", "job-search-scraper", "release_admission_bootstrap.py"}

# The reviewed shell wrapper computes its interpreter and bootstrap route.
# The replacement shell function prints exec arguments without starting the
# application or touching the admission lock.
SHELL_PROBE = r"""
exec() { printf '%s\0' "$@"; exit; }
source "$1" "$2"
"""

IMPORT_PROBE = r"""
import importlib.util, os, pathlib, sys
def no_effect(event, args):
    if event == "open":
        flags = args[2]
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            raise RuntimeError("Import tried to write.")
    elif (event.startswith(("socket.", "sqlite3.", "subprocess.", "ctypes."))
          or event in {"os.exec", "os.system", "os.fork", "os.posix_spawn", "os.remove", "os.rename",
                       "os.mkdir", "os.rmdir", "os.link", "os.symlink", "os.chmod", "os.chown"}):
        raise RuntimeError("Import tried an external operation.")
sys.addaudithook(no_effect)
source, mode = pathlib.Path(sys.argv[1]), sys.argv[2]
sys.path.insert(0, str(source))
package = source / "job_search_helper"
spec = importlib.util.find_spec("job_search_helper")
expected = package / ("__init__.so" if mode == "extension" else "__init__.py")
if spec is None or pathlib.Path(spec.origin) != expected:
    raise RuntimeError("Python selected a different package route.")
try:
    import job_search_helper
except ImportError as error:
    if (mode == "parked" and str(error) == "Job Search Helper is held for source maintenance"
            or mode == "extension" and getattr(error, "path", None) == str(expected)):
        print("guarded")
        raise SystemExit(0)
    raise
if mode != "open":
    raise RuntimeError("Expected canonical import refusal.")
from job_search_helper import runner
if pathlib.Path(runner.__file__).parent != package:
    raise RuntimeError("Unexpected normal runner.")
if runner.scrape_main(["--help"]) != 0:
    raise RuntimeError("Normal runner help refused.")
print("admitted-help")
"""


@dataclass(frozen=True)
class LauncherPolicy:
    interpreter: Path
    interpreter_target: Path
    shell: Path
    before: dict[str, str]
    after: dict[str, str]


def verify_pinned_launch_files(project, endpoints):
    require(set(endpoints) == LAUNCH_FILES, "Incomplete approved launcher file inventory")
    for relative, expected in endpoints.items():
        data, _ = read_regular(project / relative)
        require(sha256(data).hexdigest() == expected, "Launcher source differs from its approved hash")


def probe_launchers(project, launches, stage, target):
    if stage not in PROBE_STAGES:
        return
    expect_after = (target == "INSTALLED") != (stage == "preflight")
    endpoints = launches.after if expect_after else launches.before
    verify_pinned_launch_files(project, endpoints)
    require(launches.interpreter == project / ".venv/bin/python"
            and launches.interpreter.resolve(strict=True) == launches.interpreter_target
            and launches.shell.resolve(strict=True) == launches.shell,
            "Launcher interpreter or shell differs from the approved route")
    env = {"PATH": "/usr/bin:/bin", "HOME": str(project.parent), "LANG": "C", "PYTHONDONTWRITEBYTECODE": "1"}
    bootstrap = project / "release_admission_bootstrap.py"
    routes = [("job-search-helper", "start"), ("job-search-scraper", "start")]
    if expect_after:
        routes.append(("job-search-scraper", "ordinary-company-event"))
    for name, argument in routes:
        route = subprocess.run([str(launches.shell), "-c", SHELL_PROBE, "probe", str(project / name), argument],
                               cwd="/", env=env, capture_output=True, timeout=1, check=True)
        expected = (str(launches.interpreter), "-I", "-S", str(bootstrap), argument)
        require(route.stdout == b"\0".join(map(os.fsencode, expected)) + b"\0" and not route.stderr,
                "Public launcher did not select its approved admission path")
    mode = "parked" if stage == "pre-publish" else "extension" if stage == "published" else "open"
    result = subprocess.run([str(launches.interpreter), "-I", "-B", "-X", "pycache_prefix=/dev/null",
                             "-c", IMPORT_PROBE, str(project / "src"), mode],
                            cwd="/", env=env, capture_output=True, timeout=3, check=True)
    marker = b"admitted-help" if mode == "open" else b"guarded"
    require(result.stdout.splitlines()[-1:] == [marker] and not result.stderr,
            "Python launcher boundary did not match its release phase")
    verify_pinned_launch_files(project, endpoints)
