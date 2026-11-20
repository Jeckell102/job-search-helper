# Independent QA — M3 ordinary normal-cycle outcome slice

**Verdict: ACCEPT at source/test level only.** This does not close Milestone 3,
F6, live acceptance, the company-only producer route, coordinator automation,
or any release/activation gate.

## Accepted behavior

- Ordinary normal-cycle assignments save a bounded Company source revision in
  durable cycle state. The F6 inventory-inbox payload remains byte-compatible;
  M3 provenance is not added to receipt-bound inbox bytes.
- Completed, partial, browser-incomplete, storage-pending, verified-zero,
  legacy-provenance-missing, and post-storage stale outcomes classify
  conservatively from saved facts.
- A stale outcome keeps the frozen work revision as immutable identity and the
  fresh Company revision as separate comparison evidence. It is durably
  retained for audit, withheld from the reserved `repair-coordinator`
  consumer, and cannot be directly acknowledged by that consumer.
- `Pause`, `Paused`, `Remove`, `Removed`, and `Withdrawn` are all stale states.
- Current/actionable outcomes keep their prior canonical shape and deterministic
  IDs; stale-only comparison evidence cannot break coordinator compatibility.
- Serial, parallel, and local-pipeline assignment paths retain the source fence;
  serial and parallel paths both retain browser-pending and incomplete-
  discovery evidence.
- Company-event, operator, recovery, and repaired-retry cycles remain excluded
  from this first ordinary-cycle-only slice.

## Independent and coordinator verification

Independent QA passed 146 focused/adjacent checks plus direct stale, reserved-
consumer, Boolean-limit, status-spelling, and compatibility probes. The
coordinator reran a wider changed-boundary matrix: **266 passed in 54.18s**,
followed by a clean `git diff --check`.

Reviewed SHA-256 values:

- `engine.py`: `018ac01e1c76b69e8839ba077af46415d3ebc0ed001bcb1fa7376a1cb66658cf`
- `local_pipeline.py`: `13902c45e05c38ab6f71b1c8d9bae3b573615904f94afae382d778e27aa5011c`
- `outcomes.py`: `41dce85793127f31008f172ed6d381456ec76f39b2b3b569c49b8d9e24116c56`
- `scrape_outcome_producer.py`: `ae33df3ab71dd529ce92654222be44e0fa2d026d75f54a90946d151d9857ae84`
- `sqlite_repository.py`: `d809347a4c8d8fffc3ac4b59cd72ba45da9a8074c9820cc3e01e2006a36a6201`

## Explicit remaining work

The runner still supplies a generic cycle-level `storage_confirmed` signal;
that is not the exact per-company F6 publication receipt required for closure.
This slice is post-storage and therefore cannot prove that stale source changes
were prevented before job writes. The pre-persistence admission owner and test,
company-only outcome call site, bounded failure-fact capture, coordinator
delivery/retry behavior, and live acceptance remain separate work.

No protected checkout, service, Google, database, request, cycle, credential,
lock, raw-job, or Jetson state was changed while developing or reviewing this
slice.
