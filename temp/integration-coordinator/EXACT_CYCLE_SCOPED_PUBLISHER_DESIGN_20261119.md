# Exact-cycle scoped publisher design — 2026-11-19

## Independent architecture decision

The retained cycle cannot use `RunSheetsSync`, `SheetsSynchronizer.pull`, the
global local-outbox publisher, or `LocalPipeline._reconcile_receipt`.
`RunSheetsSync` performs a workbook-wide control pull and drains shared dirty
rows. `LocalPipeline` is bound to the local SQLite repository in this runner,
so its receipt readback is not proof of a Google Sheets write.

The required implementation is a separate selected-plan publisher. It may
open the normal remote repository directly, using the current compact schema
profile, but it must consume only frozen `InventoryInbox` plans for one
explicit cycle ID. It must never call the global synchronizer.

## Required ordering

For each selected Company plan:

1. Read only the named plan, cursor, and existing receipt.
2. Verify the selected Company's current control fields. A pause, claim,
   changed board, or version mismatch holds only that selected work.
3. If the receipt is already `SYNC_PENDING`, perform exact remote readback
   first and do not replay the write automatically.
4. Otherwise persist `SYNC_PENDING` before issuing the selected remote commit.
5. Commit exactly the remaining frozen operations through the existing remote
   repository identity/expected guards.
6. Reread only the identities and owned fields represented by those frozen
   operations. A whole-workbook `read`/`read_many` is disallowed.
7. Compare persisted operation fingerprints with the fresh remote rows. Only
   a matching remote fingerprint may confirm the receipt, advance the frozen
   plan cursor, and acknowledge the inventory.

Conflict, timeout, lost acknowledgement, or mismatching readback retains the
exact plan, cursor, receipt, and inventory. It must not refetch or
automatically replay.

## Acceptance matrix

- One named plan plus an unrelated dirty SQLite row and second inbox cycle:
  only the named frozen operations reach remote commit; every unrelated local,
  inbox, outbox, and remote value remains unchanged.
- Expected/identity conflict: no cursor advance or acknowledgement.
- Lost acknowledgement: receipt remains `SYNC_PENDING`; the next run performs
  readback only and does not issue a second write.
- Matching readback: receipt becomes `SYNC_CONFIRMED`; only the named cursor
  advances and only its completed inventory may be acknowledged.
- Mismatching readback: no advance or acknowledgement.
- Paused/claimed/changed-board selected Company: no remote mutation.
- Compact-profile `Opportunity ID` and Job Evidence routing remain valid.
- No call to `run_scoped_sync`, `SheetsSynchronizer.pull`, global
  `publish_batch`, cleanup, manual intake, review export, or outcome delivery.

## Operational gate

The accepted containment hold remains the production behavior until this
implementation passes the full matrix and independent QA. This document does
not authorize a live recovery or weaken the five existing manual holds.

## Current retained-plan facts

The authoritative read-only inbox audit found eight existing plans. Seven have
their cursor already at the end and therefore require exact remote readback,
checkpoint finalization, and acknowledgement only. `COMP-0054` has 208 frozen
operations with cursor 67 and 141 remaining operations (about 974 KB encoded).
No retained plan repeats the same tab/record identity. Chunk recovery must
still use a digest-bound durable chunk journal and compare-and-swap cursor;
these facts do not justify an unbounded request.

There are also 39 unblocked durable inventories with no frozen plan. A
selected-plan publisher cannot process them and therefore cannot lift the
cycle blocker by itself. They need a separate exact planner that consumes the
existing saved inventory without refetching, uses the compact local schema,
performs narrow current-Company guards, freezes immutable operations, and then
hands them to the selected publisher. Until both components pass QA, the
production containment hold remains correct.

## Exact planner boundary for the 39 unplanned inventories

Independent review disqualified `LocalPipeline.run(sync_only=True)` and a
direct call to `LocalPipeline.stage`: both are coupled to global iteration,
publication, unblocking, or failure-status mutation. The planner must be a
separate bounded component that accepts explicit cycle and Company IDs and
never fetches or publishes.

For each explicitly selected unblocked inventory it must validate exact cycle
membership/stage, payload identity, compact local schema, active/unclaimed
Company controls, and requested careers URL both locally and through a narrow
remote Company-controls read. It then builds the operations and final state
entirely in memory using the existing planning/engine rules. The immutable
plan plus `LOCAL_COMMITTED` receipt is persisted first; only afterward is the
selected cycle checkpoint changed from the recoverable queued split to
inventory/durable-plan state. Those databases cannot share one transaction,
so a crash between them must leave the plan retained and idempotently
reconcilable, never deleted or silently replanned.

The planner may change only the selected plan/receipt and selected cycle item.
It must leave local job rows, dirty publisher rows, Company-event outbox,
unrelated cycles/inventories, remote rows, and all blocked inventories
untouched. Publication repeats the current remote Company guard before its
first selected write.
