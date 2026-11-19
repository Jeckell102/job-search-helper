# Generic legacy-to-v2 selected recovery design — 2026-11-19

## Decision

Legacy local cursors are not publication proof. Build a selected-company,
exact-v2 conversion path outside the normal scraper; preserve every legacy
payload and cursor verbatim in an archive/journal.

Current Davidson migration supports only completed cursors, so it can model
Shield AI's 1/1 cursor but cannot accept Saronic's 67/208 cursor unchanged.

## Required conversion contract

1. Accept exactly one cycle/company and immutable legacy payload, plan, and
   cursor; fresh local snapshots/controls; compact schema; and fresh selected
   remote Company guards.
2. Split the legacy stream at its cursor. Prove the prefix against actual local
   rows, retaining snapshot, fingerprints, and dirty-set evidence. Freeze
   suffix prestate with identity, manual, salary, source-hash, and review
   guards. Any drift holds before a journal or receipt.
3. Atomically create a versioned v2 migration journal with legacy digest/cursor,
   prefix/suffix proofs, exact plan/projection/binding and source/input/release/
   configuration digests, plus immutable authorization. Create verified local
   prefix evidence only after actual readback; apply only the suffix in bounded
   chunks and never replay the prefix.
4. After the entire local plan is verified, create a bound `LOCAL_COMMITTED`
   receipt and exact remote intent. Only exact remote readback may transition
   `SYNC_PENDING` to `SYNC_CONFIRMED`; retries must reread the same scope and
   never replay a remote write.
5. Acknowledge only selected dirty cells after the exact receipt confirms; do
   not clear the global outbox, finalize the broad cycle, or modify another
   company.

## Planned code and tests

Extend/rename `exact_legacy_migration*`, add a cursor-aware verified-prefix
helper in `exact_local_plan`, and use existing v2 planner, inbox/journal,
receipt, and exact Sheets readback surfaces. Add tested 1/1 Shield and 67/208
Saronic fixtures; fail before write on prefix, identity, protected/manual,
salary, source, control, schema, profile, or release drift; and cover crashes
after conversion, prefix proof, every suffix chunk, receipt, remote intent,
and ambiguous remote write. Assert zero remote calls before complete local
verification/receipt.

Every mutating conversion must use the signer-bound authorization design with
purpose `legacy-v2-selected-recovery`, binding its exact legacy cursor,
prefix/suffix proofs, v2 plan/projection, and release/source/input/configuration
pins. It remains a supported-CLI gate until deployment/runtime/keyring are
protected from a hostile local administrator.
