# Amphenol Aerospace — COMP-0490 checkpoint

Status: blocked; not counted complete.

The official employer-scoped source is the AcquireTM board at
`https://amphenol-aerospace.acquiretm.com/home.aspx`. The adapter is pinned to
the unfiltered board and has focused coverage for ASP.NET pagination, listing
reconciliation, JSON-LD identity, and HTML description extraction.

On 2026-11-01, the installed normal pipeline was run twice. Both rereads
returned `partial` with `AcquireTM total changed or pagination repeated` and
zero installed jobs. A direct diagnostic observed 41 advertised listings,
with 25 on page 1 and 16 on page 2, but that observation was not stable through
the normal pipeline twice. The company is therefore not complete and must not
be added to completion ledgers.

Focused tests: `5 passed` (`tests/test_acquiretm.py`).
