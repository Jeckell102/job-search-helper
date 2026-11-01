# GDIT checkpoint — 2026-11-01

- Company: General Dynamics Information Technology (COMP-0011)
- Official source: `https://www.gdit.com/careers/`
- ATS: employer-scoped Workday `External_Career_Site`
- Routing repair: pinned `https://gdit.wd5.myworkdayjobs.com/External_Career_Site` in `company_sources.py`; generic Workday adapter handles pagination and details.
- Focused tests: passed (`tests/test_company_sources.py` and `tests/test_workday.py`).
- Installed normal pipeline reread 1: `partial`, 0 jobs; Workday listing page 1 network/timeout after bounded retries.
- Installed normal pipeline reread 2: `partial`, 0 jobs; same bounded listing-page failure.
- Terminal blocker: live Workday listing access was unavailable from the installed normal pipeline, so inventory completeness and stable job count are unverified.
- Completion: not counted complete. Shared completion ledgers were not edited.
- Evidence: `evidence/installed-validation-20261101.json`
