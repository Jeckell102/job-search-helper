# BAE Systems, Inc. (COMP-0073) checkpoint

Terminal status: **blocked; not counted complete**.

- Official source: `https://jobs.baesystems.com/global/en/`
- ATS/source: Phenom, `https://jobs.baesystems.com/global/en/search-results`
- Focused adapter/routing tests: 50 passed (`tests/test_phenom.py`, `tests/test_phenom_reconciliation.py`, `tests/test_raytheon_canonical.py`).
- Installed reread 1: listing reached 2,071; detail reconciliation reached 200/2,071 without a terminal result.
- Installed reread 2: listing reached 2,071; bounded normal-pipeline run exited 124 before a terminal result.
- Stable installed job count: not established.
- Evidence: `evidence/installed-validation-20261101.json`

The source is reachable, but the installed normal pipeline cannot complete the full live detail reconciliation in the verification window. Do not count BAE complete until a terminal `complete` inventory is produced by two stable rereads.
