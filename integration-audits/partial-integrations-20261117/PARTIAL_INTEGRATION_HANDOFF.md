# Partial-company integration handoff — 17 November 2026

<!-- AGENT_WORKFLOW_START -->
## Agent role and next-item instructions

**Your role: Job Scraper Integration Engineer.** Use this handoff to implement and verify the next unfinished integration task in `/home/chris/job-search-helper_old`. Work on the fix, not just another plan. Complete one bounded task per invocation unless the user asks you to continue through more items. Follow current repository instructions and the user's authorized scope.

### Current next item

**W02/Aitech — Replace the historical fixed inventory-size check with complete current enumeration. Status: READY.**

Start with COMP-0428 Aitech Systems. Inspect its current official listing structure and existing fixed 17-link guard, then replace that historical count with complete employer-scoped enumeration, full descriptions, and a final reread through normal dispatch. Black River remains `IMPLEMENTED_AWAITING_VALIDATION` because its production `CareersTransport` cannot fetch the first public detail from this environment. Read the latest copy of this file before starting; if a task is already in progress, check its owner and saved work before continuing it or choosing another item.

**Priority order:** W01 → W03 transport fixes together with the overlapping Hughes W02 count fix → remaining W02 count fixes → W04 Lockheed routing → W06 Serve Robotics and Ubiquiti → W05 redirect repairs → W08 provider repairs → remaining discovery, scope, and access investigations. W07 must be resolved before enabling Caterpillar completeness. W09 is adoption verification of an existing implementation, not a request to build it again.

Split multi-company work orders into clearly named subtasks when appropriate. A completed subtask does not complete its whole work order or all affected companies.

### Required workflow

1. **Claim the task in this file before editing code.** Update the task ledger with the task/subtask ID, exact company scope, `IN_PROGRESS`, your task/agent identifier, and a UTC timestamp. Check current code and earlier progress so you do not duplicate or overwrite another agent's work.
2. **Implement the bounded fix.** Follow the selected work order and the acceptance contract later in this document. Preserve employer scope, stable job identity, full-description requirements, manual decisions, and saved valid work.
3. **Verify the result.** Run relevant regression checks and fresh validation through the normal dispatcher for the task's stated company scope. Record actual results. A fixture pass, a reachable page, or removal of the first error is not a fully integrated company. Keep installation, run adoption, and Sheet publication status separate from adapter validation.
4. **Update this handoff immediately when the task finishes, before your final response.** Update the ledger, add a dated progress-log entry, and add a current implementation note to each affected company entry. Record what changed, code/test paths, exact validation commands and evidence locations, results and counts, unresolved issues, deployment/adoption status, and the commit or backup reference. Preserve the original audit reasons and snapshot as historical evidence.
5. **Set the next item explicitly.** Replace the “Current next item” assignment with the highest-priority eligible unfinished task and a concrete first action. If part of a work order remains, say exactly which companies or checks are unfinished.
6. **Report incomplete work honestly.** Use `IMPLEMENTED_AWAITING_VALIDATION` when code is written but required validation is missing. Use `BLOCKED` with the exact failed step, evidence, and condition needed to resume when progress cannot continue. Do not mark a task `COMPLETE` or a company integrated merely because the code was committed. `COMPLETE` requires the stated implementation scope and required validation to pass; separately list any installation, run-adoption, or publication work still outside that scope.
7. **Save the updated handoff to GitHub with the work**, following the project instruction to save copies after updates. Refresh affected package hashes if maintaining `PACKAGE_MANIFEST.json`. In your final response, identify the completed task, verification, remaining limits, saved handoff, and next item.

This Markdown file is the live task record. The audit and source snapshots below describe 17 November 2026 and must not be presented as fresh run status after fixes. Update this file directly; do not regenerate it from the historical snapshots in a way that overwrites progress, task ownership, or company implementation notes.

### Task ledger

Only tasks explicitly recorded as complete with evidence are complete. Work orders absent from this ledger are unstarted unless their original description identifies an existing implementation, as W09 does.

| Task | Scope | Status | Owner / updated UTC | Outcome / next action |
|---|---|---|---|---|
| W01 | Shared Rippling parser; 13 listed companies | COMPLETE | /root / 2026-11-17T16:05:43Z | Added explicit old/new query-key validation. Twelve boards passed full normal-dispatch validation; goTenna is separately partial because its recorded board now returns HTTP 404 before parser execution. See `W01_RIPPLING_VALIDATION_2026-11-17.md`. |
| W03 + W02/Hughes | COMP-0118 Hughes Network Systems | COMPLETE | /root / 2026-11-17T16:32:11Z | Pinned the scoped EchoStar API transport and replaced the historical count/page assumption with dynamic enumeration and complete reread validation. Live normal dispatch completed with 6 full postings. See `W03_HUGHES_VALIDATION_2026-11-17.md`. |
| W02/Black River | COMP-0166 Black River Systems Company | IMPLEMENTED_AWAITING_VALIDATION | /root / 2026-11-17T16:40:00Z | Replaced the stale 14-link guard and added structural regression tests. The live normal-dispatch run did not finish within the bounded validation window, so no integration completion claim is made. |
| W02/Freefly | COMP-0171 Freefly Systems | COMPLETE | /root / 2026-11-17T16:48:00Z | Removed the stale 15-posting guard, retained structured inventory/detail/recheck validation, and completed live normal dispatch with 14 full postings. |
| W02/Aitech | COMP-0428 Aitech Systems | COMPLETE | /root / 2026-11-17T16:52:00Z | Removed the stale 17-link guard and completed live normal dispatch with 15 full postings and a stable final reread. |
| W02/JR Automation | COMP-0250 JR Automation | COMPLETE | /root / 2026-11-17T16:56:00Z | Replaced the stale 64-total and corrected canonical page paths; live normal dispatch completed with 59 full postings and a stable six-page reread. |
| W02/KUKA | COMP-0246 KUKA Robotics | COMPLETE | /root / 2026-11-17T17:00:00Z | Removed the stale 115-item gate while retaining the exact employer facet; live normal dispatch completed with 111 full postings and a stable reread. |

Statuses: `READY`, `IN_PROGRESS`, `IMPLEMENTED_AWAITING_VALIDATION`, `BLOCKED`, `COMPLETE`.

### Progress log

- **W01 / 13 Rippling companies / /root / 2026-11-17T16:13:00Z:**
- **Status and outcome:** COMPLETE for the shared parser repair. The parser accepts the current trailing `en-US` query-key form and the verified `true`/`false` boolean variant while rejecting non-boolean flags, unrecognized/ambiguous key layouts, non-`en-US` locale, and any filters. Twelve companies passed full normal-dispatch inventory validation with final rereads. goTenna remains partial because `https://ats.rippling.com/gotenna/jobs` returns HTTP 404; that is a source repair/discovery issue, not the parser exception.
- **Changes:** `src/job_search_helper/shared_boards.py` adds `_rippling_filters` and uses it before Rippling pagination validation. `tests/test_shared_boards.py` covers the trailing locale, both valid boolean states, malformed/ambiguous/filtered keys, wrong board identity, and a 21-posting two-page listing.
- **Verification:** `PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider' PYTHONPATH=src /home/chris/job-search-helper_old/.venv/bin/python -m pytest -q tests/test_shared_boards.py tests/test_rippling_locations.py` passed 20 tests. The full live normal-dispatch results, source URLs, counts, and final-recheck outcomes are in `W01_RIPPLING_VALIDATION_2026-11-17.md`.
- **Installation / run adoption / Sheet publication:** not performed. The validation invoked adapters read-only; it did not start a scraper cycle, write local inventory state, or publish to Google Sheets.
- **GitHub backup / commit:** pending this task's backup commit.
- **Remaining work or blocker:** COMP-0110 goTenna current source returns HTTP 404 and must remain partial until a verified employer-scoped public source is established. This does not invalidate the W01 parser repair.
- **Next task and exact first action:** W03 + W02/Hughes. Inspect the current Hughes public API response, narrow the allowed endpoint contract, and replace the exact 14-job/two-page check with dynamic reconciliation tests.

- **W03 + W02/Hughes / COMP-0118 Hughes Network Systems / /root / 2026-11-17T16:32:11Z:**
- **Status and outcome:** COMPLETE. The exact public `jobs.echostar.com/api/jobs?tags4=Hughes&page=<n>` route is now allowed only when its Hughes scope and bounded page parameter are present. The adapter no longer assumes 14 jobs or two pages; it enumerates all dynamic pages, checks stable totals, validates unique employer-scoped full-description records, and rereads full membership.
- **Changes:** `src/job_search_helper/ats.py` adds the narrow Hughes API allowlist. `src/job_search_helper/hughes.py` adds page validation, dynamic page traversal, row/total reconciliation, and full-inventory reread. `tests/test_hughes.py` covers normal top-level dispatch, below/above historical totals, explicit empty, malformed/duplicate/truncated/scope failures, changing membership, and transport restrictions.
- **Verification:** Focused regression passed 20 tests. Read-only production normal dispatch completed with six full postings (102169, 101937, 100842, 100916, 100844, 100999), full descriptions, and a stable final reread. See `W03_HUGHES_VALIDATION_2026-11-17.md`.
- **Installation / run adoption / Sheet publication:** not performed. No scraper cycle, local inventory state, or Google Sheets data was changed.
- **GitHub backup / commit:** pending this task's backup commit.
- **Remaining work or blocker:** none for the bounded Hughes adapter repair. Adoption by a future scraper run remains separate.
- **Next task and exact first action:** W02/Black River. Inspect the current employer listing route and replace the fixed 14-link guard with structural pagination/completeness validation.

- **W02/Black River / COMP-0166 Black River Systems Company / /root / 2026-11-17T16:40:00Z:**
- **Status and outcome:** IMPLEMENTED_AWAITING_VALIDATION. The adapter now accepts the verified first-party dated posting URL structure across years and no longer rejects the current 15-link inventory merely because it differs from a stale count of 14. It remains fail-closed for an unproven empty listing and preserves employer/full-description/detail validation plus a final link-set reread.
- **Changes:** `src/job_search_helper/black_river.py` replaces the fixed count with structural dated-posting recognition and an explicit nonempty-listing requirement. `tests/test_black_river.py` covers a 15-role inventory through normal dispatch, empty listings, incomplete descriptions, and changing final membership.
- **Verification:** Focused regression passed 17 tests. The 2026-11-17 public listing exposed 15 first-party role URLs and no pagination controls. The required live normal-dispatch validation was attempted twice; both attempts entered the public listing but did not return an inventory result before the bounded request window elapsed. The second bounded command stopped during detail retrieval without a result. No live completion count is recorded.
- **Installation / run adoption / Sheet publication:** not performed. No scraper cycle, local inventory state, or Google Sheets data was changed.
- **GitHub backup / commit:** pending this task's backup commit.
- **Remaining work or blocker:** isolate the slow public detail request or run the read-only normal dispatcher with a permitted longer validation window; then record the actual result and only then mark the company complete or partial.
- **Next task and exact first action:** W02/Black River remains the active next item. Inspect timed public detail retrieval one URL at a time, then rerun normal dispatch to a result.

- **W02/Freefly / COMP-0171 Freefly Systems / /root / 2026-11-17T16:48:00Z:**
- **Status and outcome:** COMPLETE. The adapter no longer treats a current 14-posting inventory as incomplete merely because it differs from the historical count of 15. It retains structured listing IDs, full employer-scoped details, duplicate validation, and stable final membership reread.
- **Changes:** `src/job_search_helper/freefly.py` removes the stale fixed count. `tests/test_freefly.py` covers normal dispatcher inventories below and above that count, invalid/empty listings, incomplete details, and changed final membership.
- **Verification:** Focused regression passed 17 tests. Read-only normal dispatch on 2026-11-17, using `CareersTransport(timeout=6, interval=0.2)`, completed with 14 full postings, all descriptions present, and a stable final reread.
- **Installation / run adoption / Sheet publication:** not performed. No scraper cycle, local inventory state, or Google Sheets data was changed.
- **GitHub backup / commit:** pending this task's backup commit.
- **Remaining work or blocker:** none for the bounded Freefly adapter repair. Adoption by a future scraper run remains separate.
- **Next task and exact first action:** W02/Aitech. Inspect its official listing contract and replace the stale 17-link guard with structural completeness validation.

After each task, append an entry using this structure:

- **Task / company scope / owner / updated UTC:**
- **Status and outcome:**
- **Changes:** code and test paths, with a short explanation.
- **Verification:** commands, evidence paths, live source/date, inventory and full-description counts, reconciliation results, and unresolved failures.
- **Installation / run adoption / Sheet publication:** state each separately; use “not performed” where applicable.
- **GitHub backup / commit:**
- **Remaining work or blocker:**
- **Next task and exact first action:**

<!-- AGENT_WORKFLOW_END -->

## Read this first

The best first repair is the shared Rippling listing parser: **13 partial companies** report the same exception, and the exact exception was reproduced against current public Forterra and DroneUp page data. Next address historical fixed job-count checks and HTML/API transport mismatches. These are concrete implementation problems, although clearing the first error does not establish complete inventory coverage.

This is an audit and implementation plan. No fixes described here were installed by this audit, no company was marked complete, no Sheet values were changed, and no scraper was started or stopped. The earlier Bosch Rexroth wrapper is an exception: it was already installed before this audit and needs run-level verification, not a duplicate implementation.

**Scope:** all 334 companies whose final cycle stage is `partial`. These are company inventory outcomes, not 334 individual job records. The separate blocked, failed, and unsupported companies are outside this list. Every partial has a record below containing its exact failure, source, disposition, and next step. Detailed code analysis and live probes are distinguished from initial triage; this document does not claim 334 complete live integration tests.

Runtime: `/home/chris/job-search-helper_old`. All code paths below are relative to that runtime unless stated otherwise. Requested handoff directory: `/home/chris/job-search-helper_old/temp/partial-integration-audit-20261117/`.

## Snapshot and evidence

The read-only local database snapshot at **2026-11-17 15:35:10 UTC / 10:35:10 EST** captured cycle `CYC-DE2DC903A35A`, started at 13:13:55 UTC and finished at 15:25:01 UTC. Its status is `Complete with exceptions`.

| Stage | Companies |
|---|---:|
| Complete | 402 |
| Partial — this audit | 334 |
| Blocked | 35 |
| Unsupported | 20 |
| Failed | 5 |
| Total | 796 |

The final cycle has no queued/fetching stage. This is **not evidence that Google Sheets publication has drained**; outbox delivery is a separate question and was not audited here. The displayed complete counter stays at 402 because a finished attempt can end partial. The generic browser fallback preserves found descriptions but explicitly does not establish a full inventory; neither zero pending URLs nor a successful detail pass is enough to promote its coverage to complete. See `README-AUTOMATED.md` and `docs/shared-ats-integrations.md`.

Evidence files alongside this report:

- `snapshot.json`: all 334 exact cycle reasons, company/source metadata, previous-cycle status, pending URL counts, and runtime Python source hashes. Company configuration is the local Companies cache, not a new live Sheet read. `last_inventory_count` may be historical and is not the current cycle's successful fetch count.
- `public-source-probes.json`: 173 distinct public source GET checks, including all 162 C1/C2/C3 records (shared exact URLs were deduplicated) and targeted adapter investigations. Records carry UTC timestamps, status, final URL, redirect chain, SHA-256 of the response, extracted candidate links, and relevant schema evidence. No full downloaded job bodies are included. These are bounded page checks, not full-board validations.
- `candidate-endpoint-probes.json`: five follow-up requests to candidate native endpoints. A successful response proves reachability/schema only; it does not prove all pages and full descriptions.
- `code-findings.json`: exact code lines/hashes, offline source-repair outputs, and reproductions for Caterpillar and Garrett Motion.
- `triage.json`: machine-readable per-company assignments and next actions, generated from the snapshot and reviewed overrides.
- `bosch-validation-summary.json`: compact receipt of the earlier same-day Rexroth validation, copied from the existing workspace artifact. It is not a fresh validation performed by this audit.
- `capture_snapshot.py`, `probe_sources.py`, `probe_candidates.py`, `capture_code_findings.py`, `build_handoff.py`, and `handoff-notes.md`: reproducible audit inputs. Re-run into a new dated directory to preserve this evidence.

The reason groups below are an **initial heuristic** based on the first direct-fetch failure, before browser fallback text. They are mutually exclusive for counting, but technical causes overlap. They are not estimates of guaranteed integrations. For example, Ansys TLS failure falls in A3 under this simple classifier, and Leidos's B1 record also reports a 2,000-result ceiling. Use each exact reason and the reviewed disposition, not just the group name.

| Initial reason group | Companies |
|---|---:|
| A1 Shared adapter exception | 13 |
| A2 Source/transport contract mismatch | 5 |
| A3 Provider parser/pagination/validation | 33 |
| B1 Workday access/response investigation | 48 |
| B2 Other access/HTTP response investigation | 56 |
| B3 Network/service failure | 13 |
| C1 Employer scope or multiple boards | 15 |
| C2 Native source discovery/routing | 128 |
| C3 Stale URL/redirect/request repair | 19 |
| D1 No proven public inventory | 4 |

Reviewed dispositions (not guaranteed successful conversions):

| Disposition | Companies |
|---|---:|
| Access and response investigation | 103 |
| Access plus inventory-ceiling investigation | 1 |
| Already implemented; run adoption pending | 1 |
| Canonical-source candidate | 1 |
| Correctness repair required before enablement | 1 |
| Employer scope needs proof | 15 |
| Existing adapter repair candidate | 1 |
| Existing detail parser candidate | 1 |
| Existing provider investigation | 18 |
| Existing provider pagination candidate | 1 |
| Existing provider parser candidate | 1 |
| Filtered scope repair candidate | 1 |
| Legacy URL normalization candidate | 1 |
| Native integration candidate | 9 |
| Native route mapping candidate | 1 |
| Native source discovery candidate | 1 |
| Native source unresolved | 1 |
| Network/TLS investigation | 1 |
| Network/source investigation | 13 |
| No complete public inventory yet proven | 1 |
| No proven complete public inventory | 4 |
| Provider discovery and scope candidate | 7 |
| Provider discovery candidate | 11 |
| Regional scope/integration gap | 1 |
| Regional/multiple-board scope needs proof | 2 |
| Source and parser migration candidate | 1 |
| Source configuration repair candidate | 1 |
| Source discovery still required | 92 |
| Source/redirect investigation | 15 |
| Strong canonical-source candidate | 1 |
| Strong native integration candidate | 2 |
| Strong provider-routing candidate | 1 |
| Strong repair candidate | 21 |
| Strong routing candidate | 1 |
| Successor/employer scope needs proof | 1 |

## First implementation work orders

### W01 — Repair the shared Rippling query-key schema (first priority)

Companies: Forterra COMP-0066; goTenna COMP-0110; Performance Drone Works COMP-0178; DroneUp COMP-0188; Bonsai Robotics COMP-0237; Advanced Navigation COMP-0260; ADLINK COMP-0288; Foundation COMP-0320; Blue Robotics COMP-0349; Kraken Robotics COMP-0350; Cyngn COMP-0483; Overland AI COMP-0495; Mytra COMP-0539.

**Confirmed:** `src/job_search_helper/shared_boards.py:414-415` selects `queryKey[-1]`, then calls `.get`. Current Forterra and DroneUp state is shaped like `["board", slug, "job-posts", true, {searchQuery, departments, workplaceType, country, state, city, page, pageSize}, "en-US"]`. The last item is a string. Both replays raise `AttributeError: 'str' object has no attribute 'get'` at line 415. See probe keys `rippling-forterra` and `rippling-droneup`, including traceback and actual query keys.

**Implement:** recognize explicitly validated old/new query-key layouts; identify the unique filter object with the required pagination/scope fields; validate board identity, locale and optional flag semantics. Reject ambiguous or malformed layouts as partial with a useful diagnostic. Keep total/page/pageSize checks, distinct-ID and duplicate-location handling, detail validation, and final membership reconciliation. Do not blindly choose any dictionary or suppress the exception.

**Tests/validation:** extend `tests/test_shared_boards.py`, `tests/test_shared_board_helpers.py`, and Rippling fixtures with a trailing locale, old key shape, missing/ambiguous filter object, actual filters, wrong board, duplicate locations, and multi-page inventory. The two live checks reproduced only page-one failure; run full normal-dispatch validation for those two boards, then one >20-job board and all 13 affected companies. An existing primary error can mask a later description failure.

### W02 — Replace historical fixed inventory sizes with completeness evidence

These count requirements are in production code, not just fixtures:

| Company | Code | Historical requirement | Current evidence |
|---|---|---|---|
| Black River COMP-0166 | `black_river.py:67` | exactly 14 links | cycle found 15; public page HTTP 200 |
| Freefly COMP-0171 | `freefly.py:54` | exactly 15 postings | cycle found 14; public page HTTP 200 |
| Aitech COMP-0428 | `aitech.py:49` | exactly 17 links | cycle found 15; public page HTTP 200 |
| JR Automation COMP-0250 | `jr_automation.py:158` | total exactly 64 | cycle rejects inventory size; filtered page HTTP 200; current total not extracted in this audit |
| KUKA COMP-0246 | `kuka.py:32` | exactly 115 feed items | cycle rejects count or foreign scope; current feed not independently fetched here |
| Hughes COMP-0118 | `hughes.py:24` | exactly 14 jobs / 2 pages | live public API HTTP 200, `totalCount=6`, six rows |
| ASTi COMP-0336 | `asti.py:48` | exactly 2 roles | latent count restriction behind current transport error; current role count not verified |

**Implement:** replace stale historical numbers with validated live totals, complete listing containers or an explicitly documented unpaginated feed, complete traversal, unique stable IDs, full detail coverage, and a final reread. Keep job-family/legal-entity scope guards independent of count. Use bounded reconciliation for listings that genuinely change during a scan. Changing 14 to 15 merely moves the defect to the next job opening. Simply deleting a count check without replacement completeness evidence is also insufficient.

For Hughes, make page count dynamic and validate every page/total/reread; do not still fetch page 2 unconditionally after allowing total 6. For JR, preserve the exact JR Automation brand filter and all-page reconciliation. For KUKA, retain `KUKA_FACET` validation; the recorded combined error does not prove count alone is the current cause. For ASTi, review title-derived posting IDs and duplicate title handling before broadening beyond two roles.

**Tests:** inventories both above and below the old size, explicit empty state, missing listing marker, duplicate/missing IDs, changed final membership, wrong employer, missing description, truncated page, and pagination across more than the old number of pages. Search existing tests by function name; several adapters have no same-named test file, so do not invent a path or assume coverage exists.

### W03 — Fix normal dispatch using the wrong transport

| Company | Confirmed code path | Repair |
|---|---|---|
| ASTi COMP-0336 | `ats.py:1023` supplies `discovery_transport or transport or HTTPTransport()` to a static HTML adapter; its own `CareersTransport()` default is bypassed | Use the validated HTML transport when no caller-supplied HTML transport exists; retain fixture injection |
| Mass Virtual COMP-0344 | same pattern at `ats.py:1037`; feed is rejected by `_safe_api_url` | Narrowly support its official Paylocity feed or use the adapter's validated public transport, then validate employer and full descriptions |
| Hughes COMP-0118 | `ats.py:1005` / `hughes.py` uses `HTTPTransport`; `jobs.echostar.com/api/jobs?tags4=Hughes&page=1` is not allowed | Add an exact scoped endpoint contract with query/page validation, plus W02 |
| VideoRay COMP-0348 | `videoray.py:147` falls back from missing HTML transport to the Workday API transport, then requests `videoray.com/about-us/careers/` | Keep separate HTML and Workday clients; preserve explicit VideoRay attribution and overlap handling |

**Live evidence:** ASTi page, Mass Virtual feed, and Hughes API all returned HTTP 200 to a bounded public GET. The production API URL guard independently rejected all three URLs with the exact recorded message. Mass Virtual feed currently has one job row; row completeness and end-to-end success remain unverified. VideoRay's code mismatch was inspected; its parent Workday and local full inventory were not freshly verified.

**Tests:** use the actual top-level `fetch_inventory` dispatch with mocked network boundaries and default client selection, not only adapter calls with permissive fake clients. Existing `tests/test_asti.py` and `tests/test_massvirtual.py` inject a fake directly and therefore miss this wiring failure. Retain tests for denied/unknown host, unsafe redirects, unsupported query changes, foreign employer, missing descriptions and unproven emptiness. Do not solve this by allowing arbitrary HTTPS API destinations.

### W04 — Reach the existing Lockheed integration

COMP-0074 current cached URL is `https://www.lockheedmartin.com/en-us/careers/`. The fresh official page links `https://lockheedmartin.eightfold.ai/careers`. `lockheed.py` already implements a scoped Eightfold inventory; `browser_scraper.py:635-638` dispatches to it only for the exact Eightfold URL. Offline `repair_source` with the current cached inputs returns the original Browser URL unchanged. The `company_sources.py` COMP-0074 repair entry does not recognize this current nonempty landing URL.

**Implement:** add the exact verified landing URL to accepted source aliases, preserving company ID/name checks; follow normal repair→browser dispatch through to the existing adapter. Validate existing Eightfold listing/detail/pagination and final reconciliation. Do not create another Lockheed scraper. Treat official page→tenant linkage as verified; complete current tenant operation is still untested here. Use `tests/test_eightfold_scan.py` and locate existing Lockheed tests by `fetch_lockheed` before adding dispatch regression coverage.

### W05 — Canonical redirect repairs with scope preserved

- **IERUS COMP-0449:** `https://hire.jobscore.com/jobs/ierustechnologiesinc/feed.atom` returns 301 to `https://careers.jobscore.com/jobs/ierustechnologiesinc/feed.atom`, which returns 200. `ierus.py` pins both source identity and detail host to the old host. Update the exact trusted canonical source, record/detail host guards and source aliases together; parse/reconcile the Atom feed and check whether it is truncated or paginated before calling it complete.
- **Scythe Robotics COMP-0506:** `https://app.dover.com/jobs/scytherobotics` redirects 301 to `https://jobs.dover.com/scytherobotics?src=app`, HTTP 200. `scythe_robotics.py` pins the old host/path. Inspect the new public page's actual inventory/empty-state contract; a 200 JS shell is not complete. Preserve tenant and stable posting identity.
- **GD Land Systems COMP-0097:** two HTTP 308 redirects lead from `/careers/job-search` to `/careers/search/`, preserving the encoded `state` query. Current endpoint HTTP 200. Inspect new Next.js search surface, re-prove the business-unit filter and all pages; don't assume a redirect alone fixes the old HTML parser. Use `gd_land_systems.py` and preserve checkpoint source compatibility deliberately.
- **MachineMetrics COMP-0278:** trailing-slash redirect resolves, and the official page embeds Greenhouse `machinemetrics`, but its public jobs API currently returns **404**. This is not a ready source substitution. Locate the current official inventory or explicitly preserve the unresolved state.

Do not blanket-enable redirects in every transport. Validate the exact official target and path/query semantics, with bounded redirect tests and foreign-host rejection.

### W06 — Native-board routes found on current official pages

These offer promising reuse of existing provider adapters. Links are official-page evidence; full inventory acceptance remains required.

| Company | Verified linkage / follow-up | Next implementation step |
|---|---|---|
| Serve Robotics COMP-0542 | official careers embeds `jobs.ashbyhq.com/serverobotics/embed?version=2`; public posting API HTTP 200 with **23 rows** | Add exact company/source repair to the Ashby route; validate full descriptions, IDs, visibility and reread through normal dispatch |
| Ubiquiti COMP-0749 | `careers.ui.com` links Greenhouse tenant `ubiquiti`; public jobs API HTTP 200 with **168 rows** | Reuse Greenhouse; verify counts/content, official tenant identity and all required details |
| RightHand Robotics COMP-0710 | official site embeds `righthand-robotics.breezy.hr`; `/json` returns HTTP 200 list | Reuse Breezy; detail coverage and final list reread remain necessary |
| Aerotech COMP-0789 | official careers page links `aerotech.applytojob.com/apply/`, HTTP 200 | Reuse JazzHR, validate complete listing marker/pagination/details |
| Zebra COMP-0538 | official page links `zebra.wd501.myworkdayjobs.com/Zebra_careers` | Reuse Workday; retain actual intended scope; do not copy login or job-family links as a full board |
| Booz Allen COMP-0623 | official redirect to `www.boozallen.com/careers.html` links `bah.wd1.myworkdayjobs.com/BAH_Jobs` | Exact source repair and normal Workday verification |
| CrowdStrike COMP-0663 | official page links `crowdstrike.wd5.myworkdayjobs.com/crowdstrikecareers` | Reuse Workday; choose validated full scope, not highlighted family filters |
| Bentley COMP-0667 | official page links `bentleysystems.wd5.myworkdayjobs.com/bentley` | Reuse Workday; avoid example `q=AI`/`q=ProjectWise` searches |
| Fortinet COMP-0660 | official page links `edel.fa.us2.oraclecloud.com/.../sites/CX_2001` | Reuse Oracle site resolver, validate tenant/site and all requisitions |
| onsemi COMP-0731 | official page links `hctz.fa.us2.oraclecloud.com/.../sites/CX_1001` | Reuse Oracle with explicit site and complete inventory validation |
| Texas Instruments COMP-0727 | official `careers.ti.com` serves Oracle page/resources for `edbz.fa.us2.oraclecloud.com`, site CX | Verify custom-host canonical mapping before adding it; asset hosts alone are insufficient scope proof |
| Garrett Motion COMP-0638 | official page links `ehth.fa.em2.oraclecloud.com/.../sites/CX_2001` | Existing `is_oracle_host` rejects **em2** (offline reproduction false); add narrowly validated regional host support and audit every Oracle resolver/transport host guard |
| Power Integrations COMP-0791 | official page embeds `jobs.jobvite.com/power-integrations/?nl=1&fr=true` | Canonicalize known embedding parameters to a validated full board; reuse Jobvite, coordinate with Samtec parser work |
| SMC COMP-0568 | official custom page references Dayforce tenant `smcnorthamerica/CANDIDATEPORTAL`; link observed is a privacy page, plus a custom same-site search API link | Verify actual official job-board route and public listing contract first; do not mistake privacy linkage for complete board evidence |

SuccessFactors-backed candidates with current provider markers include Festo COMP-0560, Danfoss COMP-0570, ATS Corp COMP-0573, Crown COMP-0588, Tennant COMP-0594, Krones COMP-0604, Teradyne COMP-0620, CommScope COMP-0658, Supermicro COMP-0740, congatec COMP-0742, and Endress+Hauser COMP-0765. Reuse `successfactors.py` / Jobs2Web where the actual canonical listing fits; inspect the correct employer, locale, subsidiary and country scopes. Asset markers alone do not establish a valid adapter route.

Phenom markers on Zimmer Biomet COMP-0554, Trane COMP-0564, Oshkosh/JLG COMP-0621/0622, Arrow COMP-0779, Thermo Fisher COMP-0780 and Danaher COMP-0781 justify examining `phenom.py`. Several URLs are job categories or regional filters: preserve that configured intent until a verified scope change is authorized. Do not silently replace JLG or Danaher with an entire parent-company inventory.

### W07 — Caterpillar requires a correctness repair, not just a URL change

COMP-0238 is configured at `https://www.caterpillar.com/en/careers.html`, while `caterpillar.py:70-74` accepts only `careers.caterpillar.com`. The source mismatch is confirmed. The fresh official page includes a Caterpillar Workday login link, which is a candidate for further official route discovery, not proof of full board scope.

**Additional confirmed offline defect:** `_parse_xml` examines a node's child tag names, then searches recursively for the first job's fields. For synthetic `<jobs><job id=one>…</job><job id=two>…</job></jobs>` it emits **one** record. See exact XML and output in `code-findings.json`. Existing `tests/test_caterpillar.py` uses duplicate IDs and therefore does not reveal loss of a second distinct job.

The HTML fallback can emit empty descriptions, and `fetch_caterpillar` currently returns complete for any nonempty parsed list without independently proving total, all pages, US country scope or final membership. Keep this route fail-closed while fixing it. Prefer a current official native inventory if verified; otherwise correct record iteration, explicit scope, description retrieval, pagination and final reconciliation. Add two-distinct-record, missing-description, non-US, truncated/paginated and changing-listing tests before allowing complete.

### W08 — Other existing provider repairs worth a targeted pass

- **Samtec COMP-0739:** Jobvite source returned 200 and real `/samtec/job/...` links. `shared_boards.py:536-538` requires literal `jv-job-list`. Capture new complete-list markup or public feed and update structural validation, preserving explicit-empty detection and pagination. Do not treat any visible link subset as the full board.
- **Arm COMP-0724:** TalentBrew reported 452 total, retained 15, then failed to identify page 2. Current root returns 200. Inspect `shared_extended.py` page/next-link parser and canonical URLs; test all-page enumeration, repeated-page detection and final count. Apply provider improvement to Applied Materials COMP-0793 only after verifying its separate TalentBrew tenant and listing semantics.
- **Dematic COMP-0248:** configured `/KION_SCS?Country=...` is neither a supported path nor unfiltered source under `dematic.py`. Source repair currently leaves it unchanged. Determine intended country subset, validate filter IDs, and support that exact scope or an explicitly accepted replacement; do not drop all country filters just to pass the guard.
- **Lattice COMP-0736:** discovered Workday URL contains old browser parameters (`bga`, `hashed`, dimensions, timezone offsets, etc.). Distinguish harmless old embed metadata from actual filters using verified current board state. Pin the exact canonical board only when same scope is established; keep unknown filters fail-closed.
- **Gray Solutions COMP-0398:** recorded guard explicitly requires Gray AES successor `searchPositionType=37044`. Verify that legal/employer mapping and exact public iCIMS filter; never import the whole Gray family to satisfy a company row.
- **Amentum COMP-0005, HII COMP-0080, Komatsu COMP-0240:** inspect actual published total/range/page membership contract against their existing adapters. Missing totals and repeated IDs can be either changed markup or a real incomplete fetch; retain partial on ambiguity.
- **GDIT COMP-0011, MITRE COMP-0025, Textron COMP-0088, Honeywell Aerospace COMP-0436, Amphenol COMP-0490:** recorded listing drift/count disagreement calls for bounded reconciliation and stable final membership, not relaxed counts. MITRE already reports exhausted reconciliation; first determine whether the source is continually changing.
- **Field AI COMP-0217, u-blox COMP-0257, Emerson COMP-0555, BELL COMP-0631, Embraer COMP-0634:** individual malformed/missing descriptions or underfilled inventory. Re-fetch exact recorded IDs; distinguish closed posting from schema variation. Preserve full-description validation. BELL's 41 unique vs 105 advertised also requires Taleo page coverage, not just one description fix.
- **Genasys COMP-0300, Hallam-ICS COMP-0397, MilDef COMP-0429, COMROD COMP-0488:** respectively provider identity, SaaShr link parsing, Teamtailor pagination, and newly out-of-scope role link. Capture actual changed response first; preserve identity and completeness invariants.
- **ECS Solutions COMP-0405, Savox COMP-0494:** no verified jobs/explicit empty inventory. Add an explicit provider empty-state contract only if supported by current source evidence; absence of parsed links is insufficient.
- **Vanderlande COMP-0529:** discovery and configured ATS disagree; verify the current board then repair ATS+URL together. Check the separate Bastian row for parent/subsidiary overlap.

### W09 — Bosch Rexroth is already implemented; validate adoption

COMP-0571 remains partial in this completed cycle because its recorded attempt fetched 5,047 Bosch Group postings and failed validation on 15. The current runtime already contains `bosch_rexroth.py` and the exact company dispatcher at `ats.py:751-754`. Earlier same-day isolated live validation returned complete with **70 US Bosch Rexroth Corporation postings**, after rechecking 355 US Bosch listing cards, in 36.78 seconds. That receipt is summarized alongside this file; it does not update this cycle or prove Sheet publication.

Do not rebuild or revert this adapter. Verify the installed source hash matches the receipt, then validate it through the next authorized fresh process/normal run. A running Python process can retain already imported code. Preserve scoped source identity, SmartRecruiters posting IDs, and manual decisions. The broad Bosch parent inventory must not become the Rexroth inventory. Existing GitHub package: branch `integration/bosch-rexroth-20261117`, commit `ff382f890d36f069d4248ada44320a6219be8e00`, directory `integration-updates/bosch-rexroth-20261117` in `Jeckell102/job-search-helper`.

## Cases that cannot yet be promised as full integrations

**Access/response investigations (117 initial-group records):** 48 Workday, 56 other access/HTTP failures, 13 network/service failures. These are the recorded first-error groupings, not 117 proven site blocks. Workday often fails after several pages/details, and Leidos additionally hits a 2,000-result ceiling. Gather exact failed URL, status, content type, bounded response classification, page/offset and current concurrency. `_challenge` in `ats.py` already avoids treating normal successful JSON containing a keyword as a challenge; do not assume every recorded challenge is a simple false positive. Check per-host pacing/bounded retries and public source correctness. Genuine login/CAPTCHA/access-denied cases stay unresolved; no bypass is part of this plan. Existing native support does not mean a new wrapper will fix access.

**Employer scope/multiple boards (15 initial-group records, plus overlapping cases):** parent-company boards are not automatically company inventories. DroneSense→Versaterm, Dedrone→Axon, AMERGINT→CACI, CAE USA, Fox Robotics→Symbotic, JLG→Oshkosh, Hitachi Energy→Hitachi, Airbus US Space & Defense→Airbus and Accenture Federal→Accenture require explicit attributable scope. Prove legal entity/brand/business-unit facet or an official complete set of boards. Keep true US/subsidiary constraints. Keyword search and a location match are not always employer attribution. Geek+ and Astroscale already report subset/stale board ambiguity; do not silently widen to all regional companies.

**No proven public inventory (4 explicit initial-group records):** Perennial Autonomy COMP-0167, SkySafe COMP-0169, Blues COMP-0281 and Glenair COMP-0489. Current cycle evidence indicates homepage/contact, LinkedIn-only, or interest form rather than a complete public jobs list. These need a new official public source before a full scraper can be justified. The four were not newly probed in this audit. XOCEAN COMP-0354 and some other discovery-group companies may ultimately belong here too; a missing ATS link alone does not prove absence of jobs.

**Discovery still unresolved:** many C2 sources return a reachable page without a native board. The per-company register includes final URL and candidate links/markers where observed. An HTML page, a provider logo/script, a talent-community link or one job detail is only a lead. Examples of false positives in automated extraction include ModalAI's blog article about greenhouse farming and Timken's greenhouse-gas reference: neither establishes the Greenhouse ATS. Ignore raw marker-only guesses until linked public inventory is verified.

## Acceptance contract for the implementation agent

