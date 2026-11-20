"""Operator-only signer preview and execution entry point."""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path

from . import cli
from .company_events import CompanyEventBridge
from .engine import State
from .retained_operator_authorization import ACTION, EVENT_ACTION
from .retained_operator_preflight import measure_operator_membership
from .retained_operator_scope import disjoint_event_scope_evidence
from .retained_work_exception import revalidate_manifest
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
    parser.add_argument("operation", choices=("stage-event", "preview", "execute"))
    parser.add_argument("--cycle-id", required=True)
    parser.add_argument("--company-id", required=True)
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--manifest-file", required=True)
    parser.add_argument("--source-revision")
    parser.add_argument("--expires-at")
    parser.add_argument("--approval-file")
    parser.add_argument("--company-event", action="store_true")
    parser.add_argument("--max-operations", type=int, default=100)
    args = parser.parse_args(arguments)
    action = EVENT_ACTION if args.company_event else ACTION
    if args.operation == "stage-event":
        if (not args.company_event or not args.source_revision or args.expires_at or args.approval_file
                or not args.request_id.startswith("company-event:")):
            parser.error("stage-event requires --company-event, --source-revision, and an exact Company-event request ID")
    elif args.source_revision:
        parser.error("--source-revision is only for stage-event")
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
    if args.operation == "stage-event":
        with cli.writer_lock(root / "writer.lock"):
            with closing(State(str(database), readonly=True)) as state:
                disjoint_event_scope_evidence(state.cycles(), cycle_id=args.cycle_id, company_id=args.company_id)
                revalidate_manifest(manifest, state.cycle(args.cycle_id), root / "inventories.sqlite3", jobs)
            with closing(cli.get_repository(write=True, interactive=False)) as local:
                if Path(local.path).resolve() != jobs:
                    raise ValueError("retained_operator_repository_identity_changed")
                result = CompanyEventBridge(local, root)._stage_manual_retained_event_locked(
                    args.request_id.removeprefix("company-event:"), company_id=args.company_id,
                    source_revision=args.source_revision, blocking_cycle_id=args.cycle_id,
                )
        print(json.dumps(result, sort_keys=True))
        return 0
    with closing(State(str(database), readonly=True)) as state:
        with closing(cli.get_repository(write=False, interactive=False)) as local:
            if Path(local.path).resolve() != jobs:
                raise ValueError("retained_operator_repository_identity_changed")
            schemas = profile_schemas(local.get_meta("sheets_profile"))
            if schemas is None:
                raise ValueError("retained_operator_projected_workbook_required")

            def remote(*, write=False):
                # Compact publication keeps full Job Evidence in SQLite.
                # Route both snapshots and writes to the same main workbook.
                return cli.get_remote_repository(write=write, interactive=False, schemas=schemas,
                                                 evidence_archives=False)

            if args.operation == "preview":
                claims = measure_operator_membership(
                    local, remote(), state, root, manifest, runtime, expires_at=args.expires_at,
                    request_id=args.request_id, company_id=args.company_id, action=action,
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
                    request_id=args.request_id, company_id=args.company_id, action=action,
                    max_operations=args.max_operations,
                )
    print(json.dumps(result, sort_keys=True))
    return 0
