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
  values and one missing remote `Companies` row. A bounded live read confirms
  the salary cells are not uniform echoes; at least one has content that does
  not belong in a salary field.
- No local row, remote cell, baseline, receipt, lock, or state machine was
  modified while gathering this evidence.

## Required owner decision

Choose a disposition for each protected salary value and for the missing
Companies row. The coordinator must record the chosen disposition before any
mutation and must re-read the exact live cell/identity immediately before a
write.

| Disposition | Effect | Safety consequence |
|---|---|---|
| Retain hold | Leave every conflict and pending delivery unchanged. | Safest default; publisher and final-pilot gate remain blocked. |
| Preserve remote value locally | Import only a specified, freshly re-read remote value into its matching local row and baseline, then clear only that exact conflict. | Changes local protected data; unsuitable for malformed values unless expressly approved. No Google write. |
| Correct remote value | Write only owner-supplied correction(s) with identity and expected-value guards, then read back and reconcile the exact matching local row. | Requires explicit owner-approved field values and a bounded Google write. |
| Restore missing Company row | Recreate the exact missing Company only after owner approves its current identity and controls. | A Google write; never automatic. |

The first two choices do not imply that malformed remote values are valid.
They merely determine whether the discrepancy remains held or is preserved as
the current local record. Neither choice authorizes a broad cleanup.

## Required execution record after approval

For every chosen row, record only its durable identity, field, before/after
value hashes, observed timestamp, expected-value guard, local baseline version,
operation result, and confirmed readback. Keep raw job and user data out of
the GitHub-backed coordination record. If any identity, guard, or readback
differs, stop that row and retain its conflict.

Publisher work can be reconsidered only after all conflicts that share a dirty
row are resolved and a fresh status has zero pending delivery blockers. The
remaining conflicts may not be silently bypassed to claim a clean final gate.