1. Re-read current repository instructions and current runtime files. Compare `snapshot.json` source hashes before editing. The installed runtime has newer modules than GitHub main; do not overwrite it with the older main checkout or apply a broad archive. Work in an isolated copy/branch and keep the user's existing modifications.
2. Confirm the exact company ID, name, configured source and intended geography/business-unit scope. Add source repairs only for exact known aliases. Use current official employer→board evidence, not an inferred slug or search result. In particular, preserve manual source/filter choices unless replacement scope is demonstrably equivalent or authorized.
3. Implement one shared fix/work order at a time. Use the real normal dispatcher and production transport contracts in tests. Retain meaningful diagnostics with page/posting ID and preserve saved valid jobs on partial failures.
4. `complete` requires a verified complete enumeration (including pagination/total/explicit-empty contract), unique canonical stable IDs, full public descriptions for every in-scope active posting, and a final stable membership check or bounded reconciliation. Listing size can change legitimately. Every unresolved detail, ambiguous scope, truncation or challenge remains partial/blocked/unsupported as appropriate.
5. Validate fixtures and then the actual public source through normal dispatch without Sheet/database publication. Document date, source, scope, listing total, unique IDs, fetched full descriptions, rejected/missing records, pages and reread results. A fixture-only pass or one HTTP 200 is not production completion. Test representative boards when changing a shared provider, then the affected cohort.
6. Keep original source/job identity stable where possible. If changing scope/ATS identity, explicitly review existing stored jobs, checkpoint keys and closure eligibility; do not convert prior parent-board records into employer-scoped jobs by relabeling them. Do not auto-close jobs from incomplete inventories. Protect manual selections, notes and existing Opportunities.
7. Before installing or resuming, inspect current process/locks in the actual host environment. Sandbox PID visibility alone is not reliable proof the scraper stopped. Never remove writer/scraper locks to force a second process. Recheck current cycle state and exact CLI semantics; this audited cycle already ended with exceptions, so do not blindly assume a resume will retry it.
8. Verify separately: adapter live success, run adoption/company completion, durable local inventory, and Google Sheets outbox delivery. Record each. Do not manually promote company stages or `Last Checked` to make the counter move.
9. Commit relevant code/tests/docs and save to the user's GitHub, preserving existing changes. This audit is documentation only; the future agent needs authorization for any additional operational changes outside that task's scope.

Suggested start order: W01 shared Rippling → W03 transport wiring with Hughes W02 → remaining W02 count contracts → W04 Lockheed routing → W06 Serve/Ubiquiti → W05 redirects → W08 provider-specific repairs → discovery/scoping/access investigations. Address W07 before enabling Caterpillar completeness.

## Full company register

The register is generated from the immutable snapshot plus reviewed implementation notes. `Initial group` is the automated reason bucket; `Disposition` is the reviewed work assignment. `Candidate code` is a navigation aid (name/ID text matching plus explicit corrections), not proof that runtime dispatch reached every listed module. Read the exact reason first. Source-probe candidate links are discovery leads, never automatic replacement URLs.

### COMP-0003 — Leidos

**Disposition:** Access plus inventory-ceiling investigation · **Work order:** Access investigations

**Initial group:** B1 Workday access/response investigation

**Configured source:** `Workday` — https://careers.leidos.com/

**Cycle source/result ATS:** https://leidos.wd5.myworkdayjobs.com/wday/cxs/leidos/External — `Workday`

**Exact recorded reason:** Verified company source repair: https://leidos.wd5.myworkdayjobs.com/External. Direct fetch returned partial: Leidos Workday listing reached its 2,000-result ceiling; Human verification detected; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Leidos reason includes both Workday 2000-result ceiling and challenge. Reconcile provider limit using verified disjoint public scope partitions if supported; separately classify denied responses. Neither retry nor larger offset alone proves complete.

**Candidate code:** `src/job_search_helper/workday.py`

**Existing test candidates:** `tests/test_workday.py`, `tests/test_workday_leidos.py`, `tests/test_workday_leidos_reconcile.py`, `tests/test_workday_reconcile.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0005 — Amentum

**Disposition:** Existing provider investigation · **Work order:** W08

**Initial group:** A3 Provider parser/pagination/validation

**Configured source:** `Amentum careers` — https://www.amentumcareers.com/jobs/search

**Cycle source/result ATS:** https://www.amentumcareers.com/jobs/search — `Amentum careers`

**Exact recorded reason:** Verified company source repair: https://www.amentumcareers.com/jobs/search. Direct fetch returned partial: Verified company source repair: https://www.amentumcareers.com/jobs/search. Amentum listing total is missing or ambiguous.. Browser fallback returned partial: Browser fallback saved 191 job descriptions; 2554 job URLs await retry. Inventory completeness unknown; no closure inference. Browser time limit reached (300 seconds); saved progress retained.

**Next action:** Reproduce the precise direct-fetch failure below, inspect listing/detail schema and completeness contract; keep unresolved records partial.

**Candidate code:** `src/job_search_helper/ats.py`, `src/job_search_helper/amentum.py`

**Existing test candidates:** `tests/test_amentum.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 2554 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0007 — Parsons

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B1 Workday access/response investigation

**Configured source:** `Workday` — https://jobs.parsons.com/

**Cycle source/result ATS:** https://parsons.wd5.myworkdayjobs.com/wday/cxs/parsons/Search — `Workday`

**Exact recorded reason:** Verified company source repair: https://parsons.wd5.myworkdayjobs.com/wday/cxs/parsons/Search. Direct fetch returned partial: Workday listing page 1: Human verification detected; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Capture the failed Workday request page/posting and response classification; inspect host pacing and source filters. Validate all pages/details after recovery. Do not assume a new wrapper fixes genuine access denial.

**Candidate code:** `src/job_search_helper/workday.py`

**Existing test candidates:** `tests/test_workday.py`, `tests/test_workday_leidos.py`, `tests/test_workday_leidos_reconcile.py`, `tests/test_workday_reconcile.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0011 — General Dynamics Information Technology

**Disposition:** Existing provider investigation · **Work order:** W08

**Initial group:** A3 Provider parser/pagination/validation

**Configured source:** `Workday` — https://www.gdit.com/careers/

**Cycle source/result ATS:** https://gdit.wd5.myworkdayjobs.com/External_Career_Site — `Workday`

**Exact recorded reason:** Verified company source repair: https://gdit.wd5.myworkdayjobs.com/External_Career_Site. Direct fetch returned partial: GDIT Workday listing total changed during pagination.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Reproduce the precise direct-fetch failure below, inspect listing/detail schema and completeness contract; keep unresolved records partial.

**Candidate code:** `src/job_search_helper/ats.py`, `src/job_search_helper/gdit.py`

**Existing test candidates:** `tests/test_gdit.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0024 — Draper

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B1 Workday access/response investigation

**Configured source:** `Workday` — https://draper.wd5.myworkdayjobs.com/en-US/Draper_Careers

**Cycle source/result ATS:** https://draper.wd5.myworkdayjobs.com/wday/cxs/draper/Draper_Careers — `Workday`

**Exact recorded reason:** Direct fetch returned partial: Workday job detail https://draper.wd5.myworkdayjobs.com/Draper_Careers/job/Cambridge-MA/Senior-Embedded-Software-Engineer_JR003134: Human verification detected; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Capture the failed Workday request page/posting and response classification; inspect host pacing and source filters. Validate all pages/details after recovery. Do not assume a new wrapper fixes genuine access denial.

**Candidate code:** `src/job_search_helper/workday.py`

**Existing test candidates:** `tests/test_workday.py`, `tests/test_workday_leidos.py`, `tests/test_workday_leidos_reconcile.py`, `tests/test_workday_reconcile.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0025 — MITRE

**Disposition:** Existing provider investigation · **Work order:** W08

**Initial group:** A3 Provider parser/pagination/validation

**Configured source:** `Phenom (career site)` — https://careers.mitre.org/us/en

**Cycle source/result ATS:** https://careers.mitre.org/us/en/search-results?s=1 — `Phenom`

**Exact recorded reason:** Phenom listing page 8: Phenom bounded reconciliation exhausted; inventory remains incomplete. job detail R117056: Phenom posting closed during inventory retrieval.; job detail R116559: Phenom posting closed during inventory retrieval.

**Next action:** Reproduce the precise direct-fetch failure below, inspect listing/detail schema and completeness contract; keep unresolved records partial.

**Candidate code:** `src/job_search_helper/ats.py`, `src/job_search_helper/phenom.py`

**Existing test candidates:** `tests/test_phenom.py`, `tests/test_phenom_reconciliation.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0032 — Soar Technology (SoarTech)

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Browser` — https://lyntris.jobboardhq.com/search

**Cycle source/result ATS:** https://lyntris.jobboardhq.com/search — `Browser`

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found within the bounded careers-page discovery limit; the careers page is reachable but inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 20 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference.

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:07.934480+00:00; HTTP 200; final URL https://lyntris.jobboardhq.com/search; error none; evidence key `COMP-0032`.

**Extracted provider-link leads (unverified scope):** https://lyntris.jobboardhq.com ; https://lyntris.jobboardhq.com/ ; https://lyntris.jobboardhq.com/ScriptResource.axd?d=Jw6tUGWnA15YEa3ai3FadHl6_JjYF-x95kI_WIaKSWwOHQnes0uMW3App99rtvhIbKCcjSE9nvT-cxJoDNSNa10JVc3OnlRqiPhdWJCjRgcsxNTXabTbhx5uNn1p8XKEx7IvZ2albw9HclIxJTtcXvJ0giFHNWlHUv_vnZaDH2I1&t=ffffffffa1bf0f7b ; https://lyntris.jobboardhq.com/ScriptResource.axd?d=uHIkleVeDJf4xS50Krz-yIwJTlHyNULzgByZiirBLoXo8AJPUt3lV2ZqL31KDnZ6P-SnUcVIgwLhOXuAJ1hU0lgDLpkWfHLeW42ubm26H46Yz9_rCycfmwlHZGKKHl9zOS5ibCY8QnlHL_I_JfiDSTOdcMclDx-YkIGb-AX0tfs1&t=ffffffffa1bf0f7b ; https://lyntris.jobboardhq.com/WebResource.axd?d=pynGkmcFUV13He1Qd6_TZIwBPXDRDoteMDPctb39wKkcZGogurY93XBe051QPSwx_xnBF7g4iZ0kRMCsb6zKBA2&t=639256397503738887 ; https://lyntris.jobboardhq.com/atom.xml

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0038 — Intrepid

**Disposition:** Employer scope needs proof · **Work order:** Scope investigations

**Initial group:** C1 Employer scope or multiple boards

**Configured source:** `Jibe` — https://spa.jibeapply.com/jobs?_gl=1*1xw4g69*_gcl_au*MTcwODI3NjEwNy4xNzkwMjE2MjA2*_ga*MTk2NDgyMTExLjE3OTAyMTYyMDY.*_ga_8TYZBYXW22*czE3OTAyMTYyMDYkbzEkZzAkdDE3OTAyMTYyMTMkajUzJGwwJGgw*_ga_Q8X9MZDPVD*czE3OTAyMTYyMDYkbzEkZzAkdDE3OTAyMTYyMDYkajYwJGwwJGgw

**Cycle source/result ATS:** https://spa.jibeapply.com/jobs — `Jibe`

**Exact recorded reason:** Shared Jibe tenant does not establish this company scope.

**Next action:** Prove attributable employer/legal-entity/brand and complete board set before implementing or widening a parent/shared source. Verify each regional board and deduplicate stable IDs.

**Candidate code:** `src/job_search_helper/company_sources.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:07.934929+00:00; HTTP 200; final URL https://spa.jibeapply.com/jobs; error none; evidence key `COMP-0038`.

**Extracted provider-link leads (unverified scope):** https://spa.jibeapply.com/hiring-events ; https://spa.jibeapply.com/jobs ; https://spa.jibeapply.com/jobs?keywords=%7Bsearch_term_string%7D ; https://www.icims.com/legal/privacy-notice-website ; https://www.icims.com/legal/privacy-notice-website/ ; https://www.icims.com/legal/privacy-notice-website/?_sp=eb030d53-15f5-4ea0-bbef-e2e1151b7d86.1753378076070&_ga=2.178240486.2132387372.1753378064-2059501837.1753378064

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0043 — Digital Force Technologies

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `LinkedIn widget only` — https://www.digitalforcetech.com/company/careers/

**Cycle source/result ATS:** https://www.digitalforcetech.com/company/careers/ — ``

**Exact recorded reason:** Verified company source repair: https://www.digitalforcetech.com/company/careers/. Direct fetch returned partial: Verified company source repair: https://www.digitalforcetech.com/company/careers/. No supported ATS link found on careers page or obvious same-site job links; the careers page is reachable but may use another ATS or require JavaScript, so inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:07.935422+00:00; HTTP 200; final URL https://www.digitalforcetech.com/company/careers/; error none; evidence key `COMP-0043`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0048 — AMERGINT Technologies

**Disposition:** Employer scope needs proof · **Work order:** Scope investigations

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Acquisition / merged` — https://searchcareers.caci.com/careers

**Cycle source/result ATS:** https://searchcareers.caci.com/careers — `Acquisition / merged`

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found on careers page or obvious same-site job links; the careers page is reachable but may use another ATS or require JavaScript, so inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 10 job descriptions; 1 job URLs await retry. Inventory completeness unknown; no closure inference.

**Next action:** Official route leads to a broader parent board. Establish exact subsidiary/legal-entity attribution and complete filtered membership; do not relabel parent jobs under this company.

**Candidate code:** `src/job_search_helper/company_sources.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:07.935828+00:00; HTTP 200; final URL https://searchcareers.caci.com/careers; error none; evidence key `COMP-0048`.

**Provider text/asset leads only:** eightfold. These may be false positives; not a verified board.

**Checkpoint context:** 1 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0066 — Forterra

**Current implementation status (2026-11-17):** W01 validated complete through normal dispatch: 50 full postings with stable final inventory reread. See `W01_RIPPLING_VALIDATION_2026-11-17.md`.

**Disposition:** Strong repair candidate · **Work order:** W01

**Initial group:** A1 Shared adapter exception

**Configured source:** `Rippling` — https://www.forterra.com/careers

**Cycle source/result ATS:** https://ats.rippling.com/forterra/jobs — `Rippling`

**Exact recorded reason:** Verified company source repair: https://ats.rippling.com/forterra/jobs. Public board data/transport failed validation (AttributeError); inventory incomplete.

**Next action:** Repair shared Rippling query-key schema; verify the exact board, all pages, details and final membership.

**Candidate code:** `src/job_search_helper/shared_boards.py`

**Existing test candidates:** `tests/test_shared_boards.py`

**Fresh public check:** 2026-11-17T15:39:53.503910+00:00; HTTP 200; final URL https://ats.rippling.com/forterra/jobs; error none; evidence key `rippling-forterra`.

**Extracted provider-link leads (unverified scope):** https://app.rippling.com/legal/cookie-notice ; https://app.rippling.com/legal/privacy ; https://app.rippling.com/legal/user ; https://ats.rippling.com/de-DE/forterra/jobs ; https://ats.rippling.com/en-AU/forterra/jobs ; https://ats.rippling.com/en-CA/forterra/jobs

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0069 — AeroVironment

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B1 Workday access/response investigation

**Configured source:** `Workday` — https://avav.wd1.myworkdayjobs.com/AVAV

**Cycle source/result ATS:** https://avav.wd1.myworkdayjobs.com/wday/cxs/avav/AVAV — `Workday`

**Exact recorded reason:** Direct fetch returned partial: Workday listing page 4: Human verification detected; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Capture the failed Workday request page/posting and response classification; inspect host pacing and source filters. Validate all pages/details after recovery. Do not assume a new wrapper fixes genuine access denial.

**Candidate code:** `src/job_search_helper/workday.py`

**Existing test candidates:** `tests/test_workday.py`, `tests/test_workday_leidos.py`, `tests/test_workday_leidos_reconcile.py`, `tests/test_workday_reconcile.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0070 — Sierra Nevada Corporation

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B1 Workday access/response investigation

**Configured source:** `Workday` — https://snc.wd1.myworkdayjobs.com/SNC_External_Career_Site/

**Cycle source/result ATS:** https://snc.wd1.myworkdayjobs.com/wday/cxs/snc/SNC_External_Career_Site — `Workday`

**Exact recorded reason:** Direct fetch returned partial: Workday listing page 5: Human verification detected; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Capture the failed Workday request page/posting and response classification; inspect host pacing and source filters. Validate all pages/details after recovery. Do not assume a new wrapper fixes genuine access denial.

**Candidate code:** `src/job_search_helper/workday.py`

**Existing test candidates:** `tests/test_workday.py`, `tests/test_workday_leidos.py`, `tests/test_workday_leidos_reconcile.py`, `tests/test_workday_reconcile.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0072 — General Atomics Aeronautical Systems

**Disposition:** Employer scope needs proof · **Work order:** Scope investigations

**Initial group:** C1 Employer scope or multiple boards

**Configured source:** `BrassRing (shared parent board)` — https://www.ga.com/careers/

**Cycle source/result ATS:** https://www.ga.com/careers/ — ``

**Exact recorded reason:** Direct fetch returned partial: Shared/parent board requires an explicit company scope; automatic discovery cannot assign all parent-company jobs.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 3 job URLs await retry. Inventory completeness unknown; no closure inference.

**Next action:** Prove attributable employer/legal-entity/brand and complete board set before implementing or widening a parent/shared source. Verify each regional board and deduplicate stable IDs.

**Candidate code:** `src/job_search_helper/company_sources.py`, `src/job_search_helper/brassring.py`

**Existing test candidates:** `tests/test_brassring.py`

**Fresh public check:** 2026-11-17T15:39:07.936064+00:00; HTTP 200; final URL https://www.ga.com/careers/; error none; evidence key `COMP-0072`.

**Extracted provider-link leads (unverified scope):** https://community.brassring.com/GeneralAtomicsandAffiliatedCompanies/TalentCommunity ; https://sjobs.brassring.com/TGNewUI/Search/Home/Home?partnerid=25539&siteid=5310 ; https://sjobs.brassring.com/TGNewUI/Search/Home/Home?partnerid=25539&siteid=5310#home ; https://sjobs.brassring.com/TGNewUI/Search/Home/Home?partnerid=25539&siteid=5313 ; https://sjobs.brassring.com/TGNewUI/Search/Home/Home?partnerid=25539&siteid=5757 ; https://sjobs.brassring.com/TGNewUI/Search/Home/Home?partnerid=25539&siteid=5757#home

**Checkpoint context:** 3 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0074 — Lockheed Martin

**Disposition:** Strong routing candidate · **Work order:** W04

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Browser` — https://www.lockheedmartin.com/en-us/careers/

**Cycle source/result ATS:** https://www.lockheedmartin.com/en-us/careers/ — `Browser`

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found within the bounded careers-page discovery limit; the careers page is reachable but inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 2 job descriptions; 11 job URLs await retry. Inventory completeness unknown; no closure inference. Stopped this detail pass after 5 consecutive failures; unresolved URLs and saved descriptions retained.

**Next action:** Official page links existing Eightfold tenant; current repair_source leaves Browser URL unchanged. Add exact landing alias and verify existing Lockheed adapter through normal dispatch.

**Candidate code:** `src/job_search_helper/lockheed.py`, `src/job_search_helper/browser_scraper.py`, `src/job_search_helper/company_sources.py`

**Existing test candidates:** `tests/test_browser_scraper.py`, `tests/test_lockheed.py`

**Fresh public check:** 2026-11-17T15:39:08.397967+00:00; HTTP 200; final URL https://www.lockheedmartin.com/en-us/careers/; error none; evidence key `COMP-0074`.

**Extracted provider-link leads (unverified scope):** https://lockheedmartin.eightfold.ai/careers ; https://lockheedmartin.eightfold.ai/careers/join

**Checkpoint context:** 11 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0080 — HII Mission Technologies

**Disposition:** Existing provider investigation · **Work order:** W08

**Initial group:** A3 Provider parser/pagination/validation

**Configured source:** `SuccessFactors` — https://www.hii.com/careers

**Cycle source/result ATS:** https://jobs.hii-tsd.com/search/?q=&sortColumn=referencedate&sortDirection=desc — `SuccessFactors`

**Exact recorded reason:** Verified company source repair: https://jobs.hii-tsd.com/search/?q=&sortColumn=referencedate&sortDirection=desc. HII listing page is missing postings or repeats canonical IDs.

**Next action:** Reproduce the precise direct-fetch failure below, inspect listing/detail schema and completeness contract; keep unresolved records partial.

**Candidate code:** `src/job_search_helper/ats.py`, `src/job_search_helper/hii.py`

**Existing test candidates:** `tests/test_hii.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0083 — Curtiss-Wright Defense Solutions

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B1 Workday access/response investigation

**Configured source:** `Workday` — https://curtisswright.wd1.myworkdayjobs.com/CW_External_Career_Site

**Cycle source/result ATS:** https://curtisswright.wd1.myworkdayjobs.com/wday/cxs/curtisswright/CW_External_Career_Site — `Workday`

**Exact recorded reason:** Direct fetch returned partial: Workday listing page 12: Human verification detected; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Capture the failed Workday request page/posting and response classification; inspect host pacing and source filters. Validate all pages/details after recovery. Do not assume a new wrapper fixes genuine access denial.

**Candidate code:** `src/job_search_helper/workday.py`

**Existing test candidates:** `tests/test_workday.py`, `tests/test_workday_leidos.py`, `tests/test_workday_leidos_reconcile.py`, `tests/test_workday_reconcile.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0086 — Ultra Intelligence & Communications

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B1 Workday access/response investigation

**Configured source:** `Workday` — https://ultra.wd3.myworkdayjobs.com/en-US/UICCareers

**Cycle source/result ATS:** https://ultra.wd3.myworkdayjobs.com/wday/cxs/ultra/UICCareers — `Workday`

**Exact recorded reason:** Direct fetch returned partial: Workday listing page 1: Human verification detected; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Capture the failed Workday request page/posting and response classification; inspect host pacing and source filters. Validate all pages/details after recovery. Do not assume a new wrapper fixes genuine access denial.

**Candidate code:** `src/job_search_helper/workday.py`

**Existing test candidates:** `tests/test_workday.py`, `tests/test_workday_leidos.py`, `tests/test_workday_leidos_reconcile.py`, `tests/test_workday_reconcile.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0088 — Textron Systems

**Disposition:** Existing provider investigation · **Work order:** W08

**Initial group:** A3 Provider parser/pagination/validation

**Configured source:** `Taleo` — https://www.textronsystems.com/careers/apply-today

**Cycle source/result ATS:** https://www.textronsystems.com/careers/apply-today — `Taleo`

**Exact recorded reason:** Direct fetch returned partial: Scoped careers listing count changed during pagination. Scoped careers page returned 219 unique postings out of maximum reported total 257. Scoped careers listing total changed during the lifecycle scan; inventory is not stable.. Browser fallback returned partial: Browser-scoped careers count changed during pagination. Browser fallback retrieved 227 scoped postings out of maximum reported total 257.

**Next action:** Reproduce the precise direct-fetch failure below, inspect listing/detail schema and completeness contract; keep unresolved records partial.

**Candidate code:** `src/job_search_helper/ats.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0093 — Teledyne FLIR Defense

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B1 Workday access/response investigation

**Configured source:** `Workday` — https://flir.wd1.myworkdayjobs.com/flircareers/jobs

**Cycle source/result ATS:** https://flir.wd1.myworkdayjobs.com/wday/cxs/flir/flircareers — `Workday`

**Exact recorded reason:** Direct fetch returned partial: Workday listing page 7: Human verification detected; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Capture the failed Workday request page/posting and response classification; inspect host pacing and source filters. Validate all pages/details after recovery. Do not assume a new wrapper fixes genuine access denial.

**Candidate code:** `src/job_search_helper/workday.py`

**Existing test candidates:** `tests/test_workday.py`, `tests/test_workday_leidos.py`, `tests/test_workday_leidos_reconcile.py`, `tests/test_workday_reconcile.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0096 — General Dynamics Mission Systems

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B2 Other access/HTTP response investigation

**Configured source:** `GDMS Careers` — https://gdmissionsystems.com/careers/job-search

**Cycle source/result ATS:** https://gdmissionsystems.com/careers/job-search — `GDMS Careers`

**Exact recorded reason:** Direct fetch returned partial: GDMS public careers page was unavailable (HTTP 403).. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 403).

**Next action:** Confirm current public official source and classify actual response (challenge, rate limit, changed route or other error). Respect denial; preserve partial data. A new wrapper is not yet justified.

**Candidate code:** `src/job_search_helper/discovery.py`, `src/job_search_helper/gdms.py`

**Existing test candidates:** `tests/test_gdms.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0097 — General Dynamics Land Systems

**Disposition:** Source and parser migration candidate · **Work order:** W05

**Initial group:** C3 Stale URL/redirect/request repair

**Configured source:** `GD Land Systems` — https://www.gdls.com/careers/

**Cycle source/result ATS:** https://www.gd.com/careers/job-search?state=H4sIAAjv5GoAAx2KQQqAIBQFrxJv3QlaB23atfRLfPS3Sgu1QMS7Z%2B5mmClga4PEiEnpEQcbSY2hCsGzE8JEMBxEwm4ud7PPhJHw8vlIbPUfu%2FRzmYeVvR22HJO41quuGvUDfvIOQ2YAAAA%3D — `GD Land Systems`

**Exact recorded reason:** Verified company source repair: https://www.gd.com/careers/job-search?state=H4sIAAjv5GoAAx2KQQqAIBQFrxJv3QlaB23atfRLfPS3Sgu1QMS7Z%2B5mmClga4PEiEnpEQcbSY2hCsGzE8JEMBxEwm4ud7PPhJHw8vlIbPUfu%2FRzmYeVvR22HJO41quuGvUDfvIOQ2YAAAA%3D. Direct fetch returned partial: General Dynamics public careers route returned HTTP 308 after bounded retries.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 2 job URLs await retry. Inventory completeness unknown; no closure inference.

**Next action:** Verified two 308 redirects to /careers/search/ with state preserved. Re-prove GD Land Systems business-unit scope and new listing contract; redirect alone may not repair Next.js parsing.

**Candidate code:** `src/job_search_helper/gd_land_systems.py`, `src/job_search_helper/ats.py`

**Existing test candidates:** `tests/test_gd_land_systems.py`

**Fresh public check:** 2026-11-17T15:39:08.634920+00:00; HTTP 200; final URL https://www.gd.com/careers/search/?state=H4sIAAjv5GoAAx2KQQqAIBQFrxJv3QlaB23atfRLfPS3Sgu1QMS7Z%2B5mmClga4PEiEnpEQcbSY2hCsGzE8JEMBxEwm4ud7PPhJHw8vlIbPUfu%2FRzmYeVvR22HJO41quuGvUDfvIOQ2YAAAA%3D; error none; evidence key `COMP-0097`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 2 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0098 — Blue Origin

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B1 Workday access/response investigation

**Configured source:** `Workday` — https://www.blueorigin.com/careers

**Cycle source/result ATS:** https://blueorigin.wd5.myworkdayjobs.com/wday/cxs/blueorigin/BlueOrigin — `Workday`

**Exact recorded reason:** Verified company source repair: https://blueorigin.wd5.myworkdayjobs.com/BlueOrigin. Direct fetch returned partial: Workday listing page 8: Human verification detected; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Capture the failed Workday request page/posting and response classification; inspect host pacing and source filters. Validate all pages/details after recovery. Do not assume a new wrapper fixes genuine access denial.

**Candidate code:** `src/job_search_helper/workday.py`

**Existing test candidates:** `tests/test_workday.py`, `tests/test_workday_leidos.py`, `tests/test_workday_leidos_reconcile.py`, `tests/test_workday_reconcile.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0099 — Sierra Space

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B1 Workday access/response investigation

**Configured source:** `Workday` — https://sierraspace.wd1.myworkdayjobs.com/Sierra_Space_External_Career_Site

**Cycle source/result ATS:** https://sierraspace.wd1.myworkdayjobs.com/wday/cxs/sierraspace/Sierra_Space_External_Career_Site — `Workday`

**Exact recorded reason:** Direct fetch returned partial: Workday listing page 10: Human verification detected; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Capture the failed Workday request page/posting and response classification; inspect host pacing and source filters. Validate all pages/details after recovery. Do not assume a new wrapper fixes genuine access denial.

**Candidate code:** `src/job_search_helper/workday.py`

**Existing test candidates:** `tests/test_workday.py`, `tests/test_workday_leidos.py`, `tests/test_workday_leidos_reconcile.py`, `tests/test_workday_reconcile.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0110 — goTenna

**Current implementation status (2026-11-17):** W01 parser repair is installed, but the recorded Rippling board currently returns HTTP 404 before parser execution. The company remains partial pending verified source repair/discovery. See `W01_RIPPLING_VALIDATION_2026-11-17.md`.

**Disposition:** Strong repair candidate · **Work order:** W01

**Initial group:** A1 Shared adapter exception

**Configured source:** `Rippling` — https://gotenna.com/pages/jobs

**Cycle source/result ATS:** https://gotenna.com/pages/jobs — `Rippling`

**Exact recorded reason:** Public board data/transport failed validation (AttributeError); inventory incomplete.

**Next action:** Repair shared Rippling query-key schema; verify the exact board, all pages, details and final membership.

**Candidate code:** `src/job_search_helper/shared_boards.py`

**Existing test candidates:** `tests/test_shared_boards.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0118 — Hughes Network Systems

**Current implementation status (2026-11-17):** W03 + W02/Hughes is validated complete. Normal dispatch returned six full Hughes-scoped postings with a stable complete-inventory reread after the narrow EchoStar API transport and dynamic pagination repair. See `W03_HUGHES_VALIDATION_2026-11-17.md`. Installation, scraper-run adoption, and Sheet publication were not performed.

**Disposition:** Strong repair candidate · **Work order:** W02 + W03

**Initial group:** A2 Source/transport contract mismatch

**Configured source:** `Hughes filtered EchoStar` — https://www.hughes.com/who-we-are/life-at-hughes-echostar

**Cycle source/result ATS:** https://www.hughes.com/who-we-are/life-at-hughes-echostar — `Hughes filtered EchoStar`

**Exact recorded reason:** Direct fetch returned partial: Only pinned official HTTPS API endpoints are allowed.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Live Hughes API returns 6 rows/totalCount 6 but production guard rejects URL, and module requires 14 jobs/two pages. Fix exact scoped transport and dynamic enumeration/reread together.

**Candidate code:** `src/job_search_helper/hughes.py`, `src/job_search_helper/ats.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:55.391108+00:00; HTTP 200; final URL https://jobs.echostar.com/api/jobs?tags4=Hughes&page=1; error none; evidence key `hughes-api`.

**Provider text/asset leads only:** icims. These may be false positives; not a verified board.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0130 — Motorola Solutions

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B1 Workday access/response investigation

**Configured source:** `Workday` — https://www.motorolasolutions.com/en_us/about/careers.html

**Cycle source/result ATS:** https://motorolasolutions.wd5.myworkdayjobs.com/Careers — `Workday`

**Exact recorded reason:** Verified company source repair: https://motorolasolutions.wd5.myworkdayjobs.com/Careers. Direct fetch returned blocked: Workday listing page 2: Human verification detected; manual review required.. Browser fallback returned partial: Browser fallback saved 20 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference.

**Next action:** Capture the failed Workday request page/posting and response classification; inspect host pacing and source filters. Validate all pages/details after recovery. Do not assume a new wrapper fixes genuine access denial.

**Candidate code:** `src/job_search_helper/workday.py`, `src/job_search_helper/rapiddeploy.py`

**Existing test candidates:** `tests/test_rapiddeploy.py`, `tests/test_workday.py`, `tests/test_workday_leidos.py`, `tests/test_workday_leidos_reconcile.py`, `tests/test_workday_reconcile.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0136 — Ericsson

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B2 Other access/HTTP response investigation

**Configured source:** `Ericsson Eightfold` — https://www.ericsson.com/en/careers

**Cycle source/result ATS:** https://jobs.ericsson.com/careers — `Ericsson Eightfold`

**Exact recorded reason:** Verified company source repair: https://jobs.ericsson.com/careers. Direct fetch returned partial: Verified company source repair: https://jobs.ericsson.com/careers. HTTP 403: access denied; manual review, no automatic retry.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 403).

**Next action:** Confirm current public official source and classify actual response (challenge, rate limit, changed route or other error). Respect denial; preserve partial data. A new wrapper is not yet justified.

**Candidate code:** `src/job_search_helper/discovery.py`, `src/job_search_helper/ericsson.py`, `src/job_search_helper/ats.py`

**Existing test candidates:** `tests/test_ericsson.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0140 — Cradlepoint

**Disposition:** Employer scope needs proof · **Work order:** Scope investigations

**Initial group:** C1 Employer scope or multiple boards

**Configured source:** `Eightfold (shared parent board)` — https://cradlepoint.ericsson.com/about/careers/

**Cycle source/result ATS:** https://cradlepoint.ericsson.com/about/careers/ — ``

**Exact recorded reason:** Direct fetch returned partial: Shared/parent board requires an explicit company scope; automatic discovery cannot assign all parent-company jobs.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Prove attributable employer/legal-entity/brand and complete board set before implementing or widening a parent/shared source. Verify each regional board and deduplicate stable IDs.

**Candidate code:** `src/job_search_helper/company_sources.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:08.799367+00:00; HTTP 200; final URL https://cradlepoint.ericsson.com/about/careers/; error none; evidence key `COMP-0140`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0153 — VIAVI Solutions

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B1 Workday access/response investigation

**Configured source:** `Workday` — https://viavisolutions.wd1.myworkdayjobs.com/careers

**Cycle source/result ATS:** https://viavisolutions.wd1.myworkdayjobs.com/wday/cxs/viavisolutions/careers — `Workday`

**Exact recorded reason:** Direct fetch returned partial: Workday listing page 1: Human verification detected; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Capture the failed Workday request page/posting and response classification; inspect host pacing and source filters. Validate all pages/details after recovery. Do not assume a new wrapper fixes genuine access denial.

**Candidate code:** `src/job_search_helper/workday.py`

**Existing test candidates:** `tests/test_workday.py`, `tests/test_workday_leidos.py`, `tests/test_workday_leidos_reconcile.py`, `tests/test_workday_reconcile.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `blocked`. Neither pending count nor this flag alone proves coverage.

### COMP-0154 — Analog Devices

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B1 Workday access/response investigation

**Configured source:** `Workday` — https://analogdevices.wd1.myworkdayjobs.com/External

**Cycle source/result ATS:** https://analogdevices.wd1.myworkdayjobs.com/wday/cxs/analogdevices/External — `Workday`

**Exact recorded reason:** Direct fetch returned partial: Workday listing page 1: Human verification detected; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Capture the failed Workday request page/posting and response classification; inspect host pacing and source filters. Validate all pages/details after recovery. Do not assume a new wrapper fixes genuine access denial.

**Candidate code:** `src/job_search_helper/workday.py`

**Existing test candidates:** `tests/test_workday.py`, `tests/test_workday_leidos.py`, `tests/test_workday_leidos_reconcile.py`, `tests/test_workday_reconcile.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0155 — Qorvo

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B2 Other access/HTTP response investigation

**Configured source:** `Browser` — https://www.qorvo.com/about/careers

**Cycle source/result ATS:** https://www.qorvo.com/about/careers — `Browser`

**Exact recorded reason:** Direct fetch returned failed: Careers page HTTP 429; board discovery did not complete.. Browser fallback returned partial: Browser fallback saved 2 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference.

**Next action:** Confirm current public official source and classify actual response (challenge, rate limit, changed route or other error). Respect denial; preserve partial data. A new wrapper is not yet justified.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0158 — Dedrone by Axon

**Disposition:** Employer scope needs proof · **Work order:** Scope investigations

**Initial group:** C1 Employer scope or multiple boards

**Configured source:** `Greenhouse (shared parent board)` — https://www.axon.com/careers

**Cycle source/result ATS:** https://www.axon.com/careers — ``

**Exact recorded reason:** Direct fetch returned partial: Shared/parent board requires an explicit company scope; automatic discovery cannot assign all parent-company jobs.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 3 job URLs await retry. Inventory completeness unknown; no closure inference.

**Next action:** Official route leads to a broader parent board. Establish exact subsidiary/legal-entity attribution and complete filtered membership; do not relabel parent jobs under this company.

**Candidate code:** `src/job_search_helper/company_sources.py`, `src/job_search_helper/ats.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:08.963844+00:00; HTTP 403; final URL https://www.axon.com/careers; error none; evidence key `COMP-0158`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 3 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0164 — Allen Control Systems

**Disposition:** Source/redirect investigation · **Work order:** W05 / source repair

**Initial group:** C3 Stale URL/redirect/request repair

**Configured source:** `Greenhouse` — https://job-boards.greenhouse.io/allencontrolsystems

**Cycle source/result ATS:** https://boards-api.greenhouse.io/v1/boards/allencontrolsystems/jobs?content=true — `Greenhouse`

**Exact recorded reason:** Direct fetch returned partial: HTTP 404; inventory unavailable, not evidence of closure.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 404).

**Next action:** Follow the exact current official link/redirect with bounded trusted destinations; validate replacement board and scope. A 404 is not closure. Test dispatch/source aliases and every page/detail.

**Candidate code:** `src/job_search_helper/company_sources.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:09.036667+00:00; HTTP 404; final URL https://boards-api.greenhouse.io/v1/boards/allencontrolsystems/jobs?content=true; error none; evidence key `COMP-0164`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0166 — Black River Systems Company

**Current implementation status (2026-11-17):** W02 code and regression coverage are implemented, but live normal-dispatch validation has not returned a result. The company remains partial until the public detail-retrieval delay is isolated and the complete inventory is validated.

**Disposition:** Strong repair candidate · **Work order:** W02

**Initial group:** A3 Provider parser/pagination/validation

**Configured source:** `Black River WordPress` — https://www.blackriversystems.com/careers/

**Cycle source/result ATS:** https://www.blackriversystems.com/job-opportunities/ — `Black River WordPress`

**Exact recorded reason:** Verified company source repair: https://www.blackriversystems.com/job-opportunities/. Direct fetch returned partial: Black River job link set changed; found 15 links.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Replace inspected historical fixed job count with structural/current-total completeness evidence, retain scope/detail checks and stable full reread. Recorded reason below identifies the current mismatch; KUKA count versus scope remains to isolate.

