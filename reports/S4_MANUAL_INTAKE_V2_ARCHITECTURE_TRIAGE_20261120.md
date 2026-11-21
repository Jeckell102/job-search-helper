# Architecture triage — Sprint 4 v2 foreign-writer race

Date: 2026-11-20

## Decision

Keep the prior rejection for **activation as an exact/concurrency-safe append path**. The reported Drive facts materially narrow the risk: the workbook is not shared, is not in a shared drive, and presently has one undeleted user owner and no other writer. Local scheduled synchronization is off and the local writer leases are held. They do not establish exclusion of the same owner acting from another device, script, browser tab, Apps Script, or automation between the final remote preflight and the unconditioned `batchUpdate`.

The v2 request atomically creates its own fixed developer-metadata ID and appends its row. It does not atomically assert that no row with the Company/ID/board identity exists. Therefore, an independently tied time-bounded owner quiet window is **risk mitigation and a manual operating procedure**, not a technical substitute for atomic admission or a proof of exact custody.

## Safest current route

Use a read-only import of a genuinely externally created Company as the smallest safer pilot. It creates no remote duplicate-row risk. Before the local import, require a current exact remote read of the native table that proves one literal Company/ID/board row, expected table/header identity, no manual/local conflict, and a named source/revision; then create the local baseline, revision/event, and receipt in one local SQLite transaction. Stop on ambiguity or a changed remote read.

That route remains a bounded **import** pilot, not evidence that the new remote-append protocol is safe.

## If the owner explicitly chooses the remote append pilot

It may be authorized only as a documented, one-time operational-risk exception—not as a green acceptance of the v2 design. Minimum defensible evidence:

1. A fresh owner-signed pilot authorization naming exact workbook ID/digest, table ID, Company/ID/board, fixed metadata ID, time window, and acknowledgement that same-owner concurrent activity remains possible.
2. A just-before-dispatch verifier records the supplied permission facts, exact workbook/table/header identity, no existing marker or matching row, local scheduled sync disabled, and both local writer leases held.
3. The owner pauses all known same-owner browser tabs, devices, scripts, Apps Script jobs, and automations for that window. This is attestation, not an API-enforceable lock.
4. Submit exactly once. Never replay after any uncertain response or conflict.
5. Immediately do independent exact marker/row/marker readback, inspect for one—not merely at least one—matching Company/ID/board row, and preserve the request/response/readback evidence. Any ambiguity becomes a hold plus manual workbook repair; it must not create a local event.
6. Document that the successful pilot demonstrates only the observed quiet window. It does not qualify unattended operation or discharge the foreign-writer race finding.

Even this evidence cannot prove that a same-owner write does not land immediately after final readback. It bounds operational exposure; it does not establish serializability.

## Smallest code/test changes before an exception pilot

Keep the existing explicit post-write exact-one readback. Add tests for the actual operational gate and its failure modes:

- pre-append verifier rejects wrong workbook owner/permission attestation, shared/shared-drive indication, scheduled-sync enabled, missing writer lease, stale timestamp, mismatched workbook/table/header identity, or an existing matching row/marker;
- foreign same-owner duplicate inserted after final preflight is recorded as `REMOTE_DUPLICATE_HOLD`, creates no local event, and never retries;
- foreign same-owner duplicate inserted after the immediate post-write readback is called out as unpreventable by test documentation; no claim of atomic exclusion;
- uncertain response, missing marker, changed marker, or any multi-row identity remains a non-replay hold;
- a separate read-only external-row import test proves unique literal identity, local row-ID collision preservation, baseline/event/receipt atomicity, and unchanged remote workbook;
- end-to-end test verifies that the exception-pilot command cannot be scheduled, looped, or used for a second Company.

Do not relabel a quiet-window preflight as an exclusive lock, atomic claim, or general admission control.

## Blockers to green activation

1. No server-side conditional uniqueness/admission primitive for the Company/ID/board identity.
2. Same-owner concurrency is not observable or lockable through the stated Drive permission facts.
3. The v2 fixed metadata ID guards only its own marker collision, not a foreign append with a different marker.
4. A successful quiet-window append has no proof value for unattended/repeated operation.

## Recommendation

Prefer the read-only import pilot. If the user expressly prefers the remote append, require the exception procedure above and retain the release block for any broader or automated activation.
