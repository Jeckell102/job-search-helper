# M1-M4 protected production reconciliation report

Status: source-level candidate accepted; not merged, deployed, or activated.

## Authority and boundaries

The protected checkout is `/home/chris/job-search-helper_old`.  Its branch is
`repair/annapolis-static-careers-2026-11-01` at `c9db537`, with extensive
uncommitted user work.  The reconciliation candidate was created only in
`/tmp/job-search-helper-production-reconciliation` from a local source/test
snapshot.  No production file, lock, cycle, job record, Sheet, service, or
Jetson file was changed.

The isolated automation source remains separately backed up on
`codex/integration-automation-20261118`.  This report deliberately does not
publish the protected snapshot or a patch derived from it.

## Collision assessment and resolution

The original automated merge was semantically unsafe despite avoiding textual
conflict markers.  The guarded M1-M4 path collided with protected changes in
the Company-only execution, request, SQLite, and sync boundaries.

The accepted candidate preserves protected behavior while adding only the
missing guarded runtime contracts:

- `company_events.py`: durable, canonical Company-event facts and bounded
  Company-only request bridge.
- `outcomes.py`: conservative classified outcomes with durable repair
  categories.
- `engine.py`: Company-event provenance through recovery and guarded
  interrupted-cycle pause.
- `scan_request.py`: immutable Company-only request validation, safe-boundary
  status, and pure idle/busy measurement.
- `sqlite_repository.py`: atomic Company event/outbox mutation, ordering,
  external reconciliation, and outcome payload persistence, while retaining
  the protected `read_company_columns` behavior.

Protected `runner.py`, `local_pipeline.py`, `sheets_sync.py`, and their
overlap tests were retained unchanged after compatibility review.  Two old
source-only runner assertions remain intentionally incompatible with protected
elapsed-summary and virtual-environment preflight behavior; neither is an
M1-M4 safety contract.

## Independent verification

All checks ran in the local reconciliation worktree with no production state:

- Protected overlap suite: 68 passed (`test_fresh_scan_request.py`,
  `test_runner_cycles.py`, `test_sqlite_migration.py`).
- Durable Company event/outbox/outcome suite: 39 passed.
- The intake lane also ran the source fresh-request/migration suite: 54
  passed.
- Scoped module compilation and `git diff --check` passed.

## Next safe action

Do not mechanically apply this candidate to the protected checkout.  Before a
live M1 pilot, freeze and hash-record the protected source baseline, then
perform an explicit owner-reviewed integration from this reconciliation
worktree.  Rerun the focused suites on that exact integrated source before any
interrupted-cycle recovery, Company-only request, publisher action, or scrape.
