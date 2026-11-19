# Exact-cycle saved-work sync candidate

Updated: 2026-11-19. This source-only candidate is based on the accepted and
installed interrupted-cycle recovery status source. It authorizes no Google
access, publication, scrape, recovery pause, lock deletion or production
installation.

## Need

The authoritative read-only recovery report refuses to pause
`CYC-B639C6D864EC` because it owns 47 durable inventories, eight saved plans
and eight partially applied plans. Seven plans have reached their final
operation cursor but still need normal acknowledgement; one plan stopped at
cursor 67 of 208. Five inventories are already held for manual review.

The legacy `sync` command selects every cycle represented in the durable inbox,
including retained historical work. That is broader than the exact recovery
gate and is not authorized for this reconciliation.

## Candidate behavior

`./job-search-scraper sync --cycle-id CYCLE_ID`:

- applies only to `sync`; `start --cycle-id` is rejected;
- validates one bounded, whitespace-free exact ID while holding the normal
  scraper/writer lock;
- opens the state checkpoint and durable inbox read-only before repository or
  Google setup, and refuses a missing checkpoint or missing eligible inventory;
- applies the normal local supersession contract and refuses completed or
  superseded historical checkpoints even when their inventory was retained;
- preserves `--no-retry-blocked` semantics;
- selects only the exact prevalidated cycle after the inbox opens and refuses
  if that inventory changed after preflight;
- continues through the existing `sync_only=True` path, which does not fetch
  Companies and resumes frozen plans from their durable cursors;
- leaves the legacy no-`--cycle-id` behavior unchanged.

The existing SQLite-to-Sheets synchronizer still performs its guarded startup
pull/publication. Current read-only local evidence shows one pending
`Opportunities` cell in that repository boundary. It is not an inventory from
another cycle and must retain the existing fresh-read/manual-choice guards.

## Evidence

```text
2412949030619a8d4b9c5d8b0bf8ad63f444fc54ea1b7930defd1e90d27f2cfd  engine.py base
3cf789d437e0c196d0ac6a77bb66a27e47eaed97d0ecf88cfebd29ad645762b6  candidate runner.py
664f7923019538dd7f345b528d8b7d019f69c67f482cd9e099e58b073a886839  recovery/apply tests
1aba34c2b8fdefd0430c0df135a94db567c0dec959d602264aca38a6e3de64a4  candidate runner tests
```

The exact protected overlay passed 117/117 recovery, runner, release,
local-pipeline, Company-event and retry checks with resource warnings treated
as errors. New tests prove CLI scoping, start-path rejection, read-only
prevalidation, exact selection in the presence of another saved cycle, and
no-change refusal of both completed and superseded retained inventory.

## Installation and open live gate

Independent review first rejected historical replay through an explicitly named
completed or superseded cycle. The corrected source applies the same local
unfinished/supersession contract before any repository or Google setup, and
independent re-review accepted it.

Only `runner.py` was installed under the existing integration lock. Its exact
pre-install rollback is retained at
`/tmp/job-search-exact-cycle-sync-backup-20261119-PQIZbr`. The installed hash is
`3cf789d437e0c196d0ac6a77bb66a27e47eaed97d0ecf88cfebd29ad645762b6`,
and the protected selection passed 117/117 with resource warnings treated as
errors.

The first live command attempt was blocked by the workspace sandbox before the
normal lock was created. The elevated retry was rejected by the permission
reviewer because publication of this concrete saved-work payload to Google
Sheets requires explicit user approval. No live sync, Google access or
inventory processing occurred. The remaining gate is explicit approval to
publish only the 47 inventories and eight plans for `CYC-B639C6D864EC` through
the guarded exact-cycle command. The normal Sheets synchronizer may also
publish the one already-pending `Opportunities` cell in its local dirty queue.

Independent post-install verification accepted the exact installed runner and
unchanged engine hashes, confirmed local and remote Git checkpoint `f988efb`,
rechecked the installed historical-cycle refusals, and independently observed
the unchanged 47 inventories (five blocked) and eight positive-cursor plans.
It performed no sync, scrape, recovery, Google access or file modification.