**Candidate code:** `src/job_search_helper/black_river.py`, `src/job_search_helper/ats.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:55.871774+00:00; HTTP 200; final URL https://www.blackriversystems.com/job-opportunities/; error none; evidence key `blackriver-page`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0167 — Perennial Autonomy

**Disposition:** No proven complete public inventory · **Work order:** No public inventory

**Initial group:** D1 No proven public inventory

**Configured source:** `Perennial Autonomy careers` — https://www.perennialautonomy.com/

**Cycle source/result ATS:** https://www.perennialautonomy.com/ — `Perennial Autonomy careers`

**Exact recorded reason:** Verified company source repair: https://www.perennialautonomy.com/. Verified company source repair: https://www.perennialautonomy.com/. Perennial Autonomy's official site exposes no public careers page, ATS, or verifiable job-posting inventory; completeness is unknown.

**Next action:** Seek a newly published official public job inventory; until one exists, preserve explicit unsupported/manual-source status and do not manufacture zero jobs from a contact or interest form.

**Candidate code:** `src/job_search_helper/company_sources.py`, `src/job_search_helper/ats.py`, `src/job_search_helper/perennial_autonomy.py`

**Existing test candidates:** `tests/test_perennial_autonomy.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0169 — SkySafe

**Disposition:** No proven complete public inventory · **Work order:** No public inventory

**Initial group:** D1 No proven public inventory

**Configured source:** `SkySafe official site` — https://www.skysafe.io/contact

**Cycle source/result ATS:** https://www.skysafe.io/contact — `SkySafe official site`

**Exact recorded reason:** Verified company source repair: https://www.skysafe.io/contact. Verified company source repair: https://www.skysafe.io/contact. SkySafe's official source does not expose a public employer-scoped ATS or verifiable job links; inventory completeness is unknown.

**Next action:** Seek a newly published official public job inventory; until one exists, preserve explicit unsupported/manual-source status and do not manufacture zero jobs from a contact or interest form.

**Candidate code:** `src/job_search_helper/company_sources.py`, `src/job_search_helper/ats.py`, `src/job_search_helper/skysafe.py`

**Existing test candidates:** `tests/test_skysafe.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0171 — Freefly Systems

**Current implementation status (2026-11-17):** W02/Freefly is validated complete. Normal dispatch returned 14 full Freefly postings with a stable final inventory reread after removal of the fixed-count guard. Installation, scraper-run adoption, and Sheet publication were not performed.

**Disposition:** Strong repair candidate · **Work order:** W02

**Initial group:** A3 Provider parser/pagination/validation

**Configured source:** `Freefly Careers` — https://freeflysystems.com/careers

**Cycle source/result ATS:** https://freeflysystems.com/careers/open — `Freefly Careers`

**Exact recorded reason:** Direct fetch returned partial: Freefly careers inventory changed; found 14 postings.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 1 job URLs await retry. Inventory completeness unknown; no closure inference.

**Next action:** Replace inspected historical fixed job count with structural/current-total completeness evidence, retain scope/detail checks and stable full reread. Recorded reason below identifies the current mismatch; KUKA count versus scope remains to isolate.

**Candidate code:** `src/job_search_helper/freefly.py`, `src/job_search_helper/ats.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:56.093410+00:00; HTTP 200; final URL https://freeflysystems.com/careers/open; error none; evidence key `freefly-page`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 1 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0172 — Inspired Flight Technologies

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `` — https://www.inspiredflight.com/careers

**Cycle source/result ATS:** https://www.inspiredflight.com/careers — ``

**Exact recorded reason:** Verified company source repair: https://www.inspiredflight.com/careers. Direct fetch returned partial: Verified company source repair: https://www.inspiredflight.com/careers. No supported ATS link found on careers page or obvious same-site job links; the careers page is reachable but may use another ATS or require JavaScript, so inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:09.241683+00:00; HTTP 200; final URL https://www.inspiredflight.com/careers; error none; evidence key `COMP-0172`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0173 — ModalAI

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `` — https://www.modalai.com/pages/careers

**Cycle source/result ATS:** https://www.modalai.com/pages/careers — ``

**Exact recorded reason:** Verified company source repair: https://www.modalai.com/pages/careers. Direct fetch returned partial: Verified company source repair: https://www.modalai.com/pages/careers. No supported ATS link found on careers page or obvious same-site job links; the careers page is reachable but may use another ATS or require JavaScript, so inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Automated greenhouse marker is a blog about agricultural greenhouses, not an ATS. Inspect actual official openings; no supported inventory proved by this audit.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:09.246091+00:00; HTTP 200; final URL https://www.modalai.com/pages/careers; error none; evidence key `COMP-0173`.

**Extracted provider-link leads (unverified scope):** https://www.modalai.com/blogs/in-the-news/modalai-helps-make-greenhouse-profits-bloom

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0178 — Performance Drone Works (PDW)

**Current implementation status (2026-11-17):** W01 validated complete through normal dispatch: 39 full postings with stable final inventory reread. See `W01_RIPPLING_VALIDATION_2026-11-17.md`.

**Disposition:** Strong repair candidate · **Work order:** W01

**Initial group:** A1 Shared adapter exception

**Configured source:** `Rippling` — https://ats.rippling.com/pdwcareers/jobs

**Cycle source/result ATS:** https://ats.rippling.com/pdwcareers/jobs — `Rippling`

**Exact recorded reason:** Public board data/transport failed validation (AttributeError); inventory incomplete.

**Next action:** Repair shared Rippling query-key schema; verify the exact board, all pages, details and final membership.

**Candidate code:** `src/job_search_helper/shared_boards.py`

**Existing test candidates:** `tests/test_shared_boards.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0180 — Ascent AeroSystems

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B2 Other access/HTTP response investigation

**Configured source:** `Gusto` — https://jobs.gusto.com/boards/robinson-unmanned-ab0be6b1-c413-41d2-9d68-f62c878589e4

**Cycle source/result ATS:** https://jobs.gusto.com/boards/robinson-unmanned-ab0be6b1-c413-41d2-9d68-f62c878589e4 — `Gusto`

**Exact recorded reason:** Direct fetch returned partial: Gusto public board HTTP 403; access was denied.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 403).

**Next action:** Confirm current public official source and classify actual response (challenge, rate limit, changed route or other error). Respect denial; preserve partial data. A new wrapper is not yet justified.

**Candidate code:** `src/job_search_helper/discovery.py`, `src/job_search_helper/ats.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0185 — DroneSense

**Disposition:** Employer scope needs proof · **Work order:** Scope investigations

**Initial group:** C1 Employer scope or multiple boards

**Configured source:** `Greenhouse (shared parent board)` — https://www.versaterm.com/careers/

**Cycle source/result ATS:** https://www.versaterm.com/careers/ — ``

**Exact recorded reason:** Direct fetch returned partial: Shared/parent board requires an explicit company scope; automatic discovery cannot assign all parent-company jobs.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Official route leads to a broader parent board. Establish exact subsidiary/legal-entity attribution and complete filtered membership; do not relabel parent jobs under this company.

**Candidate code:** `src/job_search_helper/company_sources.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:09.303120+00:00; HTTP 200; final URL https://www.versaterm.com/careers/; error none; evidence key `COMP-0185`.

**Extracted provider-link leads (unverified scope):** https://job-boards.greenhouse.io/versaterm

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0188 — DroneUp

**Current implementation status (2026-11-17):** W01 validated complete through normal dispatch: zero postings under an explicit complete public inventory and stable final reread. See `W01_RIPPLING_VALIDATION_2026-11-17.md`.

**Disposition:** Strong repair candidate · **Work order:** W01

**Initial group:** A1 Shared adapter exception

**Configured source:** `Rippling` — https://ats.rippling.com/droneup/jobs

**Cycle source/result ATS:** https://ats.rippling.com/droneup/jobs — `Rippling`

**Exact recorded reason:** Public board data/transport failed validation (AttributeError); inventory incomplete.

**Next action:** Repair shared Rippling query-key schema; verify the exact board, all pages, details and final membership.

**Candidate code:** `src/job_search_helper/shared_boards.py`

**Existing test candidates:** `tests/test_shared_boards.py`

**Fresh public check:** 2026-11-17T15:39:53.755409+00:00; HTTP 200; final URL https://ats.rippling.com/droneup/jobs; error none; evidence key `rippling-droneup`.

**Extracted provider-link leads (unverified scope):** https://app.rippling.com/legal/cookie-notice ; https://app.rippling.com/legal/privacy ; https://app.rippling.com/legal/user ; https://ats.rippling.com/de-DE/droneup/jobs ; https://ats.rippling.com/droneup/jobs ; https://ats.rippling.com/en-AU/droneup/jobs

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0195 — Flying Lion

**Disposition:** Source/redirect investigation · **Work order:** W05 / source repair

**Initial group:** C3 Stale URL/redirect/request repair

**Configured source:** `Browser` — (not set)

**Cycle source/result ATS:** https://flyinglioninc.com/careers — ``

**Exact recorded reason:** Verified company source repair: https://flyinglioninc.com/careers. Direct fetch returned partial: Verified company source repair: https://flyinglioninc.com/careers. Careers page HTTP 404; board discovery did not complete.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 404).

**Next action:** Follow the exact current official link/redirect with bounded trusted destinations; validate replacement board and scope. A 404 is not closure. Test dispatch/source aliases and every page/detail.

**Candidate code:** `src/job_search_helper/company_sources.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:09.565673+00:00; HTTP 404; final URL https://flyinglioninc.com/careers; error none; evidence key `COMP-0195`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0200 — Symbotic

**Disposition:** Employer scope needs proof · **Work order:** Scope investigations

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Browser` — https://www.symbotic.com/careers/

**Cycle source/result ATS:** https://www.symbotic.com/careers/ — `Browser`

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found within the bounded careers-page discovery limit; the careers page is reachable but inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 127 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference.

**Next action:** Both rows use Symbotic careers. Prove independent Fox Robotics attribution and scope before integrating; never duplicate whole Symbotic inventory under Fox.

**Candidate code:** `src/job_search_helper/company_sources.py`, `src/job_search_helper/symbotic.py`

**Existing test candidates:** `tests/test_symbotic.py`

**Fresh public check:** 2026-11-17T15:39:09.813523+00:00; HTTP 200; final URL https://www.symbotic.com/careers/; error none; evidence key `COMP-0200`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0217 — Field AI

**Disposition:** Existing provider investigation · **Work order:** W08

**Initial group:** A3 Provider parser/pagination/validation

**Configured source:** `Lever` — https://www.fieldai.com/careers

**Cycle source/result ATS:** https://api.lever.co/v0/postings/field-ai — `Lever`

**Exact recorded reason:** Verified company source repair: https://api.lever.co/v0/postings/field-ai. Direct fetch returned partial: One or more malformed/incomplete postings were skipped. Skipped postings: 1; diagnostic details printed for the first 1.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Reproduce the precise direct-fetch failure below, inspect listing/detail schema and completeness contract; keep unresolved records partial.

**Candidate code:** `src/job_search_helper/ats.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0237 — Bonsai Robotics

**Current implementation status (2026-11-17):** W01 validated complete through normal dispatch: 7 full postings with stable final inventory reread. See `W01_RIPPLING_VALIDATION_2026-11-17.md`.

**Disposition:** Strong repair candidate · **Work order:** W01

**Initial group:** A1 Shared adapter exception

**Configured source:** `Rippling` — https://bonsairobotics.ai/careers/

**Cycle source/result ATS:** https://ats.rippling.com/bonsairoboticsmain/jobs — `Rippling`

**Exact recorded reason:** Verified company source repair: https://ats.rippling.com/bonsairoboticsmain/jobs. Public board data/transport failed validation (AttributeError); inventory incomplete.

**Next action:** Repair shared Rippling query-key schema; verify the exact board, all pages, details and final membership.

**Candidate code:** `src/job_search_helper/shared_boards.py`

**Existing test candidates:** `tests/test_shared_boards.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0238 — Caterpillar

**Disposition:** Correctness repair required before enablement · **Work order:** W07

**Initial group:** A2 Source/transport contract mismatch

**Configured source:** `Caterpillar Careers` — https://www.caterpillar.com/en/careers.html

**Cycle source/result ATS:** https://www.caterpillar.com/en/careers.html — `Caterpillar Careers`

**Exact recorded reason:** Direct fetch returned partial: Caterpillar adapter received an unexpected company or source.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Browser fallback needs retry (TimeoutError).

**Next action:** Repair source mismatch only alongside XML record-iteration, full-description and complete US coverage validation. Offline two-distinct-job XML loses the second record. Investigate current official native source.

**Candidate code:** `src/job_search_helper/caterpillar.py`, `src/job_search_helper/ats.py`

**Existing test candidates:** `tests/test_caterpillar.py`

**Fresh public check:** 2026-11-17T15:39:57.177500+00:00; HTTP 200; final URL https://www.caterpillar.com/en/careers.html; error none; evidence key `caterpillar-page`.

**Provider text/asset leads only:** myworkdayjobs. These may be false positives; not a verified board.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0240 — Komatsu

**Disposition:** Existing provider investigation · **Work order:** W08

**Initial group:** A3 Provider parser/pagination/validation

**Configured source:** `SuccessFactors` — https://www.komatsu.com/en-us/careers

**Cycle source/result ATS:** https://komatsu.jobs/viewalljobs/ — `SuccessFactors`

**Exact recorded reason:** Verified company source repair: https://komatsu.jobs/viewalljobs/. Komatsu HTML membership disagreed with its published range.

**Next action:** Reproduce the precise direct-fetch failure below, inspect listing/detail schema and completeness contract; keep unresolved records partial.

**Candidate code:** `src/job_search_helper/ats.py`, `src/job_search_helper/komatsu.py`, `src/job_search_helper/successfactors.py`

**Existing test candidates:** `tests/test_komatsu.py`, `tests/test_successfactors.py`, `tests/test_successfactors_browser_fallback.py`, `tests/test_successfactors_retry.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0241 — Rockwell Automation

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B2 Other access/HTTP response investigation

**Configured source:** `Workday` — https://www.rockwellautomation.com/en-us/careers.html

**Cycle source/result ATS:** https://www.rockwellautomation.com/en-us/careers.html — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page HTTP 403: access denied or human verification; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 403).

**Next action:** Confirm current public official source and classify actual response (challenge, rate limit, changed route or other error). Respect denial; preserve partial data. A new wrapper is not yet justified.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0246 — KUKA Robotics

**Current implementation status (2026-11-17):** W02/KUKA is validated complete. All 111 current feed records carried the exact KUKA employer facet; normal dispatch retrieved full descriptions for all and confirmed a stable final feed reread. Installation, scraper-run adoption, and Sheet publication were not performed.

**Disposition:** Strong repair candidate · **Work order:** W02

**Initial group:** A3 Provider parser/pagination/validation

**Configured source:** `KUKA` — https://www.kuka.com/en-us/company/careers

**Cycle source/result ATS:** https://www.kuka.com/en-us/company/careers — `KUKA`

**Exact recorded reason:** Verified company source repair: https://www.kuka.com/en-us/company/careers. Direct fetch returned partial: Verified company source repair: https://www.kuka.com/en-us/company/careers. KUKA employer-scoped feed changed or contains non-KUKA postings.. Browser fallback returned partial: Browser fallback saved 18 job descriptions; 8 job URLs await retry. Inventory completeness unknown; no closure inference. Browser time limit reached (300 seconds); saved progress retained.

**Next action:** Replace inspected historical fixed job count with structural/current-total completeness evidence, retain scope/detail checks and stable full reread. Recorded reason below identifies the current mismatch; KUKA count versus scope remains to isolate.

**Candidate code:** `src/job_search_helper/kuka.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 8 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0247 — Omron Automation

**Disposition:** Regional scope/integration gap · **Work order:** Scope investigations

**Initial group:** A3 Provider parser/pagination/validation

**Configured source:** `OMRON IAB regional manifest` — https://automation.omron.com/en/us/careers/

**Cycle source/result ATS:** https://careers.omron.com/content/Job-Opportunities/?locale=en_US — `OMRON IAB regional manifest`

**Exact recorded reason:** Verified company source repair: https://careers.omron.com/content/Job-Opportunities/?locale=en_US. Direct fetch returned partial: Verified company source repair: https://careers.omron.com/content/Job-Opportunities/?locale=en_US. Japan / IAB is an official regional handoff (https://job.axol.jp/qd/c/omron/public/); no validated public inventory adapter is available.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Omron manifest reports official Japan/IAB handoff job.axol.jp without validated adapter. Define intended global/regional coverage and implement missing public region before marking global complete.

**Candidate code:** `src/job_search_helper/omron.py`, `src/job_search_helper/ats.py`

**Existing test candidates:** `tests/test_omron.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0248 — Dematic

**Disposition:** Filtered scope repair candidate · **Work order:** W08

**Initial group:** A3 Provider parser/pagination/validation

**Configured source:** `Workday` — https://kiongroup.wd3.myworkdayjobs.com/KION_SCS?Country=55273a1b49934d97ae15342ef51f6b95&Country=80938777cac5440fab50d729f9634969&Country=972dc4ba8d454bc0b893ff84b1529077&Country=d903bb3fedad45039383f6de334ad4db

**Cycle source/result ATS:** https://kiongroup.wd3.myworkdayjobs.com/KION_SCS?Country=55273a1b49934d97ae15342ef51f6b95&Country=80938777cac5440fab50d729f9634969&Country=972dc4ba8d454bc0b893ff84b1529077&Country=d903bb3fedad45039383f6de334ad4db — ``

**Exact recorded reason:** Direct fetch returned partial: Dematic source is not the verified KION SCS Workday board.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Current KION URL has unsupported path and multiple Country filters; repair_source leaves it unchanged. Verify intended geography and exact filter semantics; preserve scope rather than dropping filters.

**Candidate code:** `src/job_search_helper/dematic.py`, `src/job_search_helper/workday.py`, `src/job_search_helper/company_sources.py`, `src/job_search_helper/ats.py`

**Existing test candidates:** `tests/test_dematic.py`, `tests/test_workday.py`, `tests/test_workday_leidos.py`, `tests/test_workday_leidos_reconcile.py`, `tests/test_workday_reconcile.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0249 — Bastian Solutions

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B1 Workday access/response investigation

**Configured source:** `Workday` — https://vanderlande.wd3.myworkdayjobs.com/TALExternalCareers

**Cycle source/result ATS:** https://vanderlande.wd3.myworkdayjobs.com/wday/cxs/vanderlande/TALExternalCareers — `Workday`

**Exact recorded reason:** Direct fetch returned partial: Workday listing page 1: Human verification detected; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Capture the failed Workday request page/posting and response classification; inspect host pacing and source filters. Validate all pages/details after recovery. Do not assume a new wrapper fixes genuine access denial.

**Candidate code:** `src/job_search_helper/workday.py`

**Existing test candidates:** `tests/test_workday.py`, `tests/test_workday_leidos.py`, `tests/test_workday_leidos_reconcile.py`, `tests/test_workday_reconcile.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0250 — JR Automation

**Current implementation status (2026-11-17):** W02/JR Automation is validated complete. The board's canonical `/jobs/page/<n>` pagination preserves the JR brand filter; normal dispatch returned 59 full JR-only postings with a stable complete reread. Installation, scraper-run adoption, and Sheet publication were not performed.

**Disposition:** Strong repair candidate · **Work order:** W02

**Initial group:** A3 Provider parser/pagination/validation

**Configured source:** `Hitachi Careers (JR Automation)` — https://www.jrautomation.com/careers

**Cycle source/result ATS:** https://careers.hitachi.com/jobs?filter%5Bbrand%5D%5B0%5D=JR%20Automation — `Hitachi Careers (JR Automation)`

**Exact recorded reason:** Verified company source repair: https://careers.hitachi.com/jobs?filter%5Bbrand%5D%5B0%5D=JR%20Automation. Direct fetch returned partial: JR Automation published an invalid filtered inventory size.. Browser fallback returned partial: Browser fallback saved 9 job descriptions; 6 job URLs await retry. Inventory completeness unknown; no closure inference. Stopped this detail pass after 5 consecutive failures; unresolved URLs and saved descriptions retained.

**Next action:** Replace inspected historical fixed job count with structural/current-total completeness evidence, retain scope/detail checks and stable full reread. Recorded reason below identifies the current mismatch; KUKA count versus scope remains to isolate.

**Candidate code:** `src/job_search_helper/jr_automation.py`, `src/job_search_helper/ats.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:57.035651+00:00; HTTP 200; final URL https://careers.hitachi.com/jobs?filter%5Bbrand%5D%5B0%5D=JR%20Automation; error none; evidence key `jr-page`.

**Extracted provider-link leads (unverified scope):** https://hitachi.wd1.myworkdayjobs.com/hitachi/job/Holland-Michigan-United-States/Controls-Design-Engineer-I_R0148714/apply ; https://hitachi.wd1.myworkdayjobs.com/hitachi/job/Holland-Michigan-United-States/Electrician---Panel-Builder_R0150084/apply ; https://hitachi.wd1.myworkdayjobs.com/hitachi/job/Holland-Michigan-United-States/Machine-Build-Manager_R0142811/apply ; https://hitachi.wd1.myworkdayjobs.com/hitachi/job/Holland-Michigan-United-States/Project-Manager---High-Volume_R0148221/apply ; https://hitachi.wd1.myworkdayjobs.com/hitachi/job/JRATN---Elm-Hill-Pike/Senior-Project-Manager_R0141160/apply ; https://hitachi.wd1.myworkdayjobs.com/hitachi/job/Lake-Orion-Michigan-Unites-States/Controls-Engineer-II_R0132982/apply

**Checkpoint context:** 6 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0254 — Trimble

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B1 Workday access/response investigation

**Configured source:** `Browser` — https://www.trimble.com/en/careers

**Cycle source/result ATS:** https://trimblecareers.trimble.com/jobs — `Browser`

**Exact recorded reason:** Verified company source repair: https://trimblecareers.trimble.com/jobs. Direct fetch returned blocked: Verified company source repair: https://trimblecareers.trimble.com/jobs. Discovered Workday board https://trimble.wd1.myworkdayjobs.com/wday/cxs/trimble/TrimbleCareers from https://trimblecareers.trimble.com/senior-customer-success-manager-strategic-accounts-talent-pool/job/R58531. Workday listing page 10: Human verification detected; manual review required.. Browser fallback returned partial: Browser fallback saved 10 job descriptions; 11 job URLs await retry. Inventory completeness unknown; no closure inference. Stopped this detail pass after 5 consecutive failures; unresolved URLs and saved descriptions retained.

**Next action:** Capture the failed Workday request page/posting and response classification; inspect host pacing and source filters. Validate all pages/details after recovery. Do not assume a new wrapper fixes genuine access denial.

**Candidate code:** `src/job_search_helper/workday.py`

**Existing test candidates:** `tests/test_workday.py`, `tests/test_workday_leidos.py`, `tests/test_workday_leidos_reconcile.py`, `tests/test_workday_reconcile.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 11 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `blocked`. Neither pending count nor this flag alone proves coverage.

### COMP-0257 — u-blox

**Disposition:** Existing detail parser candidate · **Work order:** W08

**Initial group:** A3 Provider parser/pagination/validation

**Configured source:** `Salesforce-hosted recruiting` — https://www.u-blox.com/en/job-openings

**Cycle source/result ATS:** https://www.u-blox.com/en/job-openings — `Salesforce-hosted recruiting`

**Exact recorded reason:** Verified company source repair: https://www.u-blox.com/en/job-openings. Direct fetch returned partial: Verified company source repair: https://www.u-blox.com/en/job-openings. u-blox public detail lacks a matching nonempty job description.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** u-blox listing adapter exists but public detail lacks matching nonempty description. Inspect exact detail identity/body; do not broaden Algolia listing limits or accept summaries as full content.

**Candidate code:** `src/job_search_helper/ublox.py`, `src/job_search_helper/ats.py`

**Existing test candidates:** `tests/test_ublox.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0259 — Inertial Labs

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B1 Workday access/response investigation

**Configured source:** `Workday` — https://viavisolutions.wd1.myworkdayjobs.com/careers

**Cycle source/result ATS:** https://viavisolutions.wd1.myworkdayjobs.com/wday/cxs/viavisolutions/careers — `Workday`

**Exact recorded reason:** Direct fetch returned partial: Workday job detail https://viavisolutions.wd1.myworkdayjobs.com/careers/job/Beijing---Haidian-CHN/CTO-China-Intern_260005178: Human verification detected; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Capture the failed Workday request page/posting and response classification; inspect host pacing and source filters. Validate all pages/details after recovery. Do not assume a new wrapper fixes genuine access denial.

**Candidate code:** `src/job_search_helper/workday.py`

**Existing test candidates:** `tests/test_workday.py`, `tests/test_workday_leidos.py`, `tests/test_workday_leidos_reconcile.py`, `tests/test_workday_reconcile.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0260 — Advanced Navigation

**Current implementation status (2026-11-17):** W01 validated complete through normal dispatch: 22 full postings with stable final inventory reread. See `W01_RIPPLING_VALIDATION_2026-11-17.md`.

**Disposition:** Strong repair candidate · **Work order:** W01

**Initial group:** A1 Shared adapter exception

**Configured source:** `Rippling` — https://www.advancednavigation.com/careers/

**Cycle source/result ATS:** https://ats.rippling.com/advanced-navigation/jobs — `Rippling`

**Exact recorded reason:** Verified company source repair: https://ats.rippling.com/advanced-navigation/jobs. Public board data/transport failed validation (AttributeError); inventory incomplete.

**Next action:** Repair shared Rippling query-key schema; verify the exact board, all pages, details and final membership.

**Candidate code:** `src/job_search_helper/shared_boards.py`

**Existing test candidates:** `tests/test_shared_boards.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0271 — Cognex

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B1 Workday access/response investigation

**Configured source:** `Workday` — https://cognex.wd1.myworkdayjobs.com/External_Career_Site

**Cycle source/result ATS:** https://cognex.wd1.myworkdayjobs.com/wday/cxs/cognex/External_Career_Site — `Workday`

**Exact recorded reason:** Direct fetch returned partial: Workday job detail https://cognex.wd1.myworkdayjobs.com/External_Career_Site/job/Noida-India/Senior-Accounts-Payable-Specialist_R0012659: Human verification detected; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Capture the failed Workday request page/posting and response classification; inspect host pacing and source filters. Validate all pages/details after recovery. Do not assume a new wrapper fixes genuine access denial.

**Candidate code:** `src/job_search_helper/workday.py`

**Existing test candidates:** `tests/test_workday.py`, `tests/test_workday_leidos.py`, `tests/test_workday_leidos_reconcile.py`, `tests/test_workday_reconcile.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0278 — MachineMetrics

**Disposition:** Native source unresolved · **Work order:** W05

**Initial group:** C3 Stale URL/redirect/request repair

**Configured source:** `MachineMetrics careers` — https://www.machinemetrics.com/careers

**Cycle source/result ATS:** https://www.machinemetrics.com/careers/ — `MachineMetrics careers`

**Exact recorded reason:** Verified company source repair: https://www.machinemetrics.com/careers/. Direct fetch returned partial: Verified company source repair: https://www.machinemetrics.com/careers/. MachineMetrics careers page HTTP 301.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Official page redirects and embeds Greenhouse machinemetrics, but current native feed returns 404. Do not install this stale embed as a working fix; discover current official board or document no proved inventory.

**Candidate code:** `src/job_search_helper/machinemetrics.py`, `src/job_search_helper/company_sources.py`, `src/job_search_helper/ats.py`

**Existing test candidates:** `tests/test_machinemetrics.py`

**Fresh public check:** 2026-11-17T15:39:10.540670+00:00; HTTP 200; final URL https://www.machinemetrics.com/careers; error none; evidence key `COMP-0278`.

**Extracted provider-link leads (unverified scope):** https://boards.greenhouse.io/embed/job_board/js?for=machinemetrics

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0281 — Blues

**Disposition:** No proven complete public inventory · **Work order:** No public inventory

**Initial group:** D1 No proven public inventory

**Configured source:** `Blues careers` — https://blues.com/bluescareers/

**Cycle source/result ATS:** https://blues.com/bluescareers/ — `Blues careers`

**Exact recorded reason:** Verified company source repair: https://blues.com/bluescareers/. Verified company source repair: https://blues.com/bluescareers/. Blues official Open Positions link is LinkedIn-only; no public employer-scoped inventory or full descriptions are available to verify.

**Next action:** Seek a newly published official public job inventory; until one exists, preserve explicit unsupported/manual-source status and do not manufacture zero jobs from a contact or interest form.

**Candidate code:** `src/job_search_helper/company_sources.py`, `src/job_search_helper/ats.py`, `src/job_search_helper/blues.py`

**Existing test candidates:** `tests/test_blues.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0283 — Advantech

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B1 Workday access/response investigation

**Configured source:** `Workday` — https://advantech.wd3.myworkdayjobs.com/en-US/External

**Cycle source/result ATS:** https://advantech.wd3.myworkdayjobs.com/wday/cxs/advantech/External — `Workday`

**Exact recorded reason:** Direct fetch returned partial: Workday listing page 1: Human verification detected; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Capture the failed Workday request page/posting and response classification; inspect host pacing and source filters. Validate all pages/details after recovery. Do not assume a new wrapper fixes genuine access denial.

**Candidate code:** `src/job_search_helper/workday.py`

**Existing test candidates:** `tests/test_workday.py`, `tests/test_workday_leidos.py`, `tests/test_workday_leidos_reconcile.py`, `tests/test_workday_reconcile.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0288 — ADLINK Technology

**Current implementation status (2026-11-17):** W01 validated complete through normal dispatch: 10 full postings with stable final inventory reread. See `W01_RIPPLING_VALIDATION_2026-11-17.md`.

**Disposition:** Strong repair candidate · **Work order:** W01

**Initial group:** A1 Shared adapter exception

**Configured source:** `Rippling` — https://ats.rippling.com/ampro-adlink-technology-inc/jobs

**Cycle source/result ATS:** https://ats.rippling.com/ampro-adlink-technology-inc/jobs — `Rippling`

**Exact recorded reason:** Public board data/transport failed validation (AttributeError); inventory incomplete.

**Next action:** Repair shared Rippling query-key schema; verify the exact board, all pages, details and final membership.

**Candidate code:** `src/job_search_helper/shared_boards.py`

**Existing test candidates:** `tests/test_shared_boards.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0295 — Getac

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Browser` — https://www.getac.com/us/careers/

**Cycle source/result ATS:** https://www.getac.com/us/careers/ — ``

**Exact recorded reason:** Direct fetch returned partial: Careers discovery expected an HTML page; provide the ATS board URL.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:10.625319+00:00; HTTP 200; final URL https://www.getac.com/us/careers/; error none; evidence key `COMP-0295`.

**Provider text/asset leads only:** adp.com. These may be false positives; not a verified board.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0300 — Genasys

**Disposition:** Existing provider investigation · **Work order:** W08

**Initial group:** A3 Provider parser/pagination/validation

**Configured source:** `ApplicantPro (disabled board)` — https://www.genasys.com/careers

**Cycle source/result ATS:** https://genasys.applicantpro.com/jobs/ — `ApplicantPro`

**Exact recorded reason:** ApplicantPro public domain identity missing.

**Next action:** Reproduce the precise direct-fetch failure below, inspect listing/detail schema and completeness contract; keep unresolved records partial.

**Candidate code:** `src/job_search_helper/ats.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0302 — Deployable Technologies

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B2 Other access/HTTP response investigation

**Configured source:** `Deployable Technologies careers` — https://deployabletechnologies.com/careers/

**Cycle source/result ATS:** https://deployabletechnologies.com/careers/ — `Deployable Technologies careers`

**Exact recorded reason:** Verified company source repair: https://deployabletechnologies.com/careers/. Direct fetch returned partial: Verified company source repair: https://deployabletechnologies.com/careers/. Deployable Technologies source blocked (HTTP 403).. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Confirm current public official source and classify actual response (challenge, rate limit, changed route or other error). Respect denial; preserve partial data. A new wrapper is not yet justified.

**Candidate code:** `src/job_search_helper/discovery.py`, `src/job_search_helper/ats.py`, `src/job_search_helper/deployable.py`

**Existing test candidates:** `tests/test_deployable.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0307 — iGov

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B2 Other access/HTTP response investigation

**Configured source:** `` — https://igov.com/careers/

**Cycle source/result ATS:** https://igov.com/careers/ — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page HTTP 403: access denied or human verification; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Confirm current public official source and classify actual response (challenge, rate limit, changed route or other error). Respect denial; preserve partial data. A new wrapper is not yet justified.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0318 — Metrea

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `ADP` — https://www.metrea.aero/careers

**Cycle source/result ATS:** https://www.metrea.aero/careers — `ADP`

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found on careers page or obvious same-site job links; the careers page is reachable but may use another ATS or require JavaScript, so inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 104 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference.

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:10.856891+00:00; HTTP 200; final URL https://www.metrea.aero/careers; error none; evidence key `COMP-0318`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0320 — Foundation

**Current implementation status (2026-11-17):** W01 validated complete through normal dispatch: 26 full postings with stable final inventory reread. See `W01_RIPPLING_VALIDATION_2026-11-17.md`.

**Disposition:** Strong repair candidate · **Work order:** W01

**Initial group:** A1 Shared adapter exception

**Configured source:** `Rippling` — https://ats.rippling.com/foundation-robotics/jobs

**Cycle source/result ATS:** https://ats.rippling.com/foundation-robotics/jobs — `Rippling`

**Exact recorded reason:** Public board data/transport failed validation (AttributeError); inventory incomplete.

**Next action:** Repair shared Rippling query-key schema; verify the exact board, all pages, details and final membership.

**Candidate code:** `src/job_search_helper/shared_boards.py`

**Existing test candidates:** `tests/test_shared_boards.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0324 — Vexar Defense

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Browser` — (not set)

**Cycle source/result ATS:** https://vexardefense.com/ — ``

**Exact recorded reason:** Verified company source repair: https://vexardefense.com/. Direct fetch returned partial: Verified company source repair: https://vexardefense.com/. No supported ATS link found on careers page or obvious same-site job links; the careers page is reachable but may use another ATS or require JavaScript, so inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:11.276341+00:00; HTTP 200; final URL https://vexardefense.com/; error none; evidence key `COMP-0324`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0334 — CAE USA

**Disposition:** Employer scope needs proof · **Work order:** Scope investigations

**Initial group:** C1 Employer scope or multiple boards

**Configured source:** `Workday (shared parent board)` — https://www.cae.com/cae-usa/careers-at-cae-usa

**Cycle source/result ATS:** https://www.cae.com/cae-usa/careers-at-cae-usa — ``

**Exact recorded reason:** Direct fetch returned partial: Shared/parent board requires an explicit company scope; automatic discovery cannot assign all parent-company jobs.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 403).

**Next action:** Official route leads to a broader parent board. Establish exact subsidiary/legal-entity attribution and complete filtered membership; do not relabel parent jobs under this company.

**Candidate code:** `src/job_search_helper/company_sources.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:11.332012+00:00; HTTP 200; final URL https://www.cae.com/cae-usa/careers-at-cae-usa; error none; evidence key `COMP-0334`.

**Extracted provider-link leads (unverified scope):** https://cae.wd3.myworkdayjobs.com/career/page/86f4b6ffbc811000b9a618600baf0000 ; https://cae.wd3.myworkdayjobs.com/career/page/a5a9d72e7f2a10015ace0f39dd520000 ; https://cae.wd3.myworkdayjobs.com/en-US/career?Location_Country=bc33aa3152ec42d4995f4791a106ed09&shared_id=Yjc2M2I3NjQtNGMxNS00MTI4LWExNzUtMDI0YWZjODkzNDMx ; https://cae.wd3.myworkdayjobs.com/en-US/career?q=Tampa

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0336 — Advanced Simulation Technology inc. (ASTi)

**Disposition:** Strong repair candidate · **Work order:** W02 + W03

**Initial group:** A2 Source/transport contract mismatch

**Configured source:** `ASTi careers` — https://www.asti-usa.com/jobs/index.html

**Cycle source/result ATS:** https://www.asti-usa.com/jobs/positions.html — `ASTi careers`

**Exact recorded reason:** Verified company source repair: https://www.asti-usa.com/jobs/positions.html. Direct fetch returned partial: Only pinned official HTTPS API endpoints are allowed.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 2 job URLs await retry. Inventory completeness unknown; no closure inference.

**Next action:** Static official page returns 200; default dispatcher passes API transport rejected by URL guard. Correct HTML client and replace latent exact-two-role contract with verified complete-page evidence.

**Candidate code:** `src/job_search_helper/asti.py`, `src/job_search_helper/ats.py`

**Existing test candidates:** `tests/test_asti.py`

**Fresh public check:** 2026-11-17T15:39:55.548887+00:00; HTTP 200; final URL https://www.asti-usa.com/jobs/positions.html; error none; evidence key `asti-page`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 2 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0344 — Mass Virtual

**Disposition:** Strong repair candidate · **Work order:** W03

**Initial group:** A2 Source/transport contract mismatch

**Configured source:** `Mass Virtual Paylocity` — https://www.massvirtual.com/career

**Cycle source/result ATS:** https://recruiting.paylocity.com/recruiting/v2/api/feed/jobs/2df5ac23-47b5-4c64-b536-e7f04caf6ffe — `Mass Virtual Paylocity`

**Exact recorded reason:** Direct fetch returned partial: Only pinned official HTTPS API endpoints are allowed.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Public Paylocity feed returns 200 with one row; default API guard rejects it. Correct dispatch/transport and verify full row description, employer and repeated full feed.

**Candidate code:** `src/job_search_helper/massvirtual.py`, `src/job_search_helper/paylocity.py`, `src/job_search_helper/ats.py`

**Existing test candidates:** `tests/test_massvirtual.py`, `tests/test_paylocity.py`

**Fresh public check:** 2026-11-17T15:39:55.727062+00:00; HTTP 200; final URL https://recruiting.paylocity.com/recruiting/v2/api/feed/jobs/2df5ac23-47b5-4c64-b536-e7f04caf6ffe; error none; evidence key `massvirtual-feed`.

**Extracted provider-link leads (unverified scope):** https://recruiting.paylocity.com/recruiting/jobs/All/0ff60688-d70f-4431-a2f0-0b69ed551b46/Mass-Virtual-Inc ; https://recruiting.paylocity.com/recruiting/jobs/Apply/4547468/Mass-Virtual-Inc/DoW-SkillBridge-Internship---General-Applications ; https://recruiting.paylocity.com/recruiting/jobs/Details/4547468/Mass-Virtual-Inc/DoW-SkillBridge-Internship---General-Applications

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0348 — VideoRay

**Disposition:** Existing adapter repair candidate · **Work order:** W03

**Initial group:** A2 Source/transport contract mismatch

**Configured source:** `VideoRay local + AVAV Workday` — https://videoray.com/about-us/careers/

**Cycle source/result ATS:** https://avav.wd1.myworkdayjobs.com/en-US/AVAV?q=VideoRay — `VideoRay local + AVAV Workday`

**Exact recorded reason:** Verified company source repair: https://avav.wd1.myworkdayjobs.com/en-US/AVAV?q=VideoRay. Direct fetch returned partial: Only pinned official HTTPS API endpoints are allowed.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Separate local VideoRay HTML transport from AVAV Workday API client; then prove both inventories and VideoRay attribution and deduplicate overlap. Parent-board access remains unverified.

**Candidate code:** `src/job_search_helper/videoray.py`, `src/job_search_helper/workday.py`, `src/job_search_helper/ats.py`

**Existing test candidates:** `tests/test_videoray.py`, `tests/test_workday.py`, `tests/test_workday_leidos.py`, `tests/test_workday_leidos_reconcile.py`, `tests/test_workday_reconcile.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0349 — Blue Robotics

