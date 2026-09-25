# Architecture And Extension Guide

The public application is a Python command-line tool with a local SQLite catalog.
Its entry point is `job_search_helper.local_cli:main`. Paths below are relative
to the repository; module names are under `src/job_search_helper/`.

## Scan Flow

```text
Verified company board URLs
          |
          v
Read-only adapters fetch an Inventory
          |
          v
ScanService.stage_inventory saves a durable snapshot
          |
          v
ScanService.apply_inventory validates and writes the catalog
          |
          +--> Job listings, CSV exports, and optional screening

Application commands --> Separate application records and edit history
```

The writer runs after fetching and durable staging. Recovery can apply an
already-saved inventory without fetching it again. Application decisions do not
belong to the scraper or the screening pipeline.

## Find The Right Module

| Concern | Main files | Relevant tests |
| --- | --- | --- |
| Commands and workspace configuration | `local_cli.py`, `local_commands.py`, `config.py` | `test_local_commands.py`, `test_local_config.py` |
| Board resolution and public adapters | `ats.py`, provider modules such as `workday.py` | `test_ats.py` |
| Scan coordination, staging, and recovery | `local_scanner.py`, `scan_service.py`, `scan_lock.py` | `test_local_scans.py` |
| Catalog, identity, and application records | `models.py`, `repositories.py`, `database.py`, `migrations/` | `test_local_models.py`, `test_local_repositories.py`, `test_local_database.py` |
| Company import and catalog commands | `company_import.py`, `catalog_commands.py`, `catalog_queries.py` | `test_company_import.py`, `test_catalog_commands.py` |
| Profiles and screening assessments | `policy.py`, `local_screening.py`, `assessment_service.py` | `test_local_screening.py` |
| Dates and CSV exports | `dates.py`, `csv_format.py`, `catalog_export.py`, `export_publish.py` | `test_source_dates.py`, `test_catalog_exports.py` |

Tests live under `tests/`. `tests/check_local_install.py` verifies the actual
installed package and command in a fresh environment.

## Adding Or Improving An Adapter

There is no external plugin registration API yet. Adapters are integrated into
the package. Start by reading `ats.py` and the synthetic transport in
`tests/test_ats.py`; discuss a new provider before implementing it.

1. Define the verified public URL shapes and employer/board scope. Review URL
   validation and provider selection, including company import and `resolve_board`.
   Avoid broadening a scoped employer page into a parent organization's whole board.
2. Use an injectable transport with bounded timeouts, retries, and pagination.
   Reuse the existing transport patterns and respect access restrictions.
3. Return an `Inventory` containing posting dictionaries and an explicit status:
   `complete`, `partial`, `blocked`, `failed`, or `unsupported`.
4. Preserve stable public posting IDs, full descriptions, URLs, and original date
   strings. `JobPosting.from_adapter` maps `created_at` and `updated_at` to raw
   source dates; `dates.py` handles normalization separately.
5. Integrate dispatch through `fetch_inventory` and confirm that the local scanner
   accepts the intended board URL. Keep database writes in the scan service.
6. Test success, verified empty boards, pagination, repeated pages, missing fields,
   network failures, blocked responses, and source scope using synthetic responses.
   Add an ingestion regression test when identity or completeness behavior changes.
7. Update the supported-provider documentation and include verification in the PR.

`complete` means the intended public inventory was retrieved. It does not mean
that a posting is a good fit. Partial inventories can record observed jobs but
cannot establish absence. With the default threshold, two comparable complete
scans without a posting infer closure. A new sighting can reopen it without
changing its application record.

## Changing Stored Data

SQLite migrations are numbered and checksum-verified. Add a new migration instead
of editing a historical one. Cover upgrading an existing database, preserving
application history, and restoring a backup when changing storage behavior.

Screening stores assessments separately and retains the policy and evidence used.
It should not remove jobs or rewrite application decisions. Unknown evidence
must remain distinguishable from a negative finding.

Human-facing dates use readable text; SQLite and JSON retain ISO timestamps.
Keep source date strings so a parser change can be reviewed against original
evidence. Do not invent time zones for unzoned source values.

## Platform Boundaries

The supported environment is currently Linux. `scan_lock.py` uses POSIX locking,
and `export_publish.py` uses Linux atomic publication behavior. Platform support
work needs equivalent protections and tests, not just a different shell command.

The source tree is the working project. `RELEASE_MANIFEST.json` describes the
generated source snapshot from release assembly, not a stable runtime API.
Its checksums may become historical as development continues; release artifacts
need a freshly generated manifest when they are assembled.
