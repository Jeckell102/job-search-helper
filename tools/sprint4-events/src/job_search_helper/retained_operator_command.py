"""Operator-only signer preview and execution entry point."""
import argparse
from contextlib import closing
import json
import os
import re
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


def _selected_retry_sink(args, approval, verifier, runtime, manifest, local, jobs):
    """Bind the explicit retry operation to the exact signed event archive."""
    from .retained_operator_journal import operator_journal_binding
    from .temporary_retry import SelectedTemporaryRetrySink

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
    return SelectedTemporaryRetrySink(
        local, jobs.parent, outcome_id=args.outcome_id, request_sha256=claims["request_sha256"],
        reservation_digest=binding["reservation_digest"],
    )


def _schedule_retry(sink, local, jobs):
    from .retained_work_runner import assert_normal_lifecycle_not_held
    from .scrape_outcome_delivery import OutcomeDelivery
    from .temporary_retry import CONSUMER

    with cli.writer_lock(jobs.parent / "writer.lock"):
        assert_normal_lifecycle_not_held(jobs.parent, jobs)
        # Recheck the exact archive before opening the local writer.
        sink._selected()
        with closing(cli.get_repository(write=True, interactive=False)) as writer:
            if Path(writer.path).resolve() != jobs or writer.spreadsheet_id != local.spreadsheet_id:
                raise ValueError("retained_operator_repository_identity_changed")
            delivery = OutcomeDelivery(
                writer, SimpleNamespace(ingest_immutable=sink._ingest_immutable_locked), consumer=CONSUMER,
            )
            results = delivery.drain(limit=1, outcome_id=sink.outcome_id)
    return {"outcome_id": sink.outcome_id, "delivery": results}


def _admit_retry(sink, state, runtime, remote_reader):
    from .selected_temporary_retry_admission import admit_selected_temporary_retry_locked

    with cli.writer_lock(sink.root / "writer.lock"):
        result = admit_selected_temporary_retry_locked(sink, state, runtime)
        if result["state"] != "HELD_WORKBOOK_SNAPSHOT_REQUIRED":
            return result
        local = sink.reader
        profile = local.get_meta("sheets_profile")
        schemas = profile_schemas(profile)
        remote = remote_reader()
        if not schemas or remote.schemas != schemas or remote.spreadsheet_id != local.spreadsheet_id:
            raise ValueError("retained_operator_retry_workbook_changed")
        remote.validate_schema()
        outcome, _path, _key = sink._selected()
        cid = outcome["identity"]["company_id"]
        columns = ["Company ID", "Company Status", "Official Careers URL", "ATS / Source", "Automatic Retry?"]
        matches = [
            row for _, row in remote.read_columns("Companies", columns)
            if row.get("Company ID") == cid
        ]
        if len(matches) != 1:
            return {"state": "HELD_WORKBOOK_COMPANY", "request_id": result["request_id"]}
        snapshot = {"spreadsheet_id": remote.spreadsheet_id, "profile": profile, "cycles": None,
                    "company": matches[0]}
        return admit_selected_temporary_retry_locked(sink, state, runtime, workbook_snapshot=snapshot)


def _fetch_retry(sink, state, runtime, remote_reader, *, cycle_id):
    from .ats import fetch_inventory
    from .browser_scraper import with_browser_fallback
    from .exact_cycle_sync import _unique_company
    from .repository import _equivalent
    from .selected_temporary_retry_execution import freeze_selected_temporary_retry_locked

    def workbook_guard(company):
        remote = remote_reader()
        local = sink.reader
        if remote.schemas != profile_schemas(local.get_meta("sheets_profile")) or remote.spreadsheet_id != local.spreadsheet_id:
            raise ValueError("retained_operator_retry_workbook_changed")
        remote.validate_schema()
        fields = ["Company ID", "Company Status", "Official Careers URL", "ATS / Source", "Automatic Retry?"]
        observed = _unique_company(remote, company["Company ID"], fields)
        if any(not _equivalent(key, observed.get(key, ""), company.get(key, "")) for key in fields):
            raise ValueError("retained_operator_retry_workbook_company_changed")

    with cli.writer_lock(sink.root / "writer.lock"):
        return freeze_selected_temporary_retry_locked(
            sink, state, runtime, cycle_id=cycle_id, fetcher=with_browser_fallback(fetch_inventory),
            workbook_guard=workbook_guard,
        )


