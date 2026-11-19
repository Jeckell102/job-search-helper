# Milestone 1 read-only Samtec preflight — 2026-11-19

## Result

Milestone 1 is not ready for a live Samtec scrape. No Samtec request, scrape,
Google write, checkpoint, lock, or job record was changed by this preflight.

## Verified state

- Samtec is active `COMP-0739`; its current source revision is recorded in the
  local Company revision store.
- The supported company-only path consumes a validated durable
  `next-scan.json` request and then uses the ordinary scraper `start` path.
  Running without that durable request would be a full scan, so no request was
  created while a blocking cycle remains.
- No scraper or coordinator process is active. Stale locks were retained.
- Exact recovery status for `CYC-B639C6D864EC` still refuses a pause: it owns
  47 saved inventories and eight partially applied publication plans. The
  salary fallback/publisher cleanup removed its separate one-row publisher
  blocker, but it did not reconcile these cycle-owned records.
- A direct read-only `cli start --company-id COMP-0739 --dry-run` stopped
  before scheduling because its remote repository was built with the base
  schema and rejected the existing compact-profile `Opportunity ID` column.
  The minimal schema-preservation repair was independently reviewed, backed up
  in `a755861`, installed into the protected checkout, and its two focused
  protected tests passed. A later real Google-backed dry run did not produce a
  usable terminal receipt, so it is not counted as a successful safe-boundary
  result.

## Current controls

- Broad backlog processing remains disabled.
- No cycle was superseded, no lock removed, and no automatic repair/release
  profile was enabled.
- The next safe actions are: repair and independently test the compact-profile
  reader for the direct normal CLI; then use a read-only exact-cycle inventory/
  plan reconciliation to determine whether the old cycle can be safely
  published or explicitly reconciled without broad processing.
