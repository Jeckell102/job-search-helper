# M3/M2 pre-persistence stale-source and job-write audit — 2026-11-20

Scope: read-only audit of the sanitized current source and the authoritative
2026-11-18 integration roadmap/QA package. This is not M3/F6 closure, a code
change, host activation, or live-state evidence.

## Conclusion

The current code has good *post-storage* stale suppression and narrow
company-only request identity, but it does **not** yet have one shared
pre-persistence source-revision fence for all ordinary source-derived writes.
`outcome_source_revision` is durable cycle evidence, not admission authority.
The smallest safe next slice is a normal-cycle-only, ephemeral companion
Company guard attached to every commit attempt that writes staged jobs,
absence/missing closure, or Company completion fields. It must hold/reconcile
saved inventory on mismatch; it must not refetch, delete a request, alter a
newer request, or claim F6 synchronization.

## Existing evidence and what it proves

| Boundary | Current source/evidence | What it does prove | What it does not prove |
| --- | --- | --- | --- |
| Company fact | `company_events.canonical_company_fact` and `source_revision` bind Company ID, status, canonical careers URL, and ATS/source. Repository revision/outbox rows bind M2 events to that digest. | A relevant source change has an immutable comparison value; bridge requests carry it. | It does not automatically make an ordinary cycle's later job writes conditional on that value. |
| Company-event request | `CompanyEventBridge` atomically writes/readbacks an event-bound request and records a cancellation instruction; `scan_request._read_request` validates request/event identity. | Pending bridge work is one-company, immutable, idempotent, and a withdrawal cancels only an unadmitted bridge request. | Once a cycle begins, cancellation deliberately does not stop it. A company-event request has no current-fact revalidation in `Engine.start_cycle` comparable to operator/retry admission. |
| Serial engine | `Engine.resume` checks status/claims before fetch, saves `outcome_source_revision` after fetch, and `_stage_inventory` refreshes Company before every batch but only checks board URL. `_reconcile_absences` directly writes missing/closure changes, and `_finish_company` directly writes completion/Last Checked fields. | Pauses/removals and claims caught by `refresh_company` stop a staged batch; a careers URL replacement is rejected. | ATS/status source changes after fetch, or in the read-to-commit interval, can still write jobs, missing/closure state, or completion fields; saved revision is not compared. |
| Parallel engine | `resume_parallel.refill` freezes revision before worker fetch; the single writer rereads status/claims before `_stage_inventory`, then calls direct absence reconciliation and completion writes. | The serial writer owns Sheet writes; queued assignment captures M3 provenance. | It never compares the reread to the frozen revision, so changed ATS/source or an active-but-changed Company can write jobs, closure/missing state, or completion fields. |
| Local/deferred pipeline | `LocalPipeline.run` captures `outcome_source_revision` beside cycle state; `upload` refreshes status/claims and checks requested board; sync-only shares this route. `InventoryInbox` preserves payload/plan/receipt. | Deferred inventory remains durable; paused/claimed/board-changed work is withheld; F6 receipt planning/recovery is preserved. | A changed ATS/source with the same board, or a source change after upload's refresh and before commit, can publish saved jobs. `LocalPipeline._receipt_details` records a revision for receipt attribution but (outside repair-retry) does not validate it against current Company state. The F6 plan/payload/receipt/cursor must not be rewritten to solve this. |
| Recovery | Serial/parallel `inventory` state and local durable inbox resume into the same staging/upload paths. `sync_only=True` skips fetch and uses `LocalPipeline.upload`. | Existing inventory/cursors are retained and can resume without unnecessary refetch. | The same missing source-equality fence applies to recovered inventory and sync-only publication. |
| M3 recorder | `scrape_outcome_producer.normal_cycle_outcome_facts` compares frozen `outcome_source_revision` with a post-run Company reread and records `STALE_OR_PAUSED`; the accepted QA says this is ordinary-cycle-only. | Stale evidence is retained and withheld from repair-coordinator delivery. | It runs after storage and cannot prove that stale jobs were not already written. |
| F6 receipt | `LocalPipeline.upload` marks `SYNC_PENDING`, then exact readback/reconciliation controls cursor advance; the authoritative F6 ledger describes exact request/company/source/release/record identity. | Ambiguous publication does not blindly replay or discard frozen plans. | Receipt identity is not a substitute for pre-write source admission. Current M3 runner call also uses a generic cycle-level `storage_confirmed`, not exact per-company F6 confirmation. |

