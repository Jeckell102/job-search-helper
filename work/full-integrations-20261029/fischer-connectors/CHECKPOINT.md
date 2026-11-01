# Fischer Connectors (COMP-0491)

- Official source: `https://fischerconnectors.com/en/about-us/join-us/job-openings/`
- ATS/source: Fischer Connectors first-party careers page; no separate ATS exposed.
- Adapter/routing: `src/job_search_helper/fischer_connectors.py`, routed through the installed inventory dispatcher and guarded by the exact company/source repair.
- Focused tests: 3 passed with `PYTHONPATH=src python -m unittest -v tests/test_fischer_connectors.py`.
- Installed normal pipeline reread 1: `complete`, 7 full postings.
- Installed normal pipeline reread 2: `complete`, 7 full postings with the identical seven posting URLs.
- Stable installed job count: 7.
- Evidence: `evidence/installed-validation-20261101.json`.
- Shared completion ledgers were not edited.
