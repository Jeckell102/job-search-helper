# F2 retry-outcome provenance QA — 2026-11-20

## Verdict: ACCEPT (source boundary only)

The retry outcome adapter now records an outcome only when its stored cycle
has the exact `company-retry:<attempt>` request ID, the single admitted
Company scope, and a canonical immutable retry/release binding. It records
the fresh attempt ID, failed predecessor request ID, release ID, and full
release-binding digest.

Independent QA first rejected the candidate because a missing, unrelated, or
predecessor request ID could be recorded. The narrow repair invokes
`validate_retry_request` at outcome creation and adds explicit rejection
coverage. QA accepted the repaired boundary: missing/unrelated/predecessor
IDs, multi-company scope, changed source/release facts, and malformed lineage
are skipped; fresh source drift becomes a durable `STALE_OR_PAUSED` audit
record, which the repair-coordinator consumer cannot receive. Event, operator,
and recovery paths remain excluded.

Evidence: QA ran 53 focused checks plus nine adversarial cases and a disposable
SQLite stale-exclusion check. Coordinator regression group: 103 passed in
10.14 seconds.

This is not F2 completion, a deployed release, or authorization to dispatch a
repair. It only records bounded immutable outcomes.
