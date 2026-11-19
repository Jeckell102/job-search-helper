# Compact Plan Projection QA — 2026-11-19

Status: **STAGED / FAIL-CLOSED — NOT PRODUCTION-READY**

## Scope

This lane changed only:

- `src/job_search_helper/exact_cycle_planner.py`
- `tests/test_exact_cycle_planner.py`
- this report

No production, staging, Google, runner, inbox, publisher, recovery, or Jetson
state was changed.

## Implemented planner contract

The planner now resolves the publication projection from the local
repository's `sheets_profile` and schema. It rejects unknown profiles, unknown
operation tabs, invalid publication schemas, projected-away identities, empty
projected operations, and empty projected plans.

For a supported plan it binds all of the following into `plan_digest`:

- exact publication profile and publication-schema digest;
- full local-operation digest;
- full local operations plus final-State digest;
- exact projected remote-operation digest;
- profile/schema/remote-operation projection digest;
- existing inventory, record, control, and final-State evidence.

Compact projection removes local-only `Companies` and `Job History` fields,
and omits known local-only tabs such as `Job Evidence`. It retains visible
identity, manual-choice, salary, and other expected guards. Source-hash and
other local-only guards remain cryptographically bound in the full local
operation evidence rather than being sent as invalid compact Google headers.

Existing plans without this contract are never migrated in place. In
particular, a retained plan with a nonzero cursor is held as
`existing_frozen_plan_projection_incompatible_nonzero_cursor`, with its plan,
cursor, inventory, and State unchanged.

## Required dual-journal gate

Projection does **not** prove local durability. `_freeze` currently simulates
the full operations against `PlanningRepository`, while `save_plan` creates a
`LOCAL_COMMITTED` receipt without committing those full operations to the
authoritative SQLite repository. Publishing the compact projection at that
point could make Google visible data advance while the full local record and
dirty-row acknowledgement remain uncommitted.

Therefore all new compact no-plan inventories now fail closed as:

`compact_exact_plan_requires_durable_local_commit_journal`

Production enablement requires one lock-owned durable transaction/protocol
that:

1. records the immutable full local operations and their preconditions;
2. commits them to the authoritative local repository;
3. records the exact compact remote projection and both digests;
4. acknowledges only the visible dirty fields owned by that projection,
   without draining unrelated dirty rows or the global outbox;
5. creates `LOCAL_COMMITTED` only after the local commit is durable;
6. recovers every crash boundary without refetch, duplicate publication,
   global replay, or weakening manual-choice, salary, identity, or source-hash
   guards.

Until that contract exists and is independently tested, compact planning is a
deliberate hold, not a deployable success path.

## Test evidence

Focused command:

`PYTHONPATH=src python3.11 -m unittest tests.test_exact_cycle_planner -v`

Result: **PASS — 21 tests**.

Coverage includes compact empty-inventory Company projection, Job History
local-only pruning, retained manual/salary expected guards, source-hash local
evidence binding, full-profile compatibility, unknown profile, identity
removal, empty operation, deterministic projection/schema digests, compact
new-plan durability hold, and nonzero-cursor legacy hold/no mutation.

Adjacent command:

`PYTHONPATH=src python3.11 -m unittest tests.test_exact_cycle_planner tests.test_exact_cycle_sync tests.test_exact_cycle_recovery tests.test_exact_recovery_terminal -v`

Result: **75 passed, 7 failed (82 total)**.

The failures are expected integration gates, not a focused planner regression:

- six recovery expectations still assume newly generated plans can publish;
  five reach publisher rejection `sealed_plan_digest_invalid` because the
  concurrently owned publisher has not yet adopted the new projection seal,
  and compact-profile fixtures now correctly hold before planning;
- one dependency-lifetime expectation sees the retained inventory because
  publication did not confirm.

The coordinator/publisher lane must adopt and validate the same seal before a
full-profile plan can publish. Compact no-plan publication must remain held
even after that publisher change until the dual local/remote durable journal
above is implemented.

