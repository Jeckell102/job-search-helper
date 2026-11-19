# Live Google recovery approval packet

Prepared: 2026-11-19. This packet records read-only local evidence and a
narrow proposed live action. Nothing in this preparation accessed Google or
changed scraper, database, queue, lock, service, review, or Jetson state.

## Current blocker

- Exact cycle: `CYC-B639C6D864EC`
- Current state: `SAVED_WORK_MUST_BE_PUBLISHED_OR_RECONCILED`
- Saved Company inventories: 47
- Saved jobs: 11,313
- Inventory results: 28 complete, 11 partial, 5 blocked, 3 unsupported
- Existing publication plans: 8
- Existing operations: 233 total, 92 already applied, 141 pending
- Pending by tab: Companies 1, Job Evidence 66, Job History 73,
  Opportunities 1
- Exact ordered Company-ID digest:
  `27d5a39e7d0c165428be1fdc58ca31cb3bca9e66687ed4d80c1239dd50b48fe6`
- No Company-only request is pending, and no scraper, coordinator, publisher,
  or managed-review process is running.

The recovery assessment is read-only and refuses to pause or bypass this
cycle until every saved inventory and plan is either published or explicitly
reconciled.

## Proposed first live stage

Use only Company ID `COMP-0035` (Davidson Technologies) in exact cycle
`CYC-B639C6D864EC`.

Authoritative local facts:

- Saved jobs: 46
- Frozen operations: 19
- Operations already applied: 19
- Pending Google writes: 0
- Inventory result: complete

The exact action, if separately approved, is:

```text
./job-search-scraper sync --cycle-id CYC-B639C6D864EC --company-id COMP-0035
```

Expected behavior is Google readback and confirmation of only the 19 already
applied Davidson operations, followed by local acknowledgement and cleanup of
only Davidson's saved plan/inventory. A mismatch, remote edit, missing row,
ambiguous identity, changed Company control, lock contention, unavailable
Google connection, or uncertain confirmation must stop the action without a
new Google write or broader cleanup.

This approval would not authorize processing another Company, the remaining
141 pending operations, a fresh scrape, a service restart, lock deletion,
queue release, Jetson modification, or the final new-Company demonstration.

## Later stages, not yet authorized

- `COMP-0052` (Shield AI): one operation already applied, zero pending, zero
  saved jobs. It is another readback-only candidate after Davidson succeeds.
- `COMP-0054` (Saronic Technologies): 208 frozen operations, 67 already
  applied, 141 pending, and 276 saved jobs. This is the only existing plan
  with pending Google writes and requires its own explicit approval.
- The other 39 unplanned, unblocked inventories contain 10,987 saved jobs.
  They require narrow current-Company control checks and frozen exact plans
  before any write payload can be approved.
- Five blocked plans and the remaining blocked/unsupported inventory require
  explicit reconciliation rather than being silently treated as completed.

## Completion boundary

Recovering Davidson is an operational safety proof and reduces the retained
blocker by one Company. It is not project completion. Full completion still
requires a newly added eligible Company to trigger one Company-scoped scrape,
wrapper construction when needed, safe Google publication, and managed FIRST
PASS startup, followed by final independent acceptance.
