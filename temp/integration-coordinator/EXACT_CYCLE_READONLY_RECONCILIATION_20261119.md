# Exact-cycle read-only reconciliation — 2026-11-19

## Scope

This report covers only the retained work for
`CYC-B639C6D864EC`. It is read-only evidence; it authorizes no publication,
scrape, cycle pause, queue activation, lock removal, or replay.

## Verified durable state

- The recovery guard confirms that this is the sole active blocking cycle with
  matching local/workbook membership and scope. It still refuses a pause while
  saved work exists.
- Inventory store: 47 JSON-valid inventories, all bound to current cycle
  Company IDs; no inventory belongs to a missing member.
- Plan store: eight JSON-valid frozen plans; every plan has a matching
  inventory and current cycle member. Six plans have cursor 1, one cursor 19,
  and one cursor 67. No plan has an invalid Company identity.
- Five inventories are deliberate holds. The remaining 42 are unblocked.
- Thirty-nine unblocked inventories have a durable payload while the matching
  state checkpoint still says `queued`. This is a recoverable producer/
  checkpoint split, not evidence that those companies may be fetched again.
  The existing resume path can reconstruct them as inventory-stage work from
  the durable inbox; a re-fetch would violate preservation requirements.

## Reconciliation decision

The existing exact-cycle command has a strong cycle-selection gate, but its
current startup also performs global closed-job cleanup and manual-opportunity
work before processing the named cycle. That is outside this recovery scope
and could alter unrelated backlog state. It must be narrowed and independently
tested before any live exact-cycle sync.

The assigned coordinator/release lane owns that narrow implementation. After
it passes independent QA, the next guarded action may process only this exact
cycle's existing 42 unblocked inventories and eight frozen plans, with no
fetching, no automatic retries, no global cleanup, no manual-opportunity
import, and no coordinator outcome delivery. The five held inventories remain
held.