## Exact race windows

1. **Bridge request written -> `requested_scan`/`Engine.start_cycle`:** the
   request remains internally self-consistent, but a newer Company revision can
   exist before admission. Repair-retry and operator requests revalidate their
   source revision in `Engine.start_cycle`; company-event requests currently
   only carry it. The bridge's later withdrawal cannot cancel an active cycle
   by design.
2. **Serial: assignment check -> fetch -> revision capture:** serial records
   its M3 revision from the pre-fetch Company object. A changed URL is caught
   at staging; a changed ATS/status is not equality-compared to the frozen
   fact.
3. **Serial: `planner.refresh_company` -> `base_repo.commit`:** status/claim
   and board checks precede planning, but planned Job History/Evidence writes
   have no Company-fact expected guard in the fresh commit preflight.
4. **Final staged job batch -> absence reconciliation -> completion:** after
   `_stage_inventory` returns, `_reconcile_absences` can write missing/closure
   state and `_finish_company` can write Last Checked/success/completion fields
   before any fresh source equality test. A change in this interval must fence
   *all* three write types and must retain inbox/request state.
5. **Parallel: `refill` snapshot/revision -> worker fetch -> single writer:**
   assignment freezes the revision, but completion/staging does not compare
   it to the writer's current Company row.
6. **Local deferred: inventory save -> later `sync_only` plan/upload:** source
   fields can change for hours/days; `upload` checks pause/claim/board, not
   the original source digest. The same gap exists after an interrupted upload
   before a resumed frozen-plan commit.
7. **Any fresh-read -> Sheets write:** repository preflight fresh-reads
   identities/review controls, then issues a batch update. A source guard can
   make a preflight mismatch fail before job writes, but a remote human edit
   after that read and before Google applies the update is an unavoidable
   Sheets TOCTOU without a remote transactional compare-and-write primitive.
   It must be described as an explicit residual boundary, not claimed closed.

## Available fence material

- **Frozen ordinary work fact:** `item['outcome_source_revision']`, captured
  at parallel/local assignment and serial fetch. It must be captured at common
  admission before fetch to remove serial's initial asymmetry.
- **Current authority:** one unique `Companies` row, passed through
  `canonical_company_fact`/`source_revision`. The shared guard must require
  canonical eligibility (including `removed`/ineligible facts) and must not
  independently spell a partial pause list.
- **Company-only provenance:** request `source_revision`, `company_event`, and
  bridge receipt `request_sha256` bind the requested Company/event but do not
  itself prove currentness. For operator/retry, `Engine.start_cycle` already
  shows the required start-time equality pattern.
- **F6 material:** frozen Inbox plan, `SYNC_PENDING`/`SYNC_CONFIRMED` receipt
  and exact readback protect ambiguous storage/sync. They fence delivery and
  cursor recovery, not source freshness before a write.

## Smallest safe implementation slice (one owner)

1. Add a small shared **normal write-admission** helper that takes a frozen
   Company ID/revision and fresh Company row; it requires exactly one,
   unclaimed, canonically eligible `canonical_company_fact` (including removed
   or other ineligible facts) and exact `source_revision` equality. Only after
   equality succeeds, derive expected Company Status, Official Careers URL,
   and ATS / Source from that freshly admitted row; identify the Company
   operation by Company ID. On failure, retain the durable inventory/plan,
   block/hold that company with a bounded reason, and do not consume a newer
   request.
