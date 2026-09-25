"""Explicit local policy inspection, screening, and assessment history."""
from __future__ import annotations

import json

from .assessment_service import AssessmentService
from .catalog_commands import _text
from .database import Database
from .dates import readable_timestamp
from .local_screening import EVALUATOR_VERSION, RESULT_LABELS
from .policy import POLICY_VERSION, load_policy


SCREENING_COMMANDS = {"policy", "screen", "assessments"}


def add_screening_commands(actions, common_options):
    policy = actions.add_parser("policy", help="Inspect a profile; no file means neutral rules.")
    policy.add_argument("--profile", help="Explicit TOML profile path relative to the workspace.")
    common_options(policy)
    screen = actions.add_parser("screen", help="Preview screening of saved jobs; --apply appends assessments.")
    selection = screen.add_mutually_exclusive_group(required=True)
    selection.add_argument("--all", action="store_true", help="Include all saved jobs and statuses.")
    selection.add_argument("--job-id", action="append")
    screen.add_argument("--profile", help="Explicit TOML profile; omitted means no screening.")
    screen.add_argument("--apply", action="store_true")
    common_options(screen)
    assessments = actions.add_parser("assessments", help="Read saved screening history.")
    operations = assessments.add_subparsers(dest="assessment_action", required=True)
    listing = operations.add_parser("list")
    listing.add_argument("--job-id")
    listing.add_argument("--limit", type=int, default=100)
    listing.add_argument("--offset", type=int, default=0)
    common_options(listing)
    show = operations.add_parser("show")
    show.add_argument("id")
    common_options(show)


def execute_screening(args, settings):
    if args.local_command in {"policy", "screen"}:
        policy = load_policy(settings.workspace, args.profile)
        if args.local_command == "policy":
            result = {"ok": True, "enabled": policy.enabled, "policy_fingerprint": policy.fingerprint,
                      "format_version": POLICY_VERSION, "evaluator_version": EVALUATOR_VERSION, "rules": policy.rules}
            return result, "Local screening profile: " + ("enabled" if policy.enabled else "neutral") + "\n" + json.dumps(result, indent=2)
        with Database(settings.database, readonly=not args.apply) as database:
            result = AssessmentService(database).screen(policy, all_jobs=args.all, job_ids=args.job_id or (), apply=args.apply)
        counts = result["counts"]
        lines = [f"Screening {'saved' if args.apply else 'preview'}: {counts['new']} new, {counts['unchanged']} unchanged, {counts['skipped']} skipped."]
        if not policy.enabled:
            lines.append("No rules configured. Existing assessments remain unchanged.")
        for row in result["items"]:
            lines.append(f"{_text(row['title'] or '(no title)')} | {_text(row['company_name'])} | {RESULT_LABELS[row['result']]} | {_text(row['job_id'])}")
            lines.append("  " + _text(row["reason"]))
        if not args.apply:
            lines.append("No records changed. Add --apply to evaluate again and save against the current evidence.")
        return result, "\n".join(lines)
    with Database(settings.database, readonly=True) as database:
        service = AssessmentService(database)
        if args.assessment_action == "show":
            item = service.show(args.id)
            result, items = {"ok": True, "assessment": item}, [item]
        else:
            result = service.history(job_id=args.job_id, limit=args.limit, offset=args.offset)
            items = result["items"]
    lines = [f"Assessments: {len(items)} shown" + (f", {result['total']} total." if "total" in result else ".")]
    for item in items:
        lines.extend([f"{_text(item['title'])} | {RESULT_LABELS[item['result']]} | {readable_timestamp(item['evaluated_at'])}",
                      "  " + _text(item["reason"]), f"  Assessment: {_text(item['assessment_id'])}",
                      f"  Policy: {item['policy_fingerprint']} | Evaluator: {item['evaluator_version']}"])
        if "stale" in item:
            lines.append("  Evidence/evaluator: " + ("Needs reassessment" if item["stale"] else "Unchanged"))
            lines.append("  History: " + ("Latest saved assessment" if item["current"] else "Superseded by a later assessment"))
        if args.assessment_action == "show":
            lines.append("  Policy rules: " + _text(json.dumps(item["policy"], sort_keys=True)))
            for check in item["evidence"]:
                lines.append(f"  {_text(check['rule_id'])}: {check['outcome']} | {_text(check['field'])}: {_text(check['value'])}")
    return result, "\n".join(lines)