def _publish_retry(sink, state, runtime, remote_writer, *, cycle_id):
    from .engine import Engine
    from .inbox import InventoryInbox
    from .integration_release import assert_release_settled
    from .retained_work_runner import assert_normal_lifecycle_not_held
    from .selected_temporary_retry_execution import load_selected_retry_inventory
    from .selected_temporary_retry_publication import publish_frozen_selected_retry_locked

    with cli.writer_lock(sink.root / "writer.lock"):
        assert_release_settled(sink.root)
        assert_normal_lifecycle_not_held(sink.root, sink.reader.path, selected_retry_cycle_id=cycle_id)
        load_selected_retry_inventory(sink, state, runtime, cycle_id=cycle_id)
        path = sink.root / "inventories.sqlite3"
        if path.is_symlink() or not path.is_file():
            raise ValueError("retained_operator_retry_inbox_unavailable")
        with (closing(cli.get_repository(write=True, interactive=False)) as writer,
              closing(State(str(state.path))) as writable_state,
              closing(InventoryInbox(path, sink.reader.spreadsheet_id)) as inbox):
            engine = Engine(writer, writable_state, inbox=inbox, runtime_binding=runtime)
            return publish_frozen_selected_retry_locked(sink, engine, remote_writer, cycle_id=cycle_id)


def operator_command(arguments, admission):
    """Run only the explicitly requested, admitted operator operation."""
    parser = argparse.ArgumentParser(prog="./job-search-scraper run-retained-operator-company")
    parser.add_argument("operation", choices=("stage-event", "preview", "execute", "schedule-retry", "admit-retry", "fetch-retry", "publish-retry"))
    parser.add_argument("--cycle-id", required=True)
    parser.add_argument("--company-id", required=True)
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--manifest-file", required=True)
    parser.add_argument("--source-revision")
    parser.add_argument("--outcome-id")
    parser.add_argument("--successor-cycle-id")
    parser.add_argument("--expires-at")
    parser.add_argument("--approval-file")
    parser.add_argument("--company-event", action="store_true")
    parser.add_argument("--max-operations", type=int, default=100)
    args = parser.parse_args(arguments)
    action = EVENT_ACTION if args.company_event else ACTION
    retry_operations = {"schedule-retry", "admit-retry", "fetch-retry", "publish-retry"}
    successor_operations = {"fetch-retry", "publish-retry"}
    if args.operation in successor_operations:
        if not args.successor_cycle_id or not re.fullmatch(r"CYC-[0-9A-F]{12}", args.successor_cycle_id):
            parser.error("fetch-retry and publish-retry require an exact --successor-cycle-id")
    elif args.successor_cycle_id:
        parser.error("--successor-cycle-id is only for fetch-retry and publish-retry")

    if args.operation == "stage-event":
        if (not args.company_event or not args.source_revision or args.expires_at or args.approval_file
                or not args.request_id.startswith("company-event:")):
            parser.error("stage-event requires --company-event, --source-revision, and an exact Company-event request ID")
    elif args.source_revision:
        parser.error("--source-revision is only for stage-event")
    if args.operation == "preview" and (not args.expires_at or args.approval_file):
        parser.error("preview requires --expires-at")
    if (args.operation == "execute" or args.operation in retry_operations) and (not args.approval_file or args.expires_at):
        parser.error("execution or retry scheduling requires --approval-file")
    if args.operation in retry_operations:
        if action != EVENT_ACTION or not args.outcome_id:
            parser.error("retry operations require --company-event and --outcome-id")
    elif args.outcome_id:
        parser.error("--outcome-id is only for retry operations")
    if not 1 <= args.max_operations <= 100:
        parser.error("--max-operations must be between 1 and 100")
    if (args.operation == "execute" or args.operation in retry_operations):
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

            if args.operation in retry_operations:
                sink = _selected_retry_sink(args, approval, verifier, runtime, manifest, local, jobs)
                if args.operation == "schedule-retry":
                    result = _schedule_retry(sink, local, jobs)
                elif args.operation == "admit-retry":
                    result = _admit_retry(sink, state, runtime, remote)
                elif args.operation == "fetch-retry":
                    result = _fetch_retry(sink, state, runtime, remote, cycle_id=args.successor_cycle_id)
                else:
                    result = _publish_retry(sink, state, runtime, lambda: remote(write=True),
                                            cycle_id=args.successor_cycle_id)
            elif args.operation == "preview":
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
