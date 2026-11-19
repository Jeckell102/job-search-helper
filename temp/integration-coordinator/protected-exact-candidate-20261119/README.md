# Protected exact-cycle candidate — 2026-11-19

This is the sanitized, source-and-tests-only overlay for the current protected
MuleLab baseline. It contains no credentials, databases, job data, locks,
inventories, receipts, or runtime history. It is not a standalone checkout:
apply it only to the protected baseline whose pre-install hashes are listed
below and only through the existing integration install lock.

## Evidence

- Accepted source lifecycle input: `0a4691832a3364438fdb975fa03da58a1e3fbd70`.
- Full sanitized-copy verification: 186 focused and 180 protected-adjacent
  checks passed with warnings treated as errors.
- The earlier terminal-proof acceptance was superseded: the overlay removes
  caller-provided legacy readback proof and requires a durable matching
  `SYNC_CONFIRMED` receipt for every completed frozen plan.
- Fresh independent verification after that repair: 168 focused and
  protected-overlap checks passed. The legacy callback path, fabricated/stale
  terminal manifests, exact readback tampering, and pause-finalization bypass
  are all covered.
- The independent migration re-review then passed 243 supplied checks and 29
  independent checks. It rejected installation for one post-successor retry
  defect and a stale package manifest. The retry is now an idempotent no-op,
  its public regression passes, and the complete repaired overlay passes 248
  focused and adjacent checks with warnings treated as errors. A final
  independent acceptance rerun is still required before installation.
- No candidate Python file contains a merge marker or `*.rej` artifact.
- `SHA256SUMS` seals every packaged source and test file.
- `PROTECTED_BASELINE_SHA256SUMS` seals every currently existing protected
  target that this package would replace.

## Required protected pre-install hashes

Every existing target must match `PROTECTED_BASELINE_SHA256SUMS`. These three
new targets must be absent:

- `src/job_search_helper/exact_legacy_migration.py`
- `src/job_search_helper/exact_legacy_migration_runner.py`
- `tests/test_exact_legacy_migration.py`

Any hash mismatch, missing expected target, or unexpected existing new target
is a stop, not permission to overwrite.

## Install and rollback boundary

1. Recheck no active scraper/publisher/reviewer/coordinator process, settled
   release state, and the exact pre-install hashes above.
2. Acquire—not delete or bypass—`.integration-install.lock`.
3. Save a new per-file rollback copy and before manifest outside job data.
4. Install only Python source and test files listed in `SHA256SUMS`; do not
   touch databases, `.state`, locks, credentials, inventories, package
   metadata, or unrelated dirty files.
5. Verify installed hashes, compile, and rerun the accepted focused and
   protected-adjacent matrices without Google access.
6. On any mismatch or failure, restore only replaced files and remove only
   newly added files recorded by that rollback manifest, then verify hashes.

This package authorizes no Google write, scrape, backlog release, service
restart, automatic repair, Jetson change, or final acceptance claim.
