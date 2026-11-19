# Exact-cycle combined orchestrator — independent QA failure

Date: 2026-11-19

Affected candidate: uncommitted
`src/job_search_helper/exact_cycle_recovery.py` and focused tests.

## Result

REJECT for activation.

The candidate accepted a caller-provided `writer_lock_assertion` and treated a
literal `True` result as proof of lock ownership. That assertion was forgeable;
the focused real-path tests themselves used `lambda: True`. A future runner
could therefore call the combined planner/publisher path while the normal
scraper writer was active, allowing State, inbox, or whole-cycle checkpoint
races.

## Required repair and acceptance evidence

The public activation path must either acquire the real normal scraper/writer
lock itself or accept only a non-forgeable capability owned by a runner that
already holds that exact lock. Add a contention test proving that, while the
normal lock is held elsewhere, the recovery call fails before any State,
inbox, or remote access. Caller-controlled booleans and callbacks are not
acceptable evidence.

All other reviewed component behavior passed: explicit unique one-to-five
Company selection, all-selected local preflight before remote access,
per-Company plan/publish ordering, crash recovery without replay, selected-only
isolation, preservation of unrelated cycle/request/local dirty/outbox state,
and absence of global synchronization wiring. The focused combined set passed
68 tests in 2.408 seconds. Those results do not waive the lock defect.

No runner wiring, production activation, Google write, or live recovery was
authorized or performed.
