# Independent migration review — runner reconciliation

2026-11-19. **Recommendation: ACCEPT FOR SOURCE INSTALLATION ONLY.**

The reconciled runner preserves the current protected terminal Company bridge and adds only the previously accepted migration command/help changes. The package scope is unchanged, the current baseline matches, and the disposable reconstruction passes the checks below. No remaining blocker was found within this narrow source-installation review.

This report supersedes the prior acceptance's package/baseline hashes. It does not install the package or authorize live migration, Google publication, scraping, queue release, or service changes. The reviewer read source/test files and ran synthetic tests in a disposable copy. Protected source and production state were not modified; no live Google or job data was accessed.

## Accepted revision

Candidate: `/tmp/job-search-helper-integration-automation/temp/integration-coordinator/protected-exact-candidate-20261119/`

Current protected source: `/home/chris/job-search-helper_old/`

Reconstructed test copy: `/home/chris/Documents/Codex/2026-11-19/job-search-migration-review/work/runner-reconciliation-review/`

| Binding | SHA-256 |
| --- | --- |
| Candidate `runner.py` | `3e4155245517a135945b001defd8a28e0d8e31f1be3750c6a2ccdf6c93391471` |
| Required protected `runner.py` | `275e14909ad47c277d4fbd2e2aaa47922586ac98136e9ad255070ba57902fdc3` |
| Package `SHA256SUMS` | `a365c93822c6f3ca6419b7aea40b18626f86f7cfbe15c4317d45c1aceda25ff3` |
| `PROTECTED_BASELINE_SHA256SUMS` | `d6c0574719792ea606a5a13dcfe945c4f7afad7b92cd930937ae32ac36de7a9f` |

The reconstruction was captured at **2026-11-19 20:39:22.473954 UTC**. The package still contains exactly 13 Python files, replacing ten existing targets and adding the same three new migration files. Every packaged file is listed exactly once, all package and baseline hashes match, and all three new targets are absent from the protected checkout. Only `runner.py` differs from the previously accepted 13-file package; only its entry differs in the required baseline manifest.

The disposable copy was rebuilt from 493 current protected Python source/test and title-list inputs, then overlaid with exactly the package's 13 files. This includes the newer protected `run_sync.py` and Company bridge/sync test changes. No production database, credentials, runtime history, or environment file was copied.

## Runner and bridge preservation

The candidate-versus-current-protected diff has only three additions: the `Path` import, migration help text, and the two migration command branches. The reconciliation does not remove or alter the newer terminal bridge code.

Structural and text comparisons independently established:

- `run_start` is **byte-for-byte identical** to the current protected implementation. This includes `sync = None`, the `run_completed` gate, the final run-owned sync exit, and `CompanyEventBridge(...).process_pending(writer_lock_held=True)` at candidate lines 722-737.
- All 23 functions other than `print_help` and `scrape_main` are byte-for-byte identical to the protected implementation.
- Removing only the two migration branches from the candidate's `scrape_main` produces the same AST as protected `scrape_main`.
- Both migration branches and the help function match the previously accepted versions by AST. Their approval-file handling, explicit `--apply`, normal writer lock, settled-release check, and local-only adoption call remain intact.

The expanded suite includes `test_terminal_intake_event_becomes_one_next_scan_after_current_cycle_stops`. It verifies that final intake creates one next-run scoped request and one receipt, the current Company is fetched exactly once, there is only one cycle, and later bridge redelivery does not create another request or receipt. Related Company event/outbox, final-sync, stale-choice, and standalone-lock checks also pass.

This is preservation of the independently installed bridge implementation, not a claim that a live Company event or production scan was exercised.

## Fresh verification

**282 supplied/focused/adjacent tests passed with warnings treated as errors.** This includes the previously requested 248-test selection plus the Company event bridge, Company event outbox, and stale Sheet choice suites relevant to the newer protected changes.

**40 independent migration checks passed with warnings treated as errors.** They recheck unchanged public adoption retry, eleven altered-evidence refusals, interruption/no-replay recovery, full-row snapshot drift, premature-cleanup refusal, terminal archival, guard-only remote reads, v1 confirmed-evidence compatibility, and normal v2 receipt derivation. The latest byte-for-byte read-only preview test remains included in the supplied suite.

The first expanded run had one fixture-configuration failure: the source-only copy defaulted to the Sheets backend, so the standalone bridge selected `writer.lock` while its SQLite test expected `scraper.lock`. No candidate code was changed. The final expanded run explicitly selected `JOB_STORAGE_BACKEND=sqlite`, consistent with its SQLite fixtures, and passed all 282 checks. Both logs are retained.

All 13 package files compile. The final hash comparison and target-absence results are recorded in `final-verification.json`; acceptance requires its candidate and required-baseline change lists to be empty.

Reproduction from the reconstructed copy:

```sh
JOB_STORAGE_BACKEND=sqlite PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /home/chris/job-search-helper_old/.venv/bin/python3.11 -W error -m unittest -q test_exact_legacy_migration test_exact_local_plan test_exact_cycle_planner test_sheets_sync_exact_scope test_exact_cycle_sync test_exact_cycle_recovery test_exact_recovery_terminal test_publication_receipts test_durable_inbox test_exact_recovery_pause test_exact_recovery_pause_apply test_exact_recovery_pause_executor test_runner_cycles test_run_scoped_sync test_company_event_bridge test_company_event_outbox test_stale_sheet_choices
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /home/chris/job-search-helper_old/.venv/bin/python3.11 -W error -m unittest -v reviewer_probes adoption_probes.AdoptionChecks compatibility_probes.CompatibilityChecks runner_probes
```

Evidence beside the requested report is in `HIGH_MODEL_MIGRATION_REVIEW_EVIDENCE/runner-reconciliation-review/`: both runner diffs, reconstruction/hash inventory, final verification, test logs, independent probes, accepted manifests and README, and the superseded report.

Install only this exact package under the existing guarded install/rollback procedure, rechecking the baseline hashes and new-target absences immediately before installation. Any subsequent protected change requires reconciliation rather than bypassing the mismatch. Live migration and publication remain separate actions.
