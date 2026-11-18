# Independent acceptance: startup session no-op repair

Date: 2026-11-18
Reviewer: final_qa_rollout, independent of implementation.
Verdict: **PASS for the bounded staged repair**. This does not certify a new production installation; a rebuilt candidate, protected rollout, and independent installed checks remain mandatory.

## Exact source

Freeze confirmed before execution. Verified source hashes:

- coordinator_inference.py: `cde3e5b0b079301e48e98e8144691253606da46a238438906e053ff3ede633f2`
- test_startup_session_noop.py: `9cd37b1a971f10f0a27b19a7d31a86ea3cfdd9eb4423b241b2a6f8e0d72a4485`
- coordinator_store.py: `66aebf37b7580bdf674598799762121146405e62f877e47b1159f01731c3e581`

Full host source binding is embedded in `independent-startup-noop-verification.json`.

## Verified behavior

The implementation now closes a session only for a truthy matching session ID, an explicitly open boolean session, and no pending DISPATCHING or UNCERTAIN inference for that task. The previous `None == None` path cannot write a false field into untouched legacy tasks. Already-closed sessions and mismatched or missing owners remain unchanged. A real resolved open owned session closes once; the next recovery is a no-op.

Independently ran **44/44 focused tests**, with ResourceWarnings treated as errors, covering the new startup cases plus inference storage/reservations, coordinator resilience, and healthy in-flight observational status. Log: `independent-startup-noop-tests.log` (6.412 seconds). Tests check actual SQL statements for absent/closed/mismatched owners, retain open sessions for pending/uncertain dispatch, and verify restart converts dispatch to UNCERTAIN without replay or budget reset.

Independently backed up the real disposable migrated rehearsal database `/tmp/wrapper-final-v2-migration-rehearsal/tasks.sqlite3` through a read-only source connection into a fresh temporary directory. The copy contains exactly 111 tasks and 102 campaign registry rows. All 111 tasks initially lack inference_session_open. Two sequential `Store.recover()` calls preserved every table and every stored task JSON string exactly; SQL tracing observed **zero UPDATE/INSERT/DELETE/REPLACE statements** on both calls. Queue/autopilot/campaign remain OFF, pilot unset, and SQLite integrity is `ok`.

Complete database snapshot digest before and after both calls: `1956553684e14d9b7375f299b0de3860eae63e26326bee7fad557f8406399d03`. This digest uses the independent helper's complete table snapshot, including exact stored JSON and sqlite sequence rows; it is not the rollout controller's differently normalized digest.

Reproducible verifier: `verify_startup_noop_independent.py`. Evidence: `independent-startup-noop-verification.json`. No production database, service, source, or inference endpoint was modified or invoked. The installed database parity gate remains unchanged and must pass on the next actual rollout.
