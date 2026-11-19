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
- Existing operations: 233 total, 92 reflected by the retained local-apply
  cursor and 141 not yet locally applied
- Not-yet-locally-applied by tab: Companies 1, Job Evidence 66, Job History 73,
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
- Local-apply cursor: 19 of 19
- Google presence: not yet verified
- Maximum possible Google operation objects if the current remote rows are
  missing or differ: 19
- Inventory result: complete

Important correction: the retained cursor records durable application to the
local SQLite staging database. It is not proof that Google received those
operations. In addition, this is a pre-seal legacy plan. The newly installed
publisher correctly refuses it with
`publication_projection_version_invalid` before Google access; the following
command must therefore **not** be run yet:

```text
./job-search-scraper sync --cycle-id CYC-B639C6D864EC --company-id COMP-0035
```

The next safe live stage is instead a read-only selected-row preview. It must
read only Davidson's current Company controls and the exact rows named by the
19 frozen operations, perform no commit, create no receipt, and change no
local state. That preview will determine whether zero or as many as 19 remote
operations would be needed and will supply the evidence for an explicit
legacy-plan migration design. Any mismatch, remote edit, missing row,
ambiguous identity, changed Company control, lock contention, unavailable
Google connection, or invalid legacy operation must stop without mutation.

This approval would not authorize processing another Company, the remaining
141 pending operations, a fresh scrape, a service restart, lock deletion,
queue release, Jetson modification, or the final new-Company demonstration.

## Later stages, not yet authorized

- `COMP-0052` (Shield AI): one frozen operation and local cursor 1, with zero
  saved jobs. Remote presence remains unverified.
- `COMP-0054` (Saronic Technologies): 208 frozen operations, local cursor 67,
  141 operations not yet locally applied, and 276 saved jobs. Remote presence
  remains unverified and any migration/publication requires its own approval.
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
