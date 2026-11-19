# Independent migration review — source-installation acceptance

2026-11-19. **Recommendation: ACCEPT FOR SOURCE INSTALLATION ONLY.**

The remaining public adoption retry defect is fixed, altered retries still refuse, and the narrowed installation package reconstructs and passes independently against the current protected baseline. No remaining source-installation blocker was found in this review. This report supersedes the preceding REJECT recommendation.

This acceptance is limited to the exact package and baseline hashes below. It does not authorize or demonstrate live adoption, Google publication, scraping, queue release, service changes, or operational completion. The reviewer did not install anything or modify protected source or production state. All execution used a disposable source copy, synthetic repositories, and temporary SQLite databases.

## Exact accepted package and reconstruction

Candidate: `/tmp/job-search-helper-integration-automation/temp/integration-coordinator/protected-exact-candidate-20261119/`

Protected baseline read for reconstruction: `/home/chris/job-search-helper_old/`

Tested copy: `/home/chris/Documents/Codex/2026-11-19/job-search-migration-review/work/final-install-review/`

The independent reconstruction was captured at **2026-11-19 20:26:36.793813 UTC**, including the latest byte-for-byte read-only preview test and regenerated manifest. It copied only Python source/tests and the two title-list inputs, then overlaid exactly the 13 listed package files. No production databases, credentials, runtime history, locks, or environment files were copied.

| Artifact | SHA-256 |
| --- | --- |
| `SHA256SUMS` | `1f5e58e6cfb342102c712384fdf18911adc978343912fc399bb2e6c43ef9827d` |
| `PROTECTED_BASELINE_SHA256SUMS` | `e44aa504a446d3859fcfb0228550da02003412275c0cfdb70ba3d932de32d82b` |
| Final `README.md` | `42354076391060af671f1098169660d1feef0ca5755cbd422f5b6f0b2e850028` |
| Latest `tests/test_exact_legacy_migration.py` | `29129b18d713efa2b2dd1d235391d84ab6e3b5ccf0e56b2f3fce68cb106d3486` |

At **20:28:21 UTC**, independent final verification established:

- All 13 packaged Python files are listed exactly once and match `SHA256SUMS`; no packaged Python file is omitted.
- All 10 existing protected targets match `PROTECTED_BASELINE_SHA256SUMS`.
- The three new targets listed in the README are absent from the protected checkout: the migration builder, migration runner, and migration test module.
- Every overlaid file in the tested copy matches the accepted package hash and compiles.
- All 493 copied protected source/test/title-list inputs remained unchanged during the review.

The only candidate metadata change after capture was the README's test count changing from 247 to 248. That change was read, verified against the independent result, and included in the final evidence. Package source and both checksum manifests remained unchanged.

## Previous blockers closed

**Public post-successor retry — closed.** The original independent reproduction now calls `adopt_retained_legacy_migration` twice with identical approval pins. Both return `REMOTE_PLAN_FROZEN`. The second call leaves the records, dirty fields, predecessor/successor journal, saved plan/cursor, inbox mirror, and local application/chunk evidence unchanged. Local operation execution is patched to raise if replay occurs. The retry creates no publication receipt, remote plan, remote chunk, or local acknowledgement.

`begin_exact_legacy_migration` now recognizes and compares the immutable migration journal before first-adoption-only checks. The public path then verifies local adoption and the saved successor/mirror. This closes the crash-equivalent boundary after successor commit but before the caller receives its result. Public recovery after an interruption between local adoption and inbox completion also passes without replay.

**Altered retries — protections retained.** Eleven independent variants each raise the expected `ValueError`, preserve the post-edit database state without further mutations, and create zero receipts:

| Altered evidence | Refusal verified |
| --- | --- |
| Approval snapshot pin | `Exact legacy approval pins no longer match current evidence.` |
| Full local row: Job History / Review Notes | Same approval-pin refusal |
| Saved successor payload or cursor | `Exact legacy frozen successor changed after adoption.` |
| Inbox mirror apply ID, record digest, or state | Same frozen-successor refusal |
| Local application plan digest | `Exact legacy local adoption conflicts with its journal.` |
| Local chunk operations digest | `Exact legacy adopted chunk evidence changed.` |
| Inventory blocked state | `Exact retained inventory is missing or blocked.` |
| Migration journal successor digest | `Exact legacy migration journal conflicts with retry.` |

