# Retained cycle reconciliation map — 2026-11-19

Scope: read-only source and local-state analysis of `CYC-B639C6D864EC`, plus
`company-queue-status --local-only` (no pending request). No scraper, publish,
queue write, lock change, database mutation, or Google action was performed.

## Current retained state

- Cycle is `In Progress`, scope 800 Companies: 764 queued, 20 complete, 8
  partial, 3 inventory, 3 blocked, and 2 unsupported.
- Saved inbox holds 47 inventories (five blocked) and eight legacy plans; all
  eight legacy cursors are nonzero. There is no publication receipt for the
  cycle.
- The only non-terminal inventory/plan candidates are `COMP-0035` Davidson
  (legacy migration state `FROZEN`), `COMP-0052` Shield AI, and `COMP-0054`
  Saronic. They are not cleared for action by this mapping.

## Command boundary

| Surface | Classification |
| --- | --- |
| `company-queue-status --local-only` | Read-only; current result: no pending request. |
| `recover-interrupted-cycle-status` | Assessment only; current result blocks pause. |
| `legacy-migration-preview` for Davidson | Local SQLite read-only, but adoption remains separately held. |
| `sync --cycle-id … --company-id` | Bounded selected-company recovery, but mutates local state, reads back, and publishes selected Sheets changes. |
| `recover-interrupted-cycle --apply` | Mutating and currently fail-closed because saved work remains. |
| `start --resume` | Broad 800-company scan and Sheets-write path; prohibited for this recovery. |

## Required gate before any selected sync

Require an explicit set of one to three company IDs; exact prestate inventory,
plan digest and cursor; current company URL/status/claim controls; no live
writer and retained-lock evidence; settled release journal; fresh selected
remote readback; an exact receipt-binding plan; and independent QA/release
approval. Terminal holds require a true selected-row confirmation path that
creates exact `SYNC_CONFIRMED` receipts; legacy cursors alone are insufficient.

This map preserves the normal scraper and rules out guessing, broad resume, or
unbounded publication as a way to clear the cycle.
