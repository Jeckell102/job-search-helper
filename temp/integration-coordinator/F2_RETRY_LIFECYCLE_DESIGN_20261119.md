# F2 retry lifecycle gap and bounded repair design

Date: 2026-11-19

## Why this remains open

The installed F2/F3 admission boundary correctly fails closed for a *new*
repair retry when its release binding is absent, mismatched, nonterminal, or
rolled back. Independent audit found that a previously admitted retry could
reach a resume/recovery path without rechecking that binding. It also found
that the coordinator retains useful retry/original evidence but has no durable
rollback-required lifecycle record keyed to a complete release binding.

Neither gap is acceptable for a live company pilot.

## Bounded repair sequence

1. Revalidate the exact immutable release binding before every retry resume or
   reconstruction, before a fetch, write, local-cycle rebuild, or cursor
   advance. A refusal must retain the request, cycle, inventory, and cursor.
2. Require a canonical SHA-256 of the complete release binding in every retry
   outcome and its durable receipt, not merely a release ID.
3. Add a coordinator-only SQLite lifecycle ledger. It records immutable retry
   outcome evidence and a derived state; it must not start a scraper, call
   Google, release code, roll back code, or delete data.

## Lifecycle ledger contract

The additive coordinator tables are `repair_retry_outcome_events` (immutable,
append-only evidence keyed by outcome ID) and `repair_retry_lifecycles`
(derived state keyed by retry attempt ID). A valid retry identity requires
`attempt_id`, `failed_request_id`, `release_version`, and
`release_binding_sha256`; partial or malformed identity is rejected before any
coordinator write.

| Outcome | Derived state | Effect |
| --- | --- | --- |
| Complete retry | `VALIDATED_COMPLETE` | One durable success summary. |
| Qualified retry integration failure | `ROLLBACK_REQUIRED` | Create a fresh repair identity; preserve data; flag operator action only. |
| Temporary/storage/blocked retry issue | `OBSERVED_HELD` | Preserve evidence; do not infer a release failure. |
| Nonidentical outcome or pin for same attempt | `RECONCILIATION_REQUIRED` | Retain both facts; no repair task or state destruction. |

Late original-attempt outcomes are immutable evidence only and must not reopen
the repaired attempt. Duplicate delivery is idempotent. A rollback-required
record is a durable fact for an operator, not permission for automatic
rollback.

## Required test evidence

- local and reconstructed resume after replacement/rollback refuses before any
  fetch/write and retains all pending state;
- matching completed binding resumes normally;
- retry outcomes contain complete release provenance and malformed lineage is
  rejected before persistence;
- successful retry, retry failure, late original outcome, duplicate delivery,
  temporary/storage hold, and conflicting second event all have the contract
  above;
- the existing delivery drain acknowledges only the exact durable outcome
  receipt.

Current pre-repair coordinator intake/delivery checks: 43 passed. They prove
late-original evidence retention and fresh retry repair-key generation, but
not the lifecycle ledger or rollback-required state.
