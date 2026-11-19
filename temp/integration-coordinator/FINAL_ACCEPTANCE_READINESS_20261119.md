# Final acceptance readiness — 2026-11-19

This is a read-only readiness record. It authorizes no Google access, scrape,
repair, release, FIRST PASS, lock deletion, or Company/Job change.

## Frozen cases

| Order | Company | Source structure | Required result |
|---|---|---|---|
| Hold control | COMP-0072 General Atomics Aeronautical Systems | BrassRing parent and multiple boards | Continue safely without widening or writing if legal-entity and complete-membership proof is absent. A hold is not a completed company. |
| Completion candidate | COMP-0066 Forterra | Rippling tenant board | Proceed only from a fresh version-pinned configuration defect and current Company revision. Run the PDW shared-adapter regression immediately after any change. |
| Completion candidate | COMP-0164 Allen Control | Greenhouse stale tenant/API | Proceed only if fresh official tenant and employer-scope evidence succeeds. |
| Regression control | COMP-0178 PDW | Shared Rippling adapter | Must remain unchanged after any Forterra repair. It is a regression check, not a substitute completion. |

The set must not be silently substituted. If the General Atomics case remains a
hold, the roadmap still needs a third independently approved completion case or
an explicit scope decision; safe hold behavior alone does not satisfy three
completed Companies.

## Current blockers

- The automatic repair profile registry is empty. No Company is currently
  qualified for automatic repair promotion.
- The Jetson F4 synthetic HTTP transport-recovery sub-gate is independently
  verified with limits: its authoritative sanitized receipt shows the real
  synthetic request interrupted, observed `UNCERTAIN`, and settled `FAILED`
  without replay; both services and the deployed hashes were independently
  rechecked. This closes F4 only. It does not authorize broad inference,
  recovery, release, or final acceptance. See
  `F4_LIVE_PROOF_VERIFICATION.md` and `COORDINATOR_STATUS.md`.
- The local publisher is not ready for an interactive Google session: its
  read-only status reports one pending `Opportunities` `Last Checked` cell and
  21 protected remote-edit conflicts. The pending cell and every conflict must
  be reconciled or explicitly retained under the normal safeguards before any
  bounded publisher/readback. Current public-source evidence also remains open.
- A bounded read-only workbook inspection confirmed that the 20 held
  `Opportunities` `Salary / Range` conflicts contain independent remote values;
  at least one is field-inappropriate content rather than a salary value. The
  remaining conflict is a missing remote `Companies` row. These are protected
  user-data discrepancies, not a permission to bulk-import, clear, restore, or
  overwrite any value. They require an owner-approved, record-by-record
  reconciliation decision.
- Historical broad in-progress cycles remain recorded. A company-only run is
  unsafe until the exact recovery contract and current scope guards are
  reviewed.
- Three protected lock records name absent PIDs: scraper `485601`, writer
  `634767`, and scrape/FIRST-PASS controller `283795`. A fresh process check
  found no matching PID. These records remain untouched; never delete or
  bypass them without an owner-reviewed recovery procedure.

## Read-only protected-state snapshot

Independent QA refreshed this snapshot on 2026-11-19. No scraper,
coordinator, review, or publisher process is active. Coordinator controls are
disabled (`autopilot`, campaign, and queue), and the automatic profile registry
is empty. The latest saved broad cycle, `CYC-B639C6D864EC`, remains
`In Progress` with an 800-company scope; it has 47 inventories, eight
partially applied sync plans, five blocked inventories, and a stale `RUNNING`/`SCRAPING`
controller workflow whose owner PID is absent. It is retained recovery
evidence, not a live process. Nineteen historical cycles are also recorded as
`In Progress`. These facts authorize neither recovery nor a new run.

The sole pending delivery is the `Last Checked` update for a Saronic
Technologies opportunity. It is blocked because the same row has a protected
  remote `Salary / Range` conflict; the remote value is retained and the local
  delivery receipt is absent. The normal publisher correctly refuses to send a
  partial row around that conflict. The permitted owner choices and required
  guarded evidence are defined in
  `PUBLISHER_RECONCILIATION_DECISION_RECORD_20261119.md`.

## Guarded sequence

1. Reconfirm installed hashes and rollback, host `ACTIVE`, queue/campaign off,
   no active task/open receipt, and unchanged supervision counts.
2. Preserve the accepted F4 evidence and reconfirm its services/hashes only if
   a later gate needs it. Do not infer broader authorization from that proof.
3. Identify and safely reconcile or explicitly retain the one local pending
   publisher receipt and 21 protected conflicts. The remote salary conflicts
   require owner-approved, record-by-record handling; do not bulk-import or
   overwrite them. Only then request interactive Google authorization for a
   bounded normal publisher/readback; do not start a scrape.
4. Freshly verify Company ID/revision, employer scope, source access,
   pagination and detail coverage for all frozen cases and PDW. Source drift or
   access failure becomes an explicit hold.
5. Reconcile local cycles, request identities, lock ownership, outboxes, sync
   health and the current profile registry without changing them.
6. Owner-review the exact broad-cycle recovery contract. Apply it only if
   every identity and scope guard passes; never remove locks as a shortcut.
7. Record expected Company/config/adapter/release identities and each stop/hold
   condition before any inference or scrape.
8. Exercise the General Atomics hold first. Then Forterra only if it qualifies,
   followed immediately by PDW regression. Then Allen only if official scope
   proof qualifies it. Capture local and confirmed Sheets receipts, complete
   descriptions, stable reread, managed FIRST PASS start, restart/duplicate
   behavior, pause and rollback evidence at every boundary.

A failed preflight or hold is preserved as evidence and stops that case. It
does not earn repair or completion credit.
