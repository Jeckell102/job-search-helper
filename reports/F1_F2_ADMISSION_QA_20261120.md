# F1/F2 admission-boundary QA — 2026-11-20

## Scope

This report records independent source-level QA of two narrow coordinator
repairs. It is not a live-pilot, Sheets, or deployment acceptance.

## F1 stale company-event withdrawal — ACCEPT

Independent QA ran the bridge suite (11/11 passed) and the
dispatcher/handoff/bootstrap group (22/22 passed). The direct stale-event case
proves an older withdrawal cannot remove a newer durable company-only request,
does not change its bytes or event ID, and creates neither cancellation nor
cancelled-request evidence. The stale event returns
`SUPERSEDED_BY_DURABLE_REQUEST`; normal newest-revision watermark processing,
including lost-ack retry coverage, later supersedes it safely.

## F2 repair-retry admission serialization — ACCEPT

Independent QA ran 46 retry/release/controller checks and 31 normal
request/runner regressions. `RepairRetryBridge.deliver` takes the established
normal scraper lock before source revision and active-release validation,
intent handling, and request read/decision/write. QA verified that a stale
source, a rolled-back/replaced release, and lock contention create neither a
partial intent nor a request. Crash/idempotent recovery remains covered.

`release_and_schedule` calls the bridge after `activate_release` exits its
writer-lock context; QA verified no nested-lock path was introduced.

## F2 partial-publication recovery — ACCEPT

Independent QA ran 73 targeted local-pipeline/durable-inbox/retry checks and
43 runner/fresh-request/release regressions. The new regression injects an
ordinary `RepositoryError` after one acknowledged prefix of a release-bound
retry plan. It verifies the frozen plan, cursor (`1`), release-bound receipt,
and saved inventory survive. A later `sync_only` recovery finishes the same
suffix with a fetcher that would fail if called, proving it did not refetch or
replace the plan. Cursor-zero replan/discard behavior and non-retry/ambiguous
paths remain unchanged.

## Boundaries still open

F1 external Sheet/idle-busy proof remains open. F2 outcome-precedence
integration remains open. No Google client,
remote write, global sync, broad scan, old-cycle mutation, automatic release,
or live Samtec action occurred in this QA work.