**Current implementation status (2026-11-17):** W01 validated complete through normal dispatch: 1 full posting with stable final inventory reread. See `W01_RIPPLING_VALIDATION_2026-11-17.md`.

**Disposition:** Strong repair candidate · **Work order:** W01

**Initial group:** A1 Shared adapter exception

**Configured source:** `Rippling` — https://bluerobotics.com/jobs/

**Cycle source/result ATS:** https://bluerobotics.com/jobs/ — `Rippling`

**Exact recorded reason:** Public board data/transport failed validation (AttributeError); inventory incomplete.

**Next action:** Repair shared Rippling query-key schema; verify the exact board, all pages, details and final membership.

**Candidate code:** `src/job_search_helper/shared_boards.py`

**Existing test candidates:** `tests/test_shared_boards.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0350 — Kraken Robotics

**Current implementation status (2026-11-17):** W01 validated complete through normal dispatch: 22 full postings with stable final inventory reread. See `W01_RIPPLING_VALIDATION_2026-11-17.md`.

**Disposition:** Strong repair candidate · **Work order:** W01

**Initial group:** A1 Shared adapter exception

**Configured source:** `Rippling` — https://ats.rippling.com/kraken-robotics-inc/jobs

**Cycle source/result ATS:** https://ats.rippling.com/kraken-robotics-inc/jobs — `Rippling`

**Exact recorded reason:** Public board data/transport failed validation (AttributeError); inventory incomplete.

**Next action:** Repair shared Rippling query-key schema; verify the exact board, all pages, details and final membership.

**Candidate code:** `src/job_search_helper/shared_boards.py`

**Existing test candidates:** `tests/test_shared_boards.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0354 — XOCEAN

**Disposition:** No complete public inventory yet proven · **Work order:** No public inventory

**Initial group:** C2 Native source discovery/routing

**Configured source:** `` — https://xocean.com/careers/

**Cycle source/result ATS:** https://www.xocean.com/careers/ — ``

**Exact recorded reason:** Verified company source repair: https://www.xocean.com/careers/. Direct fetch returned partial: Verified company source repair: https://www.xocean.com/careers/. No supported ATS link found on careers page or obvious same-site job links; the careers page is reachable but may use another ATS or require JavaScript, so inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Existing source notes describe careers email/LinkedIn, and fresh static probe found no native ATS. Investigate any new official public board; do not infer empty inventory.

**Candidate code:** `src/job_search_helper/xocean.py`, `src/job_search_helper/company_sources.py`

**Existing test candidates:** `tests/test_xocean.py`

**Fresh public check:** 2026-11-17T15:39:11.489366+00:00; HTTP 200; final URL https://xocean.com/careers/; error none; evidence key `COMP-0354`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0361 — Fugro

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B1 Workday access/response investigation

**Configured source:** `Workday` — https://www.fugro.com/careers

**Cycle source/result ATS:** https://fugro.wd3.myworkdayjobs.com/wday/cxs/fugro/careers — `Workday`

**Exact recorded reason:** Verified company source repair: https://fugro.wd3.myworkdayjobs.com/careers. Direct fetch returned partial: Workday listing page 1: Human verification detected; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Capture the failed Workday request page/posting and response classification; inspect host pacing and source filters. Validate all pages/details after recovery. Do not assume a new wrapper fixes genuine access denial.

**Candidate code:** `src/job_search_helper/workday.py`

**Existing test candidates:** `tests/test_workday.py`, `tests/test_workday_leidos.py`, `tests/test_workday_leidos_reconcile.py`, `tests/test_workday_reconcile.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0362 — ATLAS Space Operations

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B2 Other access/HTTP response investigation

**Configured source:** `ATLAS Space careers` — https://atlasspace.com/careers/

**Cycle source/result ATS:** https://atlasspace.com/careers/ — `ATLAS Space careers`

**Exact recorded reason:** Verified company source repair: https://atlasspace.com/careers/. Direct fetch returned partial: Verified company source repair: https://atlasspace.com/careers/. ATLAS careers page blocked (HTTP 403).. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Confirm current public official source and classify actual response (challenge, rate limit, changed route or other error). Respect denial; preserve partial data. A new wrapper is not yet justified.

**Candidate code:** `src/job_search_helper/discovery.py`, `src/job_search_helper/ats.py`, `src/job_search_helper/atlas_space.py`

**Existing test candidates:** `tests/test_atlas_space.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0382 — Capella Space

**Disposition:** Source/redirect investigation · **Work order:** W05 / source repair

**Initial group:** C3 Stale URL/redirect/request repair

**Configured source:** `Greenhouse` — https://www.capellaspace.com/careers

**Cycle source/result ATS:** https://boards-api.greenhouse.io/v1/boards/capellaspace/jobs?content=true — `Greenhouse`

**Exact recorded reason:** Verified company source repair: https://boards.greenhouse.io/capellaspace. Direct fetch returned partial: HTTP 404; inventory unavailable, not evidence of closure.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 404).

**Next action:** Follow the exact current official link/redirect with bounded trusted destinations; validate replacement board and scope. A 404 is not closure. Test dispatch/source aliases and every page/detail.

**Candidate code:** `src/job_search_helper/company_sources.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:11.705291+00:00; HTTP 404; final URL https://boards-api.greenhouse.io/v1/boards/capellaspace/jobs?content=true; error none; evidence key `COMP-0382`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0388 — E Tech Group

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B2 Other access/HTTP response investigation

**Configured source:** `Greenhouse` — https://etechgroup.com/careers/

**Cycle source/result ATS:** https://etechgroup.com/careers/ — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page HTTP 403: access denied or human verification; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 403).

**Next action:** Confirm current public official source and classify actual response (challenge, rate limit, changed route or other error). Respect denial; preserve partial data. A new wrapper is not yet justified.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0395 — BW Design Group

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B1 Workday access/response investigation

**Configured source:** `Workday` — https://barrywehmiller.wd1.myworkdayjobs.com/BWCareers?q=Design+Group

**Cycle source/result ATS:** https://barrywehmiller.wd1.myworkdayjobs.com/wday/cxs/barrywehmiller/BWCareers?q=Design+Group — `Workday`

**Exact recorded reason:** Direct fetch returned partial: Workday job detail https://barrywehmiller.wd1.myworkdayjobs.com/BWCareers/job/Fort-Worth-TX/Structural-Engineer--PE_R017627: Human verification detected; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Capture the failed Workday request page/posting and response classification; inspect host pacing and source filters. Validate all pages/details after recovery. Do not assume a new wrapper fixes genuine access denial.

**Candidate code:** `src/job_search_helper/workday.py`

**Existing test candidates:** `tests/test_workday.py`, `tests/test_workday_leidos.py`, `tests/test_workday_leidos_reconcile.py`, `tests/test_workday_reconcile.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0397 — Hallam-ICS

**Disposition:** Existing provider investigation · **Work order:** W08

**Initial group:** A3 Provider parser/pagination/validation

**Configured source:** `SaaShr` — https://www.hallam-ics.com/careers

**Cycle source/result ATS:** https://secure7.saashr.com/ta/6211585.careers?CareersSearch=&career_portal_id=4915719&ein_id=118982210&lang=en-US — `SaaShr`

**Exact recorded reason:** Verified company source repair: https://secure7.saashr.com/ta/6211585.careers?CareersSearch=&career_portal_id=4915719&ein_id=118982210&lang=en-US. Direct fetch returned partial: SaaShr page exposed no verifiable Hallam-ICS job detail links.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Reproduce the precise direct-fetch failure below, inspect listing/detail schema and completeness contract; keep unresolved records partial.

**Candidate code:** `src/job_search_helper/ats.py`, `src/job_search_helper/saashr.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0398 — Gray Solutions

**Disposition:** Successor/employer scope needs proof · **Work order:** W08

**Initial group:** A3 Provider parser/pagination/validation

**Configured source:** `iCIMS` — https://careershub-gray.icims.com/jobs/search?bga=true&hashed=-625916723&height=500&jan1offset=-360&jun1offset=-300&mobile=false&needsRedirect=false&ss=1&width=1270

**Cycle source/result ATS:** https://careershub-gray.icims.com/jobs/search — `iCIMS`

**Exact recorded reason:** Direct fetch returned partial: Gray Solutions is represented by the verified Gray AES successor scope only; use searchPositionType=37044 and do not import the shared Gray-family board.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Recorded guard requires verified Gray AES successor searchPositionType=37044. Prove mapping and filtered iCIMS inventory, never import whole Gray family.

**Candidate code:** `src/job_search_helper/icims.py`, `src/job_search_helper/company_sources.py`

**Existing test candidates:** `tests/test_icims.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0405 — ECS Solutions

**Disposition:** Existing provider investigation · **Work order:** W08

**Initial group:** A3 Provider parser/pagination/validation

**Configured source:** `isolved` — https://magnumsystems.com/about/careers/

**Cycle source/result ATS:** https://magnumsystems.isolvedhire.com/jobs/ — `isolved`

**Exact recorded reason:** Verified company source repair: https://magnumsystems.isolvedhire.com/jobs/. Empty HTML inventory requires explicit provider evidence.

**Next action:** Reproduce the precise direct-fetch failure below, inspect listing/detail schema and completeness contract; keep unresolved records partial.

**Candidate code:** `src/job_search_helper/ats.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0407 — Mavenir

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B1 Workday access/response investigation

**Configured source:** `Workday` — https://mavenir.wd1.myworkdayjobs.com/Mavenir_Careers

**Cycle source/result ATS:** https://mavenir.wd1.myworkdayjobs.com/wday/cxs/mavenir/Mavenir_Careers — `Workday`

**Exact recorded reason:** Direct fetch returned partial: Workday job detail https://mavenir.wd1.myworkdayjobs.com/Mavenir_Careers/job/Bangalore-India/Data-Science-Systems-Architect_R0016642-1: Human verification detected; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Capture the failed Workday request page/posting and response classification; inspect host pacing and source filters. Validate all pages/details after recovery. Do not assume a new wrapper fixes genuine access denial.

**Candidate code:** `src/job_search_helper/workday.py`

**Existing test candidates:** `tests/test_workday.py`, `tests/test_workday_leidos.py`, `tests/test_workday_leidos_reconcile.py`, `tests/test_workday_reconcile.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `blocked`. Neither pending count nor this flag alone proves coverage.

### COMP-0413 — Boldyn Networks

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B1 Workday access/response investigation

**Configured source:** `Workday` — https://baicommunications.wd3.myworkdayjobs.com/External

**Cycle source/result ATS:** https://baicommunications.wd3.myworkdayjobs.com/wday/cxs/baicommunications/External — `Workday`

**Exact recorded reason:** Direct fetch returned partial: Workday listing page 1: Human verification detected; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Capture the failed Workday request page/posting and response classification; inspect host pacing and source filters. Validate all pages/details after recovery. Do not assume a new wrapper fixes genuine access denial.

**Candidate code:** `src/job_search_helper/workday.py`

**Existing test candidates:** `tests/test_workday.py`, `tests/test_workday_leidos.py`, `tests/test_workday_leidos_reconcile.py`, `tests/test_workday_reconcile.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0419 — Mission Secure

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B2 Other access/HTTP response investigation

**Configured source:** `Browser` — https://careers.servicenow.com/

**Cycle source/result ATS:** https://careers.servicenow.com/ — ``

**Exact recorded reason:** Verified company source repair: https://careers.servicenow.com/. Direct fetch returned partial: Verified company source repair: https://careers.servicenow.com/. Careers page HTTP 403: access denied or human verification; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 403).

**Next action:** Confirm current public official source and classify actual response (challenge, rate limit, changed route or other error). Respect denial; preserve partial data. A new wrapper is not yet justified.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0428 — Aitech Systems

**Current implementation status (2026-11-17):** W02/Aitech is validated complete. Normal dispatch returned 15 full Aitech postings with full descriptions and a stable final inventory reread after removal of the fixed-count guard. Regression: `tests/test_aitech.py tests/test_next_100_middle.py`, 4 passed. Installation, scraper-run adoption, and Sheet publication were not performed.

**Disposition:** Strong repair candidate · **Work order:** W02

**Initial group:** A3 Provider parser/pagination/validation

**Configured source:** `Aitech Comeet` — https://aitechsystems.com/careers/

**Cycle source/result ATS:** https://aitechsystems.com/careers/ — `Aitech Comeet`

**Exact recorded reason:** Verified company source repair: https://aitechsystems.com/careers/. Direct fetch returned partial: Verified company source repair: https://aitechsystems.com/careers/. Aitech role inventory changed; found 15 role links.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Replace inspected historical fixed job count with structural/current-total completeness evidence, retain scope/detail checks and stable full reread. Recorded reason below identifies the current mismatch; KUKA count versus scope remains to isolate.

**Candidate code:** `src/job_search_helper/aitech.py`, `src/job_search_helper/ats.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:56.137903+00:00; HTTP 200; final URL https://aitechsystems.com/careers/; error none; evidence key `aitech-page`.

**Provider text/asset leads only:** comeet. These may be false positives; not a verified board.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0429 — MilDef

**Disposition:** Existing provider investigation · **Work order:** W08

**Initial group:** A3 Provider parser/pagination/validation

**Configured source:** `Teamtailor` — https://careers.mildef.com/jobs

**Cycle source/result ATS:** https://careers.mildef.com/jobs — `Teamtailor`

**Exact recorded reason:** Teamtailor listing is paginated or its total disagrees.

**Next action:** Reproduce the precise direct-fetch failure below, inspect listing/detail schema and completeness contract; keep unresolved records partial.

**Candidate code:** `src/job_search_helper/ats.py`, `src/job_search_helper/teamtailor.py`

**Existing test candidates:** `tests/test_teamtailor.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0432 — Moog

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B1 Workday access/response investigation

**Configured source:** `Workday` — https://moog.wd5.myworkdayjobs.com/MOOG_External_Career_Site

**Cycle source/result ATS:** https://moog.wd5.myworkdayjobs.com/wday/cxs/moog/MOOG_External_Career_Site — `Workday`

**Exact recorded reason:** Direct fetch returned partial: Workday listing page 2: Human verification detected; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Capture the failed Workday request page/posting and response classification; inspect host pacing and source filters. Validate all pages/details after recovery. Do not assume a new wrapper fixes genuine access denial.

**Candidate code:** `src/job_search_helper/workday.py`

**Existing test candidates:** `tests/test_workday.py`, `tests/test_workday_leidos.py`, `tests/test_workday_leidos_reconcile.py`, `tests/test_workday_reconcile.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0434 — Woodward

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B1 Workday access/response investigation

**Configured source:** `Workday` — https://woodward.wd5.myworkdayjobs.com/woodward

**Cycle source/result ATS:** https://woodward.wd5.myworkdayjobs.com/wday/cxs/woodward/woodward — `Workday`

**Exact recorded reason:** Direct fetch returned partial: Workday listing page 1: Human verification detected; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Capture the failed Workday request page/posting and response classification; inspect host pacing and source filters. Validate all pages/details after recovery. Do not assume a new wrapper fixes genuine access denial.

**Candidate code:** `src/job_search_helper/workday.py`

**Existing test candidates:** `tests/test_workday.py`, `tests/test_workday_leidos.py`, `tests/test_workday_leidos_reconcile.py`, `tests/test_workday_reconcile.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0436 — Honeywell Aerospace Technologies

**Disposition:** Existing provider investigation · **Work order:** W08

**Initial group:** A3 Provider parser/pagination/validation

**Configured source:** `Oracle Recruiting Cloud` — https://icfcjb.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/Aerospace/jobs

**Cycle source/result ATS:** https://icfcjb.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/Aerospace/jobs — ``

**Exact recorded reason:** Verified company source repair: https://icfcjb.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/Aerospace/jobs. Direct fetch returned partial: Verified company source repair: https://icfcjb.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/Aerospace/jobs. Honeywell published counters [789] do not reconcile with 788 unique published IDs. . Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Reproduce the precise direct-fetch failure below, inspect listing/detail schema and completeness contract; keep unresolved records partial.

**Candidate code:** `src/job_search_helper/ats.py`, `src/job_search_helper/oracle.py`

**Existing test candidates:** `tests/test_oracle.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0449 — IERUS Technologies

**Disposition:** Strong canonical-source candidate · **Work order:** W05

**Initial group:** C3 Stale URL/redirect/request repair

**Configured source:** `JobScore` — https://ierustech.com/careers/open-positions/

**Cycle source/result ATS:** https://hire.jobscore.com/jobs/ierustechnologiesinc/feed.atom — `JobScore`

**Exact recorded reason:** Verified company source repair: https://hire.jobscore.com/jobs/ierustechnologiesinc/feed.atom. Direct fetch returned partial: IERUS JobScore feed HTTP 301; inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Verified 301 hire.jobscore.com to careers.jobscore.com same tenant feed. Update exact source/detail host checks, then validate Atom completeness and reread.

**Candidate code:** `src/job_search_helper/ierus.py`, `src/job_search_helper/company_sources.py`, `src/job_search_helper/ats.py`

**Existing test candidates:** `tests/test_ierus.py`

**Fresh public check:** 2026-11-17T15:39:11.881097+00:00; HTTP 200; final URL https://careers.jobscore.com/jobs/ierustechnologiesinc/feed.atom; error none; evidence key `COMP-0449`.

**Provider text/asset leads only:** jobscore, phenom. These may be false positives; not a verified board.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0451 — The Aerospace Corporation

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B1 Workday access/response investigation

**Configured source:** `Workday` — https://aero.wd5.myworkdayjobs.com/External

**Cycle source/result ATS:** https://aero.wd5.myworkdayjobs.com/wday/cxs/aero/External — `Workday`

**Exact recorded reason:** Direct fetch returned partial: Workday job detail https://aero.wd5.myworkdayjobs.com/External/job/El-Segundo-CA/Spacecraft-Thermal-Engineer_R017244: Human verification detected; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Capture the failed Workday request page/posting and response classification; inspect host pacing and source filters. Validate all pages/details after recovery. Do not assume a new wrapper fixes genuine access denial.

**Candidate code:** `src/job_search_helper/workday.py`

**Existing test candidates:** `tests/test_workday.py`, `tests/test_workday_leidos.py`, `tests/test_workday_leidos_reconcile.py`, `tests/test_workday_reconcile.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0473 — CentralSquare Technologies

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B2 Other access/HTTP response investigation

**Configured source:** `CentralSquare HireBridge` — https://www.centralsquare.com/why-centralsquare/careers

**Cycle source/result ATS:** https://recruit.hirebridge.com/v3/Jobs/list.aspx?cid=7724 — `CentralSquare HireBridge`

**Exact recorded reason:** Verified company source repair: https://recruit.hirebridge.com/v3/Jobs/list.aspx?cid=7724. Direct fetch returned partial: CentralSquare HireBridge page blocked (HTTP 429).. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 429).

**Next action:** Confirm current public official source and classify actual response (challenge, rate limit, changed route or other error). Respect denial; preserve partial data. A new wrapper is not yet justified.

**Candidate code:** `src/job_search_helper/discovery.py`, `src/job_search_helper/ats.py`, `src/job_search_helper/centralsquare.py`

**Existing test candidates:** `tests/test_centralsquare.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0483 — Cyngn

**Current implementation status (2026-11-17):** W01 validated complete through normal dispatch: 19 full postings with stable final inventory reread. See `W01_RIPPLING_VALIDATION_2026-11-17.md`.

**Disposition:** Strong repair candidate · **Work order:** W01

**Initial group:** A1 Shared adapter exception

**Configured source:** `Rippling` — https://www.cyngn.com/company/careers

**Cycle source/result ATS:** https://ats.rippling.com/cyngn/jobs — `Rippling`

**Exact recorded reason:** Verified company source repair: https://ats.rippling.com/cyngn/jobs. Public board data/transport failed validation (AttributeError); inventory incomplete.

**Next action:** Repair shared Rippling query-key schema; verify the exact board, all pages, details and final membership.

**Candidate code:** `src/job_search_helper/shared_boards.py`

**Existing test candidates:** `tests/test_shared_boards.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0485 — Fox Robotics

**Disposition:** Employer scope needs proof · **Work order:** Scope investigations

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Browser (shared parent board)` — https://www.symbotic.com/careers/jobs/

**Cycle source/result ATS:** https://www.symbotic.com/careers/jobs/ — `Browser`

**Exact recorded reason:** Verified company source repair: https://www.symbotic.com/careers/jobs/. Direct fetch returned partial: Verified company source repair: https://www.symbotic.com/careers/jobs/. No supported ATS link found within the bounded careers-page discovery limit; the careers page is reachable but inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 127 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference.

**Next action:** Both rows use Symbotic careers. Prove independent Fox Robotics attribution and scope before integrating; never duplicate whole Symbotic inventory under Fox.

**Candidate code:** `src/job_search_helper/company_sources.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:11.928385+00:00; HTTP 200; final URL https://www.symbotic.com/careers/jobs/; error none; evidence key `COMP-0485`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0487 — Vislink Technologies

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B2 Other access/HTTP response investigation

**Configured source:** `Vislink careers` — https://www.vislink.com/about/careers/

**Cycle source/result ATS:** https://www.vislink.com/about/careers/ — `Vislink careers`

**Exact recorded reason:** Verified company source repair: https://www.vislink.com/about/careers/. Direct fetch returned partial: Verified company source repair: https://www.vislink.com/about/careers/. Vislink careers page HTTP 403: access denied or human verification.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 403).

**Next action:** Confirm current public official source and classify actual response (challenge, rate limit, changed route or other error). Respect denial; preserve partial data. A new wrapper is not yet justified.

**Candidate code:** `src/job_search_helper/discovery.py`, `src/job_search_helper/ats.py`, `src/job_search_helper/vislink.py`

**Existing test candidates:** `tests/test_vislink.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0488 — COMROD

**Disposition:** Existing provider investigation · **Work order:** W08

**Initial group:** A3 Provider parser/pagination/validation

**Configured source:** `COMROD careers` — https://www.comrod.com/about/careers/

**Cycle source/result ATS:** https://www.comrod.com/about/careers/ — `COMROD careers`

**Exact recorded reason:** Verified company source repair: https://www.comrod.com/about/careers/. Direct fetch returned partial: Verified company source repair: https://www.comrod.com/about/careers/. COMROD role link is outside the published careers scope.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 3 job URLs await retry. Inventory completeness unknown; no closure inference.

**Next action:** Reproduce the precise direct-fetch failure below, inspect listing/detail schema and completeness contract; keep unresolved records partial.

**Candidate code:** `src/job_search_helper/ats.py`, `src/job_search_helper/comrod.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 3 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0489 — Glenair

**Disposition:** No proven complete public inventory · **Work order:** No public inventory

**Initial group:** D1 No proven public inventory

**Configured source:** `Glenair employment inquiry` — https://www.glenair.com/contact/employment.htm

**Cycle source/result ATS:** https://www.glenair.com/contact/employment.htm — `Glenair employment inquiry`

**Exact recorded reason:** Verified company source repair: https://www.glenair.com/contact/employment.htm. Verified company source repair: https://www.glenair.com/contact/employment.htm. Glenair's official North America source is an employment-interest form, not a public job board or ATS; no public postings can be inventoried.

**Next action:** Seek a newly published official public job inventory; until one exists, preserve explicit unsupported/manual-source status and do not manufacture zero jobs from a contact or interest form.

**Candidate code:** `src/job_search_helper/company_sources.py`, `src/job_search_helper/ats.py`, `src/job_search_helper/glenair.py`

**Existing test candidates:** `tests/test_glenair.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0490 — Amphenol Aerospace

**Disposition:** Existing provider investigation · **Work order:** W08

**Initial group:** A3 Provider parser/pagination/validation

**Configured source:** `AcquireTM` — https://amphenol-aerospace.acquiretm.com/home.aspx

**Cycle source/result ATS:** https://amphenol-aerospace.acquiretm.com/home.aspx — `AcquireTM`

**Exact recorded reason:** Verified company source repair: https://amphenol-aerospace.acquiretm.com/home.aspx. Verified company source repair: https://amphenol-aerospace.acquiretm.com/home.aspx. AcquireTM total changed or pagination repeated.

**Next action:** Reproduce the precise direct-fetch failure below, inspect listing/detail schema and completeness contract; keep unresolved records partial.

**Candidate code:** `src/job_search_helper/ats.py`, `src/job_search_helper/acquiretm.py`

**Existing test candidates:** `tests/test_acquiretm.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0494 — Savox Communications

**Disposition:** Existing provider investigation · **Work order:** W08

**Initial group:** A3 Provider parser/pagination/validation

**Configured source:** `Savox careers` — https://www.savox.com/careers

**Cycle source/result ATS:** https://www.savox.com/careers — `Savox careers`

**Exact recorded reason:** Verified company source repair: https://www.savox.com/careers. Direct fetch returned partial: Verified company source repair: https://www.savox.com/careers. Savox careers page has no published job links.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Reproduce the precise direct-fetch failure below, inspect listing/detail schema and completeness contract; keep unresolved records partial.

**Candidate code:** `src/job_search_helper/ats.py`, `src/job_search_helper/savox.py`

**Existing test candidates:** `tests/test_savox.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0495 — Overland AI

**Current implementation status (2026-11-17):** W01 validated complete through normal dispatch: 46 full postings with stable final inventory reread. See `W01_RIPPLING_VALIDATION_2026-11-17.md`.

**Disposition:** Strong repair candidate · **Work order:** W01

**Initial group:** A1 Shared adapter exception

**Configured source:** `Rippling` — https://www.overland.ai/careers

**Cycle source/result ATS:** https://ats.rippling.com/overland-ai/jobs — `Rippling`

**Exact recorded reason:** Verified company source repair: https://ats.rippling.com/overland-ai/jobs. Public board data/transport failed validation (AttributeError); inventory incomplete.

**Next action:** Repair shared Rippling query-key schema; verify the exact board, all pages, details and final membership.

**Candidate code:** `src/job_search_helper/shared_boards.py`

**Existing test candidates:** `tests/test_shared_boards.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0506 — Scythe Robotics

**Disposition:** Canonical-source candidate · **Work order:** W05

**Initial group:** C3 Stale URL/redirect/request repair

**Configured source:** `Dover careers` — https://joinscythe.com/

**Cycle source/result ATS:** https://app.dover.com/jobs/scytherobotics — `Dover careers`

**Exact recorded reason:** Verified company source repair: https://app.dover.com/jobs/scytherobotics. Direct fetch returned partial: Scythe Robotics careers page HTTP 301.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Verified Dover migration to jobs.dover.com/scytherobotics?src=app (200). Inspect new listing/detail/empty schema and update narrow old-host/path checks.

**Candidate code:** `src/job_search_helper/scythe_robotics.py`, `src/job_search_helper/company_sources.py`, `src/job_search_helper/ats.py`

**Existing test candidates:** `tests/test_scythe_robotics.py`

**Fresh public check:** 2026-11-17T15:39:11.981902+00:00; HTTP 200; final URL https://jobs.dover.com/scytherobotics?src=app; error none; evidence key `COMP-0506`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0508 — Axiom Space

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B1 Workday access/response investigation

**Configured source:** `Workday` — https://axiomspace.com/careers

**Cycle source/result ATS:** https://axiomspace.wd5.myworkdayjobs.com/wday/cxs/axiomspace/External_Career_Site — `Workday`

**Exact recorded reason:** Direct fetch returned partial: Discovered Workday board https://axiomspace.wd5.myworkdayjobs.com/wday/cxs/axiomspace/External_Career_Site from https://axiomspace.com/careers. Workday listing page 10: Human verification detected; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Capture the failed Workday request page/posting and response classification; inspect host pacing and source filters. Validate all pages/details after recovery. Do not assume a new wrapper fixes genuine access denial.

**Candidate code:** `src/job_search_helper/workday.py`

**Existing test candidates:** `tests/test_workday.py`, `tests/test_workday_leidos.py`, `tests/test_workday_leidos_reconcile.py`, `tests/test_workday_reconcile.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0523 — Swisslog

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://www.swisslog.com/en-us/careers/openings

**Cycle source/result ATS:** https://www.swisslog.com/en-us/careers/openings — `Official careers`

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found within the bounded careers-page discovery limit; the careers page is reachable but inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 1 job descriptions; 21 job URLs await retry. Inventory completeness unknown; no closure inference. Browser time limit reached (300 seconds); saved progress retained.

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:12.160751+00:00; HTTP 200; final URL https://www.swisslog.com/en-us/careers/openings; error none; evidence key `COMP-0523`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 21 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0524 — Swisslog Healthcare

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://www.swisslog-healthcare.com/en-us/careers/openings

**Cycle source/result ATS:** https://www.swisslog-healthcare.com/en-us/careers/openings — `Official careers`

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found within the bounded careers-page discovery limit; the careers page is reachable but inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 12 job descriptions; 5 job URLs await retry. Inventory completeness unknown; no closure inference. Browser time limit reached (300 seconds); saved progress retained.

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:12.721638+00:00; HTTP 200; final URL https://www.swisslog-healthcare.com/en-us/careers/openings; error none; evidence key `COMP-0524`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 5 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0525 — TGW Logistics

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://www.tgw-group.com/us/career/jobs/

**Cycle source/result ATS:** https://www.tgw-group.com/us/career/jobs/ — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found within the bounded careers-page discovery limit; the careers page is reachable but inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 903 job URLs await retry. Inventory completeness unknown; no closure inference. Stopped this detail pass after 5 consecutive failures; unresolved URLs and saved descriptions retained.

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:13.078426+00:00; HTTP 200; final URL https://www.tgw-group.com/us/career/jobs/; error none; evidence key `COMP-0525`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 903 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0527 — Hai Robotics

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://www.hairobotics.com/join-us

**Cycle source/result ATS:** https://www.hairobotics.com/join-us — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found within the bounded careers-page discovery limit; the careers page is reachable but inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference.

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:13.217652+00:00; HTTP 200; final URL https://www.hairobotics.com/join-us; error none; evidence key `COMP-0527`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0528 — AutoStore

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B1 Workday access/response investigation

**Configured source:** `Workday` — https://autostore.wd3.myworkdayjobs.com/autostore

**Cycle source/result ATS:** https://autostore.wd3.myworkdayjobs.com/wday/cxs/autostore/autostore — `Workday`

**Exact recorded reason:** Direct fetch returned partial: Workday listing page 2: Human verification detected; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Capture the failed Workday request page/posting and response classification; inspect host pacing and source filters. Validate all pages/details after recovery. Do not assume a new wrapper fixes genuine access denial.

**Candidate code:** `src/job_search_helper/workday.py`

**Existing test candidates:** `tests/test_workday.py`, `tests/test_workday_leidos.py`, `tests/test_workday_leidos_reconcile.py`, `tests/test_workday_reconcile.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0529 — Vanderlande

**Disposition:** Source configuration repair candidate · **Work order:** W08

**Initial group:** A3 Provider parser/pagination/validation

**Configured source:** `Workday / official careers` — https://careers.vanderlande.com/all-jobs/

**Cycle source/result ATS:** https://careers.vanderlande.com/all-jobs/ — ``

**Exact recorded reason:** Direct fetch returned partial: Discovered board disagrees with ATS / Source; verify the company configuration.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Discovered ATS disagrees with configured ATS. Verify canonical current Vanderlande board, repair exact ATS+URL together and check Bastian overlap/scope.

**Candidate code:** `src/job_search_helper/discovery.py`, `src/job_search_helper/company_sources.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0532 — Körber Supply Chain

**Disposition:** Network/source investigation · **Work order:** Access investigations

**Initial group:** B3 Network/service failure

**Configured source:** `Official careers` — https://jobs.koerber.com/go/NA-KSC/9767501/

**Cycle source/result ATS:** https://jobs.koerber.com/go/NA-KSC/9767501/ — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page network/timeout failure; board discovery did not complete.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Browser fallback needs retry (TimeoutError).

**Next action:** Recheck canonical official URL, TLS/DNS/HTTP status and bounded timeout behavior; confirm native provider after recovery. Do not disable certificate verification or infer an empty board.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0534 — WITRON

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B2 Other access/HTTP response investigation

**Configured source:** `Official careers` — https://careers.witron.com/

**Cycle source/result ATS:** https://careers.witron.com/ — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page HTTP 403: access denied or human verification; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 403).

**Next action:** Confirm current public official source and classify actual response (challenge, rate limit, changed route or other error). Respect denial; preserve partial data. A new wrapper is not yet justified.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0536 — Honeywell Industrial Automation

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Oracle Recruiting` — https://careers.honeywell.com/en/sites/Honeywell/jobs

**Cycle source/result ATS:** https://careers.honeywell.com/en/sites/Honeywell/jobs — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found on careers page or obvious same-site job links; the careers page is reachable but may use another ATS or require JavaScript, so inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Browser fallback needs retry (Error).

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:13.402116+00:00; HTTP 200; final URL https://careers.honeywell.com/en/sites/Honeywell/jobs; error none; evidence key `COMP-0536`.

**Extracted provider-link leads (unverified scope):** https://ibqbjb.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/images?imageId=054D3A1F-6627-4694-9575-2BD0A55CA334 ; https://ibqbjb.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/images?imageId=0B9DABE2-BADA-49F1-8330-BB92C1D99BF0 ; https://ibqbjb.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/images?imageId=0DD359BE-37A0-4089-846B-7311E3A82B3A ; https://ibqbjb.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/images?imageId=410D5B04-AFF9-4AC6-AC66-36FD17477F0C ; https://ibqbjb.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/images?imageId=463765E6-9B9A-459C-83B6-89FA2C457C4A ; https://ibqbjb.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/images?imageId=5623294C-D017-44D7-82FC-C30EA83F5CA3

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0537 — Mobile Industrial Robots (MiR)

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Teradyne careers` — https://mobile-industrial-robots.com/about/career/open-vacancies

**Cycle source/result ATS:** https://mobile-industrial-robots.com/about/career/open-vacancies — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found on careers page or obvious same-site job links; the careers page is reachable but may use another ATS or require JavaScript, so inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 38 job URLs await retry. Inventory completeness unknown; no closure inference. Stopped this detail pass after 5 consecutive failures; unresolved URLs and saved descriptions retained.

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:14.299997+00:00; HTTP 200; final URL https://mobile-industrial-robots.com/about/career/open-vacancies; error none; evidence key `COMP-0537`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 38 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0538 — Zebra Technologies

**Disposition:** Native integration candidate · **Work order:** W06

**Initial group:** C1 Employer scope or multiple boards

**Configured source:** `Official careers` — https://www.zebra.com/us/en/about-zebra/careers.html

**Cycle source/result ATS:** https://www.zebra.com/us/en/about-zebra/careers.html — ``

**Exact recorded reason:** Direct fetch returned partial: Multiple ATS boards linked by careers page; select the company's board explicitly.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 1 job URLs await retry. Inventory completeness unknown; no closure inference.

**Next action:** Current official page links employer Workday tenant. Add exact source repair using linked board, not login/highlighted search links; verify current response and all-page/detail completeness.

**Candidate code:** `src/job_search_helper/workday.py`, `src/job_search_helper/company_sources.py`

**Existing test candidates:** `tests/test_workday.py`, `tests/test_workday_leidos.py`, `tests/test_workday_leidos_reconcile.py`, `tests/test_workday_reconcile.py`

**Fresh public check:** 2026-11-17T15:39:14.368576+00:00; HTTP 200; final URL https://www.zebra.com/us/en/about-zebra/careers.html; error none; evidence key `COMP-0538`.

**Extracted provider-link leads (unverified scope):** https://zebra.wd501.myworkdayjobs.com/Zebra_careers ; https://zebra.wd501.myworkdayjobs.com/en-US/Zebra_careers/jobs?jobFamilyGroup=281a47809d0e100122c06ac3b01a0000 ; https://zebra.wd501.myworkdayjobs.com/en-US/Zebra_careers/jobs?jobFamilyGroup=281a47809d0e100122c07b06ca790000&jobFamilyGroup=281a47809d0e100122c091509a340000 ; https://zebra.wd501.myworkdayjobs.com/en-US/Zebra_careers?jobFamilyGroup=281a47809d0e100122c07f3e9f3b0000&jobFamilyGroup=281a47809d0e100122c0668ee76c0000&jobFamilyGroup=281a47809d0e100122c05b1e2b5f0000&jobFamilyGroup=281a47809d0e100122c06f941d810000&jobFamilyGroup=281a47809d0e100122c061be4b880000&jobFamilyGroup=281a47809d0e100122c071fd4b0c0000&jobFamilyGroup=281a47809d0e100122c08e4d47920000&jobFamilyGroup=281a47809d0e100122c0e6d694590000&jobFamilyGroup=281a47809d0e100122c0e205658b0000 ; https://zebra.wd501.myworkdayjobs.com/en-US/Zebra_careers?jobFamilyGroup=281a47809d0e100122c08be3dd400000 ; https://zebra.wd501.myworkdayjobs.com/en-US/Zebra_careers?workerSubType=2e88c140a2411000e8503b59f9a80000

**Checkpoint context:** 1 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0539 — Mytra

**Current implementation status (2026-11-17):** W01 validated complete through normal dispatch: 40 full postings with stable final inventory reread. See `W01_RIPPLING_VALIDATION_2026-11-17.md`.

**Disposition:** Strong repair candidate · **Work order:** W01

**Initial group:** A1 Shared adapter exception

**Configured source:** `Rippling` — https://mytra.ai/careers

**Cycle source/result ATS:** https://mytra.ai/careers — `Rippling`

**Exact recorded reason:** Public board data/transport failed validation (AttributeError); inventory incomplete.

**Next action:** Repair shared Rippling query-key schema; verify the exact board, all pages, details and final membership.

**Candidate code:** `src/job_search_helper/shared_boards.py`

**Existing test candidates:** `tests/test_shared_boards.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0542 — Serve Robotics

**Disposition:** Strong native integration candidate · **Work order:** W06

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Ashby / official careers` — https://www.serverobotics.com/careers/

**Cycle source/result ATS:** https://www.serverobotics.com/careers/ — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found on careers page or obvious same-site job links; the careers page is reachable but may use another ATS or require JavaScript, so inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Official Ashby embed verified; public serverobotics posting feed HTTP 200 with 23 rows. Reuse Ashby normal dispatch and verify full descriptions and inventory reread.

