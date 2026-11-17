# W03 + W02/Hughes runtime change set — 17 November 2026

The live runtime at `/home/chris/job-search-helper_old` differs from the GitHub repository layout. This source-level record preserves the verified W03 + W02/Hughes implementation for transfer.

`src/job_search_helper/ats.py` adds a narrow `_safe_api_url` contract for only `https://jobs.echostar.com/api/jobs?tags4=Hughes&page=<integer 1..1000>`, rejecting changed tags, duplicate or extra query values, invalid pages, changed routes/hosts, credentials, non-HTTPS, and fragments.

`src/job_search_helper/hughes.py` removes the `total == 14` and unconditional second-page requirement. It validates each requested page, derives the page count from the first result's declared total and actual page size, reconciles every row to the total, validates unique Hughes-only requisition IDs and full descriptions, then rereads the complete dynamic page range to confirm stable membership.

`tests/test_hughes.py` exercises normal dispatcher routing, the transport guard, dynamic inventories below and above the stale count, empty results, multi-page pagination, malformed/truncated/duplicate/wrong-scope records, and final membership changes. Focused regression: 20 passed. Live normal dispatch: complete, six full postings, stable reread.
