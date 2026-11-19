# Protected-baseline exact-cycle reconciliation — 2026-11-19

## Scope and safety boundary

This is an offline source-and-tests-only reconciliation record.  The temporary
copy is `/tmp/job-search-helper-protected-reconciliation-o8XL4Q`.  It was made
from the current protected MuleLab source and tests while excluding `.state`,
SQLite files, locks, credentials, job inventories, `work/`, and Git metadata.
No production file, process, lock, database, Google row, scraper, queue,
release, or Jetson service was changed.

## Fresh protected-state evidence

- No scraper, coordinator, publisher, or review process was found.
- Retained controller PID `283795`, scraper PID `5325`, writer PID `717646`,
  and review-writeback PID `4` were absent.  The lock files remain untouched.
- `CYC-B639C6D864EC` retains 47 inventories and eight partial plans.  It is a
  recovery hold, not permission for a company-only scrape or a broad sync.

## Accepted source input

The source/fixture-approved exact finalization checkpoint is
`0a4691832a3364438fdb975fa03da58a1e3fbd70`, verified on the authorized private
GitHub branch `codex/integration-automation-20261118`.  Its independent QA
matrix passed 235 checks; coordinator reruns passed 194 strict exact and 52
adjacent checks.

## Reconciliation result so far

The protected baseline is `c9db537` with material, newer local source changes.
It did not contain the exact-cycle module stack.  A bounded patch added these
modules only to the disposable copy and all compile:

- `exact_cycle_planner.py`
- `exact_cycle_receipt.py`
- `exact_cycle_recovery.py`
- `exact_cycle_sync.py`
- `exact_local_plan.py`
- `exact_recovery_pause.py`
- `exact_recovery_pause_apply.py`
- `exact_recovery_pause_executor.py`
- `exact_recovery_terminal.py`

New exact-cycle tests were likewise added only to that copy.  The first run
exposed omitted non-sensitive title-list assets; after adding those assets to
the copy, the test failures identified the real seams: production SQLite lacks
the exact local journals and production Sheets synchronization lacks the narrow
exact APIs.

An automatic three-way-style apply intentionally left explicit rejects for
`inbox.py`, `runner.py`, `sheets_sync.py`, and `sqlite_repository.py`.  It did
not silently replace their newer protected behavior.  `publication_receipts.py`
already matched the accepted source hash.  The current temporary copy is a
diagnostic integration workspace, not a candidate and not deployable.

## Required manual merge order

1. Add SQLite exact-local migrations and journal methods while retaining
   protected Company-event, outcome, and compact-profile interfaces.
2. Merge Inbox v2 records and cleanup/legacy-reconciliation fail-closed rules
   without changing legacy-plan handling.
3. Add narrow Sheets exact planning/readback/acknowledgement APIs while
   retaining production baseline-token, Company-source hold, and salary
   fallback protections.
4. Wire the exact recovery entry into the current runner before every global
   synchronizer, cleanup, review, outcome, and performance path; preserve the
   normal runner unchanged for all other commands.
5. Re-run the exact and protected-overlap suites on temporary state, obtain
   independent QA, then consider a separately authorized protected install.

## Current gate

No live exact-cycle publisher, Google write, Samtec request, company-only
scrape, broad backlog run, automatic repair, or automatic release is enabled.
The next action is manual source-only seam reconciliation in the disposable
copy.

## Incremental merge evidence

The first manual seam was SQLite only.  The disposable copy now installs the
additive `exact_local_applications`, `exact_local_apply_chunks`, and
`exact_local_acknowledgements` journals and exposes the exact local
apply/verify wrappers, while retaining the protected Company-event and
outcome schema.  `tests/test_exact_local_plan.py` then passed 9 of 11 tests.
The two remaining failures are limited to missing Inbox v2 state methods
(`save_exact_plan` and its local-state transitions).  This confirms the next
manual seam is the Inbox v2 layer; it does not authorize a source install or
any live action.

The Inbox seam is now merged in the disposable copy.  It creates the additive
exact-plan local-state table; seals exact v2 plans to an already-saved
inventory; records monotonic local-apply/local-verify state; compare-and-swap
advances only the frozen local cursor; and refuses cleanup while an exact plan
lacks its separately registered terminal remote plan.  The complete
`tests/test_exact_local_plan.py` gate now passes: **11 passed in 0.78s**.
This is temporary-source evidence only.  The remote-plan registration,
Sheets readback/confirmation, and runner entry remain unmerged and disabled.

The planner compatibility gate now also passes: **21 passed in 0.82s** for
`tests/test_exact_cycle_planner.py`.  The remaining Inbox recovery seam was an
exact receipt lookup, added to the temporary copy with an ambiguity refusal.
The compact-profile planner recovery and frozen-plan receipt tests therefore
run against the retained protected behavior.  This proves local planning only;
no Sheets publisher or runner path is merged or enabled.

The first Sheets seam is now present in the temporary copy: explicit scope
validation resolves only named local stable identities and rejects malformed
scope, duplicate rows, stale row hints, unknown fields, invalid guards, and
ambiguous records before any remote method is reachable.  It adds no Google
read/write path.  Compilation plus the retained local/planner gate passed:
**32 passed in 1.57s** (`test_exact_local_plan.py` and
`test_exact_cycle_planner.py`).  Frozen-operation construction, selected-row
readback, and confirmation remain separate unmerged steps.

The complete protected-baseline candidate is now assembled in the same
disposable copy. The previously vetted production-based v3 merge was upgraded
with the accepted `0a46918` finalization lifecycle patch, then its reconciled
`runner.py`, `inbox.py`, `publication_receipts.py`, `sheets_sync.py`,
`sqlite_repository.py`, exact modules, and focused tests were copied into this
full sanitized protected-source copy. Preserved `*.rej` files remain audit
artifacts and are excluded from the candidate manifest; no candidate Python
file contains a conflict marker.

