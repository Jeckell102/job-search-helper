# Publisher reconciliation decision record — 2026-11-19

## Purpose and boundary

This is a sanitized, read-only decision record. It does not authorize a Google
write, a local-data change, conflict clearing, row restoration, publication,
scrape, recovery, FIRST PASS, release, or lock removal.

The only permitted next action without owner direction is another read-only
verification that the recorded state has not changed.

## Verified snapshot

- The local publisher has one dirty cell on one `Opportunities` row. It is a
  `Last Checked` advance from 2026-11-17 to 2026-11-18 and has no delivery
  attempt receipt.
- That row is not publishable because it also has a protected remote
  `Salary / Range` conflict. The normal publisher correctly excludes an entire
  conflicted row rather than delivering only its unrelated dirty field.
- There are 21 protected conflicts: 20 remote `Opportunities` `Salary / Range`
  values and one missing remote `Companies` row.
- No local row, remote cell, baseline, receipt, lock, or state machine was
  modified while gathering this evidence.

## Corrected live identity check

The initial live inspection used local row identifiers as if they were current
sheet row numbers. That assumption is invalid because the remote sheet may be
sorted or have inserted/deleted rows. It was caught before any mutation. The
initial field-content classification is withdrawn.

A second bounded inspection located every conflict by its immutable Opportunity
ID, required exactly one remote match for each, and then read only that matching
`Salary / Range` cell. All 20 are currently formatted estimated salary ranges;
none is blank, a duplicate identity, or field-inappropriate content. A separate
bounded Companies search confirms the locally retained Company named `Prepared`
is still absent remotely. This correction changes no data and is the only
acceptable identity method for any later reconciliation.

## Required owner decision

Choose a disposition for each protected salary value and for the missing
Companies row. The coordinator must record the chosen disposition before any
mutation and must re-read the exact live cell/identity immediately before a
write.

| Disposition | Effect | Safety consequence |
|---|---|---|
| Retain hold | Leave every conflict and pending delivery unchanged. | Safest default; publisher and final-pilot gate remain blocked. |
| Preserve remote value locally | Import only a specified, freshly re-read remote value into its matching local row and baseline, then clear only that exact conflict. | Changes local protected data. No Google write. |
| Correct remote value | Write only owner-supplied correction(s) with identity and expected-value guards, then read back and reconcile the exact matching local row. | Requires explicit owner-approved field values and a bounded Google write. |
| Restore missing Company row | Recreate the exact missing Company only after owner approves its current identity and controls. | A Google write; never automatic. |

The first two choices do not permit a broad cleanup. They merely determine
whether the discrepancy remains held or one exact current remote value is
preserved as the matching local record.

## Required execution record after approval

For every chosen row, record only its durable identity, field, before/after
value hashes, observed timestamp, expected-value guard, local baseline version,
operation result, and confirmed readback. Keep raw job and user data out of
the GitHub-backed coordination record. If any identity, guard, or readback
differs, stop that row and retain its conflict.

Publisher work can be reconsidered only after all conflicts that share a dirty
row are resolved and a fresh status has zero pending delivery blockers. The
remaining conflicts may not be silently bypassed to claim a clean final gate.
