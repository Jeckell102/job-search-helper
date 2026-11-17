# Scythe Robotics: verified baseline and rendered evidence

Observed 2026-11-17; live dispatcher receipt timestamp: 2026-11-17T19:06:52.577550+00:00.

## Actual live scraper check

Invoked the development checkout's job_search_helper.ats.fetch_inventory with configured ATS "Dover careers", URL https://joinscythe.com/, company ID COMP-0506 and company name "Scythe Robotics". Used default transports, a clean temporary HOME, disabled bytecode writes, no progress/checkpoint writer, and a 40-second process bound. No scrape cycle, Google credentials or Sheet publication was used.

Result: status partial; jobs 0; source https://app.dover.com/jobs/scytherobotics.
Reason: "Verified company source repair: https://app.dover.com/jobs/scytherobotics. Scythe Robotics careers page HTTP 301."
The Python process exited 0, but the inventory FAILED acceptance because its status was partial. Zero returned jobs here is NOT verified zero openings.

Source hashes:
- ats.py: d9bb458e266c425292821b72506cf5370d5ba3851e863100f3d6dbd448a38d03
- company_sources.py: dea72c7832e9b8848e17b15376d32c5c942f6a5497c59eda9e4e4b6c221dc54f
- scythe_robotics.py: 4c93cbb4bc9e496cf29c578a00dd91586a1b55c044e08077f6dfadca6ffd5277

## Rendered public page observation

A normal browser rendered https://jobs.dover.com/scytherobotics?src=app successfully. Page title: Scythe Robotics Careers. Visible employer name/logo and links identify Scythe Robotics. The rendered page explicitly displayed "No positions available at this time"; no job cards were visible in the observed view. A separate terms link ends in /audit; it is not a job. Preserve the existing audit-link exclusion.

This observation proves the visible empty-state message at that time, NOT a complete live scraper result, a stable two-pass inventory, a raw HTML parser contract, or working nonempty detail extraction. The plain web_read tool sees the JavaScript shell; it does not execute the page's JavaScript.

## Corrections to the model's diagnosis

The source mapping already exists at company_sources.py:1494. Its expected_url is joinscythe.com; its output url is the OLD Dover board. The entry has no expected_urls field: the old board is not a second recognized input alias in repair_source. Passing the old URL leaves it unchanged. fetch_inventory applies repair_source before dispatch; a wrapper's rejecting an original landing URL is not by itself a bug.

Do not call the mapping "correct and complete" or conclude "no changes required." The current implementation fails the real dispatcher check at the old board's redirect. Do not replace SOURCE with the landing domain or relax validation without proving the current board's listing contract.

Existing four Scythe tests use fixtures and cannot prove live operation. The pasted model action traces did not include code_test, so they do not establish a fresh run. Earlier operator-run receipts establish that those four fixtures passed.

## Next step

Status: LIVE_BASELINE_FAILED; RENDERED_EMPTY_STATE_OBSERVED; REPAIR_NOT_IMPLEMENTED.
Investigate a supported rendered-listing or public-data retrieval path on MuleLab. The coding profile currently has public text reads/searches and offline code tests, but no rendered-browser tool. A URL-only replacement cannot make a JavaScript shell usable by the existing static parser. Once retrieval is established, update exact tenant routing and appropriate transport/parser together, retain scope checks and stable reread, test both empty and nonempty fixtures, and repeat normal-dispatch live validation.
