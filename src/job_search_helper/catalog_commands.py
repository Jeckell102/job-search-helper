"""Company import, local inspection, and user-owned application edits."""
from __future__ import annotations

from .catalog_queries import CatalogQueries
from .company_import import CompanyImporter
from .config import workspace_path
from .database import Database
from .dates import readable_timestamp
from .models import APPLICATION_STATUSES, COMPANY_STATUSES, JOB_STATUSES
from .repositories import ApplicationRepository, CatalogRepository
from .scan_lock import scan_lock


CATALOG_COMMANDS = {"import-companies", "companies", "jobs", "applications"}
COMPANY_FLAGS = {"name": "company_name", "website": "website_url", "category": "category",
                 "technology-focus": "technology_focus", "priority": "priority", "notes": "notes",
                 "why-it-fits": "personal_rationale"}


def _edit_option(parser, name, *, clear=True):
    options = parser.add_mutually_exclusive_group()
    options.add_argument("--" + name)
    if clear:
        options.add_argument("--clear-" + name, action="store_true")


def add_catalog_commands(actions, common_options):
    imports = actions.add_parser("import-companies", help="Preview company CSV changes; --apply saves the validated import.")
    imports.add_argument("file", help="UTF-8 CSV, relative to the workspace unless absolute.")
    imports.add_argument("--apply", action="store_true")
    imports.add_argument("--preserve-ids", action="store_true", help="Allow new companies to keep supplied Company IDs.")
    common_options(imports)
    for kind, statuses in (("companies", COMPANY_STATUSES), ("jobs", JOB_STATUSES), ("applications", APPLICATION_STATUSES)):
        group = actions.add_parser(kind, help=f"View or manage local {kind}.")
        operations = group.add_subparsers(dest="catalog_action", required=True)
        listing = operations.add_parser("list", help=f"List {kind}, including all statuses unless filtered.")
        listing.add_argument("--status", choices=statuses)
        listing.add_argument("--limit", type=int, default=100)
        listing.add_argument("--offset", type=int, default=0)
        if kind != "companies":
            listing.add_argument("--company-id")
        if kind == "applications":
            listing.add_argument("--job-id")
        else:
            listing.add_argument("--search")
        common_options(listing)
        show = operations.add_parser("show", help="Show full details and readable dates.")
        show.add_argument("id")
        common_options(show)
        if kind == "companies":
            update = operations.add_parser("update", help="Edit company fields; use import to preview source changes.")
            update.add_argument("id")
            update.add_argument("--expected-version", type=int, required=True, help="Row version displayed by show.")
            update.add_argument("--status", choices=COMPANY_STATUSES)
            for flag in COMPANY_FLAGS:
                _edit_option(update, flag, clear=flag != "name")
            common_options(update)
        if kind == "applications":
            add = operations.add_parser("add", help="Record interest or an application locally; never submits a form.")
            add.add_argument("--job-id", required=True)
            add.add_argument("--status", choices=APPLICATION_STATUSES, default="interested")
            add.add_argument("--date-applied", help="YYYY-MM-DD; omitted means unknown, even for applied status.")
            add.add_argument("--notes", default="")
            add.add_argument("--resume-used", default="")
            common_options(add)
            update = operations.add_parser("update", help="Edit a local application with an appended history event.")
            update.add_argument("id")
            update.add_argument("--expected-version", type=int, required=True, help="Row version displayed by show.")
            update.add_argument("--status", choices=APPLICATION_STATUSES)
            for field in ("date-applied", "notes", "resume-used"):
                _edit_option(update, field)
            common_options(update)


def execute_catalog(args, settings):
    kind = args.local_command
    if kind == "import-companies":
        path = workspace_path(settings.workspace, args.file)
        with Database(settings.database, readonly=not args.apply) as database:
            importer = CompanyImporter(database)
            if args.apply:
                with scan_lock(database.path):
                    result = importer.apply(path, preserve_ids=args.preserve_ids)
            else:
                result = importer.preview(path, preserve_ids=args.preserve_ids)
        return result, _import_text(result)
    action = args.catalog_action
    with Database(settings.database, readonly=action in {"list", "show"}) as database:
        queries = CatalogQueries(database)
        if action == "list":
            filters = {key: getattr(args, key) for key in ("company_id", "job_id", "status", "search", "limit", "offset")
                       if hasattr(args, key)}
            result = getattr(queries, kind)(**filters)
            return result, _list_text(kind, result)
        singular = {"companies": "company", "jobs": "job", "applications": "application"}[kind]
        if action == "show":
            result = {"ok": True, singular: getattr(queries, singular)(args.id)}
        elif kind == "companies":
            changes = _changes(args, COMPANY_FLAGS)
            if args.status is not None:
                changes["status"] = args.status
            with database.transaction():
                CatalogRepository(database).update_company(args.id, expected_version=args.expected_version, **changes)
                result = {"ok": True, "company": queries.company(args.id)}
        else:
            repository = ApplicationRepository(database)
            with database.transaction():
                if action == "add":
                    identity = repository.add(args.job_id, status=args.status, date_applied=args.date_applied,
                                              notes=args.notes, resume_used=args.resume_used)
                else:
                    changes = _changes(args, {"date-applied": "date_applied", "notes": "notes", "resume-used": "resume_used"})
                    if args.status is not None:
                        changes["application_status"] = args.status
                    repository.update(args.id, expected_version=args.expected_version, **changes)
                    identity = args.id
                result = {"ok": True, "application": queries.application(identity)}
        return result, _detail_text(singular, result[singular])


