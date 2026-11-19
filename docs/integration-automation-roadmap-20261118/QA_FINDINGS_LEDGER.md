# Integration automation — QA findings ledger

Updated 2026-11-18. This is the current finding register alongside `AUTOMATION_ROADMAP.md`. The two QA reports preserve the original assessments. Document readiness is separate from runtime readiness. No runtime findings have been closed by this documentation update.

## Status and ownership rules

The coordinator assigns a named worker before dispatch; the roles below are planned ownership, not claims that workers are active. Record each finding's contract decision, implementation version, test/live evidence and independent reviewer here or in a linked receipt. Use OPEN, CONTRACT_RECORDED, IMPLEMENTED_AWAITING_QA or VERIFIED_CLOSED. A contract permits dependent implementation; it does not prove the behavior. Do not reset budgets or discard earlier failed evidence when work resumes.

All F1–F8 require verified closure for final unattended qualification. Resolve each contract before workers implement its affected boundary. Scoped Milestone 1 may start while F6/F7 are designed, but cannot pass its exit gate until those findings are verified for that path. If later milestones change a closed contract, revalidate its affected acceptance checks.

| ID | Status | Accountable role | Boundary / gate | Required acceptance evidence |
| --- | --- | --- | --- | --- |
| F1 | OPEN | Intake/storage worker; coordinator approves contract | Company revisions and event delivery; M2 | Same-transaction outbox for supported mutations/imports; external reconciliation; bootstrap catch-up; crashes before/after cross-store acknowledgement; duplicates and reordered revisions produce one logical request without loss. |
| F2 | OPEN | Intake/storage worker | Repaired retry identity and stale-result precedence; M5 | Distinct request/attempt/source/release identity; preserved pending inventories and publication cursors; retry cannot consume the failed inventory; install-before-retry crash and stale-result arrival recover safely. |
| F3 | OPEN | Repair/release worker | Shared scraper/release admission; M5 | Recorded lock ownership/order and full version pinning; concurrent startup/activation/rollback tests prove each attempt uses a complete old or new version; no mixed code/config/dependencies. |
| F4 | OPEN | Repair/release worker | Unknown inference reconciliation; M4/M6 | Durable request identity and ownership generation; disconnect after model start; reconcile retained result or acknowledged cancellation; no duplicate/overlapping inference or lost/double budget accounting; resume another company only after safe resolution. |
| F5 | OPEN | Coordinator with repair worker and independent QA | Supported capabilities and acceptance matrix; M4/M6 | Named cases fixed before qualification, including at least three unfinished companies with distinct source structures and a shared-adapter regression; explicit permitted repair types/model contribution; no per-company manual code supplied during the automatic acceptance run; unsupported capability held honestly. |
| F6 | OPEN | Intake/storage worker | Exact local-save/sync completion; M1/M5 | Request/company/source/release/record-bound LOCAL_COMMITTED, SYNC_PENDING and SYNC_CONFIRMED receipts; one real confirmed sync; lost write acknowledgement safely reconciled without rescanning or overwriting manual decisions. |
| F7 | OPEN | Intake/storage worker | Scoped scheduling while normal cycle active/paused; M1 | Explicit safe boundary, blocking-cycle/queue-age visibility, measured idle/busy start target and paused-cycle recovery policy; no implicit full scan, lock deletion, silent starvation or supersession of current work. |
| F8 | OPEN | Repair/release worker with independent QA | Supervised operation and evidence retention; M6 | Boot/reconnect catch-up, one owner, pause/shutdown, disk-pressure tests; no lost requests or premature cleanup of unacknowledged events, active releases or recovery receipts; maintained runtime DB on MuleLab. |

Detailed rationale and failure scenarios: `ROADMAP_QA_AND_APPROACH_COMPARISON.md`. Every finding needs an independent QA reviewer separate from its implementation owner; the coordinator integrates evidence and updates the restart card.

## Documentation findings

- H1 — VERIFIED_CLOSED (documentation only): The old handoff omitted the QA gates. Corrected by requiring both reports and this ledger, recording open findings in the reset card, and linking boundary contracts and closure evidence to implementation gates. Independent document review verified agreement on 2026-11-18; see `FINAL_ROADMAP_QA.md`.
- H2 — VERIFIED_CLOSED (documentation only): “Unsupported company” ambiguously meant both automatically repairable and requiring engineering. Corrected throughout the roadmap/handoff: a missing/broken integration within a qualified capability is the automatic repair case; an unqualified capability is a separate engineering-hold test. Independent document review verified the distinction on 2026-11-18.

## Architecture decision

The updated roadmap adopts the hybrid recommendation: existing Python coordinator and normal storage/routing, immutable validated configurations for qualified executor capabilities, reviewed engineering for new capabilities. Prototype one compatible family; record evidence before invoking the constrained-source-template fallback. No new queue or adapter-library replacement is required. No automatic family is certified by this document.

## Acceptance matrix checkpoint

Not yet populated. The coordinator must inspect the current backlog and create `ACCEPTANCE_MATRIX.md` in this folder before general-loop qualification, recording named company IDs, source structures, current failures, allowed repairs, expected AI contribution, storage expectations and escalation boundaries. Do not infer candidates from stale counts. Samtec may prove the known-good Milestone 1 storage path; it does not count as a currently unfinished integration unless fresh evidence establishes a new defect and the case is declared in advance.

No implementation workers are assigned by this document. Next action: fresh read-only state reconciliation, assign Milestone 1 implementation/QA ownership, and record F6/F7 contracts.