2. Capture the frozen revision at common admission for serial, parallel, and
   local pipeline before fetch. Preserve existing F6 inbox bytes; cycle state
   is the correct location, as the accepted M3 source slice established.
3. Add an **ephemeral companion guard operation** to each commit attempt that
   writes staged jobs, `_reconcile_absences` missing/closure state, or
   `_finish_company` source-derived completion fields. It uses `Companies`
   identity by Company ID plus the freshly admitted expected fields and no
   values. Repository `_prepare_cells` already validates expected fields in
   its fresh pre-write snapshot; a mismatch must reject the whole attempt
   before Job History/Evidence, closure/missing, or Company completion changes.
   The guard is never stored in an F6 frozen plan.
4. Invoke the same helper/guard from serial `_stage_inventory`, serial and
   parallel absence reconciliation/completion, local `upload`, and
   `sync_only`/recovery paths. F6 plans, inbox payloads, receipts, cursors,
   and canonical bytes/digests remain exactly unchanged on both admitted and
   rejected paths. Do not add M3 recorder logic, an event queue, a cancellation
   of an active cycle, or a second persistence pipeline.

### Separate M2 company-event admission sub-slice

Company-event admission needs a separately named M2 sub-slice: after
`scan_request` validates the immutable bridge request but before
`Engine.start_cycle` persists membership, compare its request source revision
to the one current canonically eligible Company fact. On mismatch, hold the
request with its existing bridge receipt/cancellation evidence auditable and
leave it for normal bridge supersession/reconciliation. It must not consume the
request, rewrite a newer request, or cancel an already active cycle. This is
not the ordinary normal-write guard and not M3 producer work.

## Minimum proving tests

1. Serial Company ATS/status/URL change after fetch but before first job batch:
   zero Job History/Evidence writes; frozen inventory/checkpoint retained;
   held reason is bounded.
2. Serial multi-batch change after batch one: earlier acknowledged batch is
   untouched; later batch is blocked and never silently erased or refetched.
3. Parallel assignment snapshot changed before writer staging: no job write
   for that Company; other independent Companies can finish.
4. Change the Company immediately after the final staged job batch but before
   absence reconciliation/completion: no closure, missing-count increment,
   Last Checked/success/completion state, inbox acknowledgement, or request
   consumption; retained inventory/request evidence remains recoverable.
5. Deferred local + `sync_only` source change before upload: no publication,
   inbox plan/cursor/receipt remain recoverable; newer Company request is
   preserved.
6. Recovery after a preflight source mismatch and after an ambiguous F6 write:
   stale work is held/reconciled, not reclassified as successful or refetched.
7. Company-event request whose Company revision changes before start is held at
   admission; its bridge request/receipt stays auditable. Test operator/retry
   behavior remains unchanged.
8. An unchanged revision produces one guarded batch and byte-for-byte identical
   F6 plan/payload/receipt/cursor canonical digests. The rejected path also
   preserves those exact frozen bytes/digests; duplicate/restart remains
   idempotent.

## Deliberate separation of contracts

- **Pre-write prevention (this next M2/Engine slice):** prevents a known stale
  Company fact from entering a newly planned/committed job batch. It owns the
  source guard and durable hold only.
- **Post-storage M3 suppression:** current accepted ordinary-cycle outcome
  recorder classifies stale evidence after storage and withholds it from
  repair-coordinator delivery. It cannot be cited as prevention.
- **F6 save/sync confirmation:** receipt/readback confirms exact local plan
  and sync state, including ambiguous-write recovery. It does not authorize
  source changes and must stay byte-compatible; generic `storage_confirmed`
  remains insufficient for F6 closure.

## Authoritative constraints consumed

The 2026-11-18 roadmap requires pause/removal/source change during work to
cancel or supersede stale work before installation or writes, while keeping
request/attempt/release/publication identities distinct. The finding ledger
still marks F1 and F6 operationally open/awaiting guarded acceptance. The
accepted 2026-11-20 M3 QA expressly leaves pre-persistence stale protection,
exact F6 receipt binding, and company-only producer work open.