def _changes(args, fields):
    changes = {}
    for flag, field in fields.items():
        value = getattr(args, flag.replace("-", "_"), None)
        if value is not None:
            changes[field] = value
        elif getattr(args, "clear_" + flag.replace("-", "_"), False):
            changes[field] = None if field == "date_applied" else ""
    return changes


def _text(value):
    # Public job text and CSV cells are data, including any terminal controls.
    return "".join(char if char.isprintable() or char in "\n\t" else ascii(char)[1:-1] for char in str(value))


def _import_text(result):
    counts = result["counts"]
    label = "Import saved" if result["applied"] else "Import preview"
    lines = [f"{label}: {counts['add']} new, {counts['update']} updated, {counts['unchanged']} unchanged."]
    for row in result["rows"]:
        lines.append(f"Line {row['line']}: {row['action']} {_text(row['company_name'])} ({_text(row['company_id'] or 'new ID on apply')})")
        for field, change in row["changes"].items():
            lines.append(f"  {field.replace('_', ' ')}: {_text(change['before']) or '(blank)'} -> {_text(change['after']) or '(blank)'}")
        if row["source_change"]:
            before = row["source_before"]["careers_url"] if row["source_before"] else "(none)"
            lines.append(f"  Careers URL: {_text(before)} -> {_text(row['source']['careers_url'])}")
        if row["warning"]:
            lines.append("  " + row["warning"])
    lines += [f"Line {error['line']}: {_text(error['error'])}" for error in result["errors"]]
    if result["ignored_columns"]:
        lines.append("Computed columns ignored: " + ", ".join(result["ignored_columns"]))
    if result["errors"]:
        lines.append("No records changed. Fix the listed rows and preview again.")
    elif not result["applied"]:
        lines.append("No records changed. Add --apply to save these changes after revalidation.")
    return "\n".join(lines)


def _list_text(kind, result):
    lines = [f"{kind.capitalize()}: {len(result['items'])} shown, {result['total']} total; offset {result['offset']}."]
    for row in result["items"]:
        if kind == "companies":
            lines.append(f"{_text(row['company_name'])} | {row['status']} | {_text(row['company_id'])}")
            lines.append(f"  Careers: {_text(row['careers_url'] or 'Not set')}")
            lines.append(f"  Last scan: {readable_timestamp(row['last_scan_at'])} | {row['last_scan_result'] or 'Not scanned'}")
        else:
            status = row["application_status"] if kind == "applications" else row["lifecycle_status"]
            identity = row["application_id"] if kind == "applications" else row["job_id"]
            lines.append(f"{_text(row['title'])} | {_text(row['company_name'])} | {status} | {_text(identity)}")
            if kind == "applications":
                lines.append(f"  Applied: {readable_timestamp(row['date_applied'])}; saved: {readable_timestamp(row['date_saved'])}")
            else:
                lines.append(f"  {_text(row['location'])} | {_text(row['job_url'])}")
                lines.append(f"  Last seen: {readable_timestamp(row['last_seen_at'])} | Application: {row['application_status'] or 'Not tracked'}")
                lines.append(f"  Screening: {row['screening_status']}")
    return "\n".join(lines)


def _detail_text(kind, row):
    fields = {
        "company": ("company_name", "status", "careers_url", "provider", "last_scan_at", "last_scan_result",
                    "last_apply_result", "last_scan_reason", "last_successful_scan_at", "website_url", "category",
                    "technology_focus", "priority", "notes", "personal_rationale", "created_at", "updated_at", "company_id", "row_version"),
        "job": ("title", "company_name", "location", "work_arrangement", "compensation_text", "lifecycle_status",
                "application_status", "job_url", "is_listed", "source_created_at", "source_created_raw", "source_modified_at",
                "source_modified_raw", "first_seen_at", "last_seen_at", "last_material_change_at", "closed_at", "closure_basis",
                "department", "requisition_id", "description", "screening_status", "screening_reason",
                "screening_evaluated_at", "screening_policy_fingerprint", "screening_assessment_id", "job_id", "row_version"),
        "application": ("title", "company_name", "application_status", "date_applied", "date_saved", "notes", "resume_used",
                        "job_status", "job_url", "job_url_at_application", "created_at", "updated_at", "job_id", "application_id", "row_version"),
    }
    lines = []
    for field in fields[kind]:
        value = row.get(field)
        if field.endswith("_at") or field.startswith("date_"):
            value = readable_timestamp(value)
        elif value is None or value == "":
            value = "Not set"
        elif field == "is_listed":
            value = "Yes" if value else "No"
        lines.append(f"{field.replace('_', ' ').capitalize()}: {_text(value)}")
    if "events" in row:
        lines.append("History:")
        for event in row["events"]:
            lines.append(f"  {readable_timestamp(event['recorded_at'])}: {event['old_status'] or '(new)'} -> {event['new_status']} | {_text(event['note'])}")
    return "\n".join(lines)
