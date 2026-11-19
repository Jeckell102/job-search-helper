# Current inbox promotion design for selected legacy recovery — 2026-11-19

## Review result

Independent current-baseline review rejects extending
`exact_legacy_plan_migrations` for selected prefix/suffix recovery.  Its
existing invariants intentionally require a fully settled original legacy
stream before it may create a v2 local state or replace a saved plan.  Reusing
that journal for a partial prefix would weaken the retained-cycle evidence.

## Required additive boundary

Add a dedicated `exact_selected_legacy_recoveries` inbox table keyed by exact
cycle and Company. It records the immutable signed authorization identity,
original legacy plan/inventory/workbook pins, verified prefix and suffix
evidence, protected-field conflict evidence, successor plan and local
application evidence, and a monotonic state:

```text
FROZEN -> PREFIX_VERIFIED -> SELECTED_LOCAL_VERIFIED
       -> V2_PLAN_FROZEN -> REMOTE_PLAN_FROZEN
```

The begin method must reject changed/blocked inventory, changed source plan or
cursor, receipt/local/remote/chunk ownership, a competing all-complete legacy
migration, bad scope/digest/signer evidence, duplicate resolved targets,
unapproved protected drift, and changed local controls or snapshot.

The promotion method must run inside the local writer transaction. It must
revalidate the source and signed evidence, atomically replace only the named
saved legacy plan with the sealed successor v2 plan, persist the ordinary
`LOCAL_VERIFIED` state, and then expose it to the existing exact-v2 receipt,
intent, exact-readback, acknowledgement, and cleanup path. It must not create
a receipt or invoke Sheets/Google itself.

## Current compatibility facts

- `exact_legacy_migration._legacy_shape` and
  `InventoryInbox.begin_exact_legacy_migration` require the legacy cursor to
  equal its entire operation count.
- `adopt_verified_legacy_local_plan` and
  `freeze_exact_legacy_successor` have the same all-complete assumption.
- A selected-recovery record must never coexist with any current exact local,
  remote, receipt, chunk, or all-complete migration ownership for its Company.
- Cleanup must refuse a nonterminal selected recovery and archive terminal
  selected-recovery evidence alongside the existing migration evidence.

## Required verification

Use a valid external signer and show exact v2 local verification followed by
the unchanged v2 receipt/readback/acknowledgement path. Negative coverage must
include signer/canonicalization/scope/cursor/payload/workbook drift, target or
field overlap, snapshot/control/protected-guard drift, competing ownership,
crash/retry idempotence, no receipt before promotion, and unchanged existing
all-complete migration behavior.

No protected source, job data, queue, scraper, lock, Google connection, or
remote write changed while producing this design.
