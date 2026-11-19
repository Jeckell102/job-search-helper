# Exact recovery pause executor — independent QA pass

Date: 2026-11-19

Accepted source hash:
`80313980d0f2b2971186b4a0af6299300a2fe8da55a6273c1e63fb5c27b48aa4`

Accepted test hash:
`ecb67551cc1e7488ec9a8ec385745b9dd01f354bd92421e09ff9456f9bb178cf`

## Result

PASS after repairing both blockers recorded in
`EXACT_RECOVERY_PAUSE_EXECUTOR_QA_FAILURE_20261119.md`.

The executor no longer accepts a caller-selected lock path. It requires a
present regular file-backed State database, derives the normal scraper lock as
`Path(state.path).parent / scraper_lock_name()`, and acquires it before
apply-store, State, inbox, journal, or remote access. Independent contention
returned `WriterLockBusy` with zero protected calls. Obsolete lock-path
injection raises `TypeError`.

Every Company entry is now checked individually before batching. The former
small-then-oversized reproduction is rejected. A separate 75-entry probe
produced chunk counts 24, 24, 24, and 3 with canonical UTF-8 payload sizes
481503, 481503, 481503, and 60201 bytes; every chunk is at most 50 entries and
500000 bytes.

The accepted executor also preserves the previously reviewed boundaries:

- fresh phase-A pause-journal revalidation before the first intent;
- one immutable full apply-run freeze before the first remote write;
- exact active, unclaimed, cycle-bound Company controls;
- intent-before-write and readback-only recovery for retained intents;
- exact State finalization with terminal holds and exception counts preserved;
- exact selected Scan Cycles row finalization; and
- no request, inbox, unrelated-row, Engine, or global synchronization path.

Independent QA passed 36 focused tests and a 206-test adjacent regression in
28.11 seconds. `git diff --check` passed. No runner wiring, production access,
or live mutation occurred.

## Remaining boundary

Runner integration must use the accepted public API without a second
acquisition of the non-reentrant scraper lock. Command parsing must require an
exact cycle and explicit bounded Company selection, and the production hold
must remain until runner integration passes independent QA and a fresh
read-only live preflight confirms unchanged scope.

