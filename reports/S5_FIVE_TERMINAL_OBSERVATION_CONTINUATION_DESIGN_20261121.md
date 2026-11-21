# Five retained terminal Companies — narrow observation continuation

## Finding

The five terminal holds are not candidates for a generic relaxation of
`validate_legacy_delivery_evidence`.  The current read-only witness shows that
their visible compact fields equal the frozen one-operation Companies plans,
with no dirty cells, conflicts, or delivery attempts.  The 12
`baseline_different` instances are only compact-profile local fields
(`Active Cycle ID`, `Record Updated`, and, twice, `Scan State`); they are not
remote projection fields.  The existing validator receives an untyped legacy
operation and therefore rejects any baseline difference globally.

## Minimal continuation

Add a *separate*, terminal-only observation receipt.  Do **not** alter the
old `sync_plans` payload/cursor, call the normal migration adopter, create an
ordinary publication receipt, or classify this as `SYNC_CONFIRMED`.

The new admission must accept exactly one frozen operation only when all are
true:

1. State is the named cycle and the named Company is `blocked` or
   `unsupported`; Inbox inventory is blocked; plan cursor is exactly one and
   equals the one operation's length.
2. The operation is `Companies`, has exactly `{"Company ID": company_id}` as
   final identity, is not an insert, and has no existing exact remote/local
   plan, chunk, publication receipt, or earlier incompatible terminal receipt.
3. Split its selected fields with the already authoritative
   `sheet_profile.profile_schemas(COMPACT_PROFILE)` / `LOCAL_ONLY_FIELDS`.
   The remote subset is a nonempty exact compact projection.  The local-only
   subset is nonempty only if every header is in the static local-only set.
4. Every selected local field equals the original frozen operation's value,
   there are no selected dirty cells, conflicts, manual choices, or delivery
   attempts.  For a **remote** field retain the existing clean evidence rule:
   baseline equality, or the current tightly-defined blank-missing rule only.
   For a **local-only** field allow baseline equality/difference/missing, but
   record its complete value-presence digest solely as local snapshot evidence;
   it is not delivery evidence and cannot be sent or read from Sheets.

Persist that typed local classification as an immutable candidate record before
the remote read.  Its binding includes cycle/company, SHA-256 of the original
legacy plan and inventory payload, completed cursor, compact schema/profile
digest, exact compact projection digest, local-only snapshot digest, and field
classification digest.

For the remote observation reuse `SheetsSynchronizer.plan_exact_scope` and
`readback_exact_scope` only, with a small terminal row-scope builder derived
from the compact projection.  `readback_exact_scope` already reads exactly the
identity row and requires every compact projected value/guard to match.  Do
not call `publish_exact_scope`, `freeze_exact_remote_plan`,
`claim_exact_remote_attempt`, normal `commit`, migration adoption, or cleanup.
The receipt stores the exact readback/acknowledgement digest and
`REMOTE_OBSERVED_MATCH`; an implementation must assert its remote object's
`commit` method was never reached in tests.

Use a new Inbox table, e.g. `exact_legacy_terminal_observations`, keyed by
`(cycle,company)`, with original plan/inventory/cursor/projection/local
evidence/readback digests, canonical receipt payload, and immutable terminal
state.  On replay, rederive and compare every binding and receipt byte; it may
return the old receipt but must perform neither another Sheets read nor any
write.  The original plan remains present and unchanged.

`exact_recovery_terminal.qualify_terminal_holds` may recognize this new
receipt **only** for the strict one-op blocked/unsupported Companies shape and
only after it validates the immutable binding/readback evidence.  Other
frozen-plan cases retain the present requirement for their own normal
`SYNC_CONFIRMED` receipt.  This is a terminal-disposition receipt, not proof
of a normal publisher delivery.

## Exact seams

- New narrow module: `src/job_search_helper/exact_legacy_terminal_observation.py`.
  It owns the one-operation shape gate, split snapshot, typed binding and
  read-only remote confirmation orchestration.
- `src/job_search_helper/inbox.py`: add the immutable candidate/terminal
  receipt table and compare-on-retry APIs.  It must not update `sync_plans`.
- `src/job_search_helper/exact_recovery_terminal.py`: add the strictly typed
  receipt branch to `qualify_terminal_holds`; do not change generic receipt
  semantics.
- Reuse only `sheet_profile.py` schema/local-only definitions and
  `sheets_sync.py` exact planning/readback primitives.  Leave
  `validate_legacy_delivery_evidence`, migration adoption, and the normal
  exact publisher strict and unchanged.

## Required fixtures

1. The exact five-shaped one-op fixture: two/three differing local-only
   baselines, equal remote fields, no dirty/conflict/attempt; exact readback
   yields one `REMOTE_OBSERVED_MATCH` receipt and zero commits/writes.
2. A visible-field baseline difference, local-only current-value mismatch,
   local-only dirty mark, conflict, manual choice, attempt, wrong stage,
   cursor, identity, insert, or extra operation all hold before remote access.
3. A remote mismatch/missing/duplicate identity holds with no receipt and no
   write.  A changed local snapshot after candidate capture holds before the
   remote read.
4. Replay proves canonical receipt reuse with no second remote read/write;
   changed plan, payload, compact schema, local evidence, or receipt bytes
   holds.  A conventional multi-operation plan still requires its existing
   normal confirmed receipt.

This is source-only design.  It does not authorize a live Google observation,
terminal disposition, pause, cleanup, or status change.
