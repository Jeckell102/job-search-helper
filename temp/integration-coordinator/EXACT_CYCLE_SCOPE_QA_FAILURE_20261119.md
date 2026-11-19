# Exact-cycle sync scope QA failure — 2026-11-19

## Result

**REJECTED.** The first source hardening candidate is not safe for a live
reconciliation of `CYC-B639C6D864EC`.

## Verified defect

Although `runner.py` selects and validates the named durable inbox cycle, its
exact-sync path still enters `run_scoped_sync(...)`. That helper starts the
normal synchronization worker, which performs a global remote pull and a
startup publication before the named inventory is processed. Consequently a
command that promises to reconcile only the named cycle could import or
publish unrelated workbook/local changes.

The focused exact-cycle test also had an incorrect expectation for the number
of durable inbox cycle lookups, so it did not reliably prove the intended
isolation boundary.

## Safety consequence

No live `sync --cycle-id CYC-B639C6D864EC` has been run. The 42 unblocked
inventories, eight frozen plans, five holds, locks, queues, and all unrelated
backlog state remain untouched.

## Repair assignment and acceptance criteria

The coordinator/release lane must replace or narrow this startup path so an
exact-cycle command cannot perform a global pull or startup/global publish.
It must explicitly prove that it also skips global cleanup, manual-opportunity
work, review lifecycle/export, outcome delivery, and any unnamed-cycle
fallback. The revised tests must assert those exclusions and preserve a safe
failure for a missing or racing exact cycle. Independent QA must accept the
repair before any operational command is considered.

## Independent QA delivery boundary

The local SQLite repository commit used by the ordinary pipeline is a durable
local outbox write, not Google Sheets delivery. The repaired path may not
mistake a local readback for a confirmed remote publication. Success therefore
requires a fresh remote readback limited to the frozen plan's own identities
and owned fields, after a remote guarded write containing only those frozen
operations. A second unrelated cycle and an unrelated dirty local outbox row
must remain byte-for-byte/semantically unchanged in the test fixture.

Timeout, conflict, or uncertain acknowledgement must retain the exact named
plan, cursor, and receipt as pending; it must not fetch, replay automatically,
or acknowledge any inventory. A matching selected-row remote readback is the
only condition that may advance or acknowledge the named plan.
