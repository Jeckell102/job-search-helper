# W03 + W02/Hughes validation — 17 November 2026

This record covers the Hughes transport and completeness repair. It did not start a scraper cycle, write local inventory state, or publish to Google Sheets.

## Change

`src/job_search_helper/ats.py` permits only the public read-only Hughes EchoStar endpoint `https://jobs.echostar.com/api/jobs?tags4=Hughes&page=<1..1000>`. The guard rejects a changed tag, extra query fields, invalid page, different route, credentials, non-HTTPS, and unpinned hosts.

`src/job_search_helper/hughes.py` replaces the historical `total == 14` / always-fetch-page-2 check with dynamic enumeration. It derives page count from the verified first-page row count and total, checks every later page against the same total, requires exact row-total reconciliation and unique Hughes requisition IDs, validates full descriptions, then rereads the complete inventory and compares membership.

## Regression validation

```text
PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider' PYTHONPATH=src /home/chris/job-search-helper_old/.venv/bin/python -m pytest -q tests/test_hughes.py tests/test_next_company_routes.py
```

Result: `20 passed in 0.16s`.

The normal-dispatch tests cover inventories below and above the old count, explicit empty inventory, dynamic multi-page enumeration, missing listings, duplicate IDs, changed final membership, truncated pages, wrong employer tags, and exact endpoint allowlisting.

## Read-only live normal-dispatch validation

`job_search_helper.ats.fetch_inventory('Browser', 'https://www.hughes.com/careers', 'COMP-0118', 'Hughes Network Systems')` returned `complete` on 17 November 2026 with six full postings (102169, 101937, 100842, 100916, 100844, 100999), all descriptions present, and a stable final reread. No company stage was manually promoted; scraper-run adoption and Google Sheets publication remain separate work.
