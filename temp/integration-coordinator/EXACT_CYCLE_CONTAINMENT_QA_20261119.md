# Exact-cycle containment QA — 2026-11-19

## Result

**PASS — containment only.** The protected MuleLab source now makes
`sync --cycle-id <ID>` a safe hold rather than a broad recovery operation.

## Protected source boundary

In `/home/chris/job-search-helper_old/src/job_search_helper/runner.py`, the
command calls `validate_exact_sync_cycle(...)` and then returns before
`get_repository(...)`. The validator uses read-only cycle/inbox access. This
prevents Google repository creation, the global `run_scoped_sync` pull/startup
publisher, review lifecycle, closed-job cleanup, manual-opportunity intake,
engine/local pipeline processing, and coordinator outcome delivery.

The hold message explicitly says that no inventory, workbook, review, or
coordinator change was applied. The named cycle is intentionally untouched.

## Verification

Independent QA ran in the protected source:

```
PYTHONPATH=src:tests python3.11 -m unittest discover -s ../tests -p test_runner_cycles.py
```

Result: **16 tests passed**. The added `ExactSyncContainmentTests` fixture
builds a real temporary active cycle and durable inventory, invokes named
sync, and proves repository creation is never reached.

## Limits and next action

This is not an exact remote recovery implementation. It has no selected
Google write or selected remote readback, so it cannot advance inventory,
plan cursor, or receipt. The 42 unblocked saved inventories and eight frozen
plans remain held; five manual holds remain held. A future recovery design
must use frozen identity/expected guards and a selected-row remote readback,
while proving unrelated local dirty rows, other cycles, and workbook rows are
untouched.

## Dirty-tree boundary

The protected tree was already broadly dirty. The containment change is
limited to `runner.py` immediately after exact read-only validation and one
new focused test block. It must be backed up through a scoped release manifest
rather than represented as a clean wholesale production diff.
