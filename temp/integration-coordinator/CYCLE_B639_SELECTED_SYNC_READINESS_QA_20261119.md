# Retained cycle selected-sync readiness QA — 2026-11-19

Independent scope: read-only inspection of `CYC-B639C6D864EC` candidates
Davidson (`COMP-0035`), Shield AI (`COMP-0052`), and Saronic (`COMP-0054`). No
Google call, sync/start/recover/adopt invocation, process/lock change, or file
mutation occurred.

## Verdict: no candidate is eligible for bounded selected sync

All three have complete durable local inventories and legacy plans with
nonzero local cursors, but none has a v2 exact plan, source/input binding,
receipt ID, publication projection/schema digest, control evidence, remote
intent, selected chunk, local-application journal, acknowledgement, or
publication receipt. The cycle's `publication_receipts` table is empty.

| Company | Inventory | Legacy cursor | Reason direct sync remains held |
| --- | --- | --- | --- |
| Davidson | complete, 46 jobs | 19/19 | Frozen legacy migration; signed approval and exact v2 adoption are separately held. |
| Shield AI | complete, 0 jobs | 1/1 | Legacy local cursor is not remote-delivery evidence. |
| Saronic | complete, 276 jobs | 67/208 | Incomplete legacy local cursor and no exact publication chain. |

Current records are active, unclaimed, retry-disabled, and have no dirty or
conflict fields. No scraper/coordinator/reviewer is alive; retained locks name
absent PIDs and remain untouched. There is no integration-release journal.

## Required future path

Existing legacy plans must remain held. A future exact-v2 recovery must create
a new plan/projection and durable local-application journal; bind source,
input, release, and receipt; fresh-read the three Company control fields
immediately before write; publish and exact-readback under an approved selected
scope; then retain the acknowledgement. A legacy cursor may not be treated as
remote delivery or normalized by selected sync.
