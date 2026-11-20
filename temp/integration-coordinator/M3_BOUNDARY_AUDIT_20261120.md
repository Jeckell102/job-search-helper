# Milestone 3 boundary audit — 2026-11-20

Scope: read-only inspection of the authoritative 2026-11-18 roadmap/QA package,
the current sanitized worktree, and the protected coordinator source. This is a
design/audit record, not M3 completion or activation evidence.

## Current evidence map

| Boundary | Existing implementation/evidence | Assessment |
| --- | --- | --- |
| Deterministic outcomes | `src/job_search_helper/outcomes.py` implements the eight contract outcomes, deterministic precedence, bounded facts, normalized failure fingerprint, and immutable `OUT-` ID. `tests/test_outcomes.py` covers precedence, boundedness, idempotence and release-retry binding. | Good pure foundation; it is not an executor. |
| Durable local outcome ledger | `SQLiteRepository.record_scrape_outcome`, `pending_scrape_outcomes`, and `acknowledge_scrape_outcome` persist/ack immutable records per consumer. `tests/test_sqlite_migration.py` demonstrates consumer-scoped redelivery. | At-least-once local delivery is present, but there is no transaction spanning this DB and coordinator storage. |
| Normal-run producer | `src/job_search_helper/scrape_outcome_producer.py` is called after `_run_scan_with_retries` in `runner.py`. It derives current source revision, storage status and stage, and deliberately classifies non-complete stages as `unknown`, hence `UNCLASSIFIED_HOLD`, rather than inventing a repair. | Safe for post-run repair/retry/coordinator suppression only. It runs after storage, so its reread can prevent stale outcome delivery but cannot prove no stale job write occurred. It lacks richer phase, source-URL, browser-completeness, exception/evidence-reference and deterministic defect-category facts. It has one current normal-run call site; the dedicated retained Company-event exception route has no M3 producer call. |
| Repair intake | Protected `dev/wrapper-coder/tools/coordinator_store.py` has held-only `scrape_outcome_intake`/`repair_intake`, validates canonical outcomes, deduplicates a qualified repair key, attaches repeated evidence, and pauses promotion when the authoritative Company revision no longer matches. `coordinator_outcome_delivery.py` acknowledges only after exact coordinator acceptance; `host_server.py` exposes a bounded drain. | Useful existing coordinator extension, not a second scheduler. It is outside this sanitized application worktree and has no live/runtime proof here. It holds/promotes for review; it must not be treated as unattended repair dispatch. |
| Partial inventory safety | `Engine._finish_company` sets partial state and does not advance `Last Checked`; absence reconciliation occurs only when `inventory_status == complete`. Existing adapter/pipeline tests cover partial preservation and no false closure. | Matches M3's no-unseen-job closure rule. M3 outcome records should preserve this status, not reinterpret partial as complete. |
| Stale source/cancellation | M2 company revisions/outbox emit withdrawals; the bridge cancels only its pending request. Company-only admission/retry paths validate current source revision; coordinator promotion revalidates it. | Strong M2/M5 components exist. M3 must classify currentness before repair/coordinator actions and must not cancel/alter an already-running broader cycle; pre-persistence admission owns stale-write prevention. |

## Contract for the next M3 boundary

1. The ordinary normal-cycle scraper produces one bounded immutable outcome
   **after** its normal durable inventory/storage boundary. Admitted
   company-only production is a later explicit integration slice; the retained
   exception route currently has no producer call. It supplies
   request/company/source/cycle/attempt,
   provider+adapter/release versions, phase, inventory status, source URL,
   browser completeness, and bounded evidence references. Raw response/error
   bodies stay out of identity and payload.
2. Re-read the authoritative Company fact immediately before outcome
   persistence/delivery. Changed, paused, removed, withdrawn, missing, or
   duplicate identity becomes `STALE_OR_PAUSED`; it must not create repair,
   retry, installation, or coordinator delivery. A later revision supersedes
   held work, never mutates its evidence. This post-storage boundary cannot
   promise no stale job write: that guarantee belongs to the existing
   pre-persistence Engine/cycle-admission boundary and needs separate ownership
   and tests.
3. Preserve the classifier order: stale first; then storage/sync receipt
   failure; complete/proven zero; blocked; temporary; qualified regression;
   unknown capability; unclassified hold. `partial`, pending browser URLs, or
   incomplete browser discovery can never be complete or close unseen jobs.
4. The local outcome ledger remains at-least-once. The bridge may acknowledge
   only an exact immutable outcome after the coordinator commits the matching
   durable intake/repair-evidence receipt. Duplicate delivery attaches evidence
   to one active key and never resets budget/owner. Distinct stores require
   crash/retry reconciliation rather than a cross-DB atomicity claim.
5. Only `QUALIFIED_INTEGRATION_REPAIR` with predeclared capability/version and
   explicit defect category can upsert a held repair key. Temporary/blocked/
   unknown/storage outcomes remain their respective retry/hold/reconciliation
   lanes. No M3 code may start an inference worker, install a release, or
   widen a scrape scope.

## Smallest testable next slice

Add a pure, normal-cycle outcome-fact adapter (not dispatcher wiring) that
converts the saved per-company cycle item plus the authoritative Company fact
and exact storage receipt state into `outcomes.classify_outcome` input. Keep
the existing `record_cycle_outcomes` call as its only integration point.

Required offline tests:

1. Ordinary normal-cycle completed inventory produces canonical bounded facts
   and one idempotent local outcome.
2. Partial inventory, pending browser URLs, and incomplete discovery produce a
   hold/temporary outcome and never advance completion/closure fields.
3. Source revision/status changes between storage and outcome record produce
   `STALE_OR_PAUSED` and suppress repair/retry/coordinator delivery. A separate
   Engine/cycle-admission test owner must prove source changes before
   persistence cannot produce stale job writes.
4. Local-save/sync receipt failure produces `STORAGE_OR_SYNC_FAILURE` without
   refetch or repair classification.
5. A declared qualified regression yields one held repair key through a fake
   coordinator receipt; duplicate/reordered delivery attaches evidence, while
   temporary/blocked/unqualified cases create no repair key.
6. Crash after coordinator intake before local acknowledgement redelivers the
   same outcome; crash before coordinator intake leaves it pending. No test
   may assert cross-store exactly-once execution.

## Overlap and open findings

- **M1/F6:** storage vs sync result must come from the exact publication
  receipt; do not infer confirmed storage from a generic cycle stage.
- **M2/F1:** source revision/event/request provenance and bridge cancellation
  are prerequisites; M3 must consume them, not recreate an event queue. The
  M2 admission/Engine boundary, not post-storage M3 recording, owns no-stale
  source job-write protection.
- **M5/F2/F3:** retry attempt/release identity and shared lock/version admission
  are downstream. M3 records/holds evidence only; it cannot create a repaired
  retry or activate a release.
- **M4/F4/F5:** a held repair is not permission to infer or claim a new
  capability. Inference ownership/reconciliation and qualified-family evidence
  remain separate gates.
- **M6/F8:** host drain/supervision is not live operational evidence; retention,
  reconnect and disk-pressure acceptance remain open.

Conclusion: current code supplies a conservative M3 skeleton and held-only
coordinator path, but M3 is not closed. The fact adapter plus the six offline
cases above is the smallest safe next implementation slice.
