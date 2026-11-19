# Davidson local legacy-plan migration assessment

Prepared: 2026-11-19. This assessment is local and read-only. It did not
access Google, write a database, create a receipt, alter a plan, clean up an
inventory, or start a workflow.

## Exact retained binding

- Cycle: `CYC-B639C6D864EC`
- Company: `COMP-0035` (Davidson Technologies)
- Legacy plan digest:
  `3c4883bd6b8c5e75e449e9e5f1bca6fe7f174c22e5c20c52aa06482d7e8f553c`
- Inventory digest:
  `4a807ce9ef52d5f68511b2eceaa7d96d7826110bb5e7d0b5b8cb6e0b7d07b7af`
- Legacy operation count: 19
- Local cursor: 19
- Inventory blocked flag: false

The cursor proves only that the older local application reached its end. It
does not prove remote Google publication.

## Current local readback

Every one of the 19 stable identities resolves to exactly one current local
row. Exact record comparison found:

- Companies: 1 match, 0 mismatches
- Job Evidence: 9 matches, 0 mismatches
- Job History: 7 matches, 2 mismatches
- Total: 17 exact matches, 2 protected conflicts

The two mismatches differ only in `Review Status` and `Decision`. Their stable
identity digests are:

- `1fcbce2fe62c6285edabaa47ab912195715143c8f126f373707d500b00879c99`
- `3b2ae86948defef2f205284e61c17a9f0f707df3fd987b1feeb3a4138804978d`

Those later human-review decisions supersede the retained plan. They must not
be overwritten, reset, or treated as evidence that the old Google write
completed.

The full current local-record digest is
`287eeb8ea22754ae3c49c47d0cd3b21204a151eca27927e280caccb283f4a634`.

## Current compact projection

Deterministic projection of the 19 legacy operations into today's compact
publication schema produces 10 remote operations:

- Companies: 1
- Job History: 9
- Job Evidence dropped as current local-only evidence: 9

The unadjusted compact projection digest is
`b1207a555bfefb176ec40840e135831b521637fcdc4a6fd682be74bb580af929`.
It is assessment evidence only and is **not** approved for publication because
it still contains the two superseded review decisions.

## Required safe migration contract

Any migration must:

1. CAS-bind the exact cycle, Company, plan digest, inventory digest, cursor,
   and operation count above.
2. Re-read current local Company controls and current compact remote Company
   controls without requesting absent legacy-only columns.
3. Reverify all 19 local identities and the 17 unchanged records.
4. Preserve the two current `Review Status` and `Decision` values; the old
   values may be guards/history but never remote mutations.
5. Persist an immutable legacy-migration journal before replacing or extending
   any plan evidence.
6. Freeze separate complete local operations and a compact remote projection;
   local-only Job Evidence must remain durable without becoming a Google
   operation.
7. Run an exact projected-row read-only preview before any receipt or write.
8. Require separate approval for a bounded remote write payload; a readback
   mismatch must hold without replay or cleanup.

Until this contract is implemented and independently reviewed, Davidson and
the broad cycle remain held.