Fresh verification from the full copy passed **186 focused checks** in 17.99s
and **180 protected-adjacent checks** in 27.84s with warnings treated as
errors. The focused set includes pending-cleanup refusal, legacy-confirmation
refusal, server-derived local row evidence, local acknowledgement evidence
before `LOCAL_ACKNOWLEDGED` or cleanup, uncertain-write no-replay, bounded
chunk recovery, exact compact readback, and manual/source-hash/salary guards.
The adjacent set covers current runner cycles, scoped sync, local pipeline,
SQLite migration, release controller, repaired retry, and scrape-to-FIRST-PASS
behavior. Independent read-only review of this exact full-copy candidate is
in progress. Production, Google, locks, job state, services, and Jetson remain
untouched.

The initial source-level QA acceptance was superseded by a later independent
review.  It found that terminal recovery could qualify a completed legacy plan
from a caller-supplied readback-digest envelope when no confirmed receipt
existed.  Because the resulting manifest can reach pause finalization, this is
a release-blocking confirmation-boundary bypass.  The isolated repair removes
the callback/proof route, requires the exact durable `SYNC_CONFIRMED` receipt
for every completed frozen plan, and removes four residual `*.rej` artifacts
from the candidate.  The repair matrix passed 122 focused checks and compile /
artifact hygiene checks.  This replaces—not supplements—the earlier source
acceptance; fresh independent QA is required before a protected install or any
live Sheets acceptance.

The sanitized overlay package and `SHA256SUMS` were committed and pushed to
the private feature branch. Local HEAD, the local remote-tracking ref, and an
independent `git ls-remote` query all matched
`79dd7969abe9b0440ff815abe9bccbe038e1cc30`; the feature worktree was clean.
The rollback-backed protected install then stopped at permission review before
the install script ran or any protected file changed. Because five target core
files are already modified or untracked in the protected dirty checkout, a
fresh explicit owner approval naming that overwrite/addition risk is required.
The prepared installer rechecks the five recorded pre-hashes, requires all nine
new exact modules to be absent, acquires the existing integration lock, writes
a durable per-file backup manifest, performs atomic copies, verifies every
installed hash, and automatically restores only its own file set on failure.

The owner subsequently gave that exact approval. The guarded installer ran on
2026-11-19 and reported `INSTALLED_HASH_VERIFIED` for all 27 approved source
and test files. Its durable rollback receipt is
`/tmp/job-search-protected-exact-backup-20261119T185825Z-2_4dpn9p/manifest.json`.
An independent post-install SHA-256 pass compared every installed file with
that receipt and found 27 matches with zero mismatches.

Post-install offline verification in the protected checkout passed **186
focused checks** in 18.14s and **180 protected-adjacent checks** in 25.38s,
with warnings treated as errors. The install and verification did not access
Google, start a scrape, restart a service, change the live database, delete a
lock, release a queue, or modify the Jetson. Live exact publication and the
final end-to-end company demonstration remain separately approval-gated.

Candidate core hashes:

- `runner.py`: `28c05b612544eb51c073bbb784f508ec6a48343d3e4006a8545e17d514809aae`
- `inbox.py`: `ef9056796e35ea807ba8ecf52585685543bf4196717968a665a2450ae5ced8bc`
- `publication_receipts.py`: `ae2432f3ff81652e5c0d2dcfc196d291bd42189ef0246e3b1962ca00699e31be`
- `sheets_sync.py`: `29d3032915133a491c41233fec12b8fa76d6e70773c4d49815a93de67dee92ef`
- `sqlite_repository.py`: `31cd2d926f8b704459bf79651e67a1ccc7a3c9db393e8aa95ceb187bb9e908b6`
- `exact_cycle_sync.py`: `674a549cc6eec2e4d3c1acdad78ac7f3f1d3410f19ec404eb70f2a8f383f7b04`
- `exact_local_plan.py`: `8055d43f9801a8442221eab0cb8ea3660ccb8e252420aac5653e54315bcb141e`

## Additional scoped Sheets planning evidence

The disposable copy also now has local-only `_plan_exact_row` and
`plan_exact_scope` coverage.  These helpers do not pull, discover, prune,
publish, read remotely, or write remotely.  They validate named stable
identities and frozen baseline expectations; preserve protected source-hash
and blank extracted-salary behavior; reject user-owned Opportunities and
non-append Notes; and seal the operation set.  Compilation and these focused
fixture checks passed (3 passed, 0.264s):

- `test_planning_uses_only_explicit_scope_and_requires_frozen_equality`
- `test_blank_extracted_salary_keeps_remote_estimate_as_expected_guard`
- `test_new_local_row_preserves_sealed_remote_insert_semantics`

This is temporary-source evidence only.  It does not activate a publisher,
runner, Samtec/company scrape, Google request, or any live release gate.

## Terminal qualification repair

Fresh independent QA found and then verified removal of a release-blocking
terminal-recovery bypass: a legacy callback could supply a nonempty selected
row digest even though it had not performed a remote read.  The repaired
candidate has no callback/proof parameter; completed frozen plans qualify only
with their exactly matching durable `SYNC_CONFIRMED` receipt.  All residual
`*.rej` artifacts are removed.  Independent read-only QA passed 168 tests
across terminal/pause/executor, exact Sheets, receipts, planning, local
journals, and recovery.  The remaining protected source still contains the
old one-file implementation and requires a rollback-backed targeted repair;
no Google or live recovery action is authorized by this evidence.
