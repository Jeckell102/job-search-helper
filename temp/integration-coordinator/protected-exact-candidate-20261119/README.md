# Protected exact-cycle candidate — 2026-11-19

This is the sanitized, source-and-tests-only overlay accepted for the current
protected MuleLab baseline. It contains no credentials, databases, job data,
locks, inventories, receipts, or runtime history. It is not a standalone
checkout: apply it only to the protected baseline whose pre-install hashes are
listed below and only through the existing integration install lock.

## Evidence

- Accepted source lifecycle input: `0a4691832a3364438fdb975fa03da58a1e3fbd70`.
- Full sanitized-copy verification: 186 focused and 180 protected-adjacent
  checks passed with warnings treated as errors.
- Independent verification: 196 focused and 110 adjacent checks passed with
  warnings treated as errors.
- No candidate Python file contains a merge marker. Preserved `*.rej` audit
  files are not included in this package.
- `SHA256SUMS` seals every packaged source and test file.

## Required protected pre-install hashes

- `runner.py`: `db88178ec6e0a07779ea7216f5158604422bb072a93c4d3dd3c8aca8d6643df3`
- `inbox.py`: `482895c72900ddcdfda1089090a6277af494bea7941b1f1289ac8f2ae5cb23cd`
- `publication_receipts.py`: `68b029585948b9dcf99c6277f2fe5334eed38642f5679e072fd5375d93384ff2`
- `sheets_sync.py`: `034c90e64f5d44767094a525ecb363826f40ec70eea3864e7e9ce19592934fa2`
- `sqlite_repository.py`: `27b136135be61c185ea5d33a6c9830ff106d7e859aee9a3ec3ce5992bc889713`

The nine `exact_*` source modules are expected to be absent before install.
Any hash mismatch or unexpected existing target is a stop, not permission to
overwrite.

## Install and rollback boundary

1. Recheck no active scraper/publisher/reviewer/coordinator process, settled
   release state, and the exact pre-install hashes above.
2. Acquire—not delete or bypass—`.integration-install.lock`.
3. Save a new per-file rollback copy and before manifest outside job data.
4. Install only files listed in `SHA256SUMS`; do not touch databases, `.state`,
   locks, credentials, inventories, or unrelated dirty files.
5. Verify installed hashes, compile, and rerun the accepted focused and
   protected-adjacent matrices without Google access.
6. On any mismatch or failure, restore only replaced files and remove only
   newly added files recorded by that rollback manifest, then verify hashes.

This package authorizes no Google write, scrape, backlog release, service
restart, automatic repair, Jetson change, or final acceptance claim.
