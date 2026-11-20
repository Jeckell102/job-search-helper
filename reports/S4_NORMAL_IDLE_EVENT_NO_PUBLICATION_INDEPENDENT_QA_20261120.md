# Sprint 4 ordinary no-publication independent QA

**ACCEPT both original sender fixes. HOLD the no-publication source gate on incomplete checks for contradictory exact evidence.**

## Remaining blocker

The no-publication settlement and its sender both use the same contradiction check, but that check omits exact recovery archives and only reads the request ID from publication receipt bindings. The independent fixtures reproduced these gaps:

- A typed empty temporary failure settled and was delivered even when the exact cycle and Company had an existing row in either the legacy exact plan migration archive or the legacy delivery evidence archive. The fixtures seeded each archival contradiction separately. The sender acknowledged the new outcome and replay returned the same terminal result.
- A typed empty access denial settled as FETCH_BLOCKED even when the Inbox already held a legacy SYNC_CONFIRMED receipt whose binding named the exact cycle, Company and source revision under a different request ID. The fixture registered and confirmed the alias through the normal Inbox receipt methods. The selected Company event's own request identifier stayed distinct.

Require the no-publication exclusion to cover historical exact evidence and receipt bindings that explicitly name the exact cycle. Use the same complete exclusion for settlement and sender verification. A contradictory row should keep State and mirror unfinished and prevent both outcome creation and delivery. [Current exclusion](/tmp/jsh-s4-ordinary-no-publication-qa.ylGpCIUM/src/job_search_helper/ordinary_event_settlement.py:153) · [Sender's no-publication proof](/tmp/jsh-s4-ordinary-no-publication-qa.ylGpCIUM/src/job_search_helper/ordinary_event_settlement.py:260) · [Existing exact archive schema](/tmp/jsh-s4-ordinary-no-publication-qa.ylGpCIUM/src/job_search_helper/inbox.py:274)

## Accepted boundaries

- Changing the trusted Jobs acknowledgement after ordinary publication now held outbound delivery. No transport receipt or receiver call was made. A stale result at the Jobs-before-State cut also held without a sender receipt. After State finished, the stale result was suppressed exactly once without contacting the receiver.
- Typed temporary and access errors and a supported explicit zero produced the expected local-only outcomes without opening the workbook writer. Ambiguous empty, a simultaneous typed failure and zero marker, and an active orphan exact chunk introduced during the workbook read stayed held.
- Local A→B→A and frozen-record corruption injected during the read-only workbook check left State and mirror In Progress with no new outcome. A cut after State save replayed the same result without rereading the workbook or calling the provider. Corrupting the saved observation before sender recheck held delivery, and restoring the exact bytes allowed one receiver acknowledgement.

All 120 regression cases passed, including the corrected source-neutral two-sided fixture. Ten independent cases passed, including reproductions of the remaining contradiction gaps. The 775-file path, mode and SHA-256 inventory matched the disposable copy with digest bb182e1241316ee7780193c125bc0ae73011316279ca6ea6760bde5f173f38b1. The independent fixtures blocked network lookup, connect and bind. The source snapshot, production, live Sheets, services, Jetson and GitHub were untouched. [Independent fixture](/tmp/test_jsh_s4_no_pub_independent_4CdSyrhz.py) · [Previous QA](/tmp/jsh-s4-ordinary-event-settlement-independent-qa.md)