**Candidate code:** `src/job_search_helper/ats.py`, `src/job_search_helper/company_sources.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:14.776179+00:00; HTTP 200; final URL https://www.serverobotics.com/careers/; error none; evidence key `COMP-0542`.

**Extracted provider-link leads (unverified scope):** https://jobs.ashbyhq.com/serverobotics/embed?version=2

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0545 — Loop Robots

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://us.looprobots.com/careers

**Cycle source/result ATS:** https://us.looprobots.com/careers — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found on careers page or obvious same-site job links; the careers page is reachable but may use another ATS or require JavaScript, so inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:14.849936+00:00; HTTP 200; final URL https://us.looprobots.com/careers; error none; evidence key `COMP-0545`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0547 — Amazon Robotics

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Amazon Jobs` — https://www.amazon.jobs/en/search?base_query=robotics

**Cycle source/result ATS:** https://www.amazon.jobs/en/search?base_query=robotics — `Amazon Jobs`

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found within the bounded careers-page discovery limit; the careers page is reachable but inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 10 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference.

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:15.161937+00:00; HTTP 200; final URL https://www.amazon.jobs/en/search?base_query=robotics; error none; evidence key `COMP-0547`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0549 — Intuitive

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B2 Other access/HTTP response investigation

**Configured source:** `Official careers` — https://careers.intuitive.com/en/jobs

**Cycle source/result ATS:** https://careers.intuitive.com/en/jobs — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page HTTP 403: access denied or human verification; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 403).

**Next action:** Confirm current public official source and classify actual response (challenge, rate limit, changed route or other error). Respect denial; preserve partial data. A new wrapper is not yet justified.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0550 — Johnson & Johnson MedTech Robotics

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B2 Other access/HTTP response investigation

**Configured source:** `Workday` — https://www.careers.jnj.com/en/teams/medtech-and-surgical-robotics/

**Cycle source/result ATS:** https://www.careers.jnj.com/en/teams/medtech-and-surgical-robotics/ — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page HTTP 403: access denied or human verification; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 403).

**Next action:** Confirm current public official source and classify actual response (challenge, rate limit, changed route or other error). Respect denial; preserve partial data. A new wrapper is not yet justified.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0551 — Stryker

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://careers.stryker.com/

**Cycle source/result ATS:** https://careers.stryker.com/ — `Official careers`

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found within the bounded careers-page discovery limit; the careers page is reachable but inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 10 job descriptions; 11 job URLs await retry. Inventory completeness unknown; no closure inference. Stopped this detail pass after 5 consecutive failures; unresolved URLs and saved descriptions retained.

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:15.591812+00:00; HTTP 200; final URL https://careers.stryker.com/; error none; evidence key `COMP-0551`.

**Provider text/asset leads only:** myworkdayjobs. These may be false positives; not a verified board.

**Checkpoint context:** 11 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0553 — CMR Surgical

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://us.cmrsurgical.com/careers

**Cycle source/result ATS:** https://us.cmrsurgical.com/careers — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found within the bounded careers-page discovery limit; the careers page is reachable but inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference.

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:15.837752+00:00; HTTP 200; final URL https://us.cmrsurgical.com/careers; error none; evidence key `COMP-0553`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0554 — Zimmer Biomet

**Disposition:** Provider discovery and scope candidate · **Work order:** W06

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://careers.zimmerbiomet.com/us/en/clinical-careers

**Cycle source/result ATS:** https://careers.zimmerbiomet.com/us/en/clinical-careers — `Official careers`

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found on careers page or obvious same-site job links; the careers page is reachable but may use another ATS or require JavaScript, so inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 51 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference.

**Next action:** Official page has Phenom evidence. Verify full relevant listing and preserve category/region/subsidiary intent; reuse phenom.py only after canonical tenant/filter completeness is proved.

**Candidate code:** `src/job_search_helper/phenom.py`, `src/job_search_helper/company_sources.py`

**Existing test candidates:** `tests/test_phenom.py`, `tests/test_phenom_reconciliation.py`

**Fresh public check:** 2026-11-17T15:39:15.861912+00:00; HTTP 200; final URL https://careers.zimmerbiomet.com/us/en/clinical-careers; error none; evidence key `COMP-0554`.

**Extracted provider-link leads (unverified scope):** https://career8.successfactors.com/careers?company=zimmerin01&loginFlowRequired=true&career_os=job_listing&career_ns=job_application&career_job_req_id=10584 ; https://career8.successfactors.com/careers?company=zimmerin01&loginFlowRequired=true&career_os=job_listing&career_ns=job_application&career_job_req_id=11361 ; https://career8.successfactors.com/careers?company=zimmerin01&loginFlowRequired=true&career_os=job_listing&career_ns=job_application&career_job_req_id=11978 ; https://career8.successfactors.com/careers?company=zimmerin01&loginFlowRequired=true&career_os=job_listing&career_ns=job_application&career_job_req_id=12161 ; https://career8.successfactors.com/careers?company=zimmerin01&loginFlowRequired=true&career_os=job_listing&career_ns=job_application&career_job_req_id=12206 ; https://career8.successfactors.com/careers?company=zimmerin01&loginFlowRequired=true&career_os=job_listing&career_ns=job_application&career_job_req_id=12272

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0555 — Emerson

**Disposition:** Existing provider investigation · **Work order:** W08

**Initial group:** A3 Provider parser/pagination/validation

**Configured source:** `Oracle Recruiting` — https://hdjq.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/jobs

**Cycle source/result ATS:** https://hdjq.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/jobs — ``

**Exact recorded reason:** Direct fetch returned partial: Posting 26014011: Oracle job detail is missing a title or full public description. Oracle normalized posting count does not match the inventory count.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Reproduce the precise direct-fetch failure below, inspect listing/detail schema and completeness contract; keep unresolved records partial.

**Candidate code:** `src/job_search_helper/ats.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `complete`. Neither pending count nor this flag alone proves coverage.

### COMP-0557 — Parker Hannifin

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B2 Other access/HTTP response investigation

**Configured source:** `Official careers` — https://parkercareers.ttcportals.com/search/jobs

**Cycle source/result ATS:** https://parkercareers.ttcportals.com/search/jobs — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page HTTP 403: access denied or human verification; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 403).

**Next action:** Confirm current public official source and classify actual response (challenge, rate limit, changed route or other error). Respect denial; preserve partial data. A new wrapper is not yet justified.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0558 — Mitsubishi Electric Automation

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `SilkRoad` — https://jobs.silkroad.com/meau/meauportal

**Cycle source/result ATS:** https://jobs.silkroad.com/meau/meauportal — `SilkRoad`

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found within the bounded careers-page discovery limit; the careers page is reachable but inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 5 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference.

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:16.050318+00:00; HTTP 200; final URL https://jobs.silkroad.com/meau/meauportal; error none; evidence key `COMP-0558`.

**Extracted provider-link leads (unverified scope):** https://jobs.silkroad.com/MEAU/MEAUportal ; https://jobs.silkroad.com/MEAU/MEAUportal/jobs/1207 ; https://jobs.silkroad.com/MEAU/MEAUportal/jobs/1209 ; https://jobs.silkroad.com/MEAU/MEAUportal/jobs/1210 ; https://jobs.silkroad.com/MEAU/MEAUportal/jobs/1216 ; https://jobs.silkroad.com/MEAU/MEAUportal/jobs/1217

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0560 — Festo

**Disposition:** Provider discovery candidate · **Work order:** W06

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://jobs.festo.com/viewalljobs/

**Cycle source/result ATS:** https://jobs.festo.com/viewalljobs/ — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found within the bounded careers-page discovery limit; the careers page is reachable but inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Browser fallback needs retry (TimeoutError).

**Next action:** Current official source contains SuccessFactors markers/links. Verify exact public listing/tenant, geographic and subsidiary scope, then reuse Jobs2Web or supported SuccessFactors route; asset markers alone are not board evidence.

**Candidate code:** `src/job_search_helper/successfactors.py`, `src/job_search_helper/company_sources.py`

**Existing test candidates:** `tests/test_successfactors.py`, `tests/test_successfactors_browser_fallback.py`, `tests/test_successfactors_retry.py`

**Fresh public check:** 2026-11-17T15:39:16.431602+00:00; HTTP 200; final URL https://jobs.festo.com/viewalljobs/; error none; evidence key `COMP-0560`.

**Extracted provider-link leads (unverified scope):** https://career5.successfactors.eu

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0561 — Vertiv

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Oracle Recruiting` — https://egup.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX/jobs

**Cycle source/result ATS:** https://egup.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX/jobs — ``

**Exact recorded reason:** Direct fetch returned partial: Oracle careers page did not expose one verified candidate-site identifier.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:16.568664+00:00; HTTP 200; final URL https://egup.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX/jobs; error none; evidence key `COMP-0561`.

**Extracted provider-link leads (unverified scope):** https://egup.fa.us2.oraclecloud.com:443

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0562 — GE Vernova

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B1 Workday access/response investigation

**Configured source:** `Workday` — https://careers.gevernova.com/jobs

**Cycle source/result ATS:** https://careers.gevernova.com/jobs — `Workday`

**Exact recorded reason:** Direct fetch returned blocked: Discovered Workday board https://gevernova.wd5.myworkdayjobs.com/wday/cxs/gevernova/Vernova_ExternalSite from https://careers.gevernova.com/manufacturing-team-leader/job/R5059197. Workday job detail https://gevernova.wd5.myworkdayjobs.com/Vernova_ExternalSite/job/Zamudio/Manufacturing-Shop-Operations-Manager_R5056806-2: Human verification detected; manual review required.. Browser fallback returned partial: Browser fallback saved 10 job descriptions; 11 job URLs await retry. Inventory completeness unknown; no closure inference. Stopped this detail pass after 5 consecutive failures; unresolved URLs and saved descriptions retained.

**Next action:** Capture the failed Workday request page/posting and response classification; inspect host pacing and source filters. Validate all pages/details after recovery. Do not assume a new wrapper fixes genuine access denial.

**Candidate code:** `src/job_search_helper/workday.py`

**Existing test candidates:** `tests/test_workday.py`, `tests/test_workday_leidos.py`, `tests/test_workday_leidos_reconcile.py`, `tests/test_workday_reconcile.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 11 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0563 — Hitachi Energy

**Disposition:** Employer scope needs proof · **Work order:** Scope investigations

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://careers.hitachi.com/

**Cycle source/result ATS:** https://careers.hitachi.com/ — `Official careers`

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found within the bounded careers-page discovery limit; the careers page is reachable but inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 10 job descriptions; 11 job URLs await retry. Inventory completeness unknown; no closure inference. Stopped this detail pass after 5 consecutive failures; unresolved URLs and saved descriptions retained.

**Next action:** Official route leads to a broader parent board. Establish exact subsidiary/legal-entity attribution and complete filtered membership; do not relabel parent jobs under this company.

**Candidate code:** `src/job_search_helper/company_sources.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:17.015504+00:00; HTTP 200; final URL https://careers.hitachi.com/; error none; evidence key `COMP-0563`.

**Extracted provider-link leads (unverified scope):** https://hitachi.wd1.myworkdayjobs.com/hitachi/job/Birmingham-England-United-Kingdom/Large-Project-Office-HSE-Manager--F-M-D-_R0151067/apply ; https://hitachi.wd1.myworkdayjobs.com/hitachi/job/DEAI-HD-PL-Remote/Payroll-Specialist_R0151596-1/apply ; https://hitachi.wd1.myworkdayjobs.com/hitachi/job/Houston-Texas-United-States/Site-Manager_R0150745/apply ; https://hitachi.wd1.myworkdayjobs.com/hitachi/job/Ludvika-Dalarna-County-Sweden/Starta-din-karrir-som-Produktionsmedarbetare---Power-Transformers-Training-Center_R0150103-1/apply ; https://hitachi.wd1.myworkdayjobs.com/hitachi/job/Przasnysz-Masovian-Poland/Specialista-ds-Sprzeday--k-m-n-_R0151726/apply ; https://hitachi.wd1.myworkdayjobs.com/hitachi/job/Raleigh-North-Carolina-United-States/On-Site-Service-Coordinator_R0152209/apply

**Checkpoint context:** 11 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0564 — Trane Technologies

**Disposition:** Provider discovery and scope candidate · **Work order:** W06

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://careers.tranetechnologies.com/global/en/c/services-jobs

**Cycle source/result ATS:** https://careers.tranetechnologies.com/global/en/c/services-jobs — `Official careers`

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found on careers page or obvious same-site job links; the careers page is reachable but may use another ATS or require JavaScript, so inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 70 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference.

**Next action:** Official page has Phenom evidence. Verify full relevant listing and preserve category/region/subsidiary intent; reuse phenom.py only after canonical tenant/filter completeness is proved.

**Candidate code:** `src/job_search_helper/phenom.py`, `src/job_search_helper/company_sources.py`

**Existing test candidates:** `tests/test_phenom.py`, `tests/test_phenom_reconciliation.py`

**Fresh public check:** 2026-11-17T15:39:17.328371+00:00; HTTP 200; final URL https://careers.tranetechnologies.com/global/en/c/services-jobs; error none; evidence key `COMP-0564`.

**Extracted provider-link leads (unverified scope):** https://cdn.phenompeople.com/CareerConnectResources ; https://content-us.phenompeople.com ; https://content-us.phenompeople.com/api/content-delivery/caasContentV1

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0565 — JBT Marel

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B1 Workday access/response investigation

**Configured source:** `Workday` — https://jbtm.wd108.myworkdayjobs.com/JBT_Marel_Career_Site

**Cycle source/result ATS:** https://jbtm.wd108.myworkdayjobs.com/wday/cxs/jbtm/JBT_Marel_Career_Site — `Workday`

**Exact recorded reason:** Direct fetch returned partial: Workday job detail https://jbtm.wd108.myworkdayjobs.com/JBT_Marel_Career_Site/job/ES---Madrid/AP-Operations-Specialist_25739-1: Human verification detected; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Capture the failed Workday request page/posting and response classification; inspect host pacing and source filters. Validate all pages/details after recovery. Do not assume a new wrapper fixes genuine access denial.

**Candidate code:** `src/job_search_helper/workday.py`

**Existing test candidates:** `tests/test_workday.py`, `tests/test_workday_leidos.py`, `tests/test_workday_leidos_reconcile.py`, `tests/test_workday_reconcile.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0566 — ProMach

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B1 Workday access/response investigation

**Configured source:** `Workday` — https://www.promachinnovation.com/about/careers/

**Cycle source/result ATS:** https://promachbuilt.wd108.myworkdayjobs.com/wday/cxs/promachbuilt/promach — `Workday`

**Exact recorded reason:** Direct fetch returned partial: Discovered Workday board https://promachbuilt.wd108.myworkdayjobs.com/wday/cxs/promachbuilt/promach from https://www.promachinnovation.com/about/careers/. Workday job detail https://promachbuilt.wd108.myworkdayjobs.com/promach/job/New-Freedom-PA-USA/Purchasing-Coordinator_JR101855: Human verification detected; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Capture the failed Workday request page/posting and response classification; inspect host pacing and source filters. Validate all pages/details after recovery. Do not assume a new wrapper fixes genuine access denial.

**Candidate code:** `src/job_search_helper/workday.py`

**Existing test candidates:** `tests/test_workday.py`, `tests/test_workday_leidos.py`, `tests/test_workday_leidos_reconcile.py`, `tests/test_workday_reconcile.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0567 — Tetra Pak

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://www.tetrapak.com/en-us/about-tetra-pak/careers/USCA-careers

**Cycle source/result ATS:** https://www.tetrapak.com/en-us/about-tetra-pak/careers/USCA-careers — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found within the bounded careers-page discovery limit; the careers page is reachable but inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 403).

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:17.611301+00:00; HTTP 200; final URL https://www.tetrapak.com/en-us/about-tetra-pak/careers/USCA-careers; error none; evidence key `COMP-0567`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0568 — SMC Corporation of America

**Disposition:** Native source discovery candidate · **Work order:** W06

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://careers.smcusa.com/search

**Cycle source/result ATS:** https://careers.smcusa.com/search — `Official careers`

**Exact recorded reason:** Direct fetch returned unsupported: Careers discovery expected an HTML page; provide the ATS board URL.. Browser fallback returned partial: Browser fallback saved 10 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference.

**Next action:** Dayforce privacy link identifies smcnorthamerica/CANDIDATEPORTAL and custom source exposes a search API link; first verify actual complete public board and employer linkage.

**Candidate code:** `src/job_search_helper/shared_extended.py`, `src/job_search_helper/company_sources.py`

**Existing test candidates:** `tests/test_shared_extended.py`

**Fresh public check:** 2026-11-17T15:39:17.700112+00:00; HTTP 200; final URL https://careers.smcusa.com/search; error none; evidence key `COMP-0568`.

**Extracted provider-link leads (unverified scope):** https://jobs.dayforcehcm.com/en-US/smcnorthamerica/CANDIDATEPORTAL/privacyPolicy

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0569 — Siemens

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://jobs.siemens.com/en_US/externaljobs/SearchJobs/

**Cycle source/result ATS:** https://jobs.siemens.com/en_US/externaljobs/SearchJobs/ — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found within the bounded careers-page discovery limit; the careers page is reachable but inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 1434 job URLs await retry. Inventory completeness unknown; no closure inference. Browser time limit reached (300 seconds); saved progress retained.

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:17.839575+00:00; HTTP 200; final URL https://jobs.siemens.com/en_US/externaljobs/SearchJobs/; error none; evidence key `COMP-0569`.

**Provider text/asset leads only:** avature. These may be false positives; not a verified board.

**Checkpoint context:** 1434 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0570 — Danfoss

**Disposition:** Provider discovery candidate · **Work order:** W06

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://jobs.danfoss.com/

**Cycle source/result ATS:** https://jobs.danfoss.com/ — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found within the bounded careers-page discovery limit; the careers page is reachable but inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Current official source contains SuccessFactors markers/links. Verify exact public listing/tenant, geographic and subsidiary scope, then reuse Jobs2Web or supported SuccessFactors route; asset markers alone are not board evidence.

**Candidate code:** `src/job_search_helper/successfactors.py`, `src/job_search_helper/company_sources.py`

**Existing test candidates:** `tests/test_successfactors.py`, `tests/test_successfactors_browser_fallback.py`, `tests/test_successfactors_retry.py`

**Fresh public check:** 2026-11-17T15:39:17.897382+00:00; HTTP 200; final URL https://jobs.danfoss.com/; error none; evidence key `COMP-0570`.

**Extracted provider-link leads (unverified scope):** https://career2.successfactors.eu ; https://performancemanager.successfactors.eu/companyLogoServlet/?mod=danfossas-1789763221098 ; https://rmkcdn.successfactors.com/ef55fddb/58ad7360-29a7-4e48-9107-e.png) ; https://rmkcdn.successfactors.com/ef55fddb/c514a341-afd7-4ae6-ad95-c.png);

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0571 — Bosch Rexroth

**Disposition:** Already implemented; run adoption pending · **Work order:** W09

**Initial group:** A3 Provider parser/pagination/validation

**Configured source:** `SmartRecruiters` — https://www.boschrexroth.com/en/us/jobs-and-career/

**Cycle source/result ATS:** https://careers.smartrecruiters.com/BoschGroup — `SmartRecruiters`

**Exact recorded reason:** SmartRecruiters: retrieved 5047 full postings and rechecked the public inventory. Reconciled inventory changes: added 4 (IDs: 744000162094790, 744000162099143, 744000162099579, 744000162102229); removed 8 (IDs: 744000137980736, 744000153814836, 744000153817779, 744000154094259, 744000157900487); edited 0. 15 postings failed validation: 744000160905288: SmartRecruiters full description missing.; 744000151049068: SmartRecruiters full description missing.; 744000143687749: SmartRecruiters full description missing..

**Next action:** Current runtime has new scoped Rexroth wrapper; prior same-day receipt complete with 70 US jobs. Final cycle records old broad Bosch fetch. Verify source hashes and new process adoption; do not duplicate implementation.

**Candidate code:** `src/job_search_helper/bosch_rexroth.py`, `src/job_search_helper/ats.py`, `src/job_search_helper/shared_boards.py`

**Existing test candidates:** `tests/test_bosch_rexroth.py`, `tests/test_shared_boards.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0572 — Eaton

**Disposition:** Network/source investigation · **Work order:** Access investigations

**Initial group:** B3 Network/service failure

**Configured source:** `Official careers` — https://www.eaton.com/content/eaton/us/en-us/company/careers.html

**Cycle source/result ATS:** https://www.eaton.com/content/eaton/us/en-us/company/careers.html — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page network/timeout failure; board discovery did not complete.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Browser fallback needs retry (Error).

**Next action:** Recheck canonical official URL, TLS/DNS/HTTP status and bounded timeout behavior; confirm native provider after recovery. Do not disable certificate verification or infer an empty board.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0573 — ATS Corporation

**Disposition:** Provider discovery candidate · **Work order:** W06

**Initial group:** C2 Native source discovery/routing

**Configured source:** `SuccessFactors` — https://jobs.atsautomation.com/

**Cycle source/result ATS:** https://jobs.atsautomation.com/ — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found within the bounded careers-page discovery limit; the careers page is reachable but inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Browser fallback needs retry (TimeoutError).

**Next action:** Current official source contains SuccessFactors markers/links. Verify exact public listing/tenant, geographic and subsidiary scope, then reuse Jobs2Web or supported SuccessFactors route; asset markers alone are not board evidence.

**Candidate code:** `src/job_search_helper/successfactors.py`, `src/job_search_helper/company_sources.py`

**Existing test candidates:** `tests/test_successfactors.py`, `tests/test_successfactors_browser_fallback.py`, `tests/test_successfactors_retry.py`

**Fresh public check:** 2026-11-17T15:39:18.337305+00:00; HTTP 200; final URL https://jobs.atsautomation.com/; error none; evidence key `COMP-0573`.

**Extracted provider-link leads (unverified scope):** https://career5.successfactors.eu ; https://career5.successfactors.eu/career?site=&company=atsP2&lang=en_US&login_ns=register&career_ns=home&navBarLevel=MY_PROFILE

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0578 — Dusty Robotics

**Disposition:** Source/redirect investigation · **Work order:** W05 / source repair

**Initial group:** C3 Stale URL/redirect/request repair

**Configured source:** `Greenhouse` — https://www.dustyrobotics.com/careers

**Cycle source/result ATS:** https://boards-api.greenhouse.io/v1/boards/dustyrobotics/jobs?content=true — `Greenhouse`

**Exact recorded reason:** Direct fetch returned partial: Discovered Greenhouse board https://boards-api.greenhouse.io/v1/boards/dustyrobotics from https://www.dustyrobotics.com/careers. HTTP 404; inventory unavailable, not evidence of closure.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Follow the exact current official link/redirect with bounded trusted destinations; validate replacement board and scope. A 404 is not closure. Test dispatch/source aliases and every page/detail.

**Candidate code:** `src/job_search_helper/company_sources.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:18.513048+00:00; HTTP 404; final URL https://boards-api.greenhouse.io/v1/boards/dustyrobotics/jobs?content=true; error none; evidence key `COMP-0578`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0582 — GreyOrange

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://careers.greyorange.com/greyorange/

**Cycle source/result ATS:** https://careers.greyorange.com/greyorange/ — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found on careers page or obvious same-site job links; the careers page is reachable but may use another ATS or require JavaScript, so inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:19.269862+00:00; HTTP 200; final URL https://careers.greyorange.com/greyorange/; error none; evidence key `COMP-0582`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0584 — KONE

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B1 Workday access/response investigation

**Configured source:** `Workday` — https://kone.wd3.myworkdayjobs.com/Careers

**Cycle source/result ATS:** https://kone.wd3.myworkdayjobs.com/wday/cxs/kone/Careers — `Workday`

**Exact recorded reason:** Direct fetch returned partial: Workday listing page 1: Human verification detected; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Capture the failed Workday request page/posting and response classification; inspect host pacing and source filters. Validate all pages/details after recovery. Do not assume a new wrapper fixes genuine access denial.

**Candidate code:** `src/job_search_helper/workday.py`

**Existing test candidates:** `tests/test_workday.py`, `tests/test_workday_leidos.py`, `tests/test_workday_leidos_reconcile.py`, `tests/test_workday_reconcile.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0586 — TK Elevator

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://jobs.tkelevator.com/en

**Cycle source/result ATS:** https://jobs.tkelevator.com/en — `Official careers`

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found on careers page or obvious same-site job links; the careers page is reachable but may use another ATS or require JavaScript, so inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 20 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference.

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:19.500913+00:00; HTTP 200; final URL https://jobs.tkelevator.com/en; error none; evidence key `COMP-0586`.

**Extracted provider-link leads (unverified scope):** https://career5.successfactors.eu/careers?company=C0001089563P

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0587 — Schindler Elevator

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Company website; careers URL unverified` — https://www.schindler.com/

**Cycle source/result ATS:** https://www.schindler.com/ — `Company website; careers URL unverified`

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found within the bounded careers-page discovery limit; the careers page is reachable but inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 1 job descriptions; 9 job URLs await retry. Inventory completeness unknown; no closure inference. Stopped this detail pass after 5 consecutive failures; unresolved URLs and saved descriptions retained.

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:19.781590+00:00; HTTP 200; final URL https://www.schindler.com/en.html; error none; evidence key `COMP-0587`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 9 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0588 — Crown Equipment

**Disposition:** Provider discovery candidate · **Work order:** W06

**Initial group:** C2 Native source discovery/routing

**Configured source:** `SuccessFactors` — https://us-careers.crown.com/

**Cycle source/result ATS:** https://us-careers.crown.com/ — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found within the bounded careers-page discovery limit; the careers page is reachable but inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Current official source contains SuccessFactors markers/links. Verify exact public listing/tenant, geographic and subsidiary scope, then reuse Jobs2Web or supported SuccessFactors route; asset markers alone are not board evidence.

**Candidate code:** `src/job_search_helper/successfactors.py`, `src/job_search_helper/company_sources.py`

**Existing test candidates:** `tests/test_successfactors.py`, `tests/test_successfactors_browser_fallback.py`, `tests/test_successfactors_retry.py`

**Fresh public check:** 2026-11-17T15:39:19.946939+00:00; HTTP 200; final URL https://us-careers.crown.com/; error none; evidence key `COMP-0588`.

**Extracted provider-link leads (unverified scope):** https://career4.successfactors.com ; https://career4.successfactors.com/career?site=&company=C0000169989P&lang=en_US&login_ns=register&career_ns=home&navBarLevel=MY_PROFILE

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0589 — Toyota Material Handling

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://www.toyotaforklift.com/careers

**Cycle source/result ATS:** https://www.toyotaforklift.com/careers — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found within the bounded careers-page discovery limit; the careers page is reachable but inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 1 job URLs await retry. Inventory completeness unknown; no closure inference.

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:20.313974+00:00; HTTP 200; final URL https://www.toyotaforklift.com/careers; error none; evidence key `COMP-0589`.

**Extracted provider-link leads (unverified scope):** https://recruiting.adp.com/srccar/public/RTI.home?d=TMHUCareerSite&c=1138141

**Checkpoint context:** 1 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0590 — The Raymond Corporation

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Company website; careers URL unverified` — https://www.raymondcorp.com/

**Cycle source/result ATS:** https://www.raymondcorp.com/ — ``

**Exact recorded reason:** Direct fetch returned partial: Careers discovery expected an HTML page; provide the ATS board URL.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:21.067240+00:00; HTTP 200; final URL https://www.raymondcorp.com/; error none; evidence key `COMP-0590`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0591 — Hyster-Yale

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Company website; careers URL unverified` — https://www.hyster-yale.com/

**Cycle source/result ATS:** https://www.hyster-yale.com/ — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found on careers page or obvious same-site job links; the careers page is reachable but may use another ATS or require JavaScript, so inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:21.079776+00:00; HTTP 200; final URL https://www.hyster-yale.com/; error none; evidence key `COMP-0591`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0592 — Jungheinrich

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://www.jungheinrich.com/en/career

**Cycle source/result ATS:** https://www.jungheinrich.com/en/career — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found within the bounded careers-page discovery limit; the careers page is reachable but inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 403).

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:21.425336+00:00; HTTP 200; final URL https://www.jungheinrich.com/en/career; error none; evidence key `COMP-0592`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0594 — Tennant Company

**Disposition:** Provider discovery candidate · **Work order:** W06

**Initial group:** C2 Native source discovery/routing

**Configured source:** `SuccessFactors` — https://jobs.tennantco.com/

**Cycle source/result ATS:** https://jobs.tennantco.com/ — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found within the bounded careers-page discovery limit; the careers page is reachable but inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Current official source contains SuccessFactors markers/links. Verify exact public listing/tenant, geographic and subsidiary scope, then reuse Jobs2Web or supported SuccessFactors route; asset markers alone are not board evidence.

**Candidate code:** `src/job_search_helper/successfactors.py`, `src/job_search_helper/company_sources.py`

**Existing test candidates:** `tests/test_successfactors.py`, `tests/test_successfactors_browser_fallback.py`, `tests/test_successfactors_retry.py`

**Fresh public check:** 2026-11-17T15:39:21.565149+00:00; HTTP 200; final URL https://jobs.tennantco.com/; error none; evidence key `COMP-0594`.

**Extracted provider-link leads (unverified scope):** https://career4.successfactors.com

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0595 — Nilfisk

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B1 Workday access/response investigation

**Configured source:** `Workday` — https://www.nilfisk.com/

**Cycle source/result ATS:** https://nilfisk.wd3.myworkdayjobs.com/wday/cxs/nilfisk/Nilfisk — `Workday`

**Exact recorded reason:** Direct fetch returned partial: Discovered Workday board https://nilfisk.wd3.myworkdayjobs.com/wday/cxs/nilfisk/Nilfisk from https://www.nilfisk.com/global/professional/about-nilfisk/job-and-career/. Workday listing page 1: Human verification detected; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Capture the failed Workday request page/posting and response classification; inspect host pacing and source filters. Validate all pages/details after recovery. Do not assume a new wrapper fixes genuine access denial.

**Candidate code:** `src/job_search_helper/workday.py`

**Existing test candidates:** `tests/test_workday.py`, `tests/test_workday_leidos.py`, `tests/test_workday_leidos_reconcile.py`, `tests/test_workday_reconcile.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0597 — Gausium

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://gausium.com/careers/

**Cycle source/result ATS:** https://gausium.com/careers/ — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found within the bounded careers-page discovery limit; the careers page is reachable but inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:21.628982+00:00; HTTP 200; final URL https://gausium.com/careers/; error none; evidence key `COMP-0597`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0598 — E80 Group

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Company website; careers URL unverified` — https://www.e80group.com/

**Cycle source/result ATS:** https://www.e80group.com/ — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found within the bounded careers-page discovery limit; the careers page is reachable but inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:21.910831+00:00; HTTP 200; final URL https://www.e80group.com/en/; error none; evidence key `COMP-0598`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0599 — Geek+

**Disposition:** Regional/multiple-board scope needs proof · **Work order:** Scope investigations

**Initial group:** C1 Employer scope or multiple boards

**Configured source:** `BambooHR` — https://www.geekplus.com/

**Cycle source/result ATS:** https://www.geekplus.com/ — `BambooHR`

**Exact recorded reason:** BambooHR: retrieved 6 full postings and rechecked the public inventory. Discovered tenant https://geekplus.bamboohr.com from the configured employer careers page. Employer page links a subset or stale postings on the BambooHR board; only its listed open jobs were retrieved, and company inventory completeness is unverified.

**Next action:** Recorded source exposes subset or stale employer links. Map official regional boards, prove intended employer/country set, fetch every board and deduplicate stable IDs.

**Candidate code:** `src/job_search_helper/bamboohr.py`, `src/job_search_helper/company_sources.py`

**Existing test candidates:** `tests/test_bamboohr.py`

**Fresh public check:** 2026-11-17T15:39:22.022337+00:00; HTTP 200; final URL https://www.geekplus.com/en; error none; evidence key `COMP-0599`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0600 — Addverb

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://careers.addverb.com/

**Cycle source/result ATS:** https://careers.addverb.com/ — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found on careers page or obvious same-site job links; the careers page is reachable but may use another ATS or require JavaScript, so inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:22.435853+00:00; HTTP 200; final URL https://careers.addverb.com/; error none; evidence key `COMP-0600`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0601 — ForwardX Robotics

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://www.forwardx.com/join-the-team/

**Cycle source/result ATS:** https://www.forwardx.com/join-the-team/ — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found on careers page or obvious same-site job links; the careers page is reachable but may use another ATS or require JavaScript, so inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:22.735597+00:00; HTTP 200; final URL https://www.forwardx.com/join-the-team/; error none; evidence key `COMP-0601`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0604 — Krones

**Disposition:** Provider discovery candidate · **Work order:** W06

**Initial group:** C2 Native source discovery/routing

**Configured source:** `SuccessFactors` — https://workfor.kronesusa.com/go/View-All-Jobs/9284400/

**Cycle source/result ATS:** https://workfor.kronesusa.com/go/View-All-Jobs/9284400/ — `SuccessFactors`

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found within the bounded careers-page discovery limit; the careers page is reachable but inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 21 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference.

**Next action:** Current official source contains SuccessFactors markers/links. Verify exact public listing/tenant, geographic and subsidiary scope, then reuse Jobs2Web or supported SuccessFactors route; asset markers alone are not board evidence.

**Candidate code:** `src/job_search_helper/successfactors.py`, `src/job_search_helper/company_sources.py`

**Existing test candidates:** `tests/test_successfactors.py`, `tests/test_successfactors_browser_fallback.py`, `tests/test_successfactors_retry.py`

**Fresh public check:** 2026-11-17T15:39:23.216676+00:00; HTTP 200; final URL https://workfor.kronesusa.com/go/View-All-Jobs/9284400/; error none; evidence key `COMP-0604`.

**Extracted provider-link leads (unverified scope):** https://career8.successfactors.com

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0605 — Syntegon

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://jobs.syntegon.com/en/

**Cycle source/result ATS:** https://jobs.syntegon.com/en/ — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found within the bounded careers-page discovery limit; the careers page is reachable but inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:23.398169+00:00; HTTP 200; final URL https://jobs.syntegon.com/en/; error none; evidence key `COMP-0605`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0606 — Sidel

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://www.sidel.com/en/about/careers/vacancies/

**Cycle source/result ATS:** https://www.sidel.com/en/about/careers/vacancies/ — `Official careers`

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found within the bounded careers-page discovery limit; the careers page is reachable but inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 1 job descriptions; 111 job URLs await retry. Inventory completeness unknown; no closure inference. Stopped this detail pass after 5 consecutive failures; unresolved URLs and saved descriptions retained.

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:23.604135+00:00; HTTP 200; final URL https://www.sidel.com/en/about/careers/vacancies/; error none; evidence key `COMP-0606`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 111 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0607 — Coesia

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Company website; careers URL unverified` — https://www.coesia.com/

**Cycle source/result ATS:** https://www.coesia.com/ — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found within the bounded careers-page discovery limit; the careers page is reachable but inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:24.261686+00:00; HTTP 200; final URL https://www.coesia.com/en; error none; evidence key `COMP-0607`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0608 — Barry-Wehmiller

**Disposition:** Employer scope needs proof · **Work order:** Scope investigations

**Initial group:** C1 Employer scope or multiple boards

**Configured source:** `Company website; careers URL unverified` — https://www.barrywehmiller.com/

**Cycle source/result ATS:** https://www.barrywehmiller.com/ — ``

**Exact recorded reason:** Direct fetch returned partial: Multiple ATS boards linked by careers page; select the company's board explicitly.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 1 job URLs await retry. Inventory completeness unknown; no closure inference.

**Next action:** Prove attributable employer/legal-entity/brand and complete board set before implementing or widening a parent/shared source. Verify each regional board and deduplicate stable IDs.

**Candidate code:** `src/job_search_helper/company_sources.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:25.106149+00:00; HTTP 200; final URL https://www.barrywehmiller.com/; error none; evidence key `COMP-0608`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 1 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0609 — Duravant

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Company website; careers URL unverified` — https://www.duravant.com/

**Cycle source/result ATS:** https://www.duravant.com/ — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found on careers page or obvious same-site job links; the careers page is reachable but may use another ATS or require JavaScript, so inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:25.461759+00:00; HTTP 200; final URL https://www.duravant.com/; error none; evidence key `COMP-0609`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0610 — Heat and Control

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Company website; careers URL unverified` — https://www.heatandcontrol.com/

**Cycle source/result ATS:** https://www.heatandcontrol.com/ — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found within the bounded careers-page discovery limit; the careers page is reachable but inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:25.655321+00:00; HTTP 200; final URL https://www.heatandcontrol.com/; error none; evidence key `COMP-0610`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0611 — MULTIVAC

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B2 Other access/HTTP response investigation

**Configured source:** `Company website; careers URL unverified` — https://multivac.com/

**Cycle source/result ATS:** https://multivac.com/ — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page HTTP 429; board discovery did not complete.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 429).

**Next action:** Confirm current public official source and classify actual response (challenge, rate limit, changed route or other error). Respect denial; preserve partial data. A new wrapper is not yet justified.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0612 — KHS Group

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Company website; careers URL unverified` — https://www.khs.com/

**Cycle source/result ATS:** https://www.khs.com/ — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found on careers page or obvious same-site job links; the careers page is reachable but may use another ATS or require JavaScript, so inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:25.914559+00:00; HTTP 200; final URL https://www.khs.com/; error none; evidence key `COMP-0612`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0613 — Stratasys

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Company website; careers URL unverified` — https://www.stratasys.com/

**Cycle source/result ATS:** https://www.stratasys.com/ — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found within the bounded careers-page discovery limit; the careers page is reachable but inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:26.595786+00:00; HTTP 200; final URL https://www.stratasys.com/en/; error none; evidence key `COMP-0613`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0614 — EOS

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B1 Workday access/response investigation

**Configured source:** `Workday` — https://eosgroup.wd3.myworkdayjobs.com/eos

**Cycle source/result ATS:** https://eosgroup.wd3.myworkdayjobs.com/wday/cxs/eosgroup/eos — `Workday`

**Exact recorded reason:** Direct fetch returned partial: Workday listing page 1: Human verification detected; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Capture the failed Workday request page/posting and response classification; inspect host pacing and source filters. Validate all pages/details after recovery. Do not assume a new wrapper fixes genuine access denial.

**Candidate code:** `src/job_search_helper/workday.py`

