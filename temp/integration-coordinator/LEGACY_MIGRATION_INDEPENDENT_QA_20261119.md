# Legacy migration independent QA — 2026-11-19

## Decision

**Accept the completed 13-file protected source-install evidence. Hold any
Davidson/local adoption.**

## Verified

- All 13 current protected-file SHA-256 values exactly match
  `/tmp/jsh-exact-legacy-migration-20261119T204347Z-r79t5cvt/manifest.json`,
  whose status is `INSTALLED_HASH_VERIFIED` (including runner hash
  `3e415524…`).
- The isolated `test_exact_legacy_migration` matrix passed 14/14 with bytecode
  writes disabled and temporary fixtures only.
- The read-only preview opens SQLite with `mode=ro`; its test proves both
  database files are byte-identical before and after.
- Coverage includes no local replay, protected Review Status/Decision guards,
  cross-database recovery, and idempotent retry after successor freeze.

## Blocking control gap

The adoption CLI calls a JSON file a reviewed approval but accepts any file
whose binding equals a freshly recomputed binding. It validates neither signer
or reviewer identity nor human-authorization provenance. A local CLI user
could create a preview and immediately run `legacy-migration-adopt --apply`.
Exact pins prevent drift; they do not prove the separate human-review gate.

The existing Davidson approval JSON is therefore candidate evidence only. Do
not adopt until approval provenance is designed and enforced, or a policy
explicitly authorizes current local CLI access as sufficient review.

No source, production record, database, Sheets/Google state, queue, lock,
scraper, or service was changed during this review.
