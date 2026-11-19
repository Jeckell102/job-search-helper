# Milestone 5 repaired-company retry candidate

Status: source candidate; production unchanged; independent QA and release-controller wiring pending.

## Implemented boundary

- A reviewed release produces one immutable retry identity bound to the failed request, Company ID, current Company source revision, activation time, and the complete source/dependency/configuration release digests.
- The release-to-retry bridge writes a crash-durable intent before offering one Company-only request to the normal scraper boundary. A different pending request is never overwritten; replay of the same receipt recreates the same request exactly.
- The normal request fingerprint, cycle checkpoint, remote cycle Notes, and recovery path retain the complete retry and release identity.
- Admission refuses a stale Company revision before cycle creation. Storage rechecks the live Company revision and preserves the fetched inventory without writing if the Company changes after admission.
- The normal local/publication receipt uses the admitted release ID and source revision. The normal scrape outcome carries the retry attempt and release identity for downstream reconciliation.
- Company-event and repaired-retry provenance are mutually exclusive, preventing two competing precedence chains on one request.

## Verification

The focused scraper, request, event, storage, receipt, and outcome suite passed 151 tests on Python 3.11. Coverage includes crash-after-intent recovery, idempotent delivery, queue collision, release-component mutation, stale admission, restart reconstruction, source drift before storage, exact publication binding, and preservation of attempt/release identity in the resulting outcome.

## Downstream stale-result precedence

The coordinator now persists the failed-request-to-successor-request lineage when it receives an outcome from a repaired retry. An original repair that arrived first is retained as evidence but marked superseded. An original failure that arrives late is recorded without creating or reopening repair work. A second different successor for the same failed request is rejected. If the repaired retry itself still has a qualified integration failure, its attempt identity produces a fresh repair key instead of reopening the pre-release task. Legacy non-release attempt metadata remains readable; release lineage requires the complete attempt, failed-request and release triplet.

The complete isolated coordinator suite passes 195 checks with resource warnings treated as errors, including five new precedence and conflict cases. Together with the 178 scraper/release checks, 373 checks pass across the two source surfaces.

## Explicit remaining gates

- This candidate does not install or activate a release and does not enable production automation.
- The maintained release controller now produces the retry from the exact completed release receipt and recovers a crash after activation without reinstalling. F2 now has source-level downstream stale-result precedence; independent QA, protected-store reconciliation and guarded operational evidence remain.
- F3 now has a separate source candidate for shared admission, complete-version activation, interruption blocking and rollback receipts. Independent QA, disposable production-snapshot races and guarded deployment remain open.
- The full induced-failure-to-release-to-fresh-scrape-to-confirmed-Sheets demonstration remains required.