**Existing test candidates:** `tests/test_workday.py`, `tests/test_workday_leidos.py`, `tests/test_workday_leidos_reconcile.py`, `tests/test_workday_reconcile.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0615 — Formlabs

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://careers.formlabs.com/

**Cycle source/result ATS:** https://careers.formlabs.com/ — `Official careers`

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found on careers page or obvious same-site job links; the careers page is reachable but may use another ATS or require JavaScript, so inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 265 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference.

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:26.698388+00:00; HTTP 200; final URL https://careers.formlabs.com/; error none; evidence key `COMP-0615`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0616 — TRUMPF

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B2 Other access/HTTP response investigation

**Configured source:** `Company website; careers URL unverified` — https://www.trumpf.com/

**Cycle source/result ATS:** https://www.trumpf.com/ — `Company website; careers URL unverified`

**Exact recorded reason:** Direct fetch returned blocked: Careers page HTTP 403: access denied or human verification; manual review required.. Browser fallback returned partial: Browser fallback saved 3 job descriptions; 6 job URLs await retry. Inventory completeness unknown; no closure inference. Browser time limit reached (300 seconds); saved progress retained.

**Next action:** Confirm current public official source and classify actual response (challenge, rate limit, changed route or other error). Respect denial; preserve partial data. A new wrapper is not yet justified.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 6 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0617 — DMG MORI

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Company website; careers URL unverified` — https://us.dmgmori.com/

**Cycle source/result ATS:** https://us.dmgmori.com/ — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found on careers page or obvious same-site job links; the careers page is reachable but may use another ATS or require JavaScript, so inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:27.328836+00:00; HTTP 200; final URL https://us.dmgmori.com/; error none; evidence key `COMP-0617`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0618 — Lincoln Electric

**Disposition:** Network/source investigation · **Work order:** Access investigations

**Initial group:** B3 Network/service failure

**Configured source:** `SuccessFactors` — https://jobs.lincolnelectric.com/

**Cycle source/result ATS:** https://jobs.lincolnelectric.com/ — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page network/timeout failure; board discovery did not complete.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Browser fallback needs retry (TimeoutError).

**Next action:** Recheck canonical official URL, TLS/DNS/HTTP status and bounded timeout behavior; confirm native provider after recovery. Do not disable certificate verification or infer an empty board.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0619 — AMETEK

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B2 Other access/HTTP response investigation

**Configured source:** `Official careers` — https://www.ametek.com/careers

**Cycle source/result ATS:** https://www.ametek.com/careers — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page HTTP 429; board discovery did not complete.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 1 job URLs await retry. Inventory completeness unknown; no closure inference.

**Next action:** Confirm current public official source and classify actual response (challenge, rate limit, changed route or other error). Respect denial; preserve partial data. A new wrapper is not yet justified.

**Candidate code:** `src/job_search_helper/discovery.py`, `src/job_search_helper/ats.py`, `src/job_search_helper/successfactors.py`

**Existing test candidates:** `tests/test_successfactors.py`, `tests/test_successfactors_browser_fallback.py`, `tests/test_successfactors_retry.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 1 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0620 — Teradyne

**Disposition:** Provider discovery candidate · **Work order:** W06

**Initial group:** C2 Native source discovery/routing

**Configured source:** `SuccessFactors` — https://jobs.teradyne.com/

**Cycle source/result ATS:** https://jobs.teradyne.com/ — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found within the bounded careers-page discovery limit; the careers page is reachable but inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Current official source contains SuccessFactors markers/links. Verify exact public listing/tenant, geographic and subsidiary scope, then reuse Jobs2Web or supported SuccessFactors route; asset markers alone are not board evidence.

**Candidate code:** `src/job_search_helper/successfactors.py`, `src/job_search_helper/company_sources.py`, `src/job_search_helper/ats.py`

**Existing test candidates:** `tests/test_successfactors.py`, `tests/test_successfactors_browser_fallback.py`, `tests/test_successfactors_retry.py`

**Fresh public check:** 2026-11-17T15:39:27.715832+00:00; HTTP 200; final URL https://jobs.teradyne.com/; error none; evidence key `COMP-0620`.

**Provider text/asset leads only:** successfactors. These may be false positives; not a verified board.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0621 — JLG Industries

**Disposition:** Provider discovery and scope candidate · **Work order:** W06

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Oshkosh/JLG careers` — https://careers.oshkoshcorp.com/us/en

**Cycle source/result ATS:** https://careers.oshkoshcorp.com/us/en — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found on careers page or obvious same-site job links; the careers page is reachable but may use another ATS or require JavaScript, so inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Official page has Phenom evidence. Verify full relevant listing and preserve category/region/subsidiary intent; reuse phenom.py only after canonical tenant/filter completeness is proved.

**Candidate code:** `src/job_search_helper/phenom.py`, `src/job_search_helper/company_sources.py`

**Existing test candidates:** `tests/test_phenom.py`, `tests/test_phenom_reconciliation.py`

**Fresh public check:** 2026-11-17T15:39:27.828397+00:00; HTTP 200; final URL https://careers.oshkoshcorp.com/us/en; error none; evidence key `COMP-0621`.

**Extracted provider-link leads (unverified scope):** https://cdn.phenompeople.com/CareerConnectResources ; https://content-us.phenompeople.com ; https://content-us.phenompeople.com/api/content-delivery/caasContentV1

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0622 — Oshkosh Corporation

**Disposition:** Provider discovery and scope candidate · **Work order:** W06

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://careers.oshkoshcorp.com/us/en

**Cycle source/result ATS:** https://careers.oshkoshcorp.com/us/en — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found on careers page or obvious same-site job links; the careers page is reachable but may use another ATS or require JavaScript, so inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Official page has Phenom evidence. Verify full relevant listing and preserve category/region/subsidiary intent; reuse phenom.py only after canonical tenant/filter completeness is proved.

**Candidate code:** `src/job_search_helper/phenom.py`, `src/job_search_helper/company_sources.py`

**Existing test candidates:** `tests/test_phenom.py`, `tests/test_phenom_reconciliation.py`

**Fresh public check:** 2026-11-17T15:39:27.828397+00:00; HTTP 200; final URL https://careers.oshkoshcorp.com/us/en; error none; evidence key `COMP-0621`.

**Extracted provider-link leads (unverified scope):** https://cdn.phenompeople.com/CareerConnectResources ; https://content-us.phenompeople.com ; https://content-us.phenompeople.com/api/content-delivery/caasContentV1

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0623 — Booz Allen Hamilton

**Disposition:** Native integration candidate · **Work order:** W06

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://careers.boozallen.com

**Cycle source/result ATS:** https://careers.boozallen.com — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page redirects to another host without a supported board URL; verify and record its destination.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Current official page links employer Workday tenant. Add exact source repair using linked board, not login/highlighted search links; verify current response and all-page/detail completeness.

**Candidate code:** `src/job_search_helper/workday.py`, `src/job_search_helper/company_sources.py`

**Existing test candidates:** `tests/test_workday.py`, `tests/test_workday_leidos.py`, `tests/test_workday_leidos_reconcile.py`, `tests/test_workday_reconcile.py`

**Fresh public check:** 2026-11-17T15:39:28.258975+00:00; HTTP 200; final URL https://www.boozallen.com/careers.html; error none; evidence key `COMP-0623`.

**Extracted provider-link leads (unverified scope):** https://bah.wd1.myworkdayjobs.com/BAH_Jobs

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0624 — Accenture Federal Services

**Disposition:** Employer scope needs proof · **Work order:** Scope investigations

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://www.accenture.com/us-en/careers

**Cycle source/result ATS:** https://www.accenture.com/us-en/careers — `Official careers`

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found within the bounded careers-page discovery limit; the careers page is reachable but inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 1 job descriptions; 14 job URLs await retry. Inventory completeness unknown; no closure inference. Stopped this detail pass after 5 consecutive failures; unresolved URLs and saved descriptions retained.

**Next action:** Official route leads to a broader parent board. Establish exact subsidiary/legal-entity attribution and complete filtered membership; do not relabel parent jobs under this company.

**Candidate code:** `src/job_search_helper/company_sources.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:28.757294+00:00; HTTP 200; final URL https://www.accenture.com/us-en/careers; error none; evidence key `COMP-0624`.

**Extracted provider-link leads (unverified scope):** https://accenture.wd103.myworkdayjobs.com/AccentureCareers/userHome

**Checkpoint context:** 14 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0625 — Deloitte

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://www2.deloitte.com/us/en/careers.html

**Cycle source/result ATS:** https://www2.deloitte.com/us/en/careers.html — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page redirects to another host without a supported board URL; verify and record its destination.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:29.366502+00:00; HTTP 200; final URL https://www.deloitte.com/us/en/careers/careers.html; error none; evidence key `COMP-0625`.

**Extracted provider-link leads (unverified scope):** https://www.deloitte.com/us/en/alliances/workday.html?icid=top_workday

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0626 — LMI

**Disposition:** Network/source investigation · **Work order:** Access investigations

**Initial group:** B3 Network/service failure

**Configured source:** `Official careers` — https://careers.lmi.org

**Cycle source/result ATS:** https://careers.lmi.org — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page network/timeout failure; board discovery did not complete.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Browser fallback needs retry (Error).

**Next action:** Recheck canonical official URL, TLS/DNS/HTTP status and bounded timeout behavior; confirm native provider after recovery. Do not disable certificate verification or infer an empty board.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0627 — Battelle

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B2 Other access/HTTP response investigation

**Configured source:** `Official careers` — https://www.battelle.org/careers/

**Cycle source/result ATS:** https://www.battelle.org/careers/ — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page HTTP 403: access denied or human verification; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 403).

**Next action:** Confirm current public official source and classify actual response (challenge, rate limit, changed route or other error). Respect denial; preserve partial data. A new wrapper is not yet justified.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0628 — Jacobs

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B2 Other access/HTTP response investigation

**Configured source:** `Official careers` — https://careers.jacobs.com

**Cycle source/result ATS:** https://careers.jacobs.com — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page HTTP 202: access denied or human verification; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (Error).

**Next action:** Confirm current public official source and classify actual response (challenge, rate limit, changed route or other error). Respect denial; preserve partial data. A new wrapper is not yet justified.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0629 — AECOM

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://aecom.com/careers/

**Cycle source/result ATS:** https://aecom.com/careers/ — `Official careers`

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found within the bounded careers-page discovery limit; the careers page is reachable but inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 1 job descriptions; 5 job URLs await retry. Inventory completeness unknown; no closure inference. Stopped this detail pass after 5 consecutive failures; unresolved URLs and saved descriptions retained.

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:29.568784+00:00; HTTP 200; final URL https://aecom.com/careers/; error none; evidence key `COMP-0629`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 5 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0630 — Fluor

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://www.fluor.com/careers

**Cycle source/result ATS:** https://www.fluor.com/careers — `Official careers`

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found within the bounded careers-page discovery limit; the careers page is reachable but inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 3 job descriptions; 1 job URLs await retry. Inventory completeness unknown; no closure inference.

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:29.855167+00:00; HTTP 200; final URL https://www.fluor.com/careers; error none; evidence key `COMP-0630`.

**Provider text/asset leads only:** eightfold. These may be false positives; not a verified board.

**Checkpoint context:** 1 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0631 — BELL

**Disposition:** Existing provider investigation · **Work order:** W08

**Initial group:** A3 Provider parser/pagination/validation

**Configured source:** `Taleo` — https://www.bellflight.com/careers

**Cycle source/result ATS:** https://textron.taleo.net/careersection/bell/jobsearch.ftl — `Taleo`

**Exact recorded reason:** Direct fetch returned partial: Discovered Taleo board https://textron.taleo.net/careersection/bell/jobsearch.ftl from https://www.bellflight.com/company/careers. One or more malformed/incomplete postings were skipped. Taleo returned 41 unique postings out of reported total 105.. Browser fallback returned partial: Browser fallback saved 1 job descriptions; 7 job URLs await retry. Inventory completeness unknown; no closure inference. Stopped this detail pass after 5 consecutive failures; unresolved URLs and saved descriptions retained.

**Next action:** Reproduce the precise direct-fetch failure below, inspect listing/detail schema and completeness contract; keep unresolved records partial.

**Candidate code:** `src/job_search_helper/ats.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 7 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0632 — AAR Corp.

**Disposition:** Employer scope needs proof · **Work order:** Scope investigations

**Initial group:** C1 Employer scope or multiple boards

**Configured source:** `Official careers` — https://www.aarcorp.com/careers/

**Cycle source/result ATS:** https://www.aarcorp.com/careers/ — ``

**Exact recorded reason:** Direct fetch returned partial: Multiple ATS boards linked by careers page; select the company's board explicitly.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 8 job URLs await retry. Inventory completeness unknown; no closure inference. Stopped this detail pass after 5 consecutive failures; unresolved URLs and saved descriptions retained.

**Next action:** Prove attributable employer/legal-entity/brand and complete board set before implementing or widening a parent/shared source. Verify each regional board and deduplicate stable IDs.

**Candidate code:** `src/job_search_helper/company_sources.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:29.931128+00:00; HTTP 200; final URL https://www.aarcorp.com/en/careers; error none; evidence key `COMP-0632`.

**Extracted provider-link leads (unverified scope):** https://aarcorp.taleo.net/careersection/2/jobsearch.ftl?lang=en ; https://aarcorp.taleo.net/careersection/xcelle/jobsearch.ftl?lang=en ; https://www.aarcorp.com/globalassets/6.-careers/taleo/eeo-notice-5.2025.pdf

**Checkpoint context:** 8 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0633 — Airbus U.S. Space & Defense

**Disposition:** Employer scope needs proof · **Work order:** Scope investigations

**Initial group:** C1 Employer scope or multiple boards

**Configured source:** `Official careers` — https://www.airbus.com/en/careers

**Cycle source/result ATS:** https://www.airbus.com/en/careers — ``

**Exact recorded reason:** Direct fetch returned partial: Multiple ATS boards linked by careers page; select the company's board explicitly.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 8 job URLs await retry. Inventory completeness unknown; no closure inference. Stopped this detail pass after 5 consecutive failures; unresolved URLs and saved descriptions retained.

**Next action:** Official route leads to a broader parent board. Establish exact subsidiary/legal-entity attribution and complete filtered membership; do not relabel parent jobs under this company.

**Candidate code:** `src/job_search_helper/company_sources.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:30.349886+00:00; HTTP 200; final URL https://www.airbus.com/en/careers; error none; evidence key `COMP-0633`.

**Extracted provider-link leads (unverified scope):** https://ag.wd3.myworkdayjobs.com/Airbus ; https://ag.wd3.myworkdayjobs.com/en-US/Airbus ; https://ag.wd3.myworkdayjobs.com/en-US/Airbus/job/Bangalore-Area/In-Service-Airworthiness-Engineering_JR10446954?workerSubType=f5811cef9cb501a69768a71d470a6d15&locationCountry=c4f78be1a8f14da0ab49ce1162348a5e ; https://ag.wd3.myworkdayjobs.com/en-US/Airbus/job/Bangalore-Area/Training-Product-Support-Engineer_JR10446378?workerSubType=f5811cef9cb501a69768a71d470a6d15&locationCountry=c4f78be1a8f14da0ab49ce1162348a5e ; https://ag.wd3.myworkdayjobs.com/en-US/Airbus/job/Bangkok-Area/Finance-Analyst_JR10447258?workerSubType=f5811cef9cb501a69768a71d470a6d15&locationCountry=873d0f604e3b458c990cb4d83a5c0f14 ; https://ag.wd3.myworkdayjobs.com/en-US/Airbus/job/Bristol-Area/Safety---Reliability-Engineer_JR10451843?workerSubType=f5811cef9cb501a69768a71d470a6d15&locationCountry=29247e57dbaf46fb855b224e03170bc7

**Checkpoint context:** 8 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0634 — Embraer

**Disposition:** Existing provider investigation · **Work order:** W08

**Initial group:** A3 Provider parser/pagination/validation

**Configured source:** `Breezy HR` — https://www.embraer.com/careers/

**Cycle source/result ATS:** https://embraer.breezy.hr/ — `Breezy HR`

**Exact recorded reason:** Breezy HR: retrieved 51 full postings and rechecked the public inventory. 3 postings failed validation: 8e79ba4b1faa: Breezy visible detail identity or description missing.; a4f881e9a075: Breezy visible detail identity or description missing.; fb98e09081a0: Breezy visible detail identity or description missing..

**Next action:** Reproduce the precise direct-fetch failure below, inspect listing/detail schema and completeness contract; keep unresolved records partial.

**Candidate code:** `src/job_search_helper/ats.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0635 — Gulfstream Aerospace

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B2 Other access/HTTP response investigation

**Configured source:** `Official careers` — https://www.gulfstream.com/careers/

**Cycle source/result ATS:** https://www.gulfstream.com/careers/ — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page HTTP 403: access denied or human verification; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 403).

**Next action:** Confirm current public official source and classify actual response (challenge, rate limit, changed route or other error). Respect denial; preserve partial data. A new wrapper is not yet justified.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0636 — Spirit AeroSystems

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://www.spiritaero.com/careers/

**Cycle source/result ATS:** https://www.spiritaero.com/careers/ — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page redirects to another host without a supported board URL; verify and record its destination.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 403).

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:30.869026+00:00; HTTP 200; final URL https://careers.spiritaero.com/; error none; evidence key `COMP-0636`.

**Extracted provider-link leads (unverified scope):** https://careers-spiritaero.icims.com/ ; https://www.icims.com/legal/privacy-notice-website ; https://www.icims.com/legal/privacy-notice-website/ ; https://{{client.display.name}}.jibeapply.com/

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0637 — Triumph Group

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B2 Other access/HTTP response investigation

**Configured source:** `Official careers` — https://www.triumphgroup.com/careers/

**Cycle source/result ATS:** https://www.triumphgroup.com/careers/ — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page HTTP 403: access denied or human verification; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 403).

**Next action:** Confirm current public official source and classify actual response (challenge, rate limit, changed route or other error). Respect denial; preserve partial data. A new wrapper is not yet justified.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0638 — Garrett Motion

**Disposition:** Strong provider-routing candidate · **Work order:** W06

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://www.garrettmotion.com/careers/

**Cycle source/result ATS:** https://www.garrettmotion.com/careers/ — `Official careers`

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found within the bounded careers-page discovery limit; the careers page is reachable but inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 2 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference.

**Next action:** Official Garrett page links Oracle ehth.fa.em2.oraclecloud.com site CX_2001; current is_oracle_host returns false. Add narrowly validated em-region host support across resolver/transport and verify scoped native inventory.

**Candidate code:** `src/job_search_helper/oracle.py`, `src/job_search_helper/ats.py`, `src/job_search_helper/company_sources.py`

**Existing test candidates:** `tests/test_oracle.py`

**Fresh public check:** 2026-11-17T15:39:31.200814+00:00; HTTP 200; final URL https://www.garrettmotion.com/careers/; error none; evidence key `COMP-0638`.

**Extracted provider-link leads (unverified scope):** https://ehth.fa.em2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_2001 ; https://ehth.fa.em2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_2001/jobs?keyword=Electrical+Engineering&mode=location ; https://ehth.fa.em2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_2001/jobs?keyword=Information+Technology&mode=location ; https://ehth.fa.em2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_2001/jobs?keyword=Procurement&mode=location ; https://ehth.fa.em2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_2001/jobs?keyword=Sales&mode=location ; https://ehth.fa.em2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_2001/jobs?mode=location

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0639 — Sierra Nevada Company Mission Solutions

**Disposition:** Network/source investigation · **Work order:** Access investigations

**Initial group:** B3 Network/service failure

**Configured source:** `Official careers` — https://careers.sncorp.com

**Cycle source/result ATS:** https://careers.sncorp.com — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page network/timeout failure; board discovery did not complete.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Browser fallback needs retry (TimeoutError).

**Next action:** Recheck canonical official URL, TLS/DNS/HTTP status and bounded timeout behavior; confirm native provider after recovery. Do not disable certificate verification or infer an empty board.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0640 — Merrick & Company

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://www.merrick.com/careers/

**Cycle source/result ATS:** https://www.merrick.com/careers/ — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page redirects to another host without a supported board URL; verify and record its destination.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 403).

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:31.274392+00:00; HTTP 200; final URL https://careers.merrick.com/careers-home/jobs; error none; evidence key `COMP-0640`.

**Extracted provider-link leads (unverified scope):** https://www.icims.com/legal/privacy-notice-website ; https://www.icims.com/legal/privacy-notice-website/ ; https://{{client.display.name}}.jibeapply.com/

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0642 — RAND Corporation

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B2 Other access/HTTP response investigation

**Configured source:** `Official careers` — https://www.rand.org/jobs.html

**Cycle source/result ATS:** https://www.rand.org/jobs.html — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page HTTP 403: access denied or human verification; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 403).

**Next action:** Confirm current public official source and classify actual response (challenge, rate limit, changed route or other error). Respect denial; preserve partial data. A new wrapper is not yet justified.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0643 — Johns Hopkins Applied Physics Laboratory

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://www.jhuapl.edu/careers/

**Cycle source/result ATS:** https://www.jhuapl.edu/careers/ — `Official careers`

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found within the bounded careers-page discovery limit; the careers page is reachable but inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 1 job descriptions; 7 job URLs await retry. Inventory completeness unknown; no closure inference. Stopped this detail pass after 5 consecutive failures; unresolved URLs and saved descriptions retained.

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:32.451566+00:00; HTTP 200; final URL https://www.jhuapl.edu/careers; error none; evidence key `COMP-0643`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 7 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0644 — Sandia National Laboratories

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://www.sandia.gov/careers/

**Cycle source/result ATS:** https://www.sandia.gov/careers/ — `Official careers`

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found within the bounded careers-page discovery limit; the careers page is reachable but inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 16 job descriptions; 63 job URLs await retry. Inventory completeness unknown; no closure inference. Browser time limit reached (300 seconds); saved progress retained.

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:32.906961+00:00; HTTP 200; final URL https://www.sandia.gov/careers/; error none; evidence key `COMP-0644`.

**Extracted provider-link leads (unverified scope):** https://sandia.avature.net/talentcommunity

**Checkpoint context:** 63 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0645 — Los Alamos National Laboratory

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://www.lanl.gov/careers/

**Cycle source/result ATS:** https://www.lanl.gov/careers/ — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found within the bounded careers-page discovery limit; the careers page is reachable but inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 7 job URLs await retry. Inventory completeness unknown; no closure inference. Stopped this detail pass after 5 consecutive failures; unresolved URLs and saved descriptions retained.

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:33.024320+00:00; HTTP 200; final URL https://www.lanl.gov/careers; error none; evidence key `COMP-0645`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 7 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0646 — Pacific Northwest National Laboratory

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://www.pnnl.gov/careers

**Cycle source/result ATS:** https://www.pnnl.gov/careers — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page redirects to another host without a supported board URL; verify and record its destination.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 403).

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:33.249007+00:00; HTTP 200; final URL https://careers.pnnl.gov/; error none; evidence key `COMP-0646`.

**Extracted provider-link leads (unverified scope):** https://careers-pnnl.icims.com/connect ; https://www.icims.com/legal/privacy-notice-website ; https://www.icims.com/legal/privacy-notice-website/ ; https://{{client.display.name}}.jibeapply.com/

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0647 — Idaho National Laboratory

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B2 Other access/HTTP response investigation

**Configured source:** `Official careers` — https://inl.gov/careers/

**Cycle source/result ATS:** https://inl.gov/careers/ — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page HTTP 403: access denied or human verification; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 403).

**Next action:** Confirm current public official source and classify actual response (challenge, rate limit, changed route or other error). Respect denial; preserve partial data. A new wrapper is not yet justified.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0648 — Argonne National Laboratory

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B2 Other access/HTTP response investigation

**Configured source:** `Official careers` — https://www.anl.gov/careers

**Cycle source/result ATS:** https://www.anl.gov/careers — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page HTTP 403: access denied or human verification; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 403).

**Next action:** Confirm current public official source and classify actual response (challenge, rate limit, changed route or other error). Respect denial; preserve partial data. A new wrapper is not yet justified.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0649 — MDA Space

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://mda.space/careers/

**Cycle source/result ATS:** https://mda.space/careers/ — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found on careers page or obvious same-site job links; the careers page is reachable but may use another ATS or require JavaScript, so inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:33.514658+00:00; HTTP 200; final URL https://mda.space/careers/; error none; evidence key `COMP-0649`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0650 — Intelsat

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://www.intelsat.com/careers/

**Cycle source/result ATS:** https://www.intelsat.com/careers/ — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page redirects to another host without a supported board URL; verify and record its destination.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 404).

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:34.018794+00:00; HTTP 404; final URL https://www.ses.com/intelsat/careers/; error none; evidence key `COMP-0650`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0651 — Eutelsat OneWeb

**Disposition:** Source/redirect investigation · **Work order:** W05 / source repair

**Initial group:** C3 Stale URL/redirect/request repair

**Configured source:** `Official careers` — https://www.eutelsat.com/en/careers.html

**Cycle source/result ATS:** https://www.eutelsat.com/en/careers.html — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page HTTP 404; board discovery did not complete.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 403).

**Next action:** Follow the exact current official link/redirect with bounded trusted destinations; validate replacement board and scope. A 404 is not closure. Test dispatch/source aliases and every page/detail.

**Candidate code:** `src/job_search_helper/company_sources.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:34.253077+00:00; HTTP 404; final URL https://www.eutelsat.com/en/careers.html; error none; evidence key `COMP-0651`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0654 — Relativity Space

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://www.relativityspace.com/careers

**Cycle source/result ATS:** https://www.relativityspace.com/careers — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found on careers page or obvious same-site job links; the careers page is reachable but may use another ATS or require JavaScript, so inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 393 job URLs await retry. Inventory completeness unknown; no closure inference. Stopped this detail pass after 5 consecutive failures; unresolved URLs and saved descriptions retained.

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:34.510582+00:00; HTTP 200; final URL https://www.relativityspace.com/careers; error none; evidence key `COMP-0654`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 393 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0655 — SpaceX

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://www.spacex.com/careers/

**Cycle source/result ATS:** https://www.spacex.com/careers/ — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found on careers page or obvious same-site job links; the careers page is reachable but may use another ATS or require JavaScript, so inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:34.731843+00:00; HTTP 200; final URL https://www.spacex.com/careers/; error none; evidence key `COMP-0655`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0656 — Astroscale U.S.

**Disposition:** Regional/multiple-board scope needs proof · **Work order:** Scope investigations

**Initial group:** C1 Employer scope or multiple boards

**Configured source:** `BambooHR` — https://astroscale.com/careers/

**Cycle source/result ATS:** https://astroscale.com/careers/ — `BambooHR`

**Exact recorded reason:** BambooHR: retrieved 7 full postings and rechecked the public inventory. Discovered tenant https://astroscale.bamboohr.com from the configured employer careers page. Employer page links a subset or stale postings on the BambooHR board; only its listed open jobs were retrieved, and company inventory completeness is unverified.

**Next action:** Recorded source exposes subset or stale employer links. Map official regional boards, prove intended employer/country set, fetch every board and deduplicate stable IDs.

**Candidate code:** `src/job_search_helper/bamboohr.py`, `src/job_search_helper/company_sources.py`

**Existing test candidates:** `tests/test_bamboohr.py`

**Fresh public check:** 2026-11-17T15:39:34.901867+00:00; HTTP 200; final URL https://www.astroscale.com/en/careers; error none; evidence key `COMP-0656`.

**Extracted provider-link leads (unverified scope):** https://astroscale.bamboohr.com/careers/33 ; https://astroscale.bamboohr.com/careers/342 ; https://astroscale.bamboohr.com/careers/356 ; https://astroscale.bamboohr.com/careers/468 ; https://astroscale.bamboohr.com/careers/503 ; https://astroscale.bamboohr.com/careers/546

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0657 — Ciena

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B2 Other access/HTTP response investigation

**Configured source:** `Official careers` — https://www.ciena.com/about/careers

**Cycle source/result ATS:** https://www.ciena.com/about/careers — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page HTTP 403: access denied or human verification; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 403).

**Next action:** Confirm current public official source and classify actual response (challenge, rate limit, changed route or other error). Respect denial; preserve partial data. A new wrapper is not yet justified.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0658 — CommScope

**Disposition:** Provider discovery candidate · **Work order:** W06

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://jobs.commscope.com/

**Cycle source/result ATS:** https://jobs.commscope.com/ — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found within the bounded careers-page discovery limit; the careers page is reachable but inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Current official source contains SuccessFactors markers/links. Verify exact public listing/tenant, geographic and subsidiary scope, then reuse Jobs2Web or supported SuccessFactors route; asset markers alone are not board evidence.

**Candidate code:** `src/job_search_helper/successfactors.py`, `src/job_search_helper/company_sources.py`

**Existing test candidates:** `tests/test_successfactors.py`, `tests/test_successfactors_browser_fallback.py`, `tests/test_successfactors_retry.py`

**Fresh public check:** 2026-11-17T15:39:35.227680+00:00; HTTP 200; final URL https://jobs.commscope.com/; error none; evidence key `COMP-0658`.

**Extracted provider-link leads (unverified scope):** https://career4.successfactors.com ; https://career4.successfactors.com/career?company=CommScope&site=&lang=en_US&requestParams=&login_ns=register&navBarLevel=MY_PROFILE ; https://career4.successfactors.com/career?company=CommScope&site=&lang=en_US&requestParams=&navBarLevel=MY_PROFILE ; https://career4.successfactors.com/career?site=&company=CommScope&lang=en_US&login_ns=register&career_ns=home&navBarLevel=MY_PROFILE

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0659 — NETSCOUT

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Workday` — https://www.netscout.com/careers

**Cycle source/result ATS:** https://www.netscout.com/careers — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page exceeds the discovery size limit; provide its ATS board URL.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:35.383167+00:00; HTTP 200; final URL https://www.netscout.com/company/be-a-guardian; error none; evidence key `COMP-0659`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `blocked`. Neither pending count nor this flag alone proves coverage.

### COMP-0660 — Fortinet

**Disposition:** Native integration candidate · **Work order:** W06

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://www.fortinet.com/corporate/careers

**Cycle source/result ATS:** https://www.fortinet.com/corporate/careers — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found on careers page or obvious same-site job links; the careers page is reachable but may use another ATS or require JavaScript, so inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 1 job URLs await retry. Inventory completeness unknown; no closure inference.

**Next action:** Official careers page links Oracle candidate site. Resolve exact tenant/site and reuse Oracle enumeration/details/reconciliation with intended company scope.

**Candidate code:** `src/job_search_helper/oracle.py`, `src/job_search_helper/company_sources.py`

**Existing test candidates:** `tests/test_oracle.py`

**Fresh public check:** 2026-11-17T15:39:35.433155+00:00; HTTP 200; final URL https://www.fortinet.com/corporate/careers; error none; evidence key `COMP-0660`.

**Extracted provider-link leads (unverified scope):** https://edel.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_2001

**Checkpoint context:** 1 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0662 — Zscaler

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://www.zscaler.com/careers

**Cycle source/result ATS:** https://www.zscaler.com/careers — `Official careers`

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found within the bounded careers-page discovery limit; the careers page is reachable but inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 1 job descriptions; 5 job URLs await retry. Inventory completeness unknown; no closure inference. Stopped this detail pass after 5 consecutive failures; unresolved URLs and saved descriptions retained.

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:35.653731+00:00; HTTP 200; final URL https://www.zscaler.com/careers; error none; evidence key `COMP-0662`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 5 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0663 — CrowdStrike

**Disposition:** Native integration candidate · **Work order:** W06

**Initial group:** C1 Employer scope or multiple boards

**Configured source:** `Official careers` — https://www.crowdstrike.com/careers/

**Cycle source/result ATS:** https://www.crowdstrike.com/careers/ — `Official careers`

**Exact recorded reason:** Direct fetch returned unsupported: Multiple ATS boards linked by careers page; select the company's board explicitly.. Browser fallback returned partial: Browser fallback saved 1 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference.

**Next action:** Current official page links employer Workday tenant. Add exact source repair using linked board, not login/highlighted search links; verify current response and all-page/detail completeness.

**Candidate code:** `src/job_search_helper/workday.py`, `src/job_search_helper/company_sources.py`

**Existing test candidates:** `tests/test_workday.py`, `tests/test_workday_leidos.py`, `tests/test_workday_leidos_reconcile.py`, `tests/test_workday_reconcile.py`

**Fresh public check:** 2026-11-17T15:39:36.370576+00:00; HTTP 200; final URL https://www.crowdstrike.com/en-us/careers/; error none; evidence key `COMP-0663`.

**Extracted provider-link leads (unverified scope):** https://crowdstrike.wd5.myworkdayjobs.com/crowdstrikecareers ; https://crowdstrike.wd5.myworkdayjobs.com/crowdstrikecareers/page/56040874354a1000d20c322b45450000 ; https://crowdstrike.wd5.myworkdayjobs.com/crowdstrikecareers?Job_Family=1408861ee6e2017e954d08f7b000f40b&Job_Family=1408861ee6e20177a63efbf6b000ec0b ; https://crowdstrike.wd5.myworkdayjobs.com/crowdstrikecareers?Job_Family=1408861ee6e201d67af3e0f6b000d60b ; https://crowdstrike.wd5.myworkdayjobs.com/crowdstrikecareers?Job_Family=1408861ee6e201d8b5decef6b000ca0b&Job_Family=1408861ee6e20164b2b5d4f6b000ce0b&Job_Family=1408861ee6e201ed65abf4f6b000e60b&Job_Family=1408861ee6e201e6d8ddc8f6b000c60b&Job_Family=1408861ee6e201d4db6ea7f6b000ae0b ; https://crowdstrike.wd5.myworkdayjobs.com/crowdstrikecareers?Job_Family=1408861ee6e201dd8f7601f7b000f00b&Job_Family=1408861ee6e201739a99bbf6b000bc0b&Job_Family=1408861ee6e201df327f0ff7b000fa0b

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0664 — Cloudflare

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://www.cloudflare.com/careers/

**Cycle source/result ATS:** https://www.cloudflare.com/careers/ — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found within the bounded careers-page discovery limit; the careers page is reachable but inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`, `src/job_search_helper/saic.py`, `src/job_search_helper/gd_land_systems.py`

**Existing test candidates:** `tests/test_gd_land_systems.py`, `tests/test_saic.py`

**Fresh public check:** 2026-11-17T15:39:36.370690+00:00; HTTP 200; final URL https://www.cloudflare.com/careers/; error none; evidence key `COMP-0664`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0666 — Autodesk

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B2 Other access/HTTP response investigation

**Configured source:** `Official careers` — https://www.autodesk.com/careers

**Cycle source/result ATS:** https://www.autodesk.com/careers — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page HTTP 403: access denied or human verification; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 403).

**Next action:** Confirm current public official source and classify actual response (challenge, rate limit, changed route or other error). Respect denial; preserve partial data. A new wrapper is not yet justified.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0667 — Bentley Systems

**Disposition:** Native integration candidate · **Work order:** W06

**Initial group:** C1 Employer scope or multiple boards

**Configured source:** `Official careers` — https://www.bentley.com/careers/

**Cycle source/result ATS:** https://www.bentley.com/careers/ — ``

**Exact recorded reason:** Direct fetch returned partial: Multiple ATS boards linked by careers page; select the company's board explicitly.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Current official page links employer Workday tenant. Add exact source repair using linked board, not login/highlighted search links; verify current response and all-page/detail completeness.

**Candidate code:** `src/job_search_helper/workday.py`, `src/job_search_helper/company_sources.py`

**Existing test candidates:** `tests/test_workday.py`, `tests/test_workday_leidos.py`, `tests/test_workday_leidos_reconcile.py`, `tests/test_workday_reconcile.py`

**Fresh public check:** 2026-11-17T15:39:36.586179+00:00; HTTP 200; final URL https://www.bentley.com/en/company/careers/; error none; evidence key `COMP-0667`.

**Extracted provider-link leads (unverified scope):** https://bentleysystems.wd5.myworkdayjobs.com/bentley ; https://bentleysystems.wd5.myworkdayjobs.com/bentley?q=AI ; https://bentleysystems.wd5.myworkdayjobs.com/bentley?q=ProjectWise ; https://bentleysystems.wd5.myworkdayjobs.com/bentley?q=Software+developer

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0668 — AVEVA

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B1 Workday access/response investigation

**Configured source:** `Workday` — https://www.aveva.com/en/about/careers/

**Cycle source/result ATS:** https://www.aveva.com/en/about/careers/ — `Workday`

**Exact recorded reason:** Direct fetch returned blocked: Discovered Workday board https://aveva.wd3.myworkdayjobs.com/wday/cxs/aveva/AVEVA_careers from https://www.aveva.com/en/about/careers/. Workday listing page 1: Human verification detected; manual review required.. Browser fallback returned partial: Browser fallback saved 1 job descriptions; 3 job URLs await retry. Inventory completeness unknown; no closure inference.

**Next action:** Capture the failed Workday request page/posting and response classification; inspect host pacing and source filters. Validate all pages/details after recovery. Do not assume a new wrapper fixes genuine access denial.

**Candidate code:** `src/job_search_helper/workday.py`

**Existing test candidates:** `tests/test_workday.py`, `tests/test_workday_leidos.py`, `tests/test_workday_leidos_reconcile.py`, `tests/test_workday_reconcile.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 3 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0670 — Dassault Systèmes

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://www.3ds.com/careers

**Cycle source/result ATS:** https://www.3ds.com/careers — `Official careers`

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found within the bounded careers-page discovery limit; the careers page is reachable but inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 4 job descriptions; 6 job URLs await retry. Inventory completeness unknown; no closure inference. Stopped this detail pass after 5 consecutive failures; unresolved URLs and saved descriptions retained.

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:36.728704+00:00; HTTP 200; final URL https://www.3ds.com/careers; error none; evidence key `COMP-0670`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 6 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0671 — Ansys

**Disposition:** Network/TLS investigation · **Work order:** Access investigations

**Initial group:** A3 Provider parser/pagination/validation

**Configured source:** `Official careers` — https://careers.ansys.com/

**Cycle source/result ATS:** https://careers.ansys.com/ — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page TLS verification or connection failed.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Recorded TLS/connection failure; test canonical current source and certificate/redirect chain. No confirmed parser defect; keep TLS verification enabled.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0672 — MathWorks

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B2 Other access/HTTP response investigation

**Configured source:** `Official careers` — https://www.mathworks.com/company/jobs.html

**Cycle source/result ATS:** https://www.mathworks.com/company/jobs.html — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page HTTP 403: access denied or human verification; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 403).

**Next action:** Confirm current public official source and classify actual response (challenge, rate limit, changed route or other error). Respect denial; preserve partial data. A new wrapper is not yet justified.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0673 — Qualcomm

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://www.qualcomm.com/company/careers

**Cycle source/result ATS:** https://www.qualcomm.com/company/careers — `Official careers`

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found on careers page or obvious same-site job links; the careers page is reachable but may use another ATS or require JavaScript, so inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 1 job descriptions; 4 job URLs await retry. Inventory completeness unknown; no closure inference.

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:36.957939+00:00; HTTP 200; final URL https://www.qualcomm.com/company/careers; error none; evidence key `COMP-0673`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 4 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0674 — Tektronix

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B2 Other access/HTTP response investigation

**Configured source:** `Official careers` — https://www.tek.com/en/careers

**Cycle source/result ATS:** https://www.tek.com/en/careers — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page HTTP 403: access denied or human verification; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 403).

**Next action:** Confirm current public official source and classify actual response (challenge, rate limit, changed route or other error). Respect denial; preserve partial data. A new wrapper is not yet justified.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0675 — Fluke Corporation

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://www.fluke.com/en-us/learn/careers

**Cycle source/result ATS:** https://www.fluke.com/en-us/learn/careers — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found on careers page or obvious same-site job links; the careers page is reachable but may use another ATS or require JavaScript, so inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:37.267501+00:00; HTTP 200; final URL https://www.fluke.com/en-us/learn; error none; evidence key `COMP-0675`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0676 — Rittal

**Disposition:** Source/redirect investigation · **Work order:** W05 / source repair

**Initial group:** C3 Stale URL/redirect/request repair

**Configured source:** `Official careers` — https://www.rittal.com/us-en/company/career

**Cycle source/result ATS:** https://www.rittal.com/us-en/company/career — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page HTTP 404; board discovery did not complete.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 404).

**Next action:** Follow the exact current official link/redirect with bounded trusted destinations; validate replacement board and scope. A 404 is not closure. Test dispatch/source aliases and every page/detail.

**Candidate code:** `src/job_search_helper/company_sources.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:37.298289+00:00; HTTP 404; final URL https://www.rittal.com/us-en/company/career; error none; evidence key `COMP-0676`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0677 — Weidmüller USA

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B2 Other access/HTTP response investigation

