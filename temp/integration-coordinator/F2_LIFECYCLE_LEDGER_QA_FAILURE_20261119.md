# F2 lifecycle-ledger independent QA failure

Date: 2026-11-19
Candidate package: `/tmp/jsh-f2-retry-lifecycle-ledger-source-package.tar.gz`  
Candidate SHA-256: `35414989120f2639dc42432f1e8150e01d50ed1d83d22b1df6804e63c5daecbf`

## Result

Rejected. This source-only candidate must not be installed.

The archive manifest and three-file scope were valid. The ledger-specific
tests passed 6/6, but the reconstituted coordinator suite passed only 43/44.
No protected source, state, Google data, queue, service, or lock changed.

## Reproducible findings

1. A duplicate immutable original qualified outcome returns no `repair_key`
   before repair-key derivation. The established promotion test then cannot
   retrieve its existing paused task (`Use a held repair key`). Duplicate
   delivery must retain the same held repair key and promotion must remain
   idempotent.
2. A retry record with the same failed request and attempt but a changed
   `release_binding_sha256` raises a lineage conflict inside the transaction.
   The transaction rolls back, leaving a prior `VALIDATED_COMPLETE` summary
   and only one event. The required contract is to retain the second immutable
   fact and set `RECONCILIATION_REQUIRED`, with no repair task or destructive
   state change.

## Repair assignment and acceptance

Worker `f2_lifecycle_ledger_impl` owns a new isolated candidate. It must fix
both cases without changing the observation-only boundary: no automatic
rollback, dispatch, scraper start, Google access, release activation, or data
deletion. Required rerun includes ledger tests, outcome-intake, held-promotion,
and outcome-delivery tests, followed by a fresh independent reconstitution.
