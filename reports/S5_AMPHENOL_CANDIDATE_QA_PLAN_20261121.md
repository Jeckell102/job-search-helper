# Independent candidate QA preparation — WRAP-9b6f2e2274

Prepared 2026-11-21. Scope: COMP-0490, Amphenol Aerospace, AcquireTM,
`https://amphenol-aerospace.acquiretm.com/home.aspx`.
This is a prepared evaluation plan, not candidate acceptance. No employer request,
production mutation, release, scheduler change, or candidate edit was performed.

## Current independent evidence

Private capture directory: `/tmp/jsh-s5-amphenol-current.490_viwa`.
`browser-listing-result.json` records 2026-11-21T05:03:15+00:00:
39 advertised positions, 25 first-page IDs, page 2 advertised, partial result
`AcquireTM total changed or pagination repeated.`

Offline parsing of the saved HTML independently reproduced 39/25 and page-control
2. Saved detail 2273 identifies Amphenol Aerospace, has 4,233 normalized description
characters, retains The Role/The Person sections, and current `posting()` output
equals the normalized full JSON-LD body. This is one-description evidence only.
Neither 39 nor historical 41 is an acceptance constant.

Read: current acquiretm.py, all six current test_acquiretm.py tests, ATS routes,
source repair, wrapper-development-test-protocol.md, and roadmap M4/M5 gates.
Current six tests are synthetic direct-adapter tests. They do not prove nonempty
normal dispatch/default transports or changed final membership. The broad DOM
change wait is a plausible early-read risk; this preparation does not claim that
it is the demonstrated cause.

## Before evaluation

- Wait for the generation task to settle; pin candidate source/config/tests and
  acceptance-original hashes. Never evaluate a moving draft or replace its tests
  with a weaker generated suite. Read the actual diff and new files.
- Candidate root expected:
  `/home/chris/job-search-helper_old/dev/wrapper-coder/tasks/WRAP-9b6f2e2274/repo`.
  Validate it from the authoritative task record before running.
- Authorized source target is acquiretm.py. If the draft modifies dispatcher,
  shared parsing, source repairs, browser fallback, configuration, or other
  employers, stop and identify expanded affected tests before acceptance.
- Confirm the patch uses actual captured pagination evidence. A longer sleep,
  accepting repeated IDs, deleting the advertised-total check, or declaring
  partial complete does not establish a repair.

## Minimal offline acceptance

Preserve original six tests and add/read narrowly relevant cases:

1. Nonempty `ats.fetch_inventory` from exact configured inputs uses AcquireTM and
   default production transport selection. Mock the lowest browser/network
   boundary; do not replace fetch_acquiretm itself in the proving test.
2. Captured first page plus authentic second page; delayed UpdatePanel/grid
   readiness; early unrelated body/progress change must not be accepted as a
   completed page transition. No invented page 2 labeled captured evidence.
3. Missing/repeated/duplicate IDs, changing totals, omitted page, page cap,
   foreign URL/redirect, changed final IDs or titles: partial/blocked, never
   complete. A third synthetic page verifies navigation beyond page 2 if the
   implementation changes generic paging logic.
4. Every detail requires matching ID/title/URL and exact allowed employer label;
   retain negative Amphenol Pcd/other-employer cases. Full source description is
   retained, not merely a 120-character excerpt; missing or rate-limit text fails.
5. Explicit scoped zero marker may succeed; missing marker/unproven empty shell
   cannot. Retain bounded 429/timeout handling and detail cache behavior.

Use existing host sandbox; no network, repository writes, credentials, or tests
from the production parent configuration. After the settled candidate is pinned,
the exact small regression selection is:

```bash
qa_scratch=$(mktemp -d /tmp/jsh-amphenol-offline.XXXXXX)
timeout --signal=TERM --kill-after=5s 95s /usr/bin/python3 -I \
  /home/chris/job-search-helper_old/dev/wrapper-coder/tools/coding_sandbox.py \
  /home/chris/job-search-helper_old/dev/wrapper-coder/tasks/WRAP-9b6f2e2274/repo \
  /home/chris/job-search-helper_old/.venv "$qa_scratch" \
  tests/test_acquiretm.py tests/test_company_sources.py \
  tests/test_inventory_source_validation.py
```

Also obtain the coordinator's immutable `acceptance-original` verification receipt,
whose source-manifest digest must equal the draft under review. The command above
alone tests current files and does not replace original-assertion verification.
If ats.py changes add tests/test_ats.py; if shared_boards.py changes add
tests/test_shared_boards.py and tests/test_shared_board_helpers.py plus tests for
the affected helper's callers; if browser_scraper.py changes add
tests/test_browser_scraper.py. Split bounded runs where needed. Inspect assertions;
passing an unrelated suite is not shared-adapter coverage.

## Bounded live normal-dispatch gate — PREPARED, NOT RUN

Only the coordinator may start this after source/offline acceptance and after the
Jetson task's employer reads settle. Use two fresh normal-dispatch runs, sequentially,
with default transports in isolated temporary browser contexts. Each run already
contains a complete final listing reread; observe it rather than issuing another
diagnostic scrape. The prepared evaluator records listing memberships and full
detail-body evidence without changing the request/transport logic.

```bash
timeout --signal=TERM --kill-after=10s 8m env -i \
  PATH=/usr/bin:/bin LANG=C.UTF-8 \
  PLAYWRIGHT_BROWSERS_PATH=/home/chris/.cache/ms-playwright \
  /home/chris/job-search-helper_old/.venv/bin/python -I -B \
  /tmp/jsh-amphenol-independent-qa-20261121/evaluate_candidate.py \
  /home/chris/job-search-helper_old/dev/wrapper-coder/tasks/WRAP-9b6f2e2274/repo
```

The evaluator is prepared against current public adapter interfaces. If the
reviewed candidate changes these, adapt observation only after reading that diff;
never substitute a custom fetch path. A failed/partial first run stops evaluation.
Timeout is failure/held, not permission for automatic repetition. Two stable
complete runs are initial success evidence; a naturally changing inventory gets
one coordinator-reviewed bounded reconciliation with explicit added/removed IDs,
then holds if unsettled. Never loop until an expected count appears.

The first-page saved capture and one detail are independent reference evidence,
not evidence of all current pages. Inspect complete current page transitions and
the exact public advertised total from the run, alongside returned IDs. All-page
membership, all-description verification, and explicit source/employer identity
must agree. Two equal counts alone are insufficient.

## Verdict and receipts

- Required: candidate/import/config hashes, original tests receipt, exact invocation,
  UTC interval, public configured/final URLs, status/reason, listing snapshots with
  IDs/titles, advertised-count reconciliation, per-job description hashes/lengths,
  and complete final reread. Save raw public evidence privately and references in
  the report; omit cookies, browser profiles, credentials, private job records.
- If any required proof is absent: IMPLEMENTED_AWAITING_LIVE_VALIDATION or precise
  BLOCKED/REJECTED. Do not label complete from 25 fetched details or source tests.
- Live candidate success is VALIDATED_AWAITING_INSTALLATION only. Current-production
  reconciliation, complete-version pin, guarded installation/rollback, fresh-worker
  installed verification, ordinary company-only storage/Sheets receipts, and verified
  GitHub backup remain separate gates owned by the coordinator.

Independent QA owns this checklist/evaluator only. Generation owns candidate
changes; release owner controls activation. Broad backlog and automatic releases
remain disabled; Jetson retains one inference lane.
