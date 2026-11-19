# Exact-cycle combined orchestration design — 2026-11-19

## Purpose

Connect the independently accepted planner and the still-under-review scoped
publisher without widening the existing production containment boundary. This
component is for bounded recovery of explicitly named saved inventories in one
unfinished cycle. It is not a cycle-wide sync command and never falls back to
the global synchronizer.

## Required invocation boundary

- Require one exact `cycle_id` and an explicit, unique Company-ID list.
- Hard-reject empty, duplicate, unknown, blocked, or over-bound selections
  before constructing a writable remote repository. The public command's
  first release is limited to at most five Companies.
- Never derive the selection by iterating the entire inbox, State cycle,
  Company sheet, or local queue.
- Keep retry of blocked inventories unavailable. Retained blocked/unsupported
  items belong only to the terminal-hold qualification path.

## Ordered transaction boundary

For each explicit Company, one at a time:

1. Re-read the exact State member and inbox payload under the existing scraper
   writer lock.
2. Read only that current remote Company control row. Freeze or validate the
   immutable local plan and exact `LOCAL_COMMITTED` receipt.
3. Re-read the same remote Company control row inside the publisher and require
   the versioned evidence digest to match the plan.
4. Publish only that Company's frozen plan in bounded journalled chunks.
5. Require exact selected-row readback, confirm the exact receipt, save the
   final State checkpoint, and only then acknowledge that inventory.
6. On any failure or uncertainty, retain its plan, cursor, receipt, and
   inventory and stop or hold that Company without touching another Company
   unless the caller explicitly selected it and isolation tests prove
   continuation is safe.

The planner must not open Google itself. The publisher must not inspect an
unselected Company, global local-dirty state, review exports, coordinator
outbox, another cycle, or `next-scan.json`.

## Repository construction

- Local planning uses the existing SQLite repository only as a current local
  snapshot; planning remains in-memory until the inbox plan/receipt save.
- Remote access uses the direct Google repository with only the exact
  `read_columns`, `read_rows`, and guarded `commit` operations supported by the
  scoped publisher.
- Do not enter `run_scoped_sync`, `LocalPipeline`, normal publisher startup,
  manual synchronization, closed-job cleanup, review export, outcome delivery,
  or performance persistence.

## Crash and restart acceptance

Tests must interrupt after each durable boundary: plan/receipt save, local
checkpoint save, receipt pending, chunk intent, remote acknowledgement loss,
chunk confirmation, cursor advance, receipt confirmation, State finalization,
and inbox acknowledgement. A rerun of the same exact selection must either
read back and continue without replay or fail closed with all evidence intact.

The combined test fixture must include an unselected frozen plan, an unplanned
inventory, a blocked hold, an unrelated cycle, unrelated SQLite dirty/outbox
rows, and an unchanged request file. Every one must remain byte/state
unchanged.

## Activation gate

Do not replace the production `HELD_NO_EXACT_PLANNER` return until:

1. planner source/test acceptance remains green;
2. scoped publisher repairs pass independent QA;
3. this combined orchestration and its interruption matrix pass independent
   QA;
4. a scoped source/rollback manifest is saved; and
5. a fresh read-only production preflight proves the exact blocker, processes,
   locks, inbox counts, State membership, and remote control identities are
   unchanged.

The first live action is one explicitly named, smallest-plan Company. It must
settle end to end with exact readback before a second Company is considered.
