# Ericsson checkpoint — 2026-11-01

Ericsson's official careers portal is `https://jobs.ericsson.com/careers`.
It exposes the employer-scoped Eightfold PCSx search and position-detail
endpoints. A direct public probe returned 422 postings with full descriptions,
and the dedicated adapter plus focused fixture tests pass.

The installed normal-pipeline validation reached the official careers source
but was denied with HTTP 403 by the public endpoint. The result is therefore
a confirmed external blocker, not a verified zero-opening result. No shared
completion ledger was edited.
