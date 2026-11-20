# Historical cycle reconciliation refresh — 2026-11-19

## Scope and method

Read-only refresh for `CYC-B639C6D864EC` in the protected MuleLab checkout.
No locks, databases, Company/Job records, services, Google connections, or
Jetson state were changed. This is an operator decision record, not an
authorization to run recovery.

## Current authoritative state

| Item | Current evidence |
| --- | --- |
| Cycle row | `Scan Cycles` row 48 remains `In Progress`; 800 Companies in scope, 18 Complete, 8 Partial, 5 Blocked, and 769 Remaining. Last checkpoint is `2026-11-18T16:58:40+00:00`. |
| Company rows | All 800 Company rows still name this cycle. Present states: 712 Queued, 58 Blocked / Manual Review, 22 Complete, and 8 Partial. |
| Retained inventories | 45 saved inventories exist for the exact cycle; 5 are marked blocked. |
| Retained sync plans | 6 legacy plans remain. Five blocked-company plans (`COMP-0002`, `COMP-0008`, `COMP-0016`, `COMP-0040`, `COMP-0045`) have cursor `1/1`. `COMP-0054` has cursor `67/208`, with 105 Job History, 97 Job Evidence, 5 Opportunities, and 1 Companies operations. Its next unapplied legacy operation is Job Evidence for the same Ashby Job Key as operation 67. |
| Direct remote-confirmation evidence | Two `SYNC_CONFIRMED` receipts bind this cycle as their request ID, for `COMP-0035` (10 Job History plus its Company record) and `COMP-0052` (Company record). They are already confirmed and must never be replayed. Neither is one of the six remaining `sync_plans`. |
| Outstanding publication status | No `publication_receipts` row binds any of the six retained plans. The five `1/1` cursors show legacy local completion, not a Sheets confirmation. `COMP-0054` is only partially locally progressed by its legacy cursor; it has no exact-local-state or remote-plan journal. The other 39 saved inventories have no retained plan, so they are saved-only rather than publication-ready. |
| Processes / locks | Scraper, writer, and first-pass controller lockfiles name PIDs `53107`, `717646`, and `283795`; all were absent at observation. Locks are retained. No relevant live scraper/writer/coordinator process was observed. |

## What current guards prove

The ordinary exact-cycle pause is deliberately unavailable. Its read-only gate
counts saved inventories and plans across every unfinished cycle and returns
`SAVED_WORK_MUST_BE_PUBLISHED_OR_RECONCILED` whenever either exists. Therefore
`recover-interrupted-cycle --apply` is not a valid next action for this cycle;
it would refuse before changing the cycle. Removing a lock would not make the
work safe and is prohibited.

The available migration paths are also not presently applicable:

| Candidate read-only path | Result observed | Consequence |
| --- | --- | --- |
| `legacy-migration-preview` for each of the five blocked plans | `Exact retained inventory is missing or blocked.` | No adoption or publication is authorized. |
| `legacy-migration-preview` for `COMP-0054` | `legacy_plan_local_cursor_not_complete` | A complete-plan migration cannot safely interpret the remaining 141 operations. |
| `retained-exception-preview` for the exact cycle | An initial invocation failed with `NameError: now is not defined`. A fresh invocation at `2026-11-19T22:06:26-05:00` succeeded through the repository wrapper and source-tree module after the protected dirty source imported `now` from `.engine`. | The current preview is usable as read-only evidence, but its success does not authorize an apply path. The protected source changed between observations and must be pinned and revalidated before any reconciliation action. |

The special control-before-prefix facility is deliberately **local-only** and
its generic exact-cycle publisher rejects it until a dedicated release gate is
designed. It cannot safely convert `COMP-0054` into a remote publication.

## Precise non-destructive reconciliation plan

1. Preserve the exact cycle, six plans, 45 inventories, two confirmed receipts,
   and all lockfiles. Capture current hashes/counts again immediately before any
   authorized action. Do not run `start`, `start --resume`, broad `sync`, or
   delete/replace locks.
2. Run only the existing read-only gate first, after a fresh process/lock check:

   ```bash
   ./job-search-scraper recover-interrupted-cycle-status \
     --cycle-id CYC-B639C6D864EC
   ```

   Its expected result is a saved-work refusal, not readiness. It validates that
   the cycle and blocker scope have not changed.
3. Pin the exact current protected `runner.py` bytes that made the refreshed
   `retained-exception-preview` succeed, reconcile that dirty-source change
   with the reviewed overlay, and independently prove that the command remains
   read-only. The preview must emit deterministic cycle/plan/receipt/Company
   identity claims; it is still not an apply authorization.
4. Obtain explicit owner approval for a **plan-by-plan** reconciliation design.
   The design must state how each of the five blocked local-only controls is
   retained without remote publication and how the `COMP-0054` 67-operation
   prefix, 141-operation suffix, Opportunities, and Company control will be
   compared against current protected rows. It must distinguish existing rows,
   user edits/manual decisions, and absent append-only rows.
5. Only after that design has independent QA and a signer-approved immutable
   binding may a dedicated per-company recovery command be introduced. It must:
   (a) freeze one exact legacy plan and cursor; (b) prove Company/source and
   Job Key/Source Hash ownership; (c) record a local successor journal before
   mutation; (d) separately create one exact remote receipt and read back the
   acknowledgement; and (e) leave ambiguous acknowledgements and manual
   conflicts held. Generic `sync --cycle-id` is not a substitute.
6. Reconcile every one of the 45 saved inventories: either a confirmed exact
   receipt, a durable supported hold, or a reviewed per-company plan. Only then
   may the ordinary interrupted-cycle status become eligible for a written
   `recover-interrupted-cycle --apply` pause. The cycle may never be paused
   merely to make a future company-only request easier.

## Required approvals / blockers

1. Owner decision to reconcile the historical 800-company cycle rather than
   leave it retained while new work remains blocked.
2. Independent QA approval of the preview defect repair and the dedicated
   `COMP-0054` partial-prefix/suffix contract.
3. Explicit signed, time-limited authorization for each exact plan before any
   local write; separate approval/authorization for each remote Sheets publish.
4. Interactive Google authorization and independently observed exact readback
   before a remote receipt can become `SYNC_CONFIRMED`.
5. Fresh one-writer/lock/process, current Company/source-revision, release-settlement,
   and manual-choice checks immediately before each apply. A failed guard is a
   hold, never a reason to retry broadly or delete a lock.

## Bottom line

There is no existing safe destructive/apply command for this exact retained
state. The smallest exact command available today is the read-only
`recover-interrupted-cycle-status` probe above, which should keep the cycle
blocked. The next implementation work is a reviewed, plan-level reconciliation
contract—not a broad rescan, a generic sync, or lock cleanup.