**Configured source:** `Official careers` — https://www.weidmuller.com/en/company/career/index.jsp

**Cycle source/result ATS:** https://www.weidmuller.com/en/company/career/index.jsp — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page HTTP 403: access denied or human verification; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 404).

**Next action:** Confirm current public official source and classify actual response (challenge, rate limit, changed route or other error). Respect denial; preserve partial data. A new wrapper is not yet justified.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0678 — Turck

**Disposition:** Source/redirect investigation · **Work order:** W05 / source repair

**Initial group:** C3 Stale URL/redirect/request repair

**Configured source:** `Official careers` — https://www.turck.us/en/company-careers-3805.php

**Cycle source/result ATS:** https://www.turck.us/en/company-careers-3805.php — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page HTTP 404; board discovery did not complete.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 404).

**Next action:** Follow the exact current official link/redirect with bounded trusted destinations; validate replacement board and scope. A 404 is not closure. Test dispatch/source aliases and every page/detail.

**Candidate code:** `src/job_search_helper/company_sources.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:37.645841+00:00; HTTP 404; final URL https://www.turck.us/en/company-careers-3805.php; error none; evidence key `COMP-0678`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0680 — ifm efector

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B2 Other access/HTTP response investigation

**Configured source:** `Official careers` — https://www.ifm.com/us/en/us/career

**Cycle source/result ATS:** https://www.ifm.com/us/en/us/career — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page HTTP 403: access denied or human verification; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 404).

**Next action:** Confirm current public official source and classify actual response (challenge, rate limit, changed route or other error). Respect denial; preserve partial data. A new wrapper is not yet justified.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0681 — Balluff

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B2 Other access/HTTP response investigation

**Configured source:** `Official careers` — https://www.balluff.com/en-us/careers

**Cycle source/result ATS:** https://www.balluff.com/en-us/careers — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page HTTP 403: access denied or human verification; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 403).

**Next action:** Confirm current public official source and classify actual response (challenge, rate limit, changed route or other error). Respect denial; preserve partial data. A new wrapper is not yet justified.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0682 — Pepperl+Fuchs

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B2 Other access/HTTP response investigation

**Configured source:** `Official careers` — https://www.pepperl-fuchs.com/global/en/26091.htm

**Cycle source/result ATS:** https://www.pepperl-fuchs.com/global/en/26091.htm — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page HTTP 403: access denied or human verification; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 403).

**Next action:** Confirm current public official source and classify actual response (challenge, rate limit, changed route or other error). Respect denial; preserve partial data. A new wrapper is not yet justified.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0683 — WAGO

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://www.wago.com/us/careers

**Cycle source/result ATS:** https://www.wago.com/us/careers — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found on careers page or obvious same-site job links; the careers page is reachable but may use another ATS or require JavaScript, so inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:37.651778+00:00; HTTP 200; final URL https://www.wago.com/us/careers; error none; evidence key `COMP-0683`.

**Extracted provider-link leads (unverified scope):** https://us232.dayforcehcm.com/CandidatePortal/en-us/wago

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0684 — SEW-EURODRIVE

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B2 Other access/HTTP response investigation

**Configured source:** `Official careers` — https://www.seweurodrive.com/company/careers/careers.html

**Cycle source/result ATS:** https://www.seweurodrive.com/company/careers/careers.html — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page HTTP 403: access denied or human verification; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 403).

**Next action:** Confirm current public official source and classify actual response (challenge, rate limit, changed route or other error). Respect denial; preserve partial data. A new wrapper is not yet justified.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0685 — Regal Rexnord

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B2 Other access/HTTP response investigation

**Configured source:** `Official careers` — https://www.regalrexnord.com/careers

**Cycle source/result ATS:** https://www.regalrexnord.com/careers — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page HTTP 403: access denied or human verification; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 403).

**Next action:** Confirm current public official source and classify actual response (challenge, rate limit, changed route or other error). Respect denial; preserve partial data. A new wrapper is not yet justified.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0686 — Kollmorgen

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B2 Other access/HTTP response investigation

**Configured source:** `Official careers` — https://www.kollmorgen.com/en-us/company/careers/

**Cycle source/result ATS:** https://www.kollmorgen.com/en-us/company/careers/ — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page HTTP 403: access denied or human verification; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 403).

**Next action:** Confirm current public official source and classify actual response (challenge, rate limit, changed route or other error). Respect denial; preserve partial data. A new wrapper is not yet justified.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0687 — Nidec Motion & Drives

**Disposition:** Source/redirect investigation · **Work order:** W05 / source repair

**Initial group:** C3 Stale URL/redirect/request repair

**Configured source:** `Official careers` — https://www.nidec.com/en/careers/

**Cycle source/result ATS:** https://www.nidec.com/en/careers/ — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page HTTP 404; board discovery did not complete.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 404).

**Next action:** Follow the exact current official link/redirect with bounded trusted destinations; validate replacement board and scope. A 404 is not closure. Test dispatch/source aliases and every page/detail.

**Candidate code:** `src/job_search_helper/company_sources.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:38.229324+00:00; HTTP 404; final URL https://www.nidec.com/en/careers/; error none; evidence key `COMP-0687`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0688 — Atlas Copco

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://www.atlascopco.com/en-us/careers

**Cycle source/result ATS:** https://www.atlascopco.com/en-us/careers — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page redirects to another host without a supported board URL; verify and record its destination.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 7 job URLs await retry. Inventory completeness unknown; no closure inference. Stopped this detail pass after 5 consecutive failures; unresolved URLs and saved descriptions retained.

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:38.509028+00:00; HTTP 200; final URL https://www.atlascopco.com/en-us/jobs; error none; evidence key `COMP-0688`.

**Provider text/asset leads only:** greenhouse. These may be false positives; not a verified board.

**Checkpoint context:** 7 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0689 — Ingersoll Rand

**Disposition:** Network/source investigation · **Work order:** Access investigations

**Initial group:** B3 Network/service failure

**Configured source:** `Official careers` — https://careers.ingersollrand.com/

**Cycle source/result ATS:** https://careers.ingersollrand.com/ — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page network/timeout failure; board discovery did not complete.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Browser fallback needs retry (TimeoutError).

**Next action:** Recheck canonical official URL, TLS/DNS/HTTP status and bounded timeout behavior; confirm native provider after recovery. Do not disable certificate verification or infer an empty board.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0690 — Kaeser Compressors

**Disposition:** Source/redirect investigation · **Work order:** W05 / source repair

**Initial group:** C3 Stale URL/redirect/request repair

**Configured source:** `Official careers` — https://us.kaeser.com/company/careers/

**Cycle source/result ATS:** https://us.kaeser.com/company/careers/ — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page HTTP 404; board discovery did not complete.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 404).

**Next action:** Follow the exact current official link/redirect with bounded trusted destinations; validate replacement board and scope. A 404 is not closure. Test dispatch/source aliases and every page/detail.

**Candidate code:** `src/job_search_helper/company_sources.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:38.732590+00:00; HTTP 404; final URL https://us.kaeser.com/company/careers/; error none; evidence key `COMP-0690`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0691 — Sullair

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B2 Other access/HTTP response investigation

**Configured source:** `Official careers` — https://www.sullair.com/en/careers

**Cycle source/result ATS:** https://www.sullair.com/en/careers — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page HTTP 403: access denied or human verification; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 403).

**Next action:** Confirm current public official source and classify actual response (challenge, rate limit, changed route or other error). Respect denial; preserve partial data. A new wrapper is not yet justified.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0692 — Graco

**Disposition:** Source/redirect investigation · **Work order:** W05 / source repair

**Initial group:** C3 Stale URL/redirect/request repair

**Configured source:** `Official careers` — https://www.graco.com/us/en/company/careers.html

**Cycle source/result ATS:** https://www.graco.com/us/en/company/careers.html — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page HTTP 404; board discovery did not complete.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 404).

**Next action:** Follow the exact current official link/redirect with bounded trusted destinations; validate replacement board and scope. A 404 is not closure. Test dispatch/source aliases and every page/detail.

**Candidate code:** `src/job_search_helper/company_sources.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:40.667460+00:00; HTTP 404; final URL https://www.graco.com/us/en/company/careers.html; error none; evidence key `COMP-0692`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0693 — Nordson

**Disposition:** Network/source investigation · **Work order:** Access investigations

**Initial group:** B3 Network/service failure

**Configured source:** `Official careers` — https://careers.nordson.com/

**Cycle source/result ATS:** https://careers.nordson.com/ — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page network/timeout failure; board discovery did not complete.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Browser fallback needs retry (Error).

**Next action:** Recheck canonical official URL, TLS/DNS/HTTP status and bounded timeout behavior; confirm native provider after recovery. Do not disable certificate verification or infer an empty board.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0694 — Donaldson

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://www.donaldson.com/en-us/careers/

**Cycle source/result ATS:** https://www.donaldson.com/en-us/careers/ — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found within the bounded careers-page discovery limit; the careers page is reachable but inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 3 job URLs await retry. Inventory completeness unknown; no closure inference.

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:40.741658+00:00; HTTP 200; final URL https://www.donaldson.com/en/; error none; evidence key `COMP-0694`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 3 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0695 — Applied Industrial Technologies

**Disposition:** Network/source investigation · **Work order:** Access investigations

**Initial group:** B3 Network/service failure

**Configured source:** `Official careers` — https://careers.applied.com/

**Cycle source/result ATS:** https://careers.applied.com/ — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page network/timeout failure; board discovery did not complete.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Browser fallback needs retry (Error).

**Next action:** Recheck canonical official URL, TLS/DNS/HTTP status and bounded timeout behavior; confirm native provider after recovery. Do not disable certificate verification or infer an empty board.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0696 — Motion Industries

**Disposition:** Network/source investigation · **Work order:** Access investigations

**Initial group:** B3 Network/service failure

**Configured source:** `Official careers` — https://careers.motion.com/

**Cycle source/result ATS:** https://careers.motion.com/ — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page network/timeout failure; board discovery did not complete.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Browser fallback needs retry (Error).

**Next action:** Recheck canonical official URL, TLS/DNS/HTTP status and bounded timeout behavior; confirm native provider after recovery. Do not disable certificate verification or infer an empty board.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0697 — Miller Electric Mfg.

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://www.millerwelds.com/about/careers

**Cycle source/result ATS:** https://www.millerwelds.com/about/careers — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found on careers page or obvious same-site job links; the careers page is reachable but may use another ATS or require JavaScript, so inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:40.928392+00:00; HTTP 200; final URL https://www.millerwelds.com/en-us/about/careers; error none; evidence key `COMP-0697`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0698 — ESAB

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B2 Other access/HTTP response investigation

**Configured source:** `Official careers` — https://www.esab.com/careers

**Cycle source/result ATS:** https://www.esab.com/careers — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page HTTP 403: access denied or human verification; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 403).

**Next action:** Confirm current public official source and classify actual response (challenge, rate limit, changed route or other error). Respect denial; preserve partial data. A new wrapper is not yet justified.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0699 — Schaeffler

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B2 Other access/HTTP response investigation

**Configured source:** `Official careers` — https://www.schaeffler.com/en/careers/

**Cycle source/result ATS:** https://www.schaeffler.com/en/careers/ — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page HTTP 403: access denied or human verification; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 403).

**Next action:** Confirm current public official source and classify actual response (challenge, rate limit, changed route or other error). Respect denial; preserve partial data. A new wrapper is not yet justified.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0700 — The Timken Company

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://www.timken.com/careers/

**Cycle source/result ATS:** https://www.timken.com/careers/ — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found within the bounded careers-page discovery limit; the careers page is reachable but inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 7 job URLs await retry. Inventory completeness unknown; no closure inference. Stopped this detail pass after 5 consecutive failures; unresolved URLs and saved descriptions retained.

**Next action:** Automated greenhouse marker is a greenhouse-gas reference, not an ATS. Inspect current Timken jobs surface and complete listing contract.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:41.080429+00:00; HTTP 200; final URL https://www.timken.com/careers/; error none; evidence key `COMP-0700`.

**Extracted provider-link leads (unverified scope):** https://www.epa.gov/energy/greenhouse-gases-equivalencies-calculator-calculations-and-references

**Checkpoint context:** 7 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0701 — Denso Robotics

**Disposition:** Source/redirect investigation · **Work order:** W05 / source repair

**Initial group:** C3 Stale URL/redirect/request repair

**Configured source:** `Official careers` — https://www.densorobotics.com/careers/

**Cycle source/result ATS:** https://www.densorobotics.com/careers/ — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page HTTP 404; board discovery did not complete.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 404).

**Next action:** Follow the exact current official link/redirect with bounded trusted destinations; validate replacement board and scope. A 404 is not closure. Test dispatch/source aliases and every page/detail.

**Candidate code:** `src/job_search_helper/company_sources.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:41.455802+00:00; HTTP 404; final URL https://www.densorobotics.com/careers/; error none; evidence key `COMP-0701`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0702 — Epson Robots

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://epson.com/careers

**Cycle source/result ATS:** https://epson.com/careers — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found within the bounded careers-page discovery limit; the careers page is reachable but inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:41.674212+00:00; HTTP 200; final URL https://epson.com/careers; error none; evidence key `COMP-0702`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0703 — Stäubli Robotics

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B2 Other access/HTTP response investigation

**Configured source:** `Official careers` — https://www.staubli.com/us/en/career.html

**Cycle source/result ATS:** https://www.staubli.com/us/en/career.html — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page HTTP 403: access denied or human verification; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 403).

**Next action:** Confirm current public official source and classify actual response (challenge, rate limit, changed route or other error). Respect denial; preserve partial data. A new wrapper is not yet justified.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0704 — Kawasaki Robotics

**Disposition:** Network/source investigation · **Work order:** Access investigations

**Initial group:** B3 Network/service failure

**Configured source:** `Official careers` — https://robotics.kawasaki.com/en1/careers/

**Cycle source/result ATS:** https://robotics.kawasaki.com/en1/careers/ — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page network/timeout failure; board discovery did not complete.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Browser fallback needs retry (TimeoutError).

**Next action:** Recheck canonical official URL, TLS/DNS/HTTP status and bounded timeout behavior; confirm native provider after recovery. Do not disable certificate verification or infer an empty board.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0705 — Nachi Robotic Systems

**Disposition:** Source/redirect investigation · **Work order:** W05 / source repair

**Initial group:** C3 Stale URL/redirect/request repair

**Configured source:** `Official careers` — https://www.nachirobotics.com/careers/

**Cycle source/result ATS:** https://www.nachirobotics.com/careers/ — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page HTTP 404; board discovery did not complete.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Follow the exact current official link/redirect with bounded trusted destinations; validate replacement board and scope. A 404 is not closure. Test dispatch/source aliases and every page/detail.

**Candidate code:** `src/job_search_helper/company_sources.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:41.841691+00:00; HTTP 200; final URL https://www.nachirobotics.com/contact-us/careers/; error none; evidence key `COMP-0705`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0706 — Doosan Robotics

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://www.doosanrobotics.com/en/careers

**Cycle source/result ATS:** https://www.doosanrobotics.com/en/careers — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found on careers page or obvious same-site job links; the careers page is reachable but may use another ATS or require JavaScript, so inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:41.976999+00:00; HTTP 200; final URL https://www.doosanrobotics.com/en/; error none; evidence key `COMP-0706`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0708 — OTTO Motors

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B1 Workday access/response investigation

**Configured source:** `Workday` — https://ottomotors.com/careers/

**Cycle source/result ATS:** https://rockwellautomation.wd1.myworkdayjobs.com/wday/cxs/rockwellautomation/External_Rockwell_Automation — `Workday`

**Exact recorded reason:** Direct fetch returned partial: Discovered Workday board https://rockwellautomation.wd1.myworkdayjobs.com/wday/cxs/rockwellautomation/External_Rockwell_Automation from https://ottomotors.com/careers/. Workday listing page 9: Human verification detected; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Capture the failed Workday request page/posting and response classification; inspect host pacing and source filters. Validate all pages/details after recovery. Do not assume a new wrapper fixes genuine access denial.

**Candidate code:** `src/job_search_helper/workday.py`

**Existing test candidates:** `tests/test_workday.py`, `tests/test_workday_leidos.py`, `tests/test_workday_leidos_reconcile.py`, `tests/test_workday_reconcile.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0710 — RightHand Robotics

**Disposition:** Native integration candidate · **Work order:** W06

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://www.righthandrobotics.com/careers

**Cycle source/result ATS:** https://www.righthandrobotics.com/careers — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found on careers page or obvious same-site job links; the careers page is reachable but may use another ATS or require JavaScript, so inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Official Breezy tenant embed verified and /json returns 200 list; reuse Breezy with complete details and final membership validation.

**Candidate code:** `src/job_search_helper/shared_boards.py`, `src/job_search_helper/company_sources.py`

**Existing test candidates:** `tests/test_shared_boards.py`

**Fresh public check:** 2026-11-17T15:39:42.323896+00:00; HTTP 200; final URL https://righthandrobotics.com/careers; error none; evidence key `COMP-0710`.

**Extracted provider-link leads (unverified scope):** https://righthand-robotics.breezy.hr/embed/js?inline=true&group_by=loc

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0711 — Mantis Robotics

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://www.mantisrobotics.com/careers

**Cycle source/result ATS:** https://www.mantisrobotics.com/careers — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page redirects to another host without a supported board URL; verify and record its destination.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Browser fallback needs retry (Error).

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:42.876094+00:00; HTTP 403; final URL https://www.hugedomains.com/domain_profile.cfm?d=mantisrobotics.com; error none; evidence key `COMP-0711`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0712 — PickNik Robotics

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://picknik.ai/careers/

**Cycle source/result ATS:** https://picknik.ai/careers/ — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found on careers page or obvious same-site job links; the careers page is reachable but may use another ATS or require JavaScript, so inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:42.995195+00:00; HTTP 200; final URL https://picknik.ai/careers/; error none; evidence key `COMP-0712`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0714 — Aethon

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://www.aethon.com/careers/

**Cycle source/result ATS:** https://www.aethon.com/careers/ — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found on careers page or obvious same-site job links; the careers page is reachable but may use another ATS or require JavaScript, so inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:43.108983+00:00; HTTP 200; final URL https://aethon.com/careers/; error none; evidence key `COMP-0714`.

**Extracted provider-link leads (unverified scope):** https://recruiting.paylocity.com/recruiting/jobs/Details/4230770/ST-ENGINEERING-AETHON-INC/Field-Implementation-Engineer ; https://recruiting.paylocity.com/recruiting/jobs/Details/4275655/ST-ENGINEERING-AETHON-INC/Help-Desk-Technician-Part-Time ; https://recruiting.paylocity.com/recruiting/jobs/Details/4432450/ST-ENGINEERING-AETHON-INC/Part-Time-Buyer

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0715 — Badger Technologies

**Disposition:** Source/redirect investigation · **Work order:** W05 / source repair

**Initial group:** C3 Stale URL/redirect/request repair

**Configured source:** `Official careers` — https://www.badger-technologies.com/careers/

**Cycle source/result ATS:** https://www.badger-technologies.com/careers/ — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page HTTP 404; board discovery did not complete.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 404).

**Next action:** Follow the exact current official link/redirect with bounded trusted destinations; validate replacement board and scope. A 404 is not closure. Test dispatch/source aliases and every page/detail.

**Candidate code:** `src/job_search_helper/company_sources.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:43.245480+00:00; HTTP 404; final URL https://www.badger-technologies.com/careers/; error none; evidence key `COMP-0715`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0716 — Novanta

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B1 Workday access/response investigation

**Configured source:** `Workday` — https://www.novanta.com/careers

**Cycle source/result ATS:** https://novanta.wd5.myworkdayjobs.com/wday/cxs/novanta/Novanta-Careers — `Workday`

**Exact recorded reason:** Direct fetch returned partial: Discovered Workday board https://novanta.wd5.myworkdayjobs.com/wday/cxs/novanta/Novanta-Careers from https://novanta.com/careers-culture/. Workday job detail https://novanta.wd5.myworkdayjobs.com/Novanta-Careers/job/Berlin-Germany/Working-Student-R-D--m-f-d-_R009807-1: Human verification detected; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Capture the failed Workday request page/posting and response classification; inspect host pacing and source filters. Validate all pages/details after recovery. Do not assume a new wrapper fixes genuine access denial.

**Candidate code:** `src/job_search_helper/workday.py`

**Existing test candidates:** `tests/test_workday.py`, `tests/test_workday_leidos.py`, `tests/test_workday_leidos_reconcile.py`, `tests/test_workday_reconcile.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0717 — Tesla

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B2 Other access/HTTP response investigation

**Configured source:** `Official careers` — https://www.tesla.com/careers

**Cycle source/result ATS:** https://www.tesla.com/careers — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page HTTP 403: access denied or human verification; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 403).

**Next action:** Confirm current public official source and classify actual response (challenge, rate limit, changed route or other error). Respect denial; preserve partial data. A new wrapper is not yet justified.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0718 — Rivian

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://rivian.com/careers

**Cycle source/result ATS:** https://rivian.com/careers — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page redirects to another host without a supported board URL; verify and record its destination.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 403).

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:43.261484+00:00; HTTP 200; final URL https://careers.rivian.com/careers-home/; error none; evidence key `COMP-0718`.

**Extracted provider-link leads (unverified scope):** https://www.icims.com/legal/privacy-notice-website ; https://www.icims.com/legal/privacy-notice-website/ ; https://{{client.display.name}}.jibeapply.com/

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0719 — Lucid Motors

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://lucidmotors.com/careers

**Cycle source/result ATS:** https://lucidmotors.com/careers — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found within the bounded careers-page discovery limit; the careers page is reachable but inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 1 job URLs await retry. Inventory completeness unknown; no closure inference.

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:43.497577+00:00; HTTP 200; final URL https://lucidmotors.com/careers; error none; evidence key `COMP-0719`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 1 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0720 — Hyundai Mobis

**Disposition:** Source/redirect investigation · **Work order:** W05 / source repair

**Initial group:** C3 Stale URL/redirect/request repair

**Configured source:** `Official careers` — https://www.mobis.com/en/careers

**Cycle source/result ATS:** https://www.mobis.com/en/careers — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page HTTP 404; board discovery did not complete.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 404).

**Next action:** Follow the exact current official link/redirect with bounded trusted destinations; validate replacement board and scope. A 404 is not closure. Test dispatch/source aliases and every page/detail.

**Candidate code:** `src/job_search_helper/company_sources.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:43.761538+00:00; HTTP 404; final URL https://www.mobis.com/en/careers; error none; evidence key `COMP-0720`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0721 — Magna International

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://www.magna.com/careers

**Cycle source/result ATS:** https://www.magna.com/careers — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page redirects to another host without a supported board URL; verify and record its destination.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 6 job URLs await retry. Inventory completeness unknown; no closure inference. Stopped this detail pass after 5 consecutive failures; unresolved URLs and saved descriptions retained.

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:43.944935+00:00; HTTP 200; final URL https://www.magna.com/careers; error none; evidence key `COMP-0721`.

**Extracted provider-link leads (unverified scope):** https://wd3.myworkdaysite.com/recruiting/magna/Magna ; https://www.magna.com/products/exterior-interior/greenhouse-surrounds

**Checkpoint context:** 6 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0722 — Marvell Technology

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B2 Other access/HTTP response investigation

**Configured source:** `Official careers` — https://www.marvell.com/company/careers.html

**Cycle source/result ATS:** https://www.marvell.com/company/careers.html — `Official careers`

**Exact recorded reason:** Direct fetch returned blocked: Careers page HTTP 403: access denied or human verification; manual review required.. Browser fallback returned partial: Browser fallback saved 1 job descriptions; 9 job URLs await retry. Inventory completeness unknown; no closure inference. Stopped this detail pass after 5 consecutive failures; unresolved URLs and saved descriptions retained.

**Next action:** Confirm current public official source and classify actual response (challenge, rate limit, changed route or other error). Respect denial; preserve partial data. A new wrapper is not yet justified.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 9 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `partial`. Neither pending count nor this flag alone proves coverage.

### COMP-0724 — Arm

**Disposition:** Existing provider pagination candidate · **Work order:** W08

**Initial group:** A3 Provider parser/pagination/validation

**Configured source:** `TalentBrew` — https://careers.arm.com/search-jobs

**Cycle source/result ATS:** https://careers.arm.com/search-jobs — `TalentBrew`

**Exact recorded reason:** TalentBrew job detail; page=1; posting=103414668848; advertised=452; retained=15: TalentBrew listing pagination; page=2; posting=-; advertised=452; retained=0: TalentBrew next page missing or ambiguous.

**Next action:** TalentBrew reports 452 jobs but stops before page two after 15 retained. Capture next-page/current search contract; repair strict pagination and full reread.

**Candidate code:** `src/job_search_helper/shared_extended.py`

**Existing test candidates:** `tests/test_shared_extended.py`

**Fresh public check:** 2026-11-17T15:39:57.698746+00:00; HTTP 200; final URL https://careers.arm.com/search-jobs; error none; evidence key `arm-page`.

**Provider text/asset leads only:** icims, talentbrew. These may be false positives; not a verified board.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0725 — NXP Semiconductors

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B1 Workday access/response investigation

**Configured source:** `Workday` — https://nxp.wd3.myworkdayjobs.com/en-US/careers

**Cycle source/result ATS:** https://nxp.wd3.myworkdayjobs.com/wday/cxs/nxp/careers — `Workday`

**Exact recorded reason:** Direct fetch returned partial: Workday listing page 1: Human verification detected; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 500).

**Next action:** Capture the failed Workday request page/posting and response classification; inspect host pacing and source filters. Validate all pages/details after recovery. Do not assume a new wrapper fixes genuine access denial.

**Candidate code:** `src/job_search_helper/workday.py`

**Existing test candidates:** `tests/test_workday.py`, `tests/test_workday_leidos.py`, `tests/test_workday_leidos_reconcile.py`, `tests/test_workday_reconcile.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0726 — Microchip Technology

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B2 Other access/HTTP response investigation

**Configured source:** `Workday / official careers` — https://www.microchip.com/en-us/about/careers

**Cycle source/result ATS:** https://www.microchip.com/en-us/about/careers — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page HTTP 403: access denied or human verification; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 403).

**Next action:** Confirm current public official source and classify actual response (challenge, rate limit, changed route or other error). Respect denial; preserve partial data. A new wrapper is not yet justified.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0727 — Texas Instruments

**Disposition:** Native route mapping candidate · **Work order:** W06

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Oracle Recruiting` — https://careers.ti.com/en/sites/CX/jobs

**Cycle source/result ATS:** https://careers.ti.com/en/sites/CX/jobs — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found on careers page or obvious same-site job links; the careers page is reachable but may use another ATS or require JavaScript, so inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Custom official careers page references Oracle edbz.fa.us2.oraclecloud.com site CX. Prove canonical same-site mapping; then reuse Oracle and full coverage validation.

**Candidate code:** `src/job_search_helper/oracle.py`, `src/job_search_helper/company_sources.py`

**Existing test candidates:** `tests/test_oracle.py`

**Fresh public check:** 2026-11-17T15:39:44.090565+00:00; HTTP 200; final URL https://careers.ti.com/en/sites/CX/jobs; error none; evidence key `COMP-0727`.

**Extracted provider-link leads (unverified scope):** https://edbz.fa.us2.oraclecloud.com:443

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0728 — Infineon Technologies

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://www.infineon.com/careers/our-locations/americas

**Cycle source/result ATS:** https://www.infineon.com/careers/our-locations/americas — `Official careers`

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found within the bounded careers-page discovery limit; the careers page is reachable but inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 3 job descriptions; 9 job URLs await retry. Inventory completeness unknown; no closure inference. Stopped this detail pass after 5 consecutive failures; unresolved URLs and saved descriptions retained.

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:44.152324+00:00; HTTP 200; final URL https://www.infineon.com/careers/our-locations/americas; error none; evidence key `COMP-0728`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 9 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0729 — STMicroelectronics

**Disposition:** Network/source investigation · **Work order:** Access investigations

**Initial group:** B3 Network/service failure

**Configured source:** `Official careers` — https://www.st.com/content/st_com/en/about/careers.html

**Cycle source/result ATS:** https://www.st.com/content/st_com/en/about/careers.html — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page network/timeout failure; board discovery did not complete.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Browser fallback needs retry (Error).

**Next action:** Recheck canonical official URL, TLS/DNS/HTTP status and bounded timeout behavior; confirm native provider after recovery. Do not disable certificate verification or infer an empty board.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0730 — Renesas Electronics

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://jobs.renesas.com/jobs

**Cycle source/result ATS:** https://jobs.renesas.com/jobs — `Official careers`

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found within the bounded careers-page discovery limit; the careers page is reachable but inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 12 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference.

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:44.384271+00:00; HTTP 200; final URL https://jobs.renesas.com/jobs; error none; evidence key `COMP-0730`.

**Extracted provider-link leads (unverified scope):** https://join.smartrecruiters.com/RenesasElectronics/52cc9dd7-0f97-4350-8ce0-d571757301c5-community-sign-up

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0731 — onsemi

**Disposition:** Native integration candidate · **Work order:** W06

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://www.onsemi.com/careers/professionals/career-opportunities

**Cycle source/result ATS:** https://www.onsemi.com/careers/professionals/career-opportunities — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found within the bounded careers-page discovery limit; the careers page is reachable but inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 18 job URLs await retry. Inventory completeness unknown; no closure inference. Stopped this detail pass after 5 consecutive failures; unresolved URLs and saved descriptions retained.

**Next action:** Official careers page links Oracle candidate site. Resolve exact tenant/site and reuse Oracle enumeration/details/reconciliation with intended company scope.

**Candidate code:** `src/job_search_helper/oracle.py`, `src/job_search_helper/company_sources.py`

**Existing test candidates:** `tests/test_oracle.py`

**Fresh public check:** 2026-11-17T15:39:45.677075+00:00; HTTP 200; final URL https://www.onsemi.com/careers/professionals/career-opportunities; error none; evidence key `COMP-0731`.

**Extracted provider-link leads (unverified scope):** https://hctz.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001 ; https://hctz.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/job/2500775 ; https://hctz.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/job/2501152 ; https://hctz.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/job/2501678 ; https://hctz.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/job/2501719 ; https://hctz.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/job/2501868

**Checkpoint context:** 18 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0732 — Silicon Labs

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B2 Other access/HTTP response investigation

**Configured source:** `Workday / official careers` — https://www.silabs.com/about-us/careers

**Cycle source/result ATS:** https://www.silabs.com/about-us/careers — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page HTTP 403: access denied or human verification; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 403).

**Next action:** Confirm current public official source and classify actual response (challenge, rate limit, changed route or other error). Respect denial; preserve partial data. A new wrapper is not yet justified.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0733 — Nordic Semiconductor

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B2 Other access/HTTP response investigation

**Configured source:** `Teamtailor / official careers` — https://www.nordicsemi.com/Careers

**Cycle source/result ATS:** https://www.nordicsemi.com/Careers — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page HTTP 403: access denied or human verification; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 403).

**Next action:** Confirm current public official source and classify actual response (challenge, rate limit, changed route or other error). Respect denial; preserve partial data. A new wrapper is not yet justified.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0734 — Semtech

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Workday / official careers` — https://www.semtech.com/careers

**Cycle source/result ATS:** https://www.semtech.com/careers — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found on careers page or obvious same-site job links; the careers page is reachable but may use another ATS or require JavaScript, so inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:45.775779+00:00; HTTP 200; final URL https://www.semtech.com/careers; error none; evidence key `COMP-0734`.

**Extracted provider-link leads (unverified scope):** https://semtech.wd1.myworkdayjobs.com/SemtechCareers/1/refreshFacet/318c8bb6f553100021d223d9780d30be

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0735 — Synaptics

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B2 Other access/HTTP response investigation

**Configured source:** `Official careers` — https://careers.synaptics.com/search/jobs

**Cycle source/result ATS:** https://careers.synaptics.com/search/jobs — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page HTTP 403: access denied or human verification; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 403).

**Next action:** Confirm current public official source and classify actual response (challenge, rate limit, changed route or other error). Respect denial; preserve partial data. A new wrapper is not yet justified.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0736 — Lattice Semiconductor

**Disposition:** Legacy URL normalization candidate · **Work order:** W08

**Initial group:** A3 Provider parser/pagination/validation

**Configured source:** `Workday` — https://www.latticesemi.com/About/Jobs

**Cycle source/result ATS:** https://latticesemi.wd5.myworkdayjobs.com/wday/cxs/latticesemi/latticesemiconductorscareers?bga=true&hashed=-625919477&height=500&jan1offset=-480&jun1offset=-420&mobile=false&needsRedirect=false&width=1378 — `Workday`

**Exact recorded reason:** Direct fetch returned partial: Discovered Workday board https://latticesemi.wd5.myworkdayjobs.com/wday/cxs/latticesemi/latticesemiconductorscareers?bga=true&hashed=-625919477&height=500&jan1offset=-480&jun1offset=-420&mobile=false&needsRedirect=false&width=1378 from https://www.latticesemi.com/About/Jobs. Workday filter validation: Workday URL filter is unavailable or unrecognized; verify the company's filtered board URL.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 1 job URLs await retry. Inventory completeness unknown; no closure inference.

**Next action:** Separate historical Workday browser metadata from actual filter state; verify current canonical latticesemiconductorscareers board and preserve scope.

**Candidate code:** `src/job_search_helper/workday.py`, `src/job_search_helper/discovery.py`, `src/job_search_helper/company_sources.py`

**Existing test candidates:** `tests/test_workday.py`, `tests/test_workday_leidos.py`, `tests/test_workday_leidos_reconcile.py`, `tests/test_workday_reconcile.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 1 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0737 — Vicor

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `SuccessFactors / official careers` — https://careers.vicorpower.com/?locale=en_US

**Cycle source/result ATS:** https://careers.vicorpower.com/?locale=en_US — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found within the bounded careers-page discovery limit; the careers page is reachable but inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:46.033689+00:00; HTTP 200; final URL https://careers.vicorpower.com/?locale=en_US; error none; evidence key `COMP-0737`.

**Provider text/asset leads only:** successfactors. These may be false positives; not a verified board.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0739 — Samtec

**Disposition:** Existing provider parser candidate · **Work order:** W08

**Initial group:** A3 Provider parser/pagination/validation

**Configured source:** `Jobvite` — https://jobs.jobvite.com/samtec/search

**Cycle source/result ATS:** https://jobs.jobvite.com/samtec/jobs — `Jobvite`

**Exact recorded reason:** Public HTML board has no verified job-list container; empty inventory unproven.

**Next action:** Current Jobvite page HTTP 200 has real Samtec detail links while literal jv-job-list gate rejects inventory. Validate new complete container/feed, pagination and explicit empty state.

**Candidate code:** `src/job_search_helper/shared_boards.py`

**Existing test candidates:** `tests/test_shared_boards.py`

**Fresh public check:** 2026-11-17T15:39:57.369425+00:00; HTTP 200; final URL https://jobs.jobvite.com/samtec/jobs; error none; evidence key `samtec-page`.

**Extracted provider-link leads (unverified scope):** https://app.jobvite.com ; https://jobs.jobvite.com/cdn-cgi/l/email-protection#690c011c0408071b0c1a061c1b0a0c1a291a08041d0c0a470a0604 ; https://jobs.jobvite.com/samtec/job/o7NYAfwc ; https://jobs.jobvite.com/samtec/job/oRA5AfwQ ; https://jobs.jobvite.com/samtec/job/oVj2AfwA ; https://jobs.jobvite.com/samtec/job/obvQAfwQ

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0740 — Supermicro

**Disposition:** Provider discovery candidate · **Work order:** W06

**Initial group:** C2 Native source discovery/routing

**Configured source:** `SuccessFactors` — https://jobs.supermicro.com/

**Cycle source/result ATS:** https://jobs.supermicro.com/ — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found within the bounded careers-page discovery limit; the careers page is reachable but inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Current official source contains SuccessFactors markers/links. Verify exact public listing/tenant, geographic and subsidiary scope, then reuse Jobs2Web or supported SuccessFactors route; asset markers alone are not board evidence.

**Candidate code:** `src/job_search_helper/successfactors.py`, `src/job_search_helper/company_sources.py`

**Existing test candidates:** `tests/test_successfactors.py`, `tests/test_successfactors_browser_fallback.py`, `tests/test_successfactors_retry.py`

**Fresh public check:** 2026-11-17T15:39:46.262199+00:00; HTTP 200; final URL https://jobs.supermicro.com/; error none; evidence key `COMP-0740`.

