"""Prepare or dispatch the authorized Samtec pilot in its private evidence folder."""
import base64
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from job_search_helper.retained_company_event import _verifier
from job_search_helper.retained_operator_authorization import ACTION, verify_operator_membership_authorization
from job_search_helper.selected_recovery_authorization import canonical


PROJECT = Path("/home/chris/job-search-helper_old")
SIGNER = PROJECT.parent / ".config/job-search-helper/retained-operator-signing"
CYCLE = "CYC-B639C6D864EC"
COMPANY = "COMP-0739"
REQUEST = "operator-samtec-m1-20261119"
KEY_FIELDS = {"COMPANY_RETAINED_KEY_ID", "COMPANY_RETAINED_ED25519_PUBLIC_KEY_BASE64"}


def private_bytes(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600):
            raise ValueError(f"Unsafe private file: {path.name}")
        return stream.read()


def local_trust():
    values = dict(line.split("=", 1) for line in private_bytes(SIGNER / "public-trust.env").decode().splitlines() if line)
    if set(values) != KEY_FIELDS or not all(values.values()):
        raise ValueError("Unexpected retained signer configuration")
    return values


def require_claims(value):
    if (value.get("action"), value.get("version"), value.get("cycle_id"),
        value.get("company_id"), value.get("request_id")) != (ACTION, 2, CYCLE, COMPANY, REQUEST):
        raise ValueError("Measured claims are outside the authorized pilot")
    return value


def write_new(path, data):
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def preview(root, environment):
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
    legacy = subprocess.check_output(
        ["./job-search-scraper", "retained-exception-preview", "--cycle-id", CYCLE,
         "--expires-at", expires_at, "--output", str(root / "historical")],
        cwd=PROJECT, env=environment,
    )
    manifest = Path(json.loads(legacy)["signer_input"])
    if manifest.parent != root / "historical":
        raise ValueError("Unexpected historical preview location")
    output = subprocess.check_output(
        command("preview", manifest) + ["--expires-at", expires_at], cwd=PROJECT, env=environment,
    )
    payload = require_claims(json.loads(output)["required_claims"])
    write_new(root / "historical-path", str(manifest).encode())
    write_new(root / "claims.json", canonical(payload))
    print(json.dumps({"company_id": COMPANY, "request_id": REQUEST, "action": ACTION,
                      "expires_at": payload["expires_at"], "runtime_sha256": payload["runtime_sha256"]}))


def command(operation, manifest):
    return ["./job-search-scraper", "run-retained-operator-company", operation,
            "--cycle-id", CYCLE, "--company-id", COMPANY, "--request-id", REQUEST,
            "--manifest-file", str(manifest)]


def sign(root, trust):
    payload = require_claims(json.loads(private_bytes(root / "claims.json")))
    private_key = serialization.load_pem_private_key(private_bytes(SIGNER / "operator-signing.pem"), password=None)
    if not isinstance(private_key, Ed25519PrivateKey):
        raise ValueError("Expected the dedicated Ed25519 signer")
    key_id = trust["COMPANY_RETAINED_KEY_ID"]
    signature = base64.b64encode(private_key.sign(canonical(payload))).decode("ascii")
    envelope = {"payload": payload, "key_id": key_id, "signature": signature}
    verify_operator_membership_authorization(
        envelope, payload, _verifier(key_id, trust["COMPANY_RETAINED_ED25519_PUBLIC_KEY_BASE64"]),
    )
    write_new(root / "approval.json", canonical(envelope))
    print("Exact Samtec authorization was sealed and verified.")


def execute(root, environment):
    manifest = Path(private_bytes(root / "historical-path").decode())
    if manifest.parent != root / "historical":
        raise ValueError("Unexpected historical manifest location")
    os.chdir(PROJECT)
    argv = command("execute", manifest) + ["--approval-file", str(root / "approval.json"),
                                            "--max-operations", "25"]
    os.execve(argv[0], argv, environment)


if __name__ == "__main__":
    os.umask(0o077)
    mode, directory = sys.argv[1:]
    root = Path(directory).resolve()
    if stat.S_IMODE(root.stat().st_mode) != 0o700 or root.stat().st_uid != os.geteuid():
        raise ValueError("Pilot evidence directory must be private and owned by the operator")
    trust = local_trust()
    if mode == "sign":
        sign(root, trust)
    else:
        modes = {"preview": preview, "execute": execute}
        modes[mode](root, {**os.environ, **trust})
