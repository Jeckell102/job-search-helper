# Company intake port — current-source snapshot

## Scope

This source-only port adds a default-disabled Company-event intake bridge to the
current sanitized snapshot. It does not activate a service, access Google, or
change a protected/live checkout.

## Decision

After a successful bounded `sync watch` cycle releases `writer.lock`, the
existing watcher performs one nonblocking intake tick. `once` never does this.
The durable control is disabled unless the local operator runs
`intake-enable`; `intake-status` and `intake-disable` use the same local
journal.

The dispatcher uses the existing Company-event bridge and invokes only the
public `job-search-scraper start` lifecycle. It makes no alternate scraper or
storage path. It holds when normal scraper/controller/retained/release guards
are busy. Durable request identity and a workflow handoff bind the event,
single company, revision, request id, and full request digest before a scrape
workflow starts. An unfinished exact workflow resumes only through the public
resume path; unrelated, malformed, or ambiguous workflows hold safely.

## Verification

Focused dispatcher, handoff, watcher, Company-event bridge, and scrape-first-
pass tests are run with warnings treated as errors. The tests cover disabled
default, durable controls, writer-lock release ordering, once exclusion,
holds, duplicate/restart recovery, failed child retention, exact paused resume,
forged handoff/request rejection, and intake error isolation from sync backoff.
