"""Operator-only signer preview and execution entry point."""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path

from . import cli
from .engine import State
from .retained_operator_preflight import measure_operator_membership
from .sheet_profile import profile_schemas


def _manifest(path, cycle_id):
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    manifest = value.get("manifest") if isinstance(value, dict) else None
    if not isinstance(manifest, dict) or manifest.get("cycle_id") != cycle_id:
        raise ValueError("retained_operator_manifest_scope_changed")
    return manifest


def operator_command(arguments, admission):
    """Run only the explicitly requested, admitted operator operation."""
    parser = argparse.ArgumentParser(prog="./job-search-scraper run-retained-operator-company")
    parser.add_argument("operation", choices=("preview", "execute"))
    parser.add_argument("--cycle-id", required=True)
    parser.add_argument("--company-id", required=True)
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--manifest-file", required=True)
    parser.add_argument("--expires-at")
    parser.add_argument("--approval-file")
    parser.add_argument("--max-operations", type=int, default=100)
    args = parser.parse_args(arguments)
    if args.operation == "preview" and (not args.expires_at or args.approval_file):
        parser.error("preview requires --expires-at")
    if args.operation == "execute" and (not args.approval_file or args.expires_at):
        parser.error("execute requires --approval-file")
    if not 1 <= args.max_operations <= 100:
        parser.error("--max-operations must be between 1 and 100")
    if args.operation == "execute":
        from .retained_company_event import _verifier
        approval = json.loads(Path(args.approval_file).read_text(encoding="utf-8"))
        verifier = _verifier(os.environ.get("COMPANY_RETAINED_KEY_ID"),
                             os.environ.get("COMPANY_RETAINED_ED25519_PUBLIC_KEY_BASE64"))
    database, jobs, runtime = admission
    root = database.parent
    manifest = _manifest(args.manifest_file, args.cycle_id)
    with closing(State(str(database), readonly=True)) as state:
        with closing(cli.get_repository(write=False, interactive=False)) as local:
            if Path(local.path).resolve() != jobs:
                raise ValueError("retained_operator_repository_identity_changed")
            schemas = profile_schemas(local.get_meta("sheets_profile"))
            if schemas is None:
                raise ValueError("retained_operator_projected_workbook_required")

            def remote(*, write=False):
                return cli.get_remote_repository(write=write, interactive=False, schemas=schemas)

            if args.operation == "preview":
                claims = measure_operator_membership(
                    local, remote(), state, root, manifest, runtime, expires_at=args.expires_at,
                    request_id=args.request_id, company_id=args.company_id,
                )
                result = {"required_claims": claims}
            else:
                from .ats import fetch_inventory
                from .browser_scraper import with_browser_fallback
                from .retained_operator_run import run_operator_membership
                result = run_operator_membership(
                    local, remote, state, root, manifest, runtime, approval=approval, verifier=verifier,
                    fetcher=with_browser_fallback(fetch_inventory),
                    local_writer=lambda: cli.get_repository(write=True, interactive=False),
                    remote_writer=lambda: remote(write=True),
                    request_id=args.request_id, company_id=args.company_id,
                    max_operations=args.max_operations,
                )
    print(json.dumps(result, sort_keys=True))
    return 0