**Installation manifest — closed.** The package now contains exactly 13 changed/new Python files, with complete hashes, ten verified baseline targets, and three explicit new targets. Reconstruction from that package, rather than reuse of the previous broad candidate copy, passed the suite below.

## Earlier safeguards independently retained

The four blank/nonblank remote-guard cases pass. Mismatches remain pending across database reopen, do not advance the remote cursor, and do not report a successful write. Matching guards confirm and acknowledge through genuine reads from the synthetic remote repository. Guard-only fields remain outside dirty-field acknowledgement; local Decision is preserved.

Normal v2 receipt derivation matches the sealed guard-aware fingerprints. Default v1 fingerprint semantics and saved plans remain compatible. The actual previous reader produces historical v1 confirmation evidence from unchanged synthetic remote rows; after restart, the candidate finishes acknowledgement with the identical acknowledgement ID.

The expected-only Source Hash, between-read Decision edit, inactive Company, foreign ownership, full-row planning drift, and changed local guard on restart still refuse. Company-first legacy ordering works through both exact Sheets planning and public existing-plan recovery. The synthetic Davidson-shaped case retains 19 local operations, 10 remote operations, nine local-only evidence operations, exactly two protected conflicts, and unchanged planning inputs.

The latest final-freeze snapshot protection remains present. Changing `Job History → Review Notes` after `LOCAL_COMPLETE` and before successor freeze raises `Exact legacy successor snapshot changed before freeze.` The original legacy plan/cursor and `LOCAL_COMPLETE` state remain. Promotion now also holds the local `BEGIN IMMEDIATE` transaction across the inbox successor commit, protecting the final snapshot-to-promotion boundary.

Cross-database reopen/retry and injected transaction-failure probes pass. Cleanup refuses at `FROZEN` and `LOCAL_COMPLETE`; discard and inventory block refuse while migration owns the work. After valid publication, durable confirmation, local acknowledgement, and the inbox acknowledgement marker, terminal cleanup preserves the migration archive.

The newly supplied public preview test confirms that both SQLite database files remain byte-for-byte unchanged. It is included in the tested snapshot and final suite.

## Compatibility with the current protected release binding

The `publication_receipts.py` overlay was compared directly with the current protected file. Its changes are limited to the optional guard-aware fingerprint behavior. An AST comparison proves `_receipt_id` is identical to the protected implementation, including `release_binding_sha256` validation and identity binding. The existing regression distinguishing two complete-release digests and rejecting a malformed digest passes in the reconstructed suite.

## Independent verification results

**248 supplied/focused/adjacent tests passed in 21.389 seconds**, with warnings treated as errors. The increase from the requested 247 includes the latest read-only preview regression.

**40 independent checks passed in 5.155 seconds**, also with warnings treated as errors. The former failing public-retry probe now asserts successful unchanged recovery; none of these final probes deliberately treats a remaining defect as success.

Run from the tested copy:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /home/chris/job-search-helper_old/.venv/bin/python3.11 -W error -m unittest -v reviewer_probes adoption_probes.AdoptionChecks compatibility_probes.CompatibilityChecks runner_probes
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /home/chris/job-search-helper_old/.venv/bin/python3.11 -W error -m unittest -q test_exact_legacy_migration test_exact_local_plan test_exact_cycle_planner test_sheets_sync_exact_scope test_exact_cycle_sync test_exact_cycle_recovery test_exact_recovery_terminal test_publication_receipts test_durable_inbox test_exact_recovery_pause test_exact_recovery_pause_apply test_exact_recovery_pause_executor test_runner_cycles test_run_scoped_sync
```

Evidence beside the requested report: `HIGH_MODEL_MIGRATION_REVIEW_EVIDENCE/final-install-review/`. It contains the independent probes, test logs, accepted manifests and README, the complete reconstruction/hash inventory, final verification, and the superseded report. The complete runnable reconstructed source/test copy remains at the tested-copy path above.

Source installation may proceed under the package's existing guarded install/rollback procedure after rechecking these exact hashes and target absences at installation time. A changed package or protected baseline is outside this acceptance and requires reconciliation. Live migration and publication remain separate actions.