**Extracted provider-link leads (unverified scope):** https://career4.successfactors.com ; https://career4.successfactors.com/career?site=&company=supermicro&lang=en_US&login_ns=register&career_ns=home&navBarLevel=MY_PROFILE

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0741 — Dell Technologies

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Oracle Recruiting` — https://enterpriseplatform.dell.com/hcmUI/CandidateExperience/en/sites/careers/jobs?mode=location

**Cycle source/result ATS:** https://enterpriseplatform.dell.com/hcmUI/CandidateExperience/en/sites/careers/jobs?mode=location — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found on careers page or obvious same-site job links; the careers page is reachable but may use another ATS or require JavaScript, so inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:46.492202+00:00; HTTP 200; final URL https://enterpriseplatform.dell.com/hcmUI/CandidateExperience/en/sites/careers/jobs?mode=location; error none; evidence key `COMP-0741`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0742 — congatec

**Disposition:** Provider discovery candidate · **Work order:** W06

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://www.congatec.com/us/congatec/career-1/open-positions/

**Cycle source/result ATS:** https://www.congatec.com/us/congatec/career-1/open-positions/ — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found within the bounded careers-page discovery limit; the careers page is reachable but inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 25 job URLs await retry. Inventory completeness unknown; no closure inference. Stopped this detail pass after 5 consecutive failures; unresolved URLs and saved descriptions retained.

**Next action:** Current official source contains SuccessFactors markers/links. Verify exact public listing/tenant, geographic and subsidiary scope, then reuse Jobs2Web or supported SuccessFactors route; asset markers alone are not board evidence.

**Candidate code:** `src/job_search_helper/successfactors.py`, `src/job_search_helper/company_sources.py`

**Existing test candidates:** `tests/test_successfactors.py`, `tests/test_successfactors_browser_fallback.py`, `tests/test_successfactors_retry.py`

**Fresh public check:** 2026-11-17T15:39:46.838236+00:00; HTTP 200; final URL https://www.congatec.com/us/congatec/career-1/open-positions/; error none; evidence key `COMP-0742`.

**Extracted provider-link leads (unverified scope):** https://career2.successfactors.eu/sfcareer/jobreqcareer?jobId=2718&company=congatecag&locale=en_US ; https://career2.successfactors.eu/sfcareer/jobreqcareer?jobId=3133&company=congatecag&locale=en_US ; https://career2.successfactors.eu/sfcareer/jobreqcareer?jobId=3135&company=congatecag&locale=en_US ; https://career2.successfactors.eu/sfcareer/jobreqcareer?jobId=3137&company=congatecag&locale=en_US ; https://career2.successfactors.eu/sfcareer/jobreqcareer?jobId=3141&company=congatecag&locale=en_US ; https://career2.successfactors.eu/sfcareer/jobreqcareer?jobId=3144&company=congatecag&locale=en_US

**Checkpoint context:** 25 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0743 — Eurotech

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B2 Other access/HTTP response investigation

**Configured source:** `Hirebridge / official careers` — https://www.eurotech.com/careers/

**Cycle source/result ATS:** https://www.eurotech.com/careers/ — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page HTTP 403: access denied or human verification; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Confirm current public official source and classify actual response (challenge, rate limit, changed route or other error). Respect denial; preserve partial data. A new wrapper is not yet justified.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0746 — Adtran

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B1 Workday access/response investigation

**Configured source:** `Workday` — https://www.adtran.com/en/about-us/careers

**Cycle source/result ATS:** https://adtran.wd3.myworkdayjobs.com/wday/cxs/adtran/ADTRAN — `Workday`

**Exact recorded reason:** Direct fetch returned partial: Discovered Workday board https://adtran.wd3.myworkdayjobs.com/wday/cxs/adtran/ADTRAN from https://www.adtran.com/en/about-us/careers. Workday listing page 1: Human verification detected; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 1 job URLs await retry. Inventory completeness unknown; no closure inference.

**Next action:** Capture the failed Workday request page/posting and response classification; inspect host pacing and source filters. Validate all pages/details after recovery. Do not assume a new wrapper fixes genuine access denial.

**Candidate code:** `src/job_search_helper/workday.py`

**Existing test candidates:** `tests/test_workday.py`, `tests/test_workday_leidos.py`, `tests/test_workday_leidos_reconcile.py`, `tests/test_workday_reconcile.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 1 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0747 — Ribbon Communications

**Disposition:** Source/redirect investigation · **Work order:** W05 / source repair

**Initial group:** C3 Stale URL/redirect/request repair

**Configured source:** `Workday` — https://ribboncommunications.com/company/careers

**Cycle source/result ATS:** https://vhr-genband.wd1.myworkdayjobs.com/wday/cxs/vhr-genband/ribboncareers — `Workday`

**Exact recorded reason:** Direct fetch returned partial: Discovered Workday board https://vhr-genband.wd1.myworkdayjobs.com/wday/cxs/vhr-genband/ribboncareers from https://ribboncommunications.com/company/careers. Workday listing page 1: HTTP 422; inventory unavailable, not evidence of closure. Workday normalized posting count does not match the inventory count.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Follow the exact current official link/redirect with bounded trusted destinations; validate replacement board and scope. A 404 is not closure. Test dispatch/source aliases and every page/detail.

**Candidate code:** `src/job_search_helper/company_sources.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:47.054314+00:00; HTTP 429; final URL https://vhr-genband.wd1.myworkdayjobs.com/wday/cxs/vhr-genband/ribboncareers; error none; evidence key `COMP-0747`.

**Provider text/asset leads only:** myworkdayjobs. These may be false positives; not a verified board.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0748 — EXFO

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B1 Workday access/response investigation

**Configured source:** `Workday` — https://careers.exfo.com/

**Cycle source/result ATS:** https://exfo.wd10.myworkdayjobs.com/wday/cxs/exfo/EXFO_Careers — `Workday`

**Exact recorded reason:** Direct fetch returned partial: Discovered Workday board https://exfo.wd10.myworkdayjobs.com/wday/cxs/exfo/EXFO_Careers from https://careers.exfo.com/. Workday listing page 2: Human verification detected; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Capture the failed Workday request page/posting and response classification; inspect host pacing and source filters. Validate all pages/details after recovery. Do not assume a new wrapper fixes genuine access denial.

**Candidate code:** `src/job_search_helper/workday.py`

**Existing test candidates:** `tests/test_workday.py`, `tests/test_workday_leidos.py`, `tests/test_workday_leidos_reconcile.py`, `tests/test_workday_reconcile.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0749 — Ubiquiti

**Disposition:** Strong native integration candidate · **Work order:** W06

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://careers.ui.com/

**Cycle source/result ATS:** https://careers.ui.com/ — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found on careers page or obvious same-site job links; the careers page is reachable but may use another ATS or require JavaScript, so inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Official Greenhouse Ubiquiti links verified; public ubiquiti feed HTTP 200 with 168 rows. Reuse Greenhouse and verify total, full content and reread.

**Candidate code:** `src/job_search_helper/ats.py`, `src/job_search_helper/company_sources.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:47.308724+00:00; HTTP 200; final URL https://careers.ui.com/; error none; evidence key `COMP-0749`.

**Extracted provider-link leads (unverified scope):** https://job-boards.greenhouse.io/ubiquiti/jobs/4071312009 ; https://job-boards.greenhouse.io/ubiquiti/jobs/4074814009 ; https://job-boards.greenhouse.io/ubiquiti/jobs/4074881009 ; https://job-boards.greenhouse.io/ubiquiti/jobs/4074888009 ; https://job-boards.greenhouse.io/ubiquiti/jobs/4074896009 ; https://job-boards.greenhouse.io/ubiquiti/jobs/4075273009

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0751 — Epiq Solutions

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://epiqsolutions.com/careers

**Cycle source/result ATS:** https://epiqsolutions.com/careers — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found on careers page or obvious same-site job links; the careers page is reachable but may use another ATS or require JavaScript, so inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:47.349261+00:00; HTTP 200; final URL https://epiqsolutions.com/careers; error none; evidence key `COMP-0751`.

**Extracted provider-link leads (unverified scope):** https://recruiting.paylocity.com/Recruiting/Jobs/Details/4638475 ; https://recruiting.paylocity.com/Recruiting/Jobs/Details/4669931 ; https://recruiting.paylocity.com/recruiting/jobs/Details/4500616/Epiq-Design-Solutions-LLC/Sales-Support-Representative-I---Rolling-Meadows-IL ; https://recruiting.paylocity.com/recruiting/jobs/Details/4544764/Epiq-Design-Solutions-LLC/Manufacturing-Planner---Rolling-Meadows-IL6 ; https://recruiting.paylocity.com/recruiting/jobs/Details/4566602/Epiq-Design-Solutions-LLC/Senior-Staff-Software-Engineer---Rolling-Meadows-IL ; https://recruiting.paylocity.com/recruiting/jobs/Details/4576157/Epiq-Design-Solutions-LLC/Manager-Digital-Design-FPGA-Engineering---Rolling-Meadows-IL

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0752 — Spectrum Control

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B1 Workday access/response investigation

**Configured source:** `Workday` — https://www.spectrumcontrol.com/about/careers

**Cycle source/result ATS:** https://spectrumcontrol.wd1.myworkdayjobs.com/wday/cxs/spectrumcontrol/SpectrumControl — `Workday`

**Exact recorded reason:** Direct fetch returned partial: Discovered Workday board https://spectrumcontrol.wd1.myworkdayjobs.com/wday/cxs/spectrumcontrol/SpectrumControl from https://www.spectrumcontrol.com/about/careers. Workday job detail https://spectrumcontrol.wd1.myworkdayjobs.com/SpectrumControl/job/Fairview-PA/Assembler-II--1800-M-Th-2PM-12M_JR101541: Human verification detected; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Capture the failed Workday request page/posting and response classification; inspect host pacing and source filters. Validate all pages/details after recovery. Do not assume a new wrapper fixes genuine access denial.

**Candidate code:** `src/job_search_helper/workday.py`

**Existing test candidates:** `tests/test_workday.py`, `tests/test_workday_leidos.py`, `tests/test_workday_leidos_reconcile.py`, `tests/test_workday_reconcile.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0754 — Flexiv

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://www.flexiv.com/join

**Cycle source/result ATS:** https://www.flexiv.com/join — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found on careers page or obvious same-site job links; the careers page is reachable but may use another ATS or require JavaScript, so inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:47.544884+00:00; HTTP 200; final URL https://www.flexiv.com/join; error none; evidence key `COMP-0754`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0755 — Contoro Robotics

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B2 Other access/HTTP response investigation

**Configured source:** `Official careers` — https://contoro.com/career/

**Cycle source/result ATS:** https://contoro.com/career/ — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page HTTP 403: access denied or human verification; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 403).

**Next action:** Confirm current public official source and classify actual response (challenge, rate limit, changed route or other error). Respect denial; preserve partial data. A new wrapper is not yet justified.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0756 — Jacobi Robotics

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://jacobirobotics.com/careers

**Cycle source/result ATS:** https://jacobirobotics.com/careers — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found on careers page or obvious same-site job links; the careers page is reachable but may use another ATS or require JavaScript, so inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:47.645506+00:00; HTTP 200; final URL https://jacobirobotics.com/careers; error none; evidence key `COMP-0756`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0758 — Verdant Robotics

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://www.verdantrobotics.com/careers

**Cycle source/result ATS:** https://www.verdantrobotics.com/careers — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found on careers page or obvious same-site job links; the careers page is reachable but may use another ATS or require JavaScript, so inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:47.964092+00:00; HTTP 200; final URL https://www.verdantrobotics.com/careers; error none; evidence key `COMP-0758`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0759 — Solinftec

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B2 Other access/HTTP response investigation

**Configured source:** `Official careers` — https://www.solinftec.com/en-us/us-careers/

**Cycle source/result ATS:** https://www.solinftec.com/en-us/us-careers/ — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page HTTP 403: access denied or human verification; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 403).

**Next action:** Confirm current public official source and classify actual response (challenge, rate limit, changed route or other error). Respect denial; preserve partial data. A new wrapper is not yet justified.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0760 — Basler

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B2 Other access/HTTP response investigation

**Configured source:** `Official careers` — https://www.baslerweb.com/en-us/careers/working-at-basler/

**Cycle source/result ATS:** https://www.baslerweb.com/en-us/careers/working-at-basler/ — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page HTTP 406; board discovery did not complete.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 403).

**Next action:** Confirm current public official source and classify actual response (challenge, rate limit, changed route or other error). Respect denial; preserve partial data. A new wrapper is not yet justified.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0761 — Allied Vision

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://www.alliedvision.com/en/company/career

**Cycle source/result ATS:** https://www.alliedvision.com/en/company/career — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found within the bounded careers-page discovery limit; the careers page is reachable but inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 23 job URLs await retry. Inventory completeness unknown; no closure inference. Stopped this detail pass after 5 consecutive failures; unresolved URLs and saved descriptions retained.

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:49.017035+00:00; HTTP 200; final URL https://www.alliedvision.com/en/company/career; error none; evidence key `COMP-0761`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 23 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0762 — IDS Imaging Development Systems

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B2 Other access/HTTP response investigation

**Configured source:** `Official careers` — https://www.ids-imaging.us/vacancies.html

**Cycle source/result ATS:** https://www.ids-imaging.us/vacancies.html — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page HTTP 403: access denied or human verification; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 403).

**Next action:** Confirm current public official source and classify actual response (challenge, rate limit, changed route or other error). Respect denial; preserve partial data. A new wrapper is not yet justified.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0763 — MVTec Software

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://www.mvtec.com/career

**Cycle source/result ATS:** https://www.mvtec.com/career — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found within the bounded careers-page discovery limit; the careers page is reachable but inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:49.092548+00:00; HTTP 200; final URL https://www.mvtec.com/career; error none; evidence key `COMP-0763`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0764 — Yokogawa

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://www.yokogawa.com/us/about/careers/

**Cycle source/result ATS:** https://www.yokogawa.com/us/about/careers/ — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found within the bounded careers-page discovery limit; the careers page is reachable but inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (Error).

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:49.381285+00:00; HTTP 200; final URL https://www.yokogawa.com/us/about/careers/; error none; evidence key `COMP-0764`.

**Extracted provider-link leads (unverified scope):** https://wd3.myworkdaysite.com/recruiting/yokogawa/yokogawa-career-site

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0765 — Endress+Hauser

**Disposition:** Provider discovery candidate · **Work order:** W06

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://www.us.endress.com/en/endress-hauser-group/career/job-opportunities/process-automation-jobs-us

**Cycle source/result ATS:** https://www.us.endress.com/en/endress-hauser-group/career/job-opportunities/process-automation-jobs-us — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found on careers page or obvious same-site job links; the careers page is reachable but may use another ATS or require JavaScript, so inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Current official source contains SuccessFactors markers/links. Verify exact public listing/tenant, geographic and subsidiary scope, then reuse Jobs2Web or supported SuccessFactors route; asset markers alone are not board evidence.

**Candidate code:** `src/job_search_helper/successfactors.py`, `src/job_search_helper/company_sources.py`

**Existing test candidates:** `tests/test_successfactors.py`, `tests/test_successfactors_browser_fallback.py`, `tests/test_successfactors_retry.py`

**Fresh public check:** 2026-11-17T15:39:49.527364+00:00; HTTP 200; final URL https://www.us.endress.com/en/endress-hauser-group/career/job-opportunities/process-automation-jobs-us; error none; evidence key `COMP-0765`.

**Extracted provider-link leads (unverified scope):** https://career5.successfactors.eu/career?career_company=endress&lang=en_US&company=endress&site=&loginFlowRequired=true

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0766 — VEGA Americas

**Disposition:** Network/source investigation · **Work order:** Access investigations

**Initial group:** B3 Network/service failure

**Configured source:** `Official careers` — https://www.vega.com/en-us/company/career-opportunities

**Cycle source/result ATS:** https://www.vega.com/en-us/company/career-opportunities — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page network/timeout failure; board discovery did not complete.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Recheck canonical official URL, TLS/DNS/HTTP status and bounded timeout behavior; confirm native provider after recovery. Do not disable certificate verification or infer an empty board.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0767 — Kistler

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://www.kistler.com/US/en/jobs?country=US

**Cycle source/result ATS:** https://www.kistler.com/US/en/jobs?country=US — `Official careers`

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found within the bounded careers-page discovery limit; the careers page is reachable but inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 6 job descriptions; 1 job URLs await retry. Inventory completeness unknown; no closure inference.

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:49.564111+00:00; HTTP 200; final URL https://www.kistler.com/US/en/jobs?country=US; error none; evidence key `COMP-0767`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 1 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0769 — SolarEdge

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://corporate.solaredge.com/en/careers/open-positions

**Cycle source/result ATS:** https://corporate.solaredge.com/en/careers/open-positions — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found within the bounded careers-page discovery limit; the careers page is reachable but inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:50.327194+00:00; HTTP 200; final URL https://corporate.solaredge.com/en/careers/open-positions; error none; evidence key `COMP-0769`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0771 — Fronius USA

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B1 Workday access/response investigation

**Configured source:** `Workday` — https://www.fronius.com/en-us/usa/career/jobs-at-fronius

**Cycle source/result ATS:** https://fronius.wd3.myworkdayjobs.com/wday/cxs/fronius/Job_Board?Country=bc33aa3152ec42d4995f4791a106ed09 — `Workday`

**Exact recorded reason:** Direct fetch returned partial: Discovered Workday board https://fronius.wd3.myworkdayjobs.com/wday/cxs/fronius/Job_Board?Country=bc33aa3152ec42d4995f4791a106ed09 from https://www.fronius.com/en-us/usa/career/jobs-at-fronius. Workday filter validation: Human verification detected; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 2 job URLs await retry. Inventory completeness unknown; no closure inference.

**Next action:** Capture the failed Workday request page/posting and response classification; inspect host pacing and source filters. Validate all pages/details after recovery. Do not assume a new wrapper fixes genuine access denial.

**Candidate code:** `src/job_search_helper/workday.py`

**Existing test candidates:** `tests/test_workday.py`, `tests/test_workday_leidos.py`, `tests/test_workday_leidos_reconcile.py`, `tests/test_workday_reconcile.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 2 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0772 — Generac

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B2 Other access/HTTP response investigation

**Configured source:** `Official careers` — https://careers.generac.com/en/jobs/

**Cycle source/result ATS:** https://careers.generac.com/en/jobs/ — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page HTTP 403: access denied or human verification; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 403).

**Next action:** Confirm current public official source and classify actual response (challenge, rate limit, changed route or other error). Respect denial; preserve partial data. A new wrapper is not yet justified.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0773 — Cummins

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B2 Other access/HTTP response investigation

**Configured source:** `Official careers` — https://www.cummins.com/en-na/careers

**Cycle source/result ATS:** https://www.cummins.com/en-na/careers — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page HTTP 403: access denied or human verification; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 403).

**Next action:** Confirm current public official source and classify actual response (challenge, rate limit, changed route or other error). Respect denial; preserve partial data. A new wrapper is not yet justified.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0774 — Bloom Energy

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B1 Workday access/response investigation

**Configured source:** `Workday` — https://www.bloomenergy.com/careers/

**Cycle source/result ATS:** https://bloomenergy.wd1.myworkdayjobs.com/wday/cxs/bloomenergy/BloomEnergyCareers — `Workday`

**Exact recorded reason:** Direct fetch returned partial: Discovered Workday board https://bloomenergy.wd1.myworkdayjobs.com/wday/cxs/bloomenergy/BloomEnergyCareers from https://www.bloomenergy.com/careers/. Workday job detail https://bloomenergy.wd1.myworkdayjobs.com/BloomEnergyCareers/job/Mumbai-Maharashtra/Operator---Technology-Support_JR-24158-1: Human verification detected; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Capture the failed Workday request page/posting and response classification; inspect host pacing and source filters. Validate all pages/details after recovery. Do not assume a new wrapper fixes genuine access denial.

**Candidate code:** `src/job_search_helper/workday.py`

**Existing test candidates:** `tests/test_workday.py`, `tests/test_workday_leidos.py`, `tests/test_workday_leidos_reconcile.py`, `tests/test_workday_reconcile.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0775 — FuelCell Energy

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `SuccessFactors` — https://careers.fuelcellenergy.com/

**Cycle source/result ATS:** https://careers.fuelcellenergy.com/ — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found on careers page or obvious same-site job links; the careers page is reachable but may use another ATS or require JavaScript, so inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:50.520334+00:00; HTTP 200; final URL https://careers.fuelcellenergy.com/; error none; evidence key `COMP-0775`.

**Provider text/asset leads only:** successfactors. These may be false positives; not a verified board.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0778 — Avnet

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B1 Workday access/response investigation

**Configured source:** `Workday` — https://avnet.wd1.myworkdayjobs.com/en-US/External

**Cycle source/result ATS:** https://avnet.wd1.myworkdayjobs.com/wday/cxs/avnet/External — `Workday`

**Exact recorded reason:** Direct fetch returned partial: Workday job detail https://avnet.wd1.myworkdayjobs.com/External/job/Juarez-Chihuahua-Mexico/Key-Account-Manager_JR-024953: Human verification detected; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Capture the failed Workday request page/posting and response classification; inspect host pacing and source filters. Validate all pages/details after recovery. Do not assume a new wrapper fixes genuine access denial.

**Candidate code:** `src/job_search_helper/workday.py`

**Existing test candidates:** `tests/test_workday.py`, `tests/test_workday_leidos.py`, `tests/test_workday_leidos_reconcile.py`, `tests/test_workday_reconcile.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0779 — Arrow Electronics

**Disposition:** Provider discovery and scope candidate · **Work order:** W06

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://careers.arrow.com/us/en/americas/?from=40&rk=l-americas&s=1

**Cycle source/result ATS:** https://careers.arrow.com/us/en/americas/?from=40&rk=l-americas&s=1 — `Official careers`

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found within the bounded careers-page discovery limit; the careers page is reachable but inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 162 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference.

**Next action:** Official page has Phenom evidence. Verify full relevant listing and preserve category/region/subsidiary intent; reuse phenom.py only after canonical tenant/filter completeness is proved.

**Candidate code:** `src/job_search_helper/phenom.py`, `src/job_search_helper/company_sources.py`

**Existing test candidates:** `tests/test_phenom.py`, `tests/test_phenom_reconciliation.py`

**Fresh public check:** 2026-11-17T15:39:50.883005+00:00; HTTP 200; final URL https://careers.arrow.com/us/en/americas/?from=40&rk=l-americas&s=1; error none; evidence key `COMP-0779`.

**Extracted provider-link leads (unverified scope):** https://arrow.wd1.myworkdayjobs.com/AC/job/US-CO-Denver-Colorado-Panorama-Arrow-Building/Trade-Operations-Specialist_R249251/apply ; https://arrow.wd1.myworkdayjobs.com/AC/job/US-MA-Peabody-Massachusetts-Technology-Dr/Application-Architect_R247670/apply ; https://arrow.wd1.myworkdayjobs.com/AC/job/US-MA-Peabody-Massachusetts-Technology-Dr/Field-Applications-Engineer---FPGA-specialist_R246743/apply ; https://arrow.wd1.myworkdayjobs.com/AC/job/US-MA-Peabody-Massachusetts-Technology-Dr/Field-Sales-Representative-I_R249232/apply ; https://arrow.wd1.myworkdayjobs.com/AC/job/US-MA-Peabody-Massachusetts-Technology-Dr/Key-Account-Executive_R248090-1/apply ; https://arrow.wd1.myworkdayjobs.com/AC/job/US-MA-Peabody-Massachusetts-Technology-Dr/Market-Development-Engineer_R246963/apply

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0780 — Thermo Fisher Scientific

**Disposition:** Provider discovery and scope candidate · **Work order:** W06

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://jobs.thermofisher.com/global/en/c/customer-technical-support-jobs

**Cycle source/result ATS:** https://jobs.thermofisher.com/global/en/c/customer-technical-support-jobs — `Official careers`

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found on careers page or obvious same-site job links; the careers page is reachable but may use another ATS or require JavaScript, so inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 60 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference.

**Next action:** Official page has Phenom evidence. Verify full relevant listing and preserve category/region/subsidiary intent; reuse phenom.py only after canonical tenant/filter completeness is proved.

**Candidate code:** `src/job_search_helper/phenom.py`, `src/job_search_helper/company_sources.py`

**Existing test candidates:** `tests/test_phenom.py`, `tests/test_phenom_reconciliation.py`

**Fresh public check:** 2026-11-17T15:39:50.927564+00:00; HTTP 200; final URL https://jobs.thermofisher.com/global/en/c/customer-technical-support-jobs; error none; evidence key `COMP-0780`.

**Extracted provider-link leads (unverified scope):** https://assets.phenompeople.com ; https://cdn.phenompeople.com ; https://cdn.phenompeople.com/CareerConnectResources/prod

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0781 — Danaher

**Disposition:** Provider discovery and scope candidate · **Work order:** W06

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://jobs.danaher.com/global/en/us-customer-support-jobs

**Cycle source/result ATS:** https://jobs.danaher.com/global/en/us-customer-support-jobs — `Official careers`

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found on careers page or obvious same-site job links; the careers page is reachable but may use another ATS or require JavaScript, so inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 56 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference.

**Next action:** Official page has Phenom evidence. Verify full relevant listing and preserve category/region/subsidiary intent; reuse phenom.py only after canonical tenant/filter completeness is proved.

**Candidate code:** `src/job_search_helper/phenom.py`, `src/job_search_helper/company_sources.py`

**Existing test candidates:** `tests/test_phenom.py`, `tests/test_phenom_reconciliation.py`

**Fresh public check:** 2026-11-17T15:39:51.173206+00:00; HTTP 200; final URL https://jobs.danaher.com/global/en/us-customer-support-jobs; error none; evidence key `COMP-0781`.

**Extracted provider-link leads (unverified scope):** https://cdn.phenompeople.com/CareerConnectResources ; https://content-us.phenompeople.com ; https://content-us.phenompeople.com/api/content-delivery/caasContentV1 ; https://danaher.wd1.myworkdayjobs.com/DanaherJobs/job/Boston-Massachusetts-United-States/Field-Applications-Specialist---Core-Histology_R1319766-1/apply ; https://danaher.wd1.myworkdayjobs.com/DanaherJobs/job/Chicago-Illinois-United-States/Field-Service-Engineer---Chicago--IL_R1319584/apply ; https://danaher.wd1.myworkdayjobs.com/DanaherJobs/job/Chicago-Illinois-United-States/Field-Service-Engineer-I---Digital-Pathology---Chicago-or-Minneapolis_R1319433/apply

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0782 — Waters Corporation

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B2 Other access/HTTP response investigation

**Configured source:** `iCIMS` — https://www.waters.com/nextgen/us/en/about-waters/careers.html

**Cycle source/result ATS:** https://www.waters.com/nextgen/us/en/about-waters/careers.html — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page HTTP 403: access denied or human verification; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Browser fallback needs retry (Error).

**Next action:** Confirm current public official source and classify actual response (challenge, rate limit, changed route or other error). Respect denial; preserve partial data. A new wrapper is not yet justified.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0783 — MACOM

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://www.macom.com/about-macom/careers

**Cycle source/result ATS:** https://www.macom.com/about-macom/careers — ``

**Exact recorded reason:** Direct fetch returned partial: Careers discovery expected an HTML page; provide the ATS board URL.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 403).

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:51.286220+00:00; HTTP 200; final URL https://www.macom.com/about-macom/careers; error none; evidence key `COMP-0783`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0784 — Monolithic Power Systems

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B1 Workday access/response investigation

**Configured source:** `Workday` — https://www.monolithicpower.com/about-mps/careers/job-listings.html

**Cycle source/result ATS:** https://monolithicpower.wd12.myworkdayjobs.com/wday/cxs/monolithicpower/MPS_Careers — `Workday`

**Exact recorded reason:** Direct fetch returned partial: Discovered Workday board https://monolithicpower.wd12.myworkdayjobs.com/wday/cxs/monolithicpower/MPS_Careers from https://www.monolithicpower.com/about-mps/careers/job-listings.html. Workday job detail https://monolithicpower.wd12.myworkdayjobs.com/MPS_Careers/job/Hangzhou---China/Sr-Power-Module-Design-Engineer_R-1265: Human verification detected; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (Error).

**Next action:** Capture the failed Workday request page/posting and response classification; inspect host pacing and source filters. Validate all pages/details after recovery. Do not assume a new wrapper fixes genuine access denial.

**Candidate code:** `src/job_search_helper/workday.py`

**Existing test candidates:** `tests/test_workday.py`, `tests/test_workday_leidos.py`, `tests/test_workday_leidos_reconcile.py`, `tests/test_workday_reconcile.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0785 — MKS Instruments

**Disposition:** Employer scope needs proof · **Work order:** Scope investigations

**Initial group:** C1 Employer scope or multiple boards

**Configured source:** `Workday` — https://www.mks.com/employmentinfo/employmenthome.aspx

**Cycle source/result ATS:** https://www.mks.com/employmentinfo/employmenthome.aspx — ``

**Exact recorded reason:** Direct fetch returned partial: Multiple ATS boards linked by careers page; select the company's board explicitly.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 403).

**Next action:** Prove attributable employer/legal-entity/brand and complete board set before implementing or widening a parent/shared source. Verify each regional board and deduplicate stable IDs.

**Candidate code:** `src/job_search_helper/company_sources.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:51.431975+00:00; HTTP 200; final URL https://www.mks.com/employmentinfo/employmenthome.aspx; error none; evidence key `COMP-0785`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0786 — Brooks Automation

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B1 Workday access/response investigation

**Configured source:** `Workday` — https://www.brooks.com/careers/

**Cycle source/result ATS:** https://brooksauto.wd1.myworkdayjobs.com/wday/cxs/brooksauto/Brooks_External_Site — `Workday`

**Exact recorded reason:** Direct fetch returned partial: Discovered Workday board https://brooksauto.wd1.myworkdayjobs.com/wday/cxs/brooksauto/Brooks_External_Site from https://www.brooks.com/careers/. Workday listing page 2: Human verification detected; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Capture the failed Workday request page/posting and response classification; inspect host pacing and source filters. Validate all pages/details after recovery. Do not assume a new wrapper fixes genuine access denial.

**Candidate code:** `src/job_search_helper/workday.py`

**Existing test candidates:** `tests/test_workday.py`, `tests/test_workday_leidos.py`, `tests/test_workday_leidos_reconcile.py`, `tests/test_workday_reconcile.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0787 — Azenta Life Sciences

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B1 Workday access/response investigation

**Configured source:** `Workday` — https://azenta.wd1.myworkdayjobs.com/AzentaJobs

**Cycle source/result ATS:** https://azenta.wd1.myworkdayjobs.com/wday/cxs/azenta/AzentaJobs — `Workday`

**Exact recorded reason:** Direct fetch returned partial: Workday listing page 2: Human verification detected; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Capture the failed Workday request page/posting and response classification; inspect host pacing and source filters. Validate all pages/details after recovery. Do not assume a new wrapper fixes genuine access denial.

**Candidate code:** `src/job_search_helper/workday.py`

**Existing test candidates:** `tests/test_workday.py`, `tests/test_workday_leidos.py`, `tests/test_workday_leidos_reconcile.py`, `tests/test_workday_reconcile.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0788 — Renishaw

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B1 Workday access/response investigation

**Configured source:** `Workday` — https://www.renishaw.com/en/careers--6417

**Cycle source/result ATS:** https://renishaw.wd3.myworkdayjobs.com/wday/cxs/renishaw/Renishaw — `Workday`

**Exact recorded reason:** Direct fetch returned partial: Discovered Workday board https://renishaw.wd3.myworkdayjobs.com/wday/cxs/renishaw/Renishaw from https://www.renishaw.com/en/careers--6417. Workday listing page 2: Human verification detected; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing HTTP 403).

**Next action:** Capture the failed Workday request page/posting and response classification; inspect host pacing and source filters. Validate all pages/details after recovery. Do not assume a new wrapper fixes genuine access denial.

**Candidate code:** `src/job_search_helper/workday.py`

**Existing test candidates:** `tests/test_workday.py`, `tests/test_workday_leidos.py`, `tests/test_workday_leidos_reconcile.py`, `tests/test_workday_reconcile.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0789 — Aerotech

**Disposition:** Native integration candidate · **Work order:** W06

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://www.aerotech.com/careers/search-all/

**Cycle source/result ATS:** https://www.aerotech.com/careers/search-all/ — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found within the bounded careers-page discovery limit; the careers page is reachable but inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 3 job URLs await retry. Inventory completeness unknown; no closure inference.

**Next action:** Official page links aerotech.applytojob.com/apply/ (200). Reuse JazzHR, prove complete container/pagination and full details.

**Candidate code:** `src/job_search_helper/shared_boards.py`, `src/job_search_helper/company_sources.py`

**Existing test candidates:** `tests/test_shared_boards.py`

**Fresh public check:** 2026-11-17T15:39:51.755716+00:00; HTTP 200; final URL https://www.aerotech.com/careers/search-all/; error none; evidence key `COMP-0789`.

**Extracted provider-link leads (unverified scope):** https://aerotech.applytojob.com/apply/

**Checkpoint context:** 3 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0790 — PI (Physik Instrumente)

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B2 Other access/HTTP response investigation

**Configured source:** `Softgarden` — https://pi-usa.softgarden.io/en/vacancies

**Cycle source/result ATS:** https://pi-usa.softgarden.io/en/vacancies — `Softgarden`

**Exact recorded reason:** Direct fetch returned blocked: Careers page HTTP 403: access denied or human verification; manual review required.. Browser fallback returned partial: Browser fallback saved 10 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference.

**Next action:** Confirm current public official source and classify actual response (challenge, rate limit, changed route or other error). Respect denial; preserve partial data. A new wrapper is not yet justified.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0791 — Power Integrations

**Disposition:** Native integration candidate · **Work order:** W06

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Jobvite` — https://www.power.com/company/careers

**Cycle source/result ATS:** https://www.power.com/company/careers — ``

**Exact recorded reason:** Direct fetch returned partial: No verified shared board found in bounded employer-page discovery.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Official page embeds Jobvite power-integrations with nl/fr parameters. Prove canonical full board and normalize only verified embed parameters; share Samtec-compatible listing checks.

**Candidate code:** `src/job_search_helper/shared_boards.py`, `src/job_search_helper/company_sources.py`

**Existing test candidates:** `tests/test_shared_boards.py`

**Fresh public check:** 2026-11-17T15:39:52.763189+00:00; HTTP 200; final URL https://www.power.com/company/careers; error none; evidence key `COMP-0791`.

**Extracted provider-link leads (unverified scope):** https://jobs.jobvite.com/power-integrations/?nl=1&fr=true

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0793 — Applied Materials

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://jobs.appliedmaterials.com/en/search-jobs

**Cycle source/result ATS:** https://jobs.appliedmaterials.com/en/search-jobs — `Official careers`

**Exact recorded reason:** Direct fetch returned unsupported: Careers page exceeds the discovery size limit; provide its ATS board URL.. Browser fallback returned partial: Browser fallback saved 15 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference.

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:52.951965+00:00; HTTP 200; final URL https://jobs.appliedmaterials.com/en/search-jobs; error none; evidence key `COMP-0793`.

**Provider text/asset leads only:** talentbrew, workday. These may be false positives; not a verified board.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0794 — Lam Research

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://careers.lamresearch.com/careers?hl=en_US

**Cycle source/result ATS:** https://careers.lamresearch.com/careers?hl=en_US — `Official careers`

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found on careers page or obvious same-site job links; the careers page is reachable but may use another ATS or require JavaScript, so inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 10 job descriptions; 3 job URLs await retry. Inventory completeness unknown; no closure inference.

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:53.098158+00:00; HTTP 200; final URL https://careers.lamresearch.com/careers?hl=en_US; error none; evidence key `COMP-0794`.

**Extracted provider-link leads (unverified scope):** https://performancemanager4.successfactors.com/sf/careers/jobsearch?bplte_company=LAM

**Checkpoint context:** 3 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0795 — KLA

**Disposition:** Access and response investigation · **Work order:** Access investigations

**Initial group:** B1 Workday access/response investigation

**Configured source:** `Workday` — https://kla.wd1.myworkdayjobs.com/en-US/Search

**Cycle source/result ATS:** https://kla.wd1.myworkdayjobs.com/wday/cxs/kla/Search — `Workday`

**Exact recorded reason:** Direct fetch returned partial: Workday job detail https://kla.wd1.myworkdayjobs.com/Search/job/Singapore-Singapore/Investigator--Ethics---Legal-Compliance_2643310: Human verification detected; manual review required.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Listing discovery needs retry (ListingUnavailable: Listing has no verifiable job links yet).

**Next action:** Capture the failed Workday request page/posting and response classification; inspect host pacing and source filters. Validate all pages/details after recovery. Do not assume a new wrapper fixes genuine access denial.

**Candidate code:** `src/job_search_helper/workday.py`

**Existing test candidates:** `tests/test_workday.py`, `tests/test_workday_leidos.py`, `tests/test_workday_leidos_reconcile.py`, `tests/test_workday_reconcile.py`

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0796 — ASML

**Disposition:** Source discovery still required · **Work order:** Native discovery

**Initial group:** C2 Native source discovery/routing

**Configured source:** `Official careers` — https://www.asml.com/en/careers/working-at-asml/united-states/us-customer-support-jobs

**Cycle source/result ATS:** https://www.asml.com/en/careers/working-at-asml/united-states/us-customer-support-jobs — ``

**Exact recorded reason:** Direct fetch returned partial: No supported ATS link found within the bounded careers-page discovery limit; the careers page is reachable but inventory completeness is unknown.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 43 job URLs await retry. Inventory completeness unknown; no closure inference. Stopped this detail pass after 5 consecutive failures; unresolved URLs and saved descriptions retained.

**Next action:** Inspect the exact official source and current public links/embedded listing. Reuse a supported provider only after canonical tenant and intended scope are established. No ATS candidate in a static page does not prove no jobs.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** 2026-11-17T15:39:53.106215+00:00; HTTP 200; final URL https://www.asml.com/en/careers/working-at-asml/united-states/us-customer-support-jobs; error none; evidence key `COMP-0796`.

**Discovery result:** no provider-link lead extracted from this bounded static response; inspect embedded/linked public inventory before concluding no jobs.

**Checkpoint context:** 43 saved pending URLs; discovery incomplete flag `False`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.

### COMP-0797 — Molex

**Disposition:** Network/source investigation · **Work order:** Access investigations

**Initial group:** B3 Network/service failure

**Configured source:** `Koch careers / official careers` — https://www.molex.com/en-us/about/careers

**Cycle source/result ATS:** https://www.molex.com/en-us/about/careers — ``

**Exact recorded reason:** Direct fetch returned partial: Careers page network/timeout failure; board discovery did not complete.. Browser fallback returned partial: Browser fallback saved 0 job descriptions; 0 job URLs await retry. Inventory completeness unknown; no closure inference. Browser fallback needs retry (Error).

**Next action:** Recheck canonical official URL, TLS/DNS/HTTP status and bounded timeout behavior; confirm native provider after recovery. Do not disable certificate verification or infer an empty board.

**Candidate code:** `src/job_search_helper/discovery.py`

**Existing test candidates:** Find coverage by adapter/function name; no matching test filename identified.

**Fresh public check:** not separately probed for this company; use recorded cycle evidence and relevant shared/targeted work-order evidence.

**Checkpoint context:** 0 saved pending URLs; discovery incomplete flag `True`; previous cycle stage `None`. Neither pending count nor this flag alone proves coverage.
