# Retained publication reconciliation — source-only checkpoint

Status: **source-only repair in progress; not independently accepted,
orchestrated, deployed, or live-proven**.

## Current coordinator checkpoint — 2026-11-19

The only eligible retained-publication direction remains `SessionStore` as the
sealed remote authority and `retained_publications` as local dirty provenance
and FIRST PASS release authority. The ordinary Inbox-backed path is ineligible
for retained M1 and must not be wired into a pilot.

Local verification now covers: no normal State/Inbox creation, normal scraper
lock exclusion, post-readback and post-local-ack crash recovery without replay,
sealed local-value tamper rejection before write, Company-control change
rejection at the write boundary, and a non-empty selected Job History/Job
Evidence FIRST PASS release. It also fixed a multi-table exact-scope defect:
the canonical local row scope and frozen remote projection are now joined by
stable final identity rather than positional ordering.

Latest source-only command: 66 focused retained publisher/session/provenance/
runner/exact-scope tests passed, plus `git diff --check`. This is not
independent QA acceptance. The remaining gates are an independent review of
this pinned diff, lock-domain audit, dedicated Samtec operator provenance and
reservation-only orchestration, then the roadmap's guarded operational
acceptance. No production source, job data, Google state, service, or GitHub
remote changed for this checkpoint.

## Superseding acceptance checkpoint

The SessionStore publisher repair is now the accepted source-only direction.
It has a dedicated publication lock nested inside the normal scraper lock,
strict synchronizer binding, durable pre-dispatch chunk claims, readback-only
retry, exact local acknowledgement, retained provenance confirmation, and
reservation-scoped FIRST PASS release. The ordinary-inbox retained publisher
has been removed.

The final lifecycle blocker is also closed: after durable
`FIRST_PASS_RELEASED` queue evidence is validated, the publisher removes only
the exact frozen preflight embargo row transactionally. This runs in both the
normal and already-released recovery paths. Normal work can resume and the
journal is empty for a later retained company. Independent QA accepted this
repair after 50 focused strict checks; the combined relevant suite passes
250/250.

The previously required source orchestration is now implemented and accepted.
Its non-empty offline acceptance proves matching Job History/Job Evidence,
reservation-scoped FIRST PASS, exact lifecycle settlement, no remote replay on
completed-command retry, and later retained admission reuse. The remaining
activation gates are fresh guarded operational proof, final independent
deployed-system acceptance, and verified scoped backup.

## Current canonical direction

Independent QA rejected the inbox-backed publisher for retained M1 work: it
requires an ordinary `InventoryInbox` exact-plan/receipt authority, contrary
to the retained no-inbox/no-normal-cycle isolation boundary. The SessionStore
route is the only direction eligible for repair because it owns sealed scope,
receipt/intent, and one-shot chunk/readback facts without creating normal
inbox work. The shared `retained_publications` ledger remains the authority for
local dirty provenance and FIRST PASS release state only.

## Quarantined concurrent candidate

This section is retained as history. `retained_session_store.py` and
`retained_work_publication.py` were the repair target. Their post-ack crash and
lock findings have now been repaired and independently accepted. They remain
unreachable from a normal runner command until the explicit orchestration gate
above is implemented and accepted.

## Why the candidates cannot be combined implicitly

The two candidates persist different receipt, intent, cursor, and
acknowledgement facts. Using them together would create competing answers for
whether a remote write is permitted or confirmed. That would violate the
one-shot/recovery boundary. The retained ledger may bind exactly one remote
authority per reservation.

## Required reconciliation decision

Repair the SessionStore publisher's post-ack crash convergence and add a
retained-publication lock before any wiring. Then prove: zero Inbox/State
mutation, changed Company control refusal before write, retained dirty/local
identity tamper refusal, no replay after lost response or post-ack crash, and
a non-empty Job History/Job Evidence FIRST PASS release. Remove or make the
inbox-backed retained publisher unavailable before protected integration.
