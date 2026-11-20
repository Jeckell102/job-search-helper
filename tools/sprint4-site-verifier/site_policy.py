"""Load the exact approved policy embedded in one site checker archive."""
from dataclasses import fields
import json
from pathlib import Path
import re
from zipfile import ZipFile

from alternate_writer_witness import CoverPin
from host_checkpoint import SitePolicy, SourceFile


PATH_FIELDS = {"project", "marker", "systemctl", "maintenance_bundle", "maintenance_exe",
               "wrapper_unit_file", "sync_unit_file", "wrapper_cwd", "wrapper_exe", "wrapper_cgroup"}
PATH_LIST_FIELDS = {"lock_paths", "cache_prefixes", "alternate_roots"}


def absolute(value):
    path = Path(value)
    if not path.is_absolute() or str(path) != value or ".." in path.parts:
        raise ValueError("Approved site path is not an exact absolute spelling")
    return path


def identity_pair(value):
    if not isinstance(value, list) or len(value) != 2 or any(type(item) is not int or item < 0 for item in value):
        raise ValueError("Approved site identity is malformed")
    return tuple(value)


def digest_text(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("Approved policy digest is malformed")
    return value


def load_policy(archive_path):
    executable = absolute(str(archive_path))
    with ZipFile(executable, "r") as archive:
        raw = json.loads(archive.read("approved_site_policy.json"))
    if set(raw) != {"schema", "site", "protected_pin_file", "protected_pin_sha256"} or raw["schema"] != "sprint-4-site-policy-v1":
        raise ValueError("Unrecognized approved site policy")
    values = raw["site"]
    if set(values) != {item.name for item in fields(SitePolicy)}:
        raise ValueError("Approved site fields differ from verifier contract")
    for key in PATH_FIELDS:
        values[key] = absolute(values[key])
    for key in PATH_LIST_FIELDS:
        values[key] = tuple(absolute(path) for path in values[key])
    values["network_namespace"] = identity_pair(values["network_namespace"])
    values["wrapper_args"] = tuple(values["wrapper_args"])
    values["source_paths"] = frozenset(values["source_paths"])
    for key in ("before_host", "after_host"):
        endpoint = values[key]
        digest_text(endpoint["digest"])
        values[key] = SourceFile(**endpoint)
    values["manifest_sha256"] = digest_text(values["manifest_sha256"])
    values["covers"] = tuple(CoverPin(
        path=absolute(cover["path"]), covering_directory=identity_pair(cover["covering_directory"]),
        mount_id=cover["mount_id"], namespace=identity_pair(cover["namespace"]),
        launch_uid=cover["launch_uid"], probe_paths=tuple(cover["probe_paths"]),
    ) for cover in values["covers"])
    policy = SitePolicy(**values)
    if (policy.maintenance_bundle / "host-check" != executable
            or executable.resolve(strict=True) != executable
            or policy.marker != policy.project / ".state/integration-release-journal.json"
            or policy.project / ".state/scraper.lock" not in policy.lock_paths
            or type(policy.launch_uid) is not int or policy.launch_uid <= 0
            or type(policy.wrapper_active) is not bool
            or type(policy.wrapper_port) is not int or not 1 <= policy.wrapper_port <= 65535
            or not policy.source_paths):
        raise ValueError("Approved policy does not match the controller and release routes")
    protected_pin = absolute(raw["protected_pin_file"])
    return policy, protected_pin, digest_text(raw["protected_pin_sha256"])
