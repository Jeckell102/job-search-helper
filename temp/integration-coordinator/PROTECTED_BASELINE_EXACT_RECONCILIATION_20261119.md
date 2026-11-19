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
