# General Dynamics Land Systems (COMP-0097) checkpoint

- Terminal outcome: **blocked; not counted complete**.
- Official source: the GDLS careers page leads to the General Dynamics job search with the explicit `GD Land Systems` business-unit filter.
- Installed normal pipeline: two consecutive rereads returned HTTP 403 before listing discovery.
- Focused tests: `2 passed` in `tests/test_gd_land_systems.py`.
- Adapter/routing/tests are committed separately from shared completion ledgers.
- Retry when the official filtered route permits anonymous public access; do not infer zero jobs from this blocker.
