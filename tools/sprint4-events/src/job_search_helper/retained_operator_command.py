"""Operator-only signer preview and execution entry point."""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
from types import SimpleNamespace

from . import cli
from .company_events import CompanyEventBridge
from .engine import State
from .retained_operator_authorization import (
    ACTION, EVENT_ACTION, verify_expired_event_authorization, verify_retained_scope_authorization,
)
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


def _schedule_retry(args, approval, verifier, runtime, manifest, local, jobs):
    """Schedule only one verified terminal retry without starting any scraper."""
    from .retained_operator_journal import operator_journal_binding
    from .retained_work_runner import assert_normal_lifecycle_not_held
    from .scrape_outcome_delivery import OutcomeDelivery
    from .temporary_retry import CONSUMER, SelectedTemporaryRetrySink

    claims = approval.get("payload") if isinstance(approval, dict) else None
    if (not isinstance(claims, dict)
            or (claims.get("request_id"), claims.get("company_id"), claims.get("cycle_id"),
                claims.get("historical_manifest_sha256")) != (
                args.request_id, args.company_id, args.cycle_id, manifest["manifest_digest"])):
        raise ValueError("retained_event_retry_authorization_scope_changed")
    try:
        signature = verify_retained_scope_authorization(approval, claims, verifier, action=EVENT_ACTION)
    except ValueError as error:
        if str(error) != "selected_recovery_authorization_expired":
            raise
        signature = verify_expired_event_authorization(approval, claims, verifier)
    binding = operator_journal_binding(claims, runtime, signature)
    root = jobs.parent
    sink = SelectedTemporaryRetrySink(
        local, root, outcome_id=args.outcome_id, request_sha256=claims["request_sha256"],
        reservation_digest=binding["reservation_digest"],
    )
    with cli.writer_lock(root / "writer.lock"):
        assert_normal_lifecycle_not_held(root, jobs)
        # Recheck the exact archive before opening the local writer.
        sink._selected()
        with closing(cli.get_repository(write=True, interactive=False)) as writer:
            if Path(writer.path).resolve() != jobs or writer.spreadsheet_id != local.spreadsheet_id:
                raise ValueError("retained_operator_repository_identity_changed")
            delivery = OutcomeDelivery(
                writer, SimpleNamespace(ingest_immutable=sink._ingest_immutable_locked), consumer=CONSUMER,
            )
            results = delivery.drain(limit=1, outcome_id=args.outcome_id)
    return {"outcome_id": args.outcome_id, "delivery": results}


def operator_command(arguments, admission):
    """Run only the explicitly requested, admitted operator operation."""
    parser = argparse.ArgumentParser(prog="./job-search-scraper run-retained-operator-company")
    parser.add_argument("operation", choices=("stage-event", "preview", "execute", "schedule-retry"))
    parser.add_argument("--cycle-id", required=True)
    parser.add_argument("--company-id", required=True)
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--manifest-file", required=True)
    parser.add_argument("--source-revision")
    parser.add_argument("--outcome-id")
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
    if args.operation in {"execute", "schedule-retry"} and (not args.approval_file or args.expires_at):
        parser.error("execution or retry scheduling requires --approval-file")
    if args.operation == "schedule-retry":
        if action != EVENT_ACTION or not args.outcome_id:
            parser.error("schedule-retry requires --company-event and --outcome-id")
    elif args.outcome_id:
        parser.error("--outcome-id is only for schedule-retry")
    if not 1 <= args.max_operations <= 100:
        parser.error("--max-operations must be between 1 and 100")
    if args.operation in {"execute", "schedule-retry"}:
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
            if args.operation == "schedule-retry":
                result = _schedule_retry(args, approval, verifier, runtime, manifest, local, jobs)
                print(json.dumps(result, sort_keys=True))
                return 0
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
