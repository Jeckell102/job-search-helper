# COMP-0066 Forterra local normal-dispatch evidence

Performed: 2026-11-19. Scope was a disposable in-memory fixture against the
current protected source, with bytecode writes disabled. No HTTP request,
scraper, local data store, Sheets/Google, queue, lock, service, or job record
was changed.

## Verified

- Exact normal source repair for `COMP-0066` / `Forterra` maps the official
  careers URL to Rippling `https://ats.rippling.com/forterra/jobs` and records
  verified-repair provenance.
- A synthetic, locale-qualified `forterra` board with advertised total 62 and
  page cardinalities 20/20/20/2 produced exactly 62 stable unique records.
- The adapter requested exactly the base listing plus `?page=1`, `?page=2`,
  and `?page=3`; it did not request HTTP-200 empty `?page=4`. This is the
  intended metadata-backed stop boundary, not a hard-coded public count.
- `tests.test_shared_boards` plus `tests.test_source_routing_recovery` passed
  26/26 against the same current protected source.

## Result

No tenant-specific wrapper or source rewrite is justified by the public
preflight. A later guarded pilot must still fresh-read the public inventory,
exercise full detail/reread and normal synchronization, and remain subject to
the roadmap's release/lock/queue and independent-QA gates.
